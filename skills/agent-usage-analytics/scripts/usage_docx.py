"""Minimal offline Word report from the renderer's constrained Markdown dialect.

Only text, headings and tables are emitted. Labels remain inert text, with no
external links, macros, templates or machine-specific dependencies.
"""
from __future__ import annotations

from io import BytesIO
import re
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def plain(text: str) -> str:
    return re.sub(r"\\([\\`*_\[\]<>|~&#!$])", r"\1", text)


def paragraph(text: str, style: str = "Normal", bold: bool = False) -> str:
    # Strip characters invalid in XML 1.0, preserving Unicode and whitespace.
    text = "".join(c for c in text if c in "\t\n\r" or "\x20" <= c <= "\ud7ff" or "\ue000" <= c <= "\ufffd" or "\U00010000" <= c <= "\U0010ffff")
    return (f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r>'
            + ("<w:rPr><w:b/></w:rPr>" if bold else "")
            + f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')


def word_table(lines: list[str]) -> str:
    rows = [[plain(cell.strip()) for cell in re.split(r"(?<!\\)\|", line.strip()[1:-1])]
            for line in lines]
    rows = [row for row in rows if not all(re.fullmatch(r":?-+:?", cell) for cell in row)]
    columns = len(rows[0])
    width = 15398 // columns
    result = ['<w:tbl><w:tblPr><w:tblW w:w="15398" w:type="dxa"/>'
              '<w:tblLayout w:type="fixed"/><w:tblBorders>'
              '<w:bottom w:val="single" w:sz="4" w:color="D9D9D9"/>'
              '<w:insideH w:val="single" w:sz="4" w:color="D9D9D9"/>'
              '</w:tblBorders><w:tblCellMar><w:top w:w="60" w:type="dxa"/>'
              '<w:left w:w="90" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/>'
              '<w:right w:w="90" w:type="dxa"/></w:tblCellMar></w:tblPr>',
              '<w:tblGrid>' + f'<w:gridCol w:w="{width}"/>' * columns + '</w:tblGrid>']
    for index, row in enumerate(rows):
        result.append('<w:tr><w:trPr><w:cantSplit/>' + ('<w:tblHeader/>' if index == 0 else '') + '</w:trPr>')
        for cell in row:
            result.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>'
                          + ('<w:shd w:fill="EDEDED"/>' if index == 0 else '')
                          + '</w:tcPr>' + paragraph(cell, "TableText", index == 0) + '</w:tc>')
        result.append('</w:tr>')
    return ''.join(result) + '</w:tbl>'


def render_docx(markdown: str) -> bytes:
    blocks = []
    table_lines = []
    for line in markdown.splitlines() + [""]:
        if line.startswith("| "):
            table_lines.append(line)
            continue
        if table_lines:
            blocks.append(word_table(table_lines))
            table_lines = []
        if not line:
            continue
        heading = re.match(r"^(#{1,3}) (.*)$", line)
        insight = re.match(r"^(\d+)\. \*\*(.*)\*\*$", line)
        if heading:
            style = ("Title", "Heading1", "Heading2")[len(heading[1]) - 1]
            blocks.append(paragraph(plain(heading[2]), style))
        elif insight:
            blocks.append(paragraph(plain(f"{insight[1]}. {insight[2]}"), "InsightTitle", True))
        else:
            text = line[2:] if line.startswith("> ") else line
            blocks.append(paragraph(plain(text)))
    document = (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}"><w:body>'
                + ''.join(blocks) + '<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>'
                '<w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"/>'
                '</w:sectPr></w:body></w:document>')
    styles = (f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr>'
              '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/>'
              '<w:color w:val="000000"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
              '<w:spacing w:after="100"/></w:pPr></w:pPrDefault></w:docDefaults>')
    for name, size in (("Normal", 22), ("Title", 36), ("Heading1", 28), ("Heading2", 24), ("TableText", 18), ("InsightTitle", 22)):
        heading = name in {"Title", "Heading1", "Heading2", "InsightTitle"}
        outline = {'Heading1': 0, 'Heading2': 1}.get(name)
        styles += (f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/>'
                   '<w:pPr>' + ('<w:keepNext/><w:spacing w:before="200" w:after="100"/>' if heading else '')
                   + (f'<w:outlineLvl w:val="{outline}"/>' if outline is not None else '')
                   + '</w:pPr><w:rPr>' + ('<w:b/>' if heading else '')
                   + f'<w:sz w:val="{size}"/></w:rPr></w:style>')
    styles += '</w:styles>'
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        archive.writestr('_rels/.rels', f'<Relationships xmlns="{REL}"><Relationship Id="rId1" Type="{OFFICE_REL}/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/_rels/document.xml.rels', f'<Relationships xmlns="{REL}"><Relationship Id="rId1" Type="{OFFICE_REL}/styles" Target="styles.xml"/></Relationships>')
        archive.writestr('word/document.xml', document)
        archive.writestr('word/styles.xml', styles)
    return output.getvalue()
