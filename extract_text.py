import fitz

def extract_text_from_pdf(file_path):
    text = ""
    with fitz.open(file_path) as pdf_document:
        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)
            text += page.get_text()
    return text

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract text from a PDF file")
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("-o", "--output", default="extracted_text.txt",
                        help="Output text file")
    args = parser.parse_args()

    extracted = extract_text_from_pdf(args.pdf)
    with open(args.output, "w", encoding="utf-8") as text_file:
        text_file.write(extracted)
    print(f"Text extracted successfully to '{args.output}'")
