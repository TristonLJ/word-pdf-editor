"""General PDF manipulation tools: merge, split, organize, compress, protect, etc."""

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
import pymupdf4llm
import pytesseract
from PIL import Image

from converters import _find_soffice

_TESSERACT_FALLBACK_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    hex_color = (hex_color or "").lstrip("#")
    if len(hex_color) != 6:
        return (0.0, 0.0, 0.0)
    try:
        r = int(hex_color[0:2], 16) / 255
        g = int(hex_color[2:4], 16) / 255
        b = int(hex_color[4:6], 16) / 255
        return (r, g, b)
    except ValueError:
        return (0.0, 0.0, 0.0)


def _configure_tesseract() -> None:
    found = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        return
    for path in _TESSERACT_FALLBACK_PATHS:
        if Path(path).exists():
            pytesseract.pytesseract.tesseract_cmd = path
            return
    raise FileNotFoundError(
        "Could not find tesseract(.exe). Install Tesseract OCR or add it to PATH."
    )


def office_to_pdf(path: str) -> str:
    """Convert any LibreOffice-supported office file (.docx/.pptx/.xlsx/...) to PDF."""
    path = Path(path)
    outdir = path.parent
    soffice = _find_soffice()

    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(path)],
        check=True,
        capture_output=True,
        timeout=180,
    )

    pdf_path = outdir / (path.stem + ".pdf")
    if not pdf_path.exists():
        raise RuntimeError(f"LibreOffice did not produce expected PDF: {pdf_path}")
    return str(pdf_path)


def merge_pdfs(paths: list[str], out_path: str) -> None:
    merged = fitz.open()
    try:
        for p in paths:
            with fitz.open(p) as src:
                merged.insert_pdf(src)
        merged.save(out_path)
    finally:
        merged.close()


def split_pdf(path: str, ranges: list[tuple[int, int]], outdir: str, base_name: str) -> list[str]:
    """ranges are 0-indexed, inclusive (start, end). Returns the output file paths."""
    outputs = []
    with fitz.open(path) as doc:
        for i, (start, end) in enumerate(ranges):
            start = max(0, start)
            end = min(doc.page_count - 1, end)
            if start > end:
                continue
            part = fitz.open()
            part.insert_pdf(doc, from_page=start, to_page=end)
            out_path = str(Path(outdir) / f"{base_name}-part{i + 1}.pdf")
            part.save(out_path)
            part.close()
            outputs.append(out_path)
    return outputs


def reorder_pdf(path: str, page_plan: list[dict], out_path: str) -> None:
    """page_plan: ordered list of {"index": original 0-based page index, "rotation": 0/90/180/270}.

    Pages omitted from page_plan are dropped - this single operation covers
    reordering, deleting, and per-page rotation all at once.
    """
    with fitz.open(path) as doc:
        new_doc = fitz.open()
        try:
            for entry in page_plan:
                idx = entry["index"]
                if not 0 <= idx < doc.page_count:
                    raise ValueError(f"Page index {idx} out of range")
                new_doc.insert_pdf(doc, from_page=idx, to_page=idx)
                new_page = new_doc[-1]
                rotation = entry.get("rotation", 0)
                if rotation:
                    new_page.set_rotation((new_page.rotation + rotation) % 360)
            if new_doc.page_count == 0:
                raise ValueError("At least one page must be kept")
            new_doc.save(out_path)
        finally:
            new_doc.close()


def rotate_pdf(path: str, degrees: int, out_path: str) -> None:
    with fitz.open(path) as doc:
        for page in doc:
            page.set_rotation((page.rotation + degrees) % 360)
        doc.save(out_path)


def crop_pdf(path: str, rect_fractions: tuple[float, float, float, float], out_path: str) -> None:
    """rect_fractions: (x, y, width, height) as fractions 0-1, applied to every page."""
    x, y, width, height = rect_fractions
    x = _clamp(x, 0.0, 1.0)
    y = _clamp(y, 0.0, 1.0)
    width = _clamp(width, 0.01, 1.0 - x)
    height = _clamp(height, 0.01, 1.0 - y)
    with fitz.open(path) as doc:
        for page in doc:
            r = page.rect
            crop_rect = fitz.Rect(
                r.x0 + x * r.width,
                r.y0 + y * r.height,
                r.x0 + (x + width) * r.width,
                r.y0 + (y + height) * r.height,
            )
            page.set_cropbox(crop_rect)
        doc.save(out_path)


