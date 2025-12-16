from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extract import append_records_to_csv, collect_pdfs, extract_from_pdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdf-tax-extractor",
        description="Estrae anno, titolo (herr/frau), nome e indirizzo da PDF (pagina scansionata) e aggiorna un CSV.",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="File PDF o cartelle contenenti PDF.",
    )
    parser.add_argument(
        "--csv",
        default="estrazioni.csv",
        help="Percorso CSV di output (append). Default: estrazioni.csv",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Se un input è una cartella, cerca PDF anche nelle sottocartelle.",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Non saltare i PDF già presenti nel CSV (colonna pdf_file).",
    )

    args = parser.parse_args(argv)

    pdfs = collect_pdfs(args.inputs, recursive=args.recursive)
    if not pdfs:
        print("Nessun PDF trovato.", file=sys.stderr)
        return 2

    records = []
    failed = 0
    for p in pdfs:
        try:
            records.append(extract_from_pdf(p))
        except Exception as e:
            failed += 1
            print(f"ERRORE su {p}: {e}", file=sys.stderr)

    written = append_records_to_csv(
        Path(args.csv),
        records,
        skip_existing=not args.no_skip_existing,
    )

    print(f"PDF trovati: {len(pdfs)} | record scritti: {written} | errori: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
