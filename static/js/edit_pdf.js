const filename = window.PDF_FILENAME;
const pageCount = window.PAGE_COUNT;
let currentPage = 0;
let currentMode = "text";

const pageImage = document.getElementById("page-image");
const pageContainer = document.getElementById("page-container");
const pageIndicator = document.getElementById("page-indicator");
const prevBtn = document.getElementById("prev-page");
const nextBtn = document.getElementById("next-page");
const statusEl = document.getElementById("status");
const saveBtn = document.getElementById("save-btn");
const freehandCanvas = document.getElementById("freehand-canvas");
const freehandCtx = freehandCanvas.getContext("2d");

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("status-error", isError);
}

// boxElements: placed text/image/rect overlays -> { type, page, el, data }
// freehandStrokes: completed freehand strokes -> { page, points, color, strokeWidth }
let boxElements = [];
let freehandStrokes = [];

function resizeFreehandCanvas() {
  freehandCanvas.width = pageImage.clientWidth;
  freehandCanvas.height = pageImage.clientHeight;
}

function redrawFreehandCanvas() {
  freehandCtx.clearRect(0, 0, freehandCanvas.width, freehandCanvas.height);
  freehandStrokes
    .filter((s) => s.page === currentPage)
    .forEach((stroke) => {
      if (stroke.points.length < 2) return;
      freehandCtx.strokeStyle = stroke.color;
      freehandCtx.lineWidth = stroke.strokeWidth;
      freehandCtx.lineCap = "round";
      freehandCtx.lineJoin = "round";
      freehandCtx.beginPath();
      const [x0, y0] = stroke.points[0];
      freehandCtx.moveTo(x0 * freehandCanvas.width, y0 * freehandCanvas.height);
      for (const [x, y] of stroke.points.slice(1)) {
        freehandCtx.lineTo(x * freehandCanvas.width, y * freehandCanvas.height);
      }
      freehandCtx.stroke();
    });
}

function refreshForPage() {
  boxElements.forEach((item) => {
    item.el.style.display = item.page === currentPage ? "" : "none";
  });
  redrawFreehandCanvas();
}

function loadPage(page) {
  currentPage = page;
  pageIndicator.textContent = `Page ${page + 1} of ${pageCount}`;
  pageImage.onload = () => {
    resizeFreehandCanvas();
    refreshForPage();
  };
  pageImage.src = `/page-image/${encodeURIComponent(filename)}/${page}`;
}

prevBtn.addEventListener("click", () => {
  if (currentPage > 0) loadPage(currentPage - 1);
});
nextBtn.addEventListener("click", () => {
  if (currentPage < pageCount - 1) loadPage(currentPage + 1);
});
loadPage(0);

window.addEventListener("resize", () => {
  resizeFreehandCanvas();
  redrawFreehandCanvas();
});

// --- mode switching ---
const modeButtons = document.querySelectorAll(".edit-mode-btn");
const optionPanels = {
  text: document.getElementById("text-options"),
  image: document.getElementById("image-options"),
  rect: document.getElementById("rect-options"),
  freehand: document.getElementById("freehand-options"),
};
modeButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    currentMode = btn.dataset.mode;
    modeButtons.forEach((b) => b.classList.toggle("active", b === btn));
    Object.entries(optionPanels).forEach(([mode, panel]) => {
      panel.hidden = mode !== currentMode;
    });
    freehandCanvas.style.pointerEvents = currentMode === "freehand" ? "auto" : "none";
  });
});
freehandCanvas.style.pointerEvents = "none";

// --- pending image (read once selected, used at placement time) ---
let pendingImageDataUrl = null;
document.getElementById("image-file").addEventListener("change", (evt) => {
  const file = evt.target.files[0];
  if (!file) {
    pendingImageDataUrl = null;
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    pendingImageDataUrl = reader.result;
  };
  reader.readAsDataURL(file);
});

// --- click-drag placement for text/image/rect ---
let drawing = false;
let startX, startY;
let drawEl = null;

