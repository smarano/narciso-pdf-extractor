from __future__ import annotations

import csv
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import fitz  # pymupdf
from PIL import Image

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None  # type: ignore


@dataclass
class ExtractedRecord:
    pdf_file: str
    year: str
    title: str
    name: str
    address: str
    zip: str
    city: str
    page_index: int


KEYWORDS = [
    "steuererklärung",
    "steuererklaerung",
    "tax declaration",
    "tax return",
    "income tax",
    "dichiarazione",
    "dichiarazione dei redditi",
    "dichiarazione fiscale",
]

TITLE_PATTERNS = [
    ("herr", re.compile(r"\bherr\b", re.IGNORECASE)),
    ("frau", re.compile(r"\bfrau\b", re.IGNORECASE)),
    ("herr", re.compile(r"\bmr\.?\b", re.IGNORECASE)),
    ("frau", re.compile(r"\bmrs\.?\b", re.IGNORECASE)),
    ("frau", re.compile(r"\bms\.?\b", re.IGNORECASE)),
    ("herr", re.compile(r"\bsignor\b", re.IGNORECASE)),
    ("frau", re.compile(r"\bsignora\b", re.IGNORECASE)),
]


def _require_tesseract() -> None:
    if pytesseract is None:
        raise RuntimeError(
            "pytesseract non è importabile. Installa le dipendenze: pip install -r requirements.txt"
        )
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Tesseract non è installato o non è nel PATH. Su Ubuntu: sudo apt-get install tesseract-ocr"
        )


def _normalize_text(text: str) -> str:
    # Normalize OCR artifacts a bit
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[\t\r]", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = text.replace("&", " & ")
    text = re.sub(r"[ ]{2,}", " ", text)
    return text


def _lines(text: str) -> list[str]:
    raw = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    return [ln for ln in raw if ln]


def _find_best_page(pages_text: list[str]) -> int:
    for i, t in enumerate(pages_text):
        low = t.lower()
        if any(k in low for k in KEYWORDS):
            return i
    return 0


def _extract_year(text: str) -> str:
    low = text.lower()
    # Positions of keywords in the whole text
    kw_positions: list[int] = []
    for k in KEYWORDS:
        start = 0
        while True:
            idx = low.find(k, start)
            if idx == -1:
                break
            kw_positions.append(idx)
            start = idx + len(k)
    year_matches = list(re.finditer(r"\b(19|20)\d{2}\b", text))
    if not year_matches:
        return ""

    if not kw_positions:
        return year_matches[0].group(0)

    best = None
    best_dist = 10**9
    for m in year_matches:
        pos = m.start()
        dist = min(abs(pos - kp) for kp in kw_positions)
        if dist < best_dist:
            best_dist = dist
            best = m.group(0)
    return best or year_matches[0].group(0)


def _detect_title_and_anchor(lines: list[str]) -> tuple[str, int, str]:
    """Return (title, line_index, remainder_after_title_if_present)."""
    best_idx = -1
    best_title = ""
    best_remainder = ""

    for i, ln in enumerate(lines):
        low = ln.lower()
        has_herr = re.search(r"\bherr\b", low) is not None or re.search(r"\bmr\b|\bmr\.", low) is not None
        has_frau = re.search(r"\bfrau\b", low) is not None or re.search(r"\bmrs\b|\bmrs\.|\bms\b|\bms\.", low) is not None

        if not (has_herr or has_frau):
            continue

        # If both present => take male per requirement
        title = "herr" if has_herr else "frau"

        # Try to capture name on the same line after title tokens
        remainder = ln
        remainder = re.sub(
            r"(?i)\b(herr|frau|mr\.?|mrs\.?|ms\.?|signor|signora)\b",
            "",
            remainder,
        ).strip(" -,:;")
        # If the remainder is only a separator (e.g. "Herr & Frau"), treat as empty.
        if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]", remainder) or remainder.strip() in {
            "&",
            "+",
            "und",
            "and",
        }:
            remainder = ""

        best_idx = i
        best_title = title
        best_remainder = remainder
        break

    return best_title, best_idx, best_remainder


def _split_partner_name(name_line: str, keep_left: bool = True) -> str:
    # Split on &, and/und, sometimes OCR uses '+'
    parts = re.split(r"\s*(?:&|\+|\bund\b|\band\b)\s*", name_line, flags=re.IGNORECASE)
    parts = [p.strip(" -,:;") for p in parts if p.strip(" -,:;")]
    if not parts:
        return name_line.strip()
    return parts[0] if keep_left else parts[-1]


