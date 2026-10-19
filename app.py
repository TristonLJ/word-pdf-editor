import base64
import difflib
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, Response
from werkzeug.utils import secure_filename

import converters
import excel_tools
import pdf_tools

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
# Reject uploads/payloads over 200MB outright, before they hit disk or memory.
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

# Documents live outside the project folder, in a per-user OS data directory.
# That way the source code never contains your files - sharing/copying/zipping
# this folder to someone else can never leak your documents, since they were
# never stored inside it in the first place. Each person who runs this app
# gets their own independent documents folder on their own machine.
_APP_DATA_ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
DOCUMENTS_DIR = _APP_DATA_ROOT / "WordPdfEditor" / "documents"
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

_MAX_FILENAME_LENGTH = 200


@app.before_request
def _block_cross_origin_requests():
    """Reject any state-changing request that didn't originate from this app.

    This server binds to localhost, but browsers will happily let *any*
    website you have open send background requests to it (a real, common
    attack against locally-run dev servers - a malicious page could try to
    POST to /delete/<file> or /upload behind your back). Requiring the
    Origin/Referer to match our own origin blocks that without needing any
    session/cookie machinery.
    """
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    host_url = request.host_url.rstrip("/")
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    if origin is not None:
        if origin.rstrip("/") != host_url:
            abort(403, "Cross-origin request blocked")
    elif referer is not None:
        if not referer.startswith(host_url + "/"):
            abort(403, "Cross-origin request blocked")
    else:
        abort(403, "Missing Origin/Referer header")


def safe_path(filename: str, exts=(".docx",)) -> Path:
    name = secure_filename(filename)
    if not name or len(name) > _MAX_FILENAME_LENGTH:
        abort(400, "Invalid filename")
    if not any(name.lower().endswith(ext) for ext in exts):
        abort(400, f"Filename must end with one of {exts}")
    path = DOCUMENTS_DIR / name
    if path.resolve().parent != DOCUMENTS_DIR.resolve():
        abort(400, "Invalid filename")
    return path


def new_document_path(raw_filename: str, ext: str) -> Path:
    name = secure_filename(raw_filename)
    if not name or len(name) > _MAX_FILENAME_LENGTH:
        abort(400, "Please provide a valid filename")
    if not name.lower().endswith(ext):
        name += ext
    path = DOCUMENTS_DIR / name
    if path.resolve().parent != DOCUMENTS_DIR.resolve():
        abort(400, "Invalid filename")
    if path.exists():
        abort(400, "A document with that name already exists")
    return path


def _unique_path(directory: Path, name: str) -> Path:
    """Like new_document_path, but auto-dedupes instead of erroring - tool
    outputs get re-run often and shouldn't require the user to rename each time."""
    path = directory / name
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _looks_like_docx(file_storage) -> bool:
    """.docx files are ZIP archives - check the magic bytes, not just the extension."""
    header = file_storage.stream.read(4)
    file_storage.stream.seek(0)
    return header[:2] == b"PK"


def _looks_like_pdf(file_storage) -> bool:
    header = file_storage.stream.read(5)
    file_storage.stream.seek(0)
    return header == b"%PDF-"


def _looks_like_office_doc(file_storage) -> bool:
    """.docx/.pptx/.xlsx are all ZIP archives (Office Open XML)."""
    header = file_storage.stream.read(4)
    file_storage.stream.seek(0)
    return header[:2] == b"PK"


def _looks_like_image(file_storage) -> bool:
    header = file_storage.stream.read(8)
    file_storage.stream.seek(0)
    if header[:3] == b"\xff\xd8\xff":  # JPEG
        return True
    if header[:8] == b"\x89PNG\r\n\x1a\n":  # PNG
        return True
    return False


_OFFICE_EXTENSIONS = (".docx", ".pptx", ".xlsx")
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


@app.route("/")
def index():
    docs = sorted(p.name for p in DOCUMENTS_DIR.glob("*.docx"))
    docx_stems = {p.stem for p in DOCUMENTS_DIR.glob("*.docx")}
    pdfs = sorted(p.name for p in DOCUMENTS_DIR.glob("*.pdf") if p.stem not in docx_stems)
    sheets = sorted(p.name for p in DOCUMENTS_DIR.glob("*.xlsx"))
    return render_template("index.html", documents=docs, pdfs=pdfs, sheets=sheets)


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".docx"):
        abort(400, "Only .docx files are supported")
    if not _looks_like_docx(file):
        abort(400, "That file doesn't look like a valid .docx")

    filename = secure_filename(file.filename)
    file.save(DOCUMENTS_DIR / filename)
    return redirect(f"/edit/{filename}")


@app.route("/upload-pdf", methods=["POST"])
def upload_pdf():
    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf"):
        abort(400, "Only .pdf files are supported")
    if not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    filename = secure_filename(file.filename)
    file.save(DOCUMENTS_DIR / filename)
    return redirect("/")


