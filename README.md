## PDF Tax Declaration Data Extraction

App locale (Python) per estrarre da PDF con **pagina scansionata (immagine full-page)**:

- **anno** vicino a “Steuererklärung” (o equivalenti: inglese/italiano)
- **titolo**: `herr` oppure `frau`
- **nome** (se trova `Herr & Frau` prende **solo il maschio**, cioè la parte a sinistra di `&`)
- **indirizzo** + **CAP** + **città**

I risultati vengono **aggiunti (append)** a un file CSV ad ogni esecuzione.

### Requisiti

- Python 3.10+
- Tesseract OCR installato nel sistema (necessario per i PDF scansionati)

Su Ubuntu/Debian:

```bash
sudo apt-get update && sudo apt-get install -y tesseract-ocr
# opzionale (migliora l’OCR se presenti):
sudo apt-get install -y tesseract-ocr-eng tesseract-ocr-deu tesseract-ocr-ita
```

### Installazione dipendenze Python

```bash
pip install -r requirements.txt
```

### Uso

- Processare uno o più PDF:

```bash
python -m pdf_tax_extractor /percorso/file1.pdf /percorso/file2.pdf --csv estrazioni.csv
```

- Processare tutti i PDF in una cartella:

```bash
python -m pdf_tax_extractor /percorso/cartella_con_pdf --csv estrazioni.csv
```

- Cercare anche nelle sottocartelle:

```bash
python -m pdf_tax_extractor /percorso/cartella_con_pdf --recursive --csv estrazioni.csv
```

Per default, se `estrazioni.csv` esiste, i PDF già presenti (colonna `pdf_file`) vengono **saltati**. Per disabilitare:

```bash
python -m pdf_tax_extractor /percorso/cartella --no-skip-existing --csv estrazioni.csv
```

### Output CSV

Colonne:

- `pdf_file`, `year`, `title`, `name`, `address`, `zip`, `city`, `page_index`
