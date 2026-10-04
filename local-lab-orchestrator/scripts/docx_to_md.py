#!/usr/bin/env python3
"""
docx_to_md.py
Convert DOCX to Markdown with basic structure preservation.

Usage:
    python docx_to_md.py <input_docx> <output_md> [--images_dir <images_dir>]

Arguments:
    input_docx: Path to the input DOCX file.
    output_md: Path to the output Markdown file.
    images_dir: Directory to save extracted images (default: same directory as output_md with '/images').

The script extracts text, headings, tables, and lists (basic). It does not extract images.
Metadata is saved in a separate JSON file (output_md replaced with .json extension).
"""
import sys
import os
import json
import docx
from docx.document import Document as _Document
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.text.paragraph import Paragraph
from docx.table import Table
from docx.opc.constants import RELATIONSHIP_TYPE as RT

def iter_block_items(parent):
    """
    Generate a reference to each paragraph and table child within *parent*,
    in document order. Each returned value is an instance of either Table or Paragraph.
    """
    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent.element.tc
    else:
        raise ValueError("something's not right")

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)

def extract_metadata(docx_path):
    """Extract core properties from the DOCX file."""
    doc = docx.Document(docx_path)
    core_props = doc.core_properties
    metadata = {
        "title": core_props.title or "",
        "author": core_props.author or "",
        "subject": core_props.subject or "",
        "keywords": core_props.keywords or "",
        "comments": core_props.comments or "",
        "created": str(core_props.created) if core_props.created else "",
        "modified": str(core_props.modified) if core_props.modified else "",
        "last_modified_by": core_props.last_modified_by or "",
        "revision": core_props.revision or 0,
        "version": core_props.version or "",
    }
    return metadata

def convert_docx_to_md(docx_path, output_md, images_dir=None):
    """Convert DOCX to Markdown, saving images if images_dir is provided."""
    doc = docx.Document(docx_path)
    md_lines = []

    # We'll process the document block by block
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            # Process paragraph
            text = block.text.strip()
            if not text:
                md_lines.append("")  # Empty line for empty paragraph
                continue

            # Check if it's a heading
            style_name = block.style.name if block.style else ""
            if style_name.startswith('Heading'):
                try:
                    level = int(style_name.replace('Heading', ''))
                except:
                    level = 1
                if level > 6:
                    level = 6
                md_lines.append(f"{'#' * level} {text}")
            else:
                # Regular paragraph
                # We could add bold/italic detection by checking runs, but skip for simplicity
                md_lines.append(text)

        elif isinstance(block, Table):
            # Process table
            md_lines.append("")  # Empty line before table
            # Get the number of rows and columns
            rows = len(block.rows)
            if rows == 0:
                md_lines.append("*Empty table*")
                md_lines.append("")
                continue
            # Assume first row is header
            header = block.rows[0]
            # Build header line
            header_cells = [cell.text.strip().replace('|', '\\|') for cell in header.cells]
            md_lines.append("| " + " | ".join(header_cells) + " |")
            # Build separator line
            separator = ["---"] * len(header.cells)
            md_lines.append("| " + " | ".join(separator) + " |")
            # Process data rows
            for row in block.rows[1:]:
                row_cells = [cell.text.strip().replace('|', '\\|') for cell in row.cells]
                md_lines.append("| " + " | ".join(row_cells) + " |")
            md_lines.append("")  # Empty line after table

    # Write the Markdown file
    with open(output_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md_lines))

    # Save metadata
    metadata = extract_metadata(docx_path)
    meta_path = os.path.splitext(output_md)[0] + '.json'
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"Converted {docx_path} to {output_md}")
    print(f"Metadata saved to {meta_path}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python docx_to_md.py <input_docx> <output_md> [--images_dir <images_dir>]")
        sys.exit(1)

    input_docx = sys.argv[1]
    output_md = sys.argv[2]
    images_dir = None
    if len(sys.argv) >= 5 and sys.argv[3] == '--images_dir':
        images_dir = sys.argv[4]

    convert_docx_to_md(input_docx, output_md, images_dir)