@app.route("/upload-pdf-to-word", methods=["POST"])
def upload_pdf_to_word():
    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf"):
        abort(400, "Only .pdf files are supported")
    if not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    stem = Path(secure_filename(file.filename)).stem
    out_path = new_document_path(stem, ".docx")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name
    try:
        converters.pdf_to_docx(tmp_path, str(out_path))
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return redirect(f"/edit/{out_path.name}")


@app.route("/new", methods=["POST"])
def new_document():
    raw_filename = request.form.get("filename", "")
    path = new_document_path(raw_filename, ".docx")
    converters.create_blank_docx(str(path))
    return redirect(f"/edit/{path.name}")


@app.route("/edit/<filename>")
def edit(filename):
    path = safe_path(filename, (".docx",))
    if not path.exists():
        abort(404)
    html = converters.docx_to_html(str(path))
    return render_template("editor.html", filename=path.name, content_html=html)


@app.route("/save/<filename>", methods=["POST"])
def save(filename):
    path = safe_path(filename, (".docx",))
    if not path.exists():
        abort(404)
    data = request.get_json(silent=True) or {}
    html = data.get("html", "")
    converters.html_to_docx(html, str(path))
    return jsonify({"status": "ok"})


@app.route("/export/<filename>", methods=["POST"])
def export(filename):
    path = safe_path(filename, (".docx",))
    if not path.exists():
        abort(404)
    pdf_path = converters.docx_to_pdf(str(path))
    return jsonify({"status": "ok", "pdf_filename": Path(pdf_path).name})


@app.route("/download/<filename>")
def download(filename):
    name = secure_filename(filename)
    path = DOCUMENTS_DIR / name
    if path.resolve().parent != DOCUMENTS_DIR.resolve() or not path.exists():
        abort(404)
    return send_from_directory(DOCUMENTS_DIR, name, as_attachment=True)


def _resolve_signing_pdf(filename: str) -> Path:
    """Given a .docx or .pdf filename, return the PDF path to render/sign."""
    path = safe_path(filename, (".docx", ".pdf"))
    if not path.exists():
        abort(404)
    if path.suffix.lower() == ".docx":
        pdf_path = Path(converters.docx_to_pdf(str(path)))
    else:
        pdf_path = path
    return pdf_path


@app.route("/sign/<filename>")
def sign_page(filename):
    pdf_path = _resolve_signing_pdf(filename)
    page_count = converters.get_pdf_page_count(str(pdf_path))
    return render_template(
        "sign.html",
        filename=filename,
        pdf_filename=pdf_path.name,
        page_count=page_count,
    )


@app.route("/page-image/<filename>/<int:page_number>")
def page_image(filename, page_number):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    png_bytes = converters.render_pdf_page_png(str(path), page_number)
    return Response(png_bytes, mimetype="image/png")


@app.route("/sign/<filename>", methods=["POST"])
def sign_submit(filename):
    pdf_path = _resolve_signing_pdf(filename)
    data = request.get_json(silent=True) or {}
    raw_signatures = data.get("signatures")
    if not raw_signatures:
        abort(400, "No signatures provided")

    if len(raw_signatures) > 20:
        abort(400, "Too many signatures in one request")

    signatures = []
    try:
        for sig in raw_signatures:
            _, _, b64 = sig["signature_png"].partition(",")
            if not b64:
                abort(400, "Invalid signature image")
            image_bytes = base64.b64decode(b64)
            if len(image_bytes) > 5 * 1024 * 1024:
                abort(400, "Signature image too large")
            signatures.append(
                {
                    "page": int(sig["page"]),
                    "x": float(sig["x"]),
                    "y": float(sig["y"]),
                    "width": float(sig["width"]),
                    "height": float(sig["height"]),
                    "signature_png": image_bytes,
                }
            )
    except (KeyError, TypeError, ValueError):
        abort(400, "Invalid signature payload")

    out_path = pdf_path.with_name(pdf_path.stem + "-signed.pdf")
    converters.stamp_signatures(str(pdf_path), signatures, str(out_path))
    return jsonify({"status": "ok", "pdf_filename": out_path.name})


@app.route("/delete/<filename>", methods=["POST"])
def delete(filename):
    path = safe_path(filename, (".docx", ".pdf", ".xlsx"))
    if not path.exists():
        abort(404)
    path.unlink()
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# PDF Tools: a broader local toolkit (merge, split, compress, protect, etc.)
# ---------------------------------------------------------------------------

def _run_compress(src, out, _form):
    pdf_tools.compress_pdf(src, out)


def _run_repair(src, out, _form):
    pdf_tools.repair_pdf(src, out)


def _run_ocr(src, out, _form):
    pdf_tools.ocr_pdf(src, out)


def _run_rotate(src, out, form):
    try:
        degrees = int(form.get("degrees", 90))
    except ValueError:
        degrees = 90
    if degrees not in (90, 180, 270):
        degrees = 90
    pdf_tools.rotate_pdf(src, degrees, out)


def _run_unlock(src, out, form):
    password = form.get("password", "")
    if not password:
        abort(400, "Password is required")
    pdf_tools.unlock_pdf(src, password, out)


def _run_protect(src, out, form):
    password = form.get("password", "")
    if not password:
        abort(400, "Password is required")
    pdf_tools.protect_pdf(src, password, out)


