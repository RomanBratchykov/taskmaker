#!/usr/bin/env python3
"""
pdf_to_md.py
Convert PDF to Markdown with text and image extraction.

Usage:
    python pdf_to_md.py <input_pdf> <output_md> [--images_dir <images_dir>]

Arguments:
    input_pdf: Path to the input PDF file.
    output_md: Path to the output Markdown file.
    images_dir: Directory to save extracted images (default: same directory as output_md with '/images').

The script extracts text from each page, preserves page boundaries, and extracts images.
It does not perform OCR; if a page is scanned (no text), the text will be empty.
"""
import sys
import os
import fitz  # PyMuPDF
from pathlib import Path

def pdf_to_md(input_pdf, output_md, images_dir=None):
    # Open the PDF
    doc = fitz.open(input_pdf)

    # Determine images directory
    if images_dir is None:
        images_dir = os.path.join(os.path.dirname(output_md), 'images')
    os.makedirs(images_dir, exist_ok=True)

    # We'll collect the markdown content
    md_lines = []
    md_lines.append("# Source Document\n")

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text()

        # Start a new page section
        md_lines.append(f"## Page {page_num + 1}\n")

        # Add text if available
        if text.strip():
            md_lines.append(text)
            md_lines.append("\n")  # Ensure newline after text

        # Extract images
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            # Generate a filename for the image
            image_filename = f"page{page_num+1}_img{img_index+1}.{image_ext}"
            image_path = os.path.join(images_dir, image_filename)
            # Save the image
            with open(image_path, "wb") as img_file:
                img_file.write(image_bytes)
            # Reference in Markdown
            md_lines.append(f"![{image_filename}]({os.path.join('images', image_filename)})\n")

        # Add a separator between pages (optional)
        md_lines.append("\n---\n")

    # Write the Markdown file
    with open(output_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_lines))

    doc.close()
    print(f"Converted {input_pdf} to {output_md}")
    print(f"Images saved to {images_dir}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python pdf_to_md.py <input_pdf> <output_md> [--images_dir <images_dir>]")
        sys.exit(1)

    input_pdf = sys.argv[1]
    output_md = sys.argv[2]
    images_dir = None
    if len(sys.argv) >= 5 and sys.argv[3] == '--images_dir':
        images_dir = sys.argv[4]

    pdf_to_md(input_pdf, output_md, images_dir)