#!/usr/bin/env python3
"""
docx_template.py
Analyze a DOCX template and generate a machine-readable description.

Usage:
    python docx_template.py <input_template_docx> <output_json>

Arguments:
    input_template_docx: Path to the template DOCX file.
    output_json: Path to the output JSON file describing the template.

The script extracts page settings, styles, headers/footers, and metadata.
It does not extract the main text content (to avoid clutter), but can note
if placeholder text is present.
"""
import sys
import os
import json
import docx
from docx.document import Document as _Document
from docx.oxml.shared import OxmlElement, qn
from docx.oxml.ns import nsdecls
from docx.shared import Inches, Pt

def inches_to_cm(inches):
    return inches * 2.54

def extract_template_info(docx_path):
    """Extract template information from the DOCX file."""
    doc = docx.Document(docx_path)
    info = {}

    # Page settings (from the first section)
    section = doc.sections[0]
    info["page_size"] = {
        "width": inches_to_cm(section.page_width),
        "height": inches_to_cm(section.page_height)
    }
    info["margins"] = {
        "top": inches_to_cm(section.top_margin),
        "bottom": inches_to_cm(section.bottom_margin),
        "left": inches_to_cm(section.left_margin),
        "right": inches_to_cm(section.right_margin),
        "header": inches_to_cm(section.header_distance),
        "footer": inches_to_cm(section.footer_distance)
    }

    # Extract styles
    info["styles"] = {"paragraph": {}, "character": {}}
    for style in doc.styles:
        if style.type == docx.enum.style.WD_STYLE_TYPE.PARAGRAPH:
            style_info = {
                "name": style.name,
                "type": "paragraph",
                "builtin": style.builtin,
                "hidden": style.hidden,
                # We'll try to extract some formatting if it's a direct formatting
                # Note: style.font might be None if not set
            }
            # Try to get font info
            if style.font:
                style_info["font"] = {
                    "name": style.font.name,
                    "size": style.font.size.pt if style.font.size else None,
                    "bold": style.font.bold,
                    "italic": style.font.italic,
                    "underline": style.font.underline,
                    "color": str(style.font.color.rgb) if style.font.color.rgb else None
                }
            # Paragraph format
            if style.paragraph_format:
                style_info["paragraph_format"] = {
                    "alignment": str(style.paragraph_format.alignment) if style.paragraph_format.alignment else None,
                    "line_spacing": style.paragraph_format.line_spacing,
                    "space_before": style.paragraph_format.space_before.pt if style.paragraph_format.space_before else None,
                    "space_after": style.paragraph_format.space_after.pt if style.paragraph_format.space_after else None,
                    "left_indent": style.paragraph_format.left_indent.pt if style.paragraph_format.left_indent else None,
                    "right_indent": style.paragraph_format.right_indent.pt if style.paragraph_format.right_indent else None,
                    "first_line_indent": style.paragraph_format.first_line_indent.pt if style.paragraph_format.first_line_indent else None
                }
            info["styles"]["paragraph"][style.name] = style_info
        elif style.type == docx.enum.style.WD_STYLE_TYPE.CHARACTER:
            style_info = {
                "name": style.name,
                "type": "character",
                "builtin": style.builtin,
                "hidden": style.hidden
            }
            if style.font:
                style_info["font"] = {
                    "name": style.font.name,
                    "size": style.font.size.pt if style.font.size else None,
                    "bold": style.font.bold,
                    "italic": style.font.italic,
                    "underline": style.font.underline,
                    "color": str(style.font.color.rgb) if style.font.color.rgb else None
                }
            info["styles"]["character"][style.name] = style_info

    # Identify heading styles (those with 'heading' in the name or outline level)
    heading_styles = []
    for style_name, style_info in info["styles"]["paragraph"].items():
        if "heading" in style_name.lower():
            heading_styles.append(style_name)
        else:
            # Check if the style has an outline level (like in Word's heading styles)
            # This is stored in the style's _element
            # We'll skip for simplicity and rely on the name
            pass
    info["heading_styles"] = heading_styles

    # Extract headers and footers
    info["header"] = {}
    info["footer"] = {}
    try:
        # Header
        header = section.header
        if header.is_linked_to_previous:
            info["header"]["linked_to_previous"] = True
        else:
            info["header"]["linked_to_previous"] = False
            # Extract text from paragraphs in header
            header_paragraphs = [p.text for p in header.paragraphs]
            if any(header_paragraphs):
                info["header"]["text"] = "\n".join(header_paragraphs)
            # Extract tables in header (if any)
            header_tables = []
            for tbl in header.tables:
                # We'll just note the presence and size
                header_tables.append({
                    "rows": len(tbl.rows),
                    "cols": len(tbl.columns) if tbl.rows else 0
                })
            if header_tables:
                info["header"]["tables"] = header_tables
        # Footer
        footer = section.footer
        if footer.is_linked_to_previous:
            info["footer"]["linked_to_previous"] = True
        else:
            info["footer"]["linked_to_previous"] = False
            footer_paragraphs = [p.text for p in footer.paragraphs]
            if any(footer_paragraphs):
                info["footer"]["text"] = "\n".join(footer_paragraphs)
            footer_tables = []
            for tbl in footer.tables:
                footer_tables.append({
                    "rows": len(tbl.rows),
                    "cols": len(tbl.columns) if tbl.rows else 0
                })
            if footer_tables:
                info["footer"]["tables"] = footer_tables
    except Exception as e:
        print(f"Warning: Could not extract header/footer: {e}", file=sys.stderr)

    # Extract metadata from core properties
    core_props = doc.core_properties
    info["metadata"] = {
        "title": core_props.title or "",
        "author": core_props.author or "",
        "subject": core_props.subject or "",
        "keywords": core_props.keywords or "",
        "comments": core_props.comments or "",
        "created": str(core_props.created) if core_props.created else "",
        "modified": str(core_props.modified) if core_props.modified else "",
        "last_modified_by": core_props.last_modified_by or "",
        "revision": core_props.revision or 0,
        "version": core_props.version or ""
    }

    # Optionally, extract a sample of the text to see placeholders
    # We'll get the first 500 characters of the document text
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
        if len('\n'.join(full_text)) > 500:
            break
    info["text_sample"] = '\n'.join(full_text)[:500]

    return info

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python docx_template.py <input_template_docx> <output_json>")
        sys.exit(1)

    input_docx = sys.argv[1]
    output_json = sys.argv[2]

    template_info = extract_template_info(input_docx)
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(template_info, f, indent=2)

    print(f"Template analysis saved to {output_json}")