def _run_page_numbers(src, out, form):
    position = form.get("position", "bottom-center")
    if position not in pdf_tools._PAGE_NUMBER_POSITIONS:
        position = "bottom-center"
    pdf_tools.add_page_numbers(src, out, position)


def _run_office_to_pdf(src, out, _form):
    produced = pdf_tools.office_to_pdf(src)
    Path(produced).replace(out)


def _run_pdf_to_pdfa(src, out, _form):
    pdf_tools.pdf_to_pdfa(src, out)


def _run_pdf_to_markdown(src, out, _form):
    Path(out).write_text(pdf_tools.pdf_to_markdown(src), encoding="utf-8")


def _run_sort_excel(src, out, form):
    mode = form.get("mode", "rows")
    if mode not in ("rows", "tabs", "both"):
        mode = "rows"
    excel_tools.sort_workbook(
        src,
        out,
        mode=mode,
        column=form.get("column", ""),
        descending=form.get("order") == "desc",
        has_header=form.get("has_header", "yes") == "yes",
    )


def _run_word_to_excel(src, out, _form):
    excel_tools.docx_tables_to_xlsx(src, out)


def _run_pdf_to_excel(src, out, _form):
    excel_tools.pdf_tables_to_xlsx(src, out)


def _run_image_to_excel(src, out, _form):
    excel_tools.image_table_to_xlsx(src, out)


TOOL_REGISTRY = {
    "compress-pdf": {
        "label": "Compress PDF",
        "hint": "Reduce file size",
        "category": "Optimize",
        "icon": "icon-compress",
        "accept": ".pdf",
        "fields": [],
        "run": _run_compress,
        "out_suffix": "-compressed",
    },
    "repair-pdf": {
        "label": "Repair PDF",
        "hint": "Recover a damaged or corrupted PDF",
        "category": "Optimize",
        "icon": "icon-wrench",
        "accept": ".pdf",
        "fields": [],
        "run": _run_repair,
        "out_suffix": "-repaired",
    },
    "ocr-pdf": {
        "label": "OCR PDF",
        "hint": "Make a scanned PDF searchable and selectable",
        "category": "Optimize",
        "icon": "icon-search",
        "accept": ".pdf",
        "fields": [],
        "run": _run_ocr,
        "out_suffix": "-ocr",
    },
    "rotate-pdf": {
        "label": "Rotate PDF",
        "hint": "Rotate every page",
        "category": "Edit",
        "icon": "icon-refresh",
        "accept": ".pdf",
        "fields": [
            {
                "name": "degrees",
                "type": "select",
                "label": "Rotate by",
                "options": [("90", "90°"), ("180", "180°"), ("270", "270°")],
            },
        ],
        "run": _run_rotate,
        "out_suffix": "-rotated",
    },
    "unlock-pdf": {
        "label": "Unlock PDF",
        "hint": "Remove a known password",
        "category": "Security",
        "icon": "icon-unlock",
        "accept": ".pdf",
        "fields": [{"name": "password", "type": "password", "label": "Current password"}],
        "run": _run_unlock,
        "out_suffix": "-unlocked",
    },
    "protect-pdf": {
        "label": "Protect PDF",
        "hint": "Encrypt with a password",
        "category": "Security",
        "icon": "icon-lock",
        "accept": ".pdf",
        "fields": [{"name": "password", "type": "password", "label": "New password"}],
        "run": _run_protect,
        "out_suffix": "-protected",
    },
    "add-page-numbers": {
        "label": "Add Page Numbers",
        "hint": "Stamp page numbers on every page",
        "category": "Edit",
        "icon": "icon-hash",
        "accept": ".pdf",
        "fields": [
            {
                "name": "position",
                "type": "select",
                "label": "Position",
                "options": [
                    ("bottom-center", "Bottom center"),
                    ("bottom-right", "Bottom right"),
                    ("bottom-left", "Bottom left"),
                    ("top-center", "Top center"),
                ],
            },
        ],
        "run": _run_page_numbers,
        "out_suffix": "-numbered",
    },
    "office-to-pdf": {
        "label": "Office to PDF",
        "hint": "Convert Word, PowerPoint, or Excel files to PDF",
        "category": "Convert",
        "icon": "icon-refresh",
        "accept": ".docx,.pptx,.xlsx",
        "fields": [],
        "run": _run_office_to_pdf,
        "out_suffix": "",
    },
    "pdf-to-pdfa": {
        "label": "PDF to PDF/A",
        "hint": "Convert to the ISO archival PDF/A format",
        "category": "Convert",
        "icon": "icon-archive",
        "accept": ".pdf",
        "fields": [],
        "run": _run_pdf_to_pdfa,
        "out_suffix": "-pdfa",
    },
    "pdf-to-markdown": {
        "label": "PDF to Markdown",
        "hint": "Headings, tables, lists, and links preserved",
        "category": "Convert",
        "icon": "icon-file-docx",
        "accept": ".pdf",
        "fields": [],
        "run": _run_pdf_to_markdown,
        "out_suffix": "",
        "out_ext": ".md",
    },
    "sort-excel": {
        "label": "Auto-Sort Excel",
        "hint": "Sort the rows on every sheet, the sheet tabs A–Z, or both",
        "category": "Excel",
        "icon": "icon-sort",
        "accept": ".xlsx",
        "fields": [
            {
                "name": "mode",
                "type": "select",
                "label": "What to sort",
                "options": [("rows", "Rows on every sheet"), ("tabs", "Sheet tabs A–Z"), ("both", "Both")],
            },
            {
                "name": "column",
                "type": "text",
                "label": "Sort by column (letter or header name, blank = first column)",
            },
            {
                "name": "order",
                "type": "select",
                "label": "Order",
                "options": [("asc", "Ascending (A–Z, 0–9)"), ("desc", "Descending (Z–A, 9–0)")],
            },
            {
                "name": "has_header",
                "type": "select",
                "label": "First row is a header",
                "options": [("yes", "Yes - keep it at the top"), ("no", "No")],
            },
        ],
        "run": _run_sort_excel,
        "out_suffix": "-sorted",
        "out_ext": ".xlsx",
    },
    "word-to-excel": {
        "label": "Word to Excel",
        "hint": "Every table in the document becomes its own sheet",
        "category": "Excel",
        "icon": "icon-table",
        "accept": ".docx",
        "fields": [],
        "run": _run_word_to_excel,
        "out_suffix": "",
        "out_ext": ".xlsx",
    },
    "pdf-to-excel": {
        "label": "PDF to Excel",
        "hint": "Tables become sheets. Scanned pages use OCR, so check the results",
        "category": "Excel",
        "icon": "icon-table",
        "accept": ".pdf",
        "fields": [],
        "run": _run_pdf_to_excel,
        "out_suffix": "",
        "out_ext": ".xlsx",
    },
    "image-to-excel": {
        "label": "Image to Excel",
        "hint": "Read a table from a photo or screenshot (OCR, so check the results)",
        "category": "Excel",
        "icon": "icon-table",
        "accept": ".png,.jpg,.jpeg",
        "fields": [],
        "run": _run_image_to_excel,
        "out_suffix": "",
        "out_ext": ".xlsx",
    },
}