function containerPoint(evt) {
  const rect = pageContainer.getBoundingClientRect();
  return [evt.clientX - rect.left, evt.clientY - rect.top];
}

pageContainer.addEventListener("pointerdown", (evt) => {
  if (currentMode === "freehand") return;
  if (evt.target.closest(".editable-item")) return;
  drawing = true;
  [startX, startY] = containerPoint(evt);
  drawEl = document.createElement("div");
  drawEl.className = "editable-item";
  drawEl.style.left = `${startX}px`;
  drawEl.style.top = `${startY}px`;
  pageContainer.appendChild(drawEl);
});

pageContainer.addEventListener("pointermove", (evt) => {
  if (!drawing || !drawEl) return;
  const [x, y] = containerPoint(evt);
  const left = Math.min(startX, x);
  const top = Math.min(startY, y);
  drawEl.style.left = `${left}px`;
  drawEl.style.top = `${top}px`;
  drawEl.style.width = `${Math.abs(x - startX)}px`;
  drawEl.style.height = `${Math.abs(y - startY)}px`;
});

window.addEventListener("pointerup", () => {
  if (drawing && drawEl) {
    if (drawEl.offsetWidth < 10 || drawEl.offsetHeight < 10) {
      drawEl.remove();
    } else {
      finalizeBoxElement(drawEl);
    }
  }
  drawing = false;
  drawEl = null;
});

function finalizeBoxElement(el) {
  const mode = currentMode;
  if (mode === "image" && !pendingImageDataUrl) {
    setStatus("Choose an image first", true);
    el.remove();
    return;
  }

  el.classList.add(`${mode}-item`);
  const data = {};

  if (mode === "text") {
    const text = document.getElementById("text-value").value || "Text";
    data.text = text;
    data.font_size = Number(document.getElementById("text-font-size").value) || 16;
    data.font = document.getElementById("text-font").value;
    data.color = document.getElementById("text-color").value;
    el.textContent = text;
    el.style.fontSize = `${Math.max(8, data.font_size * 0.75)}px`;
    el.style.color = data.color;
  } else if (mode === "image") {
    data.image_data = pendingImageDataUrl;
    const img = document.createElement("img");
    img.src = pendingImageDataUrl;
    img.style.width = "100%";
    img.style.height = "100%";
    img.style.pointerEvents = "none";
    el.appendChild(img);
  } else if (mode === "rect") {
    data.color = document.getElementById("rect-color").value;
    data.fill = document.getElementById("rect-fill").checked;
    el.style.borderColor = data.color;
    if (data.fill) {
      el.style.background = data.color;
      el.style.opacity = "0.5";
    }
  }

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "redact-region-remove";
  removeBtn.setAttribute("aria-label", "Remove");
  removeBtn.textContent = "×";
  removeBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    el.remove();
    boxElements = boxElements.filter((item) => item.el !== el);
  });
  el.appendChild(removeBtn);

  const handle = document.createElement("div");
  handle.className = "resize-handle";
  el.appendChild(handle);
  makeAdjustable(el, handle);

  boxElements.push({ type: mode, page: currentPage, el, data });
}

function makeAdjustable(el, handle) {
  let mode = null;
  let sX, sY, sLeft, sTop, sWidth, sHeight;

  el.addEventListener("pointerdown", (evt) => {
    if (evt.target === handle || evt.target.closest(".redact-region-remove")) return;
    evt.stopPropagation();
    mode = "drag";
    sX = evt.clientX;
    sY = evt.clientY;
    sLeft = el.offsetLeft;
    sTop = el.offsetTop;
  });

  handle.addEventListener("pointerdown", (evt) => {
    evt.stopPropagation();
    mode = "resize";
    sX = evt.clientX;
    sY = evt.clientY;
    sWidth = el.offsetWidth;
    sHeight = el.offsetHeight;
  });

  window.addEventListener("pointermove", (evt) => {
    if (!mode) return;
    const dx = evt.clientX - sX;
    const dy = evt.clientY - sY;
    if (mode === "drag") {
      const containerRect = pageContainer.getBoundingClientRect();
      const newLeft = Math.max(0, Math.min(sLeft + dx, containerRect.width - el.offsetWidth));
      const newTop = Math.max(0, Math.min(sTop + dy, containerRect.height - el.offsetHeight));
      el.style.left = `${newLeft}px`;
      el.style.top = `${newTop}px`;
    } else if (mode === "resize") {
      el.style.width = `${Math.max(10, sWidth + dx)}px`;
      el.style.height = `${Math.max(10, sHeight + dy)}px`;
    }
  });

  window.addEventListener("pointerup", () => {
    mode = null;
  });
}