_PAGE_NUMBER_POSITIONS = {
    "bottom-center": lambda r: (r.width / 2 - 10, r.height - 30),
    "bottom-right": lambda r: (r.width - 50, r.height - 30),
    "bottom-left": lambda r: (30, r.height - 30),
    "top-center": lambda r: (r.width / 2 - 10, 30),
}


def add_page_numbers(path: str, out_path: str, position: str = "bottom-center", start: int = 1) -> None:
    place = _PAGE_NUMBER_POSITIONS.get(position, _PAGE_NUMBER_POSITIONS["bottom-center"])
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            x, y = place(page.rect)
            page.insert_text((x, y), str(start + i), fontsize=11, color=(0, 0, 0))
        doc.save(out_path)


def watermark_pdf(
    path: str,
    out_path: str,
    text: str | None = None,
    image_bytes: bytes | None = None,
    opacity: float = 0.3,
) -> None:
    with fitz.open(path) as doc:
        for page in doc:
            r = page.rect
            if image_bytes:
                w, h = r.width * 0.5, r.height * 0.5
                rect = fitz.Rect(
                    (r.width - w) / 2, (r.height - h) / 2,
                    (r.width + w) / 2, (r.height + h) / 2,
                )
                page.insert_image(rect, stream=image_bytes, overlay=True)
            elif text:
                fontsize = 40
                text_width = fitz.get_text_length(text, fontsize=fontsize)
                x = max(0, (r.width - text_width) / 2)
                y = r.height / 2
                page.insert_text(
                    (x, y), text, fontsize=fontsize, color=(0.6, 0.6, 0.6), fill_opacity=opacity
                )
        doc.save(out_path)


def pdf_to_jpgs(path: str, outdir: str, base_name: str, zoom: float = 2.0) -> list[str]:
    outputs = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            out_path = str(Path(outdir) / f"{base_name}-page{i + 1}.jpg")
            pix.save(out_path, jpg_quality=90)
            outputs.append(out_path)
    return outputs


def images_to_pdf(image_paths: list[str], out_path: str) -> None:
    doc = fitz.open()
    try:
        for img_path in image_paths:
            img_doc = fitz.open(img_path)
            pdf_bytes = img_doc.convert_to_pdf()
            img_doc.close()
            img_pdf = fitz.open("pdf", pdf_bytes)
            doc.insert_pdf(img_pdf)
            img_pdf.close()
        doc.save(out_path)
    finally:
        doc.close()


def compress_pdf(path: str, out_path: str) -> None:
    """Structural compression: strip unused objects, compress streams. Reliable and safe
    for any PDF; doesn't attempt lossy image re-encoding."""
    with fitz.open(path) as doc:
        doc.save(out_path, garbage=4, deflate=True, clean=True)


def protect_pdf(path: str, password: str, out_path: str) -> None:
    with fitz.open(path) as doc:
        doc.save(
            out_path,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw=password,
            user_pw=password,
        )


def unlock_pdf(path: str, password: str, out_path: str) -> None:
    with fitz.open(path) as doc:
        if doc.is_encrypted:
            if not doc.authenticate(password):
                raise ValueError("Incorrect password")
        doc.save(out_path, encryption=fitz.PDF_ENCRYPT_NONE)


def repair_pdf(path: str, out_path: str) -> None:
    """MuPDF's parser is tolerant of malformed PDFs; opening + re-saving cleanly
    recovers most structural corruption."""
    with fitz.open(path) as doc:
        doc.save(out_path, garbage=4, deflate=True, clean=True)