# Metadata only, for the hub grid - these have their own bespoke routes/templates.
BESPOKE_TOOLS_META = {
    "merge-pdf": {"label": "Merge PDF", "hint": "Combine PDFs into one", "category": "Organize", "icon": "icon-merge"},
    "split-pdf": {"label": "Split PDF", "hint": "Split into multiple files", "category": "Organize", "icon": "icon-split"},
    "organize-pdf": {"label": "Organize PDF", "hint": "Reorder, delete, and rotate pages", "category": "Organize", "icon": "icon-grid"},
    "watermark-pdf": {"label": "Watermark PDF", "hint": "Stamp text or an image on every page", "category": "Edit", "icon": "icon-droplet"},
    "crop-pdf": {"label": "Crop PDF", "hint": "Trim page margins", "category": "Edit", "icon": "icon-crop"},
    "redact-pdf": {"label": "Redact PDF", "hint": "Permanently remove sensitive content", "category": "Security", "icon": "icon-eye-off"},
    "pdf-to-jpg": {"label": "PDF to JPG", "hint": "Export pages as images", "category": "Convert", "icon": "icon-image"},
    "jpg-to-pdf": {"label": "JPG to PDF", "hint": "Combine images into a PDF", "category": "Convert", "icon": "icon-image"},
    "html-to-pdf": {"label": "HTML to PDF", "hint": "Convert a webpage or pasted HTML to PDF", "category": "Convert", "icon": "icon-globe"},
    "compare-pdf": {"label": "Compare PDF", "hint": "Side-by-side diff between two PDFs", "category": "Security", "icon": "icon-columns"},
    "edit-pdf": {"label": "Edit PDF", "hint": "Add text, images, shapes, or freehand marks", "category": "Edit", "icon": "icon-edit"},
    "pdf-forms": {"label": "PDF Forms", "hint": "Fill existing fields, or create new ones", "category": "Edit", "icon": "icon-grid"},
}

_CATEGORY_ORDER = ["Organize", "Optimize", "Convert", "Excel", "Edit", "Security"]


@app.route("/tools")
def tools_hub():
    categories = {name: [] for name in _CATEGORY_ORDER}
    for slug, cfg in TOOL_REGISTRY.items():
        categories[cfg["category"]].append({"slug": slug, **cfg})
    for slug, meta in BESPOKE_TOOLS_META.items():
        categories[meta["category"]].append({"slug": slug, **meta})
    for tools in categories.values():
        tools.sort(key=lambda t: t["label"])
    return render_template("tools_hub.html", categories=categories, category_order=_CATEGORY_ORDER)


