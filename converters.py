"""Conversion helpers: docx <-> html <-> pdf."""

import shutil
import subprocess
from pathlib import Path

import bleach
import fitz  # PyMuPDF
import mammoth
import pypandoc
from pdf2docx import Converter as Pdf2DocxConverter

_SOFFICE_FALLBACK_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]

# Allowlist for sanitizing HTML before it's ever rendered unescaped in the
# browser (docx_to_html output feeds straight into the editor page). This
# stops a maliciously crafted .docx from carrying an XSS payload - no
# <script>, no event handler attributes, no javascript: URLs.
_ALLOWED_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u", "s", "strike",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "span", "div", "blockquote", "code", "pre",
]
_ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
    "span": ["style", "class"],
    "p": ["style"],
    "div": ["style"],
    "li": ["data-list"],
    "ol": ["data-list"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "data", "mailto"]


def _sanitize_html(html: str) -> str:
    return bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )


def _find_soffice() -> str:
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for path in _SOFFICE_FALLBACK_PATHS:
        if Path(path).exists():
            return path
    raise FileNotFoundError(
        "Could not find soffice(.exe). Install LibreOffice or add it to PATH."
    )


def docx_to_html(docx_path: str) -> str:
    """Convert a .docx file to HTML for loading into the editor."""
    with open(docx_path, "rb") as f:
        result = mammoth.convert_to_html(f)
    return _sanitize_html(result.value)


def html_to_docx(html: str, out_path: str) -> None:
    """Convert edited HTML back into a .docx file, overwriting out_path."""
    pypandoc.convert_text(_sanitize_html(html), "docx", format="html", outputfile=out_path)


def create_blank_docx(out_path: str) -> None:
    """Create a minimal empty .docx, ready to be opened in the editor."""
    pypandoc.convert_text("", "docx", format="html", outputfile=out_path)


def pdf_to_docx(pdf_path: str, out_path: str) -> None:
    """Convert a PDF into an editable .docx, preserving paragraph/table structure."""
    converter = Pdf2DocxConverter(pdf_path)
    try:
        converter.convert(out_path)
    finally:
        converter.close()


def docx_to_pdf(docx_path: str) -> str:
    """Convert a .docx file to PDF via LibreOffice headless. Returns the PDF path."""
    docx_path = Path(docx_path)
    outdir = docx_path.parent
    soffice = _find_soffice()

    subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(outdir),
            str(docx_path),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )

    pdf_path = outdir / (docx_path.stem + ".pdf")
    if not pdf_path.exists():
        raise RuntimeError(f"LibreOffice did not produce expected PDF: {pdf_path}")
    return str(pdf_path)


def get_pdf_page_count(pdf_path: str) -> int:
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def render_pdf_page_png(pdf_path: str, page_number: int, zoom: float = 1.5) -> bytes:
    """Render a PDF page to PNG bytes for display in the signing UI."""
    with fitz.open(pdf_path) as doc:
        if not 0 <= page_number < doc.page_count:
            raise ValueError(f"Page {page_number} out of range (0-{doc.page_count - 1})")
        page = doc[page_number]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pixmap.tobytes("png")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def stamp_signatures(pdf_path: str, signatures: list[dict], out_path: str) -> None:
    """Burn one or more signature images onto pages and save as out_path.

    Each entry in `signatures` is a dict with keys: page (int), x, y, width,
    height (fractions 0-1 of the page), and signature_png (bytes).
    """
    with fitz.open(pdf_path) as doc:
        for sig in signatures:
            page_number = sig["page"]
            if not 0 <= page_number < doc.page_count:
                raise ValueError(f"Page {page_number} out of range (0-{doc.page_count - 1})")
            page = doc[page_number]
            page_width, page_height = page.rect.width, page.rect.height

            x = _clamp(sig["x"], 0.0, 1.0)
            y = _clamp(sig["y"], 0.0, 1.0)
            width = _clamp(sig["width"], 0.01, 1.0 - x)
            height = _clamp(sig["height"], 0.01, 1.0 - y)

            rect = fitz.Rect(
                x * page_width,
                y * page_height,
                (x + width) * page_width,
                (y + height) * page_height,
            )
            page.insert_image(rect, stream=sig["signature_png"])
        doc.save(out_path)