def redact_pdf(path: str, regions: list[dict], out_path: str) -> None:
    """regions: list of {page, x, y, width, height} fractional rects (0-1).

    Uses real redaction (add_redact_annot + apply_redactions), which deletes
    the underlying content in the area - not just a cosmetic black box.
    """
    with fitz.open(path) as doc:
        for region in regions:
            page_number = region["page"]
            if not 0 <= page_number < doc.page_count:
                raise ValueError(f"Page {page_number} out of range")
            page = doc[page_number]
            r = page.rect
            x = _clamp(region["x"], 0.0, 1.0)
            y = _clamp(region["y"], 0.0, 1.0)
            width = _clamp(region["width"], 0.01, 1.0 - x)
            height = _clamp(region["height"], 0.01, 1.0 - y)
            rect = fitz.Rect(
                r.x0 + x * r.width,
                r.y0 + y * r.height,
                r.x0 + (x + width) * r.width,
                r.y0 + (y + height) * r.height,
            )
            page.add_redact_annot(rect, fill=(0, 0, 0))
        for page in doc:
            page.apply_redactions()
        doc.save(out_path)


def ocr_pdf(path: str, out_path: str, language: str = "eng") -> None:
    """Adds an invisible, searchable text layer over each page's scanned image
    (the original page appearance is unchanged - the text is just selectable/searchable)."""
    _configure_tesseract()
    with fitz.open(path) as doc:
        for page in doc:
            zoom = 2.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            data = pytesseract.image_to_data(img, lang=language, output_type=pytesseract.Output.DICT)
            scale = 1 / zoom
            for i in range(len(data["text"])):
                word = data["text"][i].strip()
                if not word:
                    continue
                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                rect = fitz.Rect(x * scale, y * scale, (x + w) * scale, (y + h) * scale)
                if rect.height <= 0:
                    continue
                page.insert_text(
                    (rect.x0, rect.y1), word, fontsize=rect.height * 0.8, render_mode=3
                )
        doc.save(out_path)


def pdf_to_pdfa(path: str, out_path: str) -> None:
    """Convert to PDF/A-1b (ISO-standardized archival format) via LibreOffice.

    The input PDF is opened via LibreOffice's Draw PDF-import filter (that's
    what LO uses for PDF sources), then re-exported with the PDF/A option set
    on the Draw PDF-export filter. Output always has the same stem + .pdf
    extension as the input, so it must land in a directory of its own -
    otherwise LibreOffice tries to overwrite the very file it's reading and
    fails outright.
    """
    path = Path(path)
    soffice = _find_soffice()
    filter_opts = 'pdf:draw_pdf_Export:{"SelectPdfVersion":{"type":"long","value":"1"}}'

    with tempfile.TemporaryDirectory() as tmp_outdir:
        subprocess.run(
            [soffice, "--headless", "--convert-to", filter_opts, "--outdir", tmp_outdir, str(path)],
            check=True,
            capture_output=True,
            timeout=180,
        )
        produced = Path(tmp_outdir) / (path.stem + ".pdf")
        if not produced.exists():
            raise RuntimeError(f"LibreOffice did not produce expected PDF/A file: {produced}")
        produced.replace(out_path)


def pdf_to_markdown(path: str) -> str:
    """Rule-based, layout-aware PDF -> Markdown conversion (no AI/network call)."""
    return pymupdf4llm.to_markdown(path)


def extract_text_lines(path: str) -> list[str]:
    """Every page's text, as a flat list of lines - used for diffing (Compare PDF)."""
    lines = []
    with fitz.open(path) as doc:
        for page in doc:
            lines.extend(page.get_text().splitlines())
            lines.append(f"--- page {page.number + 1} end ---")
    return lines


_FONT_MAP = {
    "helvetica": "helv",
    "times": "times",
    "courier": "cour",
}