@app.route("/tools/<slug>", methods=["GET", "POST"])
def tool_simple(slug):
    cfg = TOOL_REGISTRY.get(slug)
    if cfg is None:
        abort(404)

    if request.method == "GET":
        return render_template("tool_simple.html", slug=slug, cfg=cfg)

    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")

    accepted_exts = tuple(cfg["accept"].split(","))
    if not file.filename.lower().endswith(accepted_exts):
        abort(400, f"File must be one of: {cfg['accept']}")
    if ".pdf" in accepted_exts and not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")
    if any(ext in _OFFICE_EXTENSIONS for ext in accepted_exts) and not _looks_like_office_doc(file):
        abort(400, "That file doesn't look like a valid Office document")
    if any(ext in _IMAGE_EXTENSIONS for ext in accepted_exts) and not _looks_like_image(file):
        abort(400, "That file doesn't look like a valid JPG or PNG image")

    safe_name = secure_filename(file.filename)
    stem, src_ext = Path(safe_name).stem, Path(safe_name).suffix
    with tempfile.NamedTemporaryFile(suffix=src_ext, delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    out_name = f"{stem}{cfg['out_suffix']}{cfg.get('out_ext', '.pdf')}"
    out_path = _unique_path(DOCUMENTS_DIR, out_name)

    try:
        cfg["run"](tmp_path, str(out_path), request.form)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return send_from_directory(DOCUMENTS_DIR, out_path.name, as_attachment=True)


# --- Bespoke tools (custom UI beyond a single file + one field) -----------

@app.route("/tools/merge-pdf", methods=["GET", "POST"])
def merge_pdf():
    if request.method == "GET":
        return render_template("merge.html")

    files = request.files.getlist("files")
    if len(files) < 2:
        abort(400, "Select at least two PDFs to merge")

    tmp_paths = []
    try:
        for f in files:
            if not f.filename.lower().endswith(".pdf") or not _looks_like_pdf(f):
                abort(400, "All files must be valid PDFs")
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                f.save(tmp.name)
                tmp_paths.append(tmp.name)

        out_path = _unique_path(DOCUMENTS_DIR, "merged.pdf")
        pdf_tools.merge_pdfs(tmp_paths, str(out_path))
    finally:
        for p in tmp_paths:
            Path(p).unlink(missing_ok=True)

    return send_from_directory(DOCUMENTS_DIR, out_path.name, as_attachment=True)


def _parse_ranges(raw: str, page_count: int) -> list[tuple[int, int]]:
    ranges = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a) - 1, int(b) - 1
        else:
            start = end = int(part) - 1
        if start < 0 or end >= page_count or start > end:
            raise ValueError(f"Invalid range: {part}")
        ranges.append((start, end))
    if not ranges:
        raise ValueError("No valid page ranges given")
    return ranges


