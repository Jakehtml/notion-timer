# Notion Timer

This repository now includes a small script for extracting text from a PDF file using [PyMuPDF](https://pypi.org/project/PyMuPDF/).

## Requirements

- Python 3.9+
- `pymupdf`

Install dependencies with:

```bash
pip install -r requirements.txt
```

## Usage

Run the script with a path to your PDF file. The extracted text will be saved to `extracted_text.txt` by default.

```bash
python extract_text.py myfile.pdf
```

You can specify a custom output file with `-o`:

```bash
python extract_text.py myfile.pdf -o output.txt
```

The extraction runs entirely locally and does not upload any data.