def _extract_name_and_address(lines: list[str]) -> tuple[str, str, str, str]:
    title, idx, remainder = _detect_title_and_anchor(lines)
    if idx == -1:
        return "", "", "", ""

    # Determine name
    name_line = remainder
    j = idx + 1
    if (not name_line or name_line.strip() in {"&", "+", "und", "and"}) and j < len(lines):
        name_line = lines[j]
        j += 1

    if not name_line:
        name = ""
    else:
        # If couple name line contains both, keep left (male) per requirement.
        if re.search(r"\s(&|\bund\b|\band\b|\+)\s", name_line, re.IGNORECASE):
            name = _split_partner_name(name_line, keep_left=True)
        else:
            name = name_line.strip(" -,:;")

    # Address lines: first non-empty after name
    addr_line = ""
    zip_city_line = ""

    # If name was on same line as title, next line is likely address
    start_k = j
    for k in range(start_k, min(start_k + 6, len(lines))):
        ln = lines[k]
        if not addr_line:
            addr_line = ln
            continue
        if re.search(r"\b\d{4,6}\s+\S+", ln):
            zip_city_line = ln
            break
        # sometimes zip/city is the next line regardless
        if not zip_city_line and k == start_k + 1:
            zip_city_line = ln

    zip_code = ""
    city = ""
    m = re.search(r"\b(?P<zip>\d{4,6})\s+(?P<city>.+)$", zip_city_line)
    if m:
        zip_code = m.group("zip").strip()
        city = m.group("city").strip(" -,:;")

    # Title output must be exactly 'herr'/'frau' (lowercase)
    out_title = title

    return out_title, name, addr_line, zip_code, city


def _ocr_page(doc: fitz.Document, page_index: int, lang: str) -> str:
    _require_tesseract()
    page = doc.load_page(page_index)

    # Render at decent resolution
    mat = fitz.Matrix(2, 2)  # ~144 DPI *2
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    # OCR
    config = "--oem 3 --psm 6"
    return pytesseract.image_to_string(img, lang=lang, config=config)


def _available_tesseract_langs() -> set[str]:
    if shutil.which("tesseract") is None:
        return set()
    try:
        import subprocess

        out = subprocess.check_output(["tesseract", "--list-langs"], text=True, stderr=subprocess.STDOUT)
        langs = set()
        for ln in out.splitlines():
            ln = ln.strip()
            if not ln or ln.lower().startswith("list of available languages"):
                continue
            langs.add(ln)
        return langs
    except Exception:
        return set()


def extract_from_pdf(pdf_path: Path) -> ExtractedRecord:
    doc = fitz.open(pdf_path)
    try:
        # Try embedded text first per page, but OCR if it's mostly empty
        pages_text: list[str] = []
        for i in range(doc.page_count):
            t = doc.load_page(i).get_text("text") or ""
            t = _normalize_text(t)
            pages_text.append(t)

        page_idx = _find_best_page(pages_text)

        # If no keyword in embedded text or text is tiny, OCR (also if it's scanned)
        chosen = pages_text[page_idx]
        low = chosen.lower()
        needs_ocr = len(chosen.strip()) < 40 or not any(k in low for k in KEYWORDS)

        lang = "eng"
        available = _available_tesseract_langs()
        # Prefer tri-lang if installed
        if {"eng", "deu", "ita"}.issubset(available):
            lang = "deu+ita+eng"
        elif "deu" in available and "eng" in available:
            lang = "deu+eng"

        if needs_ocr:
            chosen = _normalize_text(_ocr_page(doc, page_idx, lang=lang))

        year = _extract_year(chosen)
        title, name, address, zip_code, city = _extract_name_and_address(_lines(chosen))

        return ExtractedRecord(
            pdf_file=str(pdf_path.name),
            year=year,
            title=title,
            name=name,
            address=address,
            zip=zip_code,
            city=city,
            page_index=page_idx,
        )
    finally:
        doc.close()


CSV_HEADER = ["pdf_file", "year", "title", "name", "address", "zip", "city", "page_index"]


def _read_existing_pdf_names(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            return {row.get("pdf_file", "") for row in r if row.get("pdf_file")}
    except Exception:
        return set()


def append_records_to_csv(csv_path: Path, records: Iterable[ExtractedRecord], skip_existing: bool = True) -> int:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_existing_pdf_names(csv_path) if skip_existing else set()
    file_exists = csv_path.exists()

    written = 0
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if not file_exists:
            w.writeheader()
        for rec in records:
            if skip_existing and rec.pdf_file in existing:
                continue
            w.writerow(
                {
                    "pdf_file": rec.pdf_file,
                    "year": rec.year,
                    "title": rec.title,
                    "name": rec.name,
                    "address": rec.address,
                    "zip": rec.zip,
                    "city": rec.city,
                    "page_index": rec.page_index,
                }
            )
            written += 1
    return written


def collect_pdfs(inputs: list[str], recursive: bool = False) -> list[Path]:
    out: list[Path] = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            pattern = "**/*.pdf" if recursive else "*.pdf"
            out.extend(sorted(p.glob(pattern)))
        else:
            out.append(p)
    # de-dup and keep only existing pdfs
    dedup: dict[str, Path] = {}
    for p in out:
        if p.suffix.lower() != ".pdf":
            continue
        if p.exists():
            dedup[str(p.resolve())] = p
    return list(dedup.values())