def apply_edits(path: str, elements: list[dict], out_path: str) -> None:
    """Draws free-form annotations onto a PDF.

    Each element is a dict with a "type" of "text" | "image" | "rect" | "freehand"
    and a "page" index. Text/image/rect carry a fractional (0-1) x/y/width/height
    rect (same convention used throughout this app); freehand carries a list of
    [x, y] fractional points traced directly on the page instead of a bounding box.
    """
    with fitz.open(path) as doc:
        for el in elements:
            page_number = el["page"]
            if not 0 <= page_number < doc.page_count:
                raise ValueError(f"Page {page_number} out of range")
            page = doc[page_number]
            r = page.rect
            kind = el["type"]

            if kind == "freehand":
                points = el.get("points", [])
                if len(points) < 2:
                    continue
                color = _hex_to_rgb(el.get("color", "#000000"))
                stroke_width = float(el.get("stroke_width", 2))
                abs_points = [
                    fitz.Point(r.x0 + px * r.width, r.y0 + py * r.height) for px, py in points
                ]
                page.draw_polyline(abs_points, color=color, width=stroke_width)
                continue

            x = _clamp(el["x"], 0.0, 1.0)
            y = _clamp(el["y"], 0.0, 1.0)
            width = _clamp(el.get("width", 0.1), 0.005, 1.0 - x)
            height = _clamp(el.get("height", 0.05), 0.005, 1.0 - y)
            rect = fitz.Rect(
                r.x0 + x * r.width,
                r.y0 + y * r.height,
                r.x0 + (x + width) * r.width,
                r.y0 + (y + height) * r.height,
            )

            if kind == "text":
                color = _hex_to_rgb(el.get("color", "#000000"))
                fontsize = float(el.get("font_size", 14))
                fontname = _FONT_MAP.get(el.get("font", "helvetica"), "helv")
                page.insert_textbox(
                    rect, el.get("text", ""), fontsize=fontsize, fontname=fontname, color=color
                )
            elif kind == "image":
                page.insert_image(rect, stream=el["image_bytes"])
            elif kind == "rect":
                color = _hex_to_rgb(el.get("color", "#000000"))
                fill = color if el.get("fill") else None
                page.draw_rect(rect, color=color, fill=fill, width=1.5)
            else:
                raise ValueError(f"Unknown element type: {kind}")
        doc.save(out_path)


def has_form_fields(path: str) -> bool:
    with fitz.open(path) as doc:
        for page in doc:
            # page.widgets() always returns a generator object (truthy even
            # when empty) - must actually pull an item to know if one exists.
            if next(page.widgets(), None) is not None:
                return True
    return False


def get_form_fields(path: str) -> list[dict]:
    """Existing form fields across all pages, with fractional (0-1) rects."""
    fields = []
    with fitz.open(path) as doc:
        for page_number, page in enumerate(doc):
            r = page.rect
            for widget in page.widgets():
                wr = widget.rect
                fields.append(
                    {
                        "page": page_number,
                        "name": widget.field_name,
                        "type": widget.field_type_string,
                        "value": widget.field_value,
                        "options": list(widget.choice_values) if widget.choice_values else [],
                        "x": (wr.x0 - r.x0) / r.width,
                        "y": (wr.y0 - r.y0) / r.height,
                        "width": wr.width / r.width,
                        "height": wr.height / r.height,
                    }
                )
    return fields


def fill_form_fields(path: str, values: dict, out_path: str) -> None:
    """values: {field_name: new_value}."""
    with fitz.open(path) as doc:
        for page in doc:
            for widget in page.widgets():
                if widget.field_name in values:
                    widget.field_value = values[widget.field_name]
                    widget.update()
        doc.save(out_path)


def add_form_fields(path: str, fields: list[dict], out_path: str) -> None:
    """fields: list of {page, x, y, width, height, type ('text'|'checkbox'|'dropdown'), name, options?}."""
    with fitz.open(path) as doc:
        for i, spec in enumerate(fields):
            page_number = spec["page"]
            if not 0 <= page_number < doc.page_count:
                raise ValueError(f"Page {page_number} out of range")
            page = doc[page_number]
            r = page.rect
            x = _clamp(spec["x"], 0.0, 1.0)
            y = _clamp(spec["y"], 0.0, 1.0)
            width = _clamp(spec.get("width", 0.2), 0.01, 1.0 - x)
            height = _clamp(spec.get("height", 0.04), 0.01, 1.0 - y)
            rect = fitz.Rect(
                r.x0 + x * r.width,
                r.y0 + y * r.height,
                r.x0 + (x + width) * r.width,
                r.y0 + (y + height) * r.height,
            )

            widget = fitz.Widget()
            widget.rect = rect
            widget.field_name = spec.get("name") or f"field_{i + 1}"

            field_type = spec.get("type", "text")
            if field_type == "checkbox":
                widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
            elif field_type == "dropdown":
                widget.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
                widget.choice_values = spec.get("options", [])
            else:
                widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT

            page.add_widget(widget)
        doc.save(out_path)