@app.route("/tools/split-pdf", methods=["GET", "POST"])
def split_pdf_route():
    if request.method == "GET":
        return render_template("split.html")

    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf") or not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    stem = Path(secure_filename(file.filename)).stem
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    tmp_outdir = tempfile.mkdtemp()
    try:
        page_count = converters.get_pdf_page_count(tmp_path)
        try:
            ranges = _parse_ranges(request.form.get("ranges", ""), page_count)
        except ValueError as e:
            abort(400, str(e))

        outputs = pdf_tools.split_pdf(tmp_path, ranges, tmp_outdir, stem)
        if not outputs:
            abort(400, "No pages matched the given ranges")

        if len(outputs) == 1:
            out_path = _unique_path(DOCUMENTS_DIR, f"{stem}-part1.pdf")
            Path(outputs[0]).replace(out_path)
            return send_from_directory(DOCUMENTS_DIR, out_path.name, as_attachment=True)

        zip_path = _unique_path(DOCUMENTS_DIR, f"{stem}-split.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in outputs:
                zf.write(p, arcname=Path(p).name)
        return send_from_directory(DOCUMENTS_DIR, zip_path.name, as_attachment=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        shutil.rmtree(tmp_outdir, ignore_errors=True)


@app.route("/tools/organize-pdf", methods=["GET", "POST"])
def organize_pdf_upload():
    if request.method == "GET":
        return render_template("organize_upload.html")

    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf") or not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    filename = secure_filename(file.filename)
    out_path = _unique_path(DOCUMENTS_DIR, filename)
    file.save(out_path)
    return redirect(f"/tools/organize-pdf/{out_path.name}")


@app.route("/tools/organize-pdf/<filename>")
def organize_pdf_editor(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    page_count = converters.get_pdf_page_count(str(path))
    return render_template("organize.html", filename=filename, page_count=page_count)


@app.route("/tools/organize-pdf/<filename>", methods=["POST"])
def organize_pdf_save(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    data = request.get_json(silent=True) or {}
    raw_plan = data.get("pages")
    if not raw_plan:
        abort(400, "No pages provided")
    try:
        page_plan = [
            {"index": int(p["index"]), "rotation": int(p.get("rotation", 0)) % 360}
            for p in raw_plan
        ]
    except (KeyError, TypeError, ValueError):
        abort(400, "Invalid page plan")

    out_path = path.with_name(path.stem + "-organized.pdf")
    pdf_tools.reorder_pdf(str(path), page_plan, str(out_path))
    return jsonify({"status": "ok", "pdf_filename": out_path.name})


@app.route("/tools/watermark-pdf", methods=["GET", "POST"])
def watermark_pdf_upload():
    if request.method == "GET":
        return render_template("watermark_upload.html")

    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf") or not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    filename = secure_filename(file.filename)
    out_path = _unique_path(DOCUMENTS_DIR, filename)
    file.save(out_path)
    return redirect(f"/tools/watermark-pdf/{out_path.name}")


@app.route("/tools/watermark-pdf/<filename>", methods=["GET", "POST"])
def watermark_pdf_configure(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)

    if request.method == "GET":
        return render_template("watermark.html", filename=filename)

    text = request.form.get("text", "").strip()
    image_file = request.files.get("image")
    try:
        opacity = float(request.form.get("opacity", 0.3))
    except ValueError:
        opacity = 0.3
    opacity = max(0.05, min(1.0, opacity))

    image_bytes = None
    if image_file and image_file.filename:
        if not _looks_like_image(image_file):
            abort(400, "That doesn't look like a valid image")
        image_bytes = image_file.read()

    if not text and not image_bytes:
        abort(400, "Provide watermark text or an image")

    out_path = path.with_name(path.stem + "-watermarked.pdf")
    pdf_tools.watermark_pdf(
        str(path), str(out_path), text=text or None, image_bytes=image_bytes, opacity=opacity
    )
    return send_from_directory(DOCUMENTS_DIR, out_path.name, as_attachment=True)


@app.route("/tools/crop-pdf", methods=["GET", "POST"])
def crop_pdf_upload():
    if request.method == "GET":
        return render_template("crop_upload.html")

    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf") or not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    filename = secure_filename(file.filename)
    out_path = _unique_path(DOCUMENTS_DIR, filename)
    file.save(out_path)
    return redirect(f"/tools/crop-pdf/{out_path.name}")


@app.route("/tools/crop-pdf/<filename>")
def crop_pdf_editor(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    return render_template("crop.html", filename=filename)


@app.route("/tools/crop-pdf/<filename>", methods=["POST"])
def crop_pdf_save(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    data = request.get_json(silent=True) or {}
    try:
        rect = (float(data["x"]), float(data["y"]), float(data["width"]), float(data["height"]))
    except (KeyError, TypeError, ValueError):
        abort(400, "Invalid crop rectangle")

    out_path = path.with_name(path.stem + "-cropped.pdf")
    pdf_tools.crop_pdf(str(path), rect, str(out_path))
    return jsonify({"status": "ok", "pdf_filename": out_path.name})


@app.route("/tools/redact-pdf", methods=["GET", "POST"])
def redact_pdf_upload():
    if request.method == "GET":
        return render_template("redact_upload.html")

    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf") or not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    filename = secure_filename(file.filename)
    out_path = _unique_path(DOCUMENTS_DIR, filename)
    file.save(out_path)
    return redirect(f"/tools/redact-pdf/{out_path.name}")


@app.route("/tools/redact-pdf/<filename>")
def redact_pdf_editor(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    page_count = converters.get_pdf_page_count(str(path))
    return render_template("redact.html", filename=filename, page_count=page_count)


@app.route("/tools/redact-pdf/<filename>", methods=["POST"])
def redact_pdf_save(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    data = request.get_json(silent=True) or {}
    raw_regions = data.get("regions")
    if not raw_regions:
        abort(400, "No redaction regions provided")
    if len(raw_regions) > 50:
        abort(400, "Too many redaction regions")
    try:
        regions = [
            {
                "page": int(r["page"]),
                "x": float(r["x"]),
                "y": float(r["y"]),
                "width": float(r["width"]),
                "height": float(r["height"]),
            }
            for r in raw_regions
        ]
    except (KeyError, TypeError, ValueError):
        abort(400, "Invalid redaction payload")

    out_path = path.with_name(path.stem + "-redacted.pdf")
    pdf_tools.redact_pdf(str(path), regions, str(out_path))
    return jsonify({"status": "ok", "pdf_filename": out_path.name})


@app.route("/tools/pdf-to-jpg", methods=["GET", "POST"])
def pdf_to_jpg():
    if request.method == "GET":
        return render_template("pdf_to_jpg.html")

    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf") or not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    stem = Path(secure_filename(file.filename)).stem
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    tmp_outdir = tempfile.mkdtemp()
    try:
        images = pdf_tools.pdf_to_jpgs(tmp_path, tmp_outdir, stem)
        if len(images) == 1:
            out_path = _unique_path(DOCUMENTS_DIR, f"{stem}.jpg")
            Path(images[0]).replace(out_path)
            return send_from_directory(DOCUMENTS_DIR, out_path.name, as_attachment=True)

        zip_path = _unique_path(DOCUMENTS_DIR, f"{stem}-images.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in images:
                zf.write(p, arcname=Path(p).name)
        return send_from_directory(DOCUMENTS_DIR, zip_path.name, as_attachment=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        shutil.rmtree(tmp_outdir, ignore_errors=True)


@app.route("/tools/jpg-to-pdf", methods=["GET", "POST"])
def jpg_to_pdf():
    if request.method == "GET":
        return render_template("jpg_to_pdf.html")

    files = request.files.getlist("files")
    if not files:
        abort(400, "Select at least one image")

    tmp_paths = []
    try:
        for f in files:
            if not f.filename.lower().endswith((".jpg", ".jpeg", ".png")) or not _looks_like_image(f):
                abort(400, "All files must be valid JPG/PNG images")
            suffix = Path(secure_filename(f.filename)).suffix
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                f.save(tmp.name)
                tmp_paths.append(tmp.name)

        out_path = _unique_path(DOCUMENTS_DIR, "images.pdf")
        pdf_tools.images_to_pdf(tmp_paths, str(out_path))
    finally:
        for p in tmp_paths:
            Path(p).unlink(missing_ok=True)

    return send_from_directory(DOCUMENTS_DIR, out_path.name, as_attachment=True)


@app.route("/tools/html-to-pdf", methods=["GET", "POST"])
def html_to_pdf():
    if request.method == "GET":
        return render_template("html_to_pdf.html")

    url = request.form.get("url", "").strip()
    pasted_html = request.form.get("html", "").strip()

    if pasted_html:
        html_content = pasted_html
        base_name = "pasted-page"
    elif url:
        if not (url.startswith("http://") or url.startswith("https://")):
            abort(400, "URL must start with http:// or https://")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                raw = response.read(10 * 1024 * 1024 + 1)
                if len(raw) > 10 * 1024 * 1024:
                    abort(400, "Page too large (over 10MB)")
                charset = response.headers.get_content_charset() or "utf-8"
                html_content = raw.decode(charset, errors="replace")
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as e:
            abort(400, f"Could not fetch that URL: {e}")
        base_name = secure_filename(url.split("//", 1)[-1].split("/")[0]) or "webpage"
    else:
        abort(400, "Provide a URL or paste HTML")

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as tmp:
        tmp.write(html_content)
        tmp_path = tmp.name

    try:
        produced = pdf_tools.office_to_pdf(tmp_path)
        out_path = _unique_path(DOCUMENTS_DIR, f"{base_name}.pdf")
        Path(produced).replace(out_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return send_from_directory(DOCUMENTS_DIR, out_path.name, as_attachment=True)


@app.route("/tools/compare-pdf", methods=["GET", "POST"])
def compare_pdf():
    if request.method == "GET":
        return render_template("compare_upload.html")

    file_a = request.files.get("file_a")
    file_b = request.files.get("file_b")
    if not file_a or not file_b or file_a.filename == "" or file_b.filename == "":
        abort(400, "Select two PDF files to compare")
    for f in (file_a, file_b):
        if not f.filename.lower().endswith(".pdf") or not _looks_like_pdf(f):
            abort(400, "Both files must be valid PDFs")

    tmp_paths = []
    try:
        for f in (file_a, file_b):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                f.save(tmp.name)
                tmp_paths.append(tmp.name)
        lines_a = pdf_tools.extract_text_lines(tmp_paths[0])
        lines_b = pdf_tools.extract_text_lines(tmp_paths[1])
    finally:
        for p in tmp_paths:
            Path(p).unlink(missing_ok=True)

    diff_table = difflib.HtmlDiff(wrapcolumn=80).make_table(
        lines_a, lines_b, fromdesc=file_a.filename, todesc=file_b.filename, context=True, numlines=3
    )
    return render_template(
        "compare_result.html", diff_table=diff_table, name_a=file_a.filename, name_b=file_b.filename
    )


@app.route("/tools/edit-pdf", methods=["GET", "POST"])
def edit_pdf_upload():
    if request.method == "GET":
        return render_template("edit_pdf_upload.html")

    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf") or not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    filename = secure_filename(file.filename)
    out_path = _unique_path(DOCUMENTS_DIR, filename)
    file.save(out_path)
    return redirect(f"/tools/edit-pdf/{out_path.name}")


@app.route("/tools/edit-pdf/<filename>")
def edit_pdf_editor(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    page_count = converters.get_pdf_page_count(str(path))
    return render_template("edit_pdf.html", filename=filename, page_count=page_count)


@app.route("/tools/edit-pdf/<filename>", methods=["POST"])
def edit_pdf_save(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    data = request.get_json(silent=True) or {}
    raw_elements = data.get("elements")
    if not raw_elements:
        abort(400, "No elements provided")
    if len(raw_elements) > 200:
        abort(400, "Too many elements in one request")

    elements = []
    try:
        for el in raw_elements:
            kind = el["type"]
            if kind not in ("text", "image", "rect", "freehand"):
                abort(400, "Invalid element type")
            entry = {"type": kind, "page": int(el["page"])}
            if kind == "freehand":
                points = el.get("points", [])
                if len(points) > 2000:
                    abort(400, "Freehand path too long")
                entry["points"] = [[float(p[0]), float(p[1])] for p in points]
                entry["color"] = str(el.get("color", "#000000"))[:16]
                entry["stroke_width"] = float(el.get("stroke_width", 2))
            else:
                entry["x"] = float(el["x"])
                entry["y"] = float(el["y"])
                entry["width"] = float(el.get("width", 0.1))
                entry["height"] = float(el.get("height", 0.05))
                if kind == "text":
                    entry["text"] = str(el.get("text", ""))[:2000]
                    entry["font_size"] = float(el.get("font_size", 14))
                    entry["font"] = str(el.get("font", "helvetica"))
                    entry["color"] = str(el.get("color", "#000000"))[:16]
                elif kind == "rect":
                    entry["color"] = str(el.get("color", "#000000"))[:16]
                    entry["fill"] = bool(el.get("fill"))
                elif kind == "image":
                    _, _, b64 = el["image_data"].partition(",")
                    if not b64:
                        abort(400, "Invalid image data")
                    image_bytes = base64.b64decode(b64)
                    if len(image_bytes) > 5 * 1024 * 1024:
                        abort(400, "Image too large")
                    entry["image_bytes"] = image_bytes
            elements.append(entry)
    except (KeyError, TypeError, ValueError):
        abort(400, "Invalid element payload")

    out_path = path.with_name(path.stem + "-edited.pdf")
    pdf_tools.apply_edits(str(path), elements, str(out_path))
    return jsonify({"status": "ok", "pdf_filename": out_path.name})


@app.route("/tools/pdf-forms", methods=["GET", "POST"])
def pdf_forms_upload():
    if request.method == "GET":
        return render_template("pdf_forms_upload.html")

    file = request.files.get("file")
    if not file or file.filename == "":
        abort(400, "No file selected")
    if not file.filename.lower().endswith(".pdf") or not _looks_like_pdf(file):
        abort(400, "That file doesn't look like a valid PDF")

    filename = secure_filename(file.filename)
    out_path = _unique_path(DOCUMENTS_DIR, filename)
    file.save(out_path)
    return redirect(f"/tools/pdf-forms/{out_path.name}")


@app.route("/tools/pdf-forms/<filename>")
def pdf_forms_editor(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    page_count = converters.get_pdf_page_count(str(path))
    mode = "fill" if pdf_tools.has_form_fields(str(path)) else "create"
    existing_fields = pdf_tools.get_form_fields(str(path)) if mode == "fill" else []
    return render_template(
        "pdf_forms.html",
        filename=filename,
        page_count=page_count,
        mode=mode,
        existing_fields=existing_fields,
    )


@app.route("/tools/pdf-forms/<filename>", methods=["POST"])
def pdf_forms_save(filename):
    path = safe_path(filename, (".pdf",))
    if not path.exists():
        abort(404)
    data = request.get_json(silent=True) or {}
    mode = data.get("mode")

    if mode == "fill":
        values = data.get("values")
        if not isinstance(values, dict):
            abort(400, "Invalid values payload")
        out_path = path.with_name(path.stem + "-filled.pdf")
        pdf_tools.fill_form_fields(str(path), values, str(out_path))
    elif mode == "create":
        raw_fields = data.get("fields")
        if not raw_fields:
            abort(400, "No fields provided")
        if len(raw_fields) > 100:
            abort(400, "Too many fields in one request")
        fields = []
        try:
            for f in raw_fields:
                field_type = f.get("type", "text")
                if field_type not in ("text", "checkbox", "dropdown"):
                    abort(400, "Invalid field type")
                entry = {
                    "page": int(f["page"]),
                    "x": float(f["x"]),
                    "y": float(f["y"]),
                    "width": float(f.get("width", 0.2)),
                    "height": float(f.get("height", 0.04)),
                    "type": field_type,
                    "name": str(f.get("name") or "")[:100],
                }
                if field_type == "dropdown":
                    entry["options"] = [str(o)[:50] for o in f.get("options", [])][:20]
                fields.append(entry)
        except (KeyError, TypeError, ValueError):
            abort(400, "Invalid field payload")
        out_path = path.with_name(path.stem + "-form.pdf")
        pdf_tools.add_form_fields(str(path), fields, str(out_path))
    else:
        abort(400, "Invalid mode")

    return jsonify({"status": "ok", "pdf_filename": out_path.name})


@app.errorhandler(RuntimeError)
@app.errorhandler(ValueError)
@app.errorhandler(OSError)
@app.errorhandler(subprocess.CalledProcessError)
def _handle_processing_error(error):
    """A malformed/corrupted file (or a bad password, etc.) tripped up one of
    the converters - fail cleanly with a 400 instead of a raw traceback.

    Note: must *return* a response here, not call abort() - abort() raises a
    new exception, which inside an errorhandler propagates as unhandled and
    falls through to Flask's generic 500 page instead of the 400 we want.
    """
    message = str(error) or "Could not process this file - it may be corrupted or in an unexpected format."
    return message, 400


if __name__ == "__main__":
    # Debug mode (auto-reload + interactive in-browser debugger) is opt-in only,
    # via FLASK_DEBUG=1. Left on by default, the interactive debugger would show
    # full stack traces and a live Python shell to whoever hits an error page -
    # fine while you're actively developing, not something that should run
    # unattended day to day.
    debug_mode = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