// --- freehand drawing ---
let freehandDrawing = false;
let currentStroke = null;

function addFreehandPoint(evt) {
  const rect = freehandCanvas.getBoundingClientRect();
  const x = (evt.clientX - rect.left) / rect.width;
  const y = (evt.clientY - rect.top) / rect.height;
  currentStroke.points.push([x, y]);
  if (currentStroke.points.length >= 2) {
    const [px, py] = currentStroke.points[currentStroke.points.length - 2];
    const [cx, cy] = currentStroke.points[currentStroke.points.length - 1];
    freehandCtx.strokeStyle = currentStroke.color;
    freehandCtx.lineWidth = currentStroke.strokeWidth;
    freehandCtx.lineCap = "round";
    freehandCtx.beginPath();
    freehandCtx.moveTo(px * freehandCanvas.width, py * freehandCanvas.height);
    freehandCtx.lineTo(cx * freehandCanvas.width, cy * freehandCanvas.height);
    freehandCtx.stroke();
  }
}

freehandCanvas.addEventListener("pointerdown", (evt) => {
  if (currentMode !== "freehand") return;
  freehandDrawing = true;
  currentStroke = {
    page: currentPage,
    points: [],
    color: document.getElementById("freehand-color").value,
    strokeWidth: Number(document.getElementById("freehand-width").value) || 2,
  };
  addFreehandPoint(evt);
});
freehandCanvas.addEventListener("pointermove", (evt) => {
  if (!freehandDrawing) return;
  addFreehandPoint(evt);
});
window.addEventListener("pointerup", () => {
  if (freehandDrawing && currentStroke && currentStroke.points.length >= 2) {
    freehandStrokes.push(currentStroke);
  }
  freehandDrawing = false;
  currentStroke = null;
});

// --- save ---
saveBtn.addEventListener("click", async () => {
  const containerWidth = pageImage.clientWidth;
  const containerHeight = pageImage.clientHeight;

  const elements = boxElements.map((item) => {
    const base = {
      type: item.type,
      page: item.page,
      x: item.el.offsetLeft / containerWidth,
      y: item.el.offsetTop / containerHeight,
      width: item.el.offsetWidth / containerWidth,
      height: item.el.offsetHeight / containerHeight,
    };
    if (item.type === "text") {
      return {
        ...base,
        text: item.data.text,
        font_size: item.data.font_size,
        font: item.data.font,
        color: item.data.color,
      };
    }
    if (item.type === "image") {
      return { ...base, image_data: item.data.image_data };
    }
    if (item.type === "rect") {
      return { ...base, color: item.data.color, fill: item.data.fill };
    }
    return base;
  });

  freehandStrokes.forEach((stroke) => {
    elements.push({
      type: "freehand",
      page: stroke.page,
      points: stroke.points,
      color: stroke.color,
      stroke_width: stroke.strokeWidth,
    });
  });

  if (elements.length === 0) {
    setStatus("Add something to the page first", true);
    return;
  }

  setStatus("Saving...");
  saveBtn.disabled = true;
  try {
    const response = await fetch(`/tools/edit-pdf/${encodeURIComponent(filename)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ elements }),
    });
    if (!response.ok) {
      setStatus("Save failed", true);
      return;
    }
    const data = await response.json();
    setStatus("Saved");
    window.location.href = `/download/${encodeURIComponent(data.pdf_filename)}`;
  } catch (err) {
    setStatus("Save failed", true);
  } finally {
    saveBtn.disabled = false;
  }
});
