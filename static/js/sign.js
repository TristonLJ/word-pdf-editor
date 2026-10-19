const pdfFilename = window.PDF_FILENAME;
const signFilename = window.SIGN_FILENAME;
const pageCount = window.PAGE_COUNT;
let currentPage = 0;

const pageImage = document.getElementById("page-image");
const pageContainer = document.getElementById("page-container");
const pageIndicator = document.getElementById("page-indicator");
const prevBtn = document.getElementById("prev-page");
const nextBtn = document.getElementById("next-page");
const statusEl = document.getElementById("status");
const signBtn = document.getElementById("sign-btn");

// Each entry: { page, el }. Signatures persist across page navigation;
// only the ones matching the currently displayed page are shown.
let signatures = [];

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("status-error", isError);
}

function updateSignBtn() {
  signBtn.disabled = signatures.length === 0;
}

function refreshOverlaysForPage() {
  signatures.forEach((sig) => {
    sig.el.style.display = sig.page === currentPage ? "" : "none";
  });
}

function loadPage(page) {
  currentPage = page;
  pageImage.src = `/page-image/${encodeURIComponent(pdfFilename)}/${page}`;
  pageIndicator.textContent = `Page ${page + 1} of ${pageCount}`;
  refreshOverlaysForPage();
}

prevBtn.addEventListener("click", () => {
  if (currentPage > 0) loadPage(currentPage - 1);
});
nextBtn.addEventListener("click", () => {
  if (currentPage < pageCount - 1) loadPage(currentPage + 1);
});

loadPage(0);

// --- Signature pad: Draw mode ---
const tabDraw = document.getElementById("tab-draw");
const tabType = document.getElementById("tab-type");
const drawPad = document.getElementById("draw-pad");
const typePad = document.getElementById("type-pad");

tabDraw.addEventListener("click", () => {
  tabDraw.classList.add("active");
  tabType.classList.remove("active");
  drawPad.hidden = false;
  typePad.hidden = true;
});
tabType.addEventListener("click", () => {
  tabType.classList.add("active");
  tabDraw.classList.remove("active");
  typePad.hidden = false;
  drawPad.hidden = true;
});

const drawCanvas = document.getElementById("draw-canvas");
const drawCtx = drawCanvas.getContext("2d");
drawCtx.lineWidth = 2.5;
drawCtx.lineCap = "round";
drawCtx.strokeStyle = "#111111";
let drawing = false;

function canvasPoint(evt, canvas) {
  const rect = canvas.getBoundingClientRect();
  return [evt.clientX - rect.left, evt.clientY - rect.top];
}

drawCanvas.addEventListener("pointerdown", (evt) => {
  drawing = true;
  const [x, y] = canvasPoint(evt, drawCanvas);
  drawCtx.beginPath();
  drawCtx.moveTo(x, y);
});
drawCanvas.addEventListener("pointermove", (evt) => {
  if (!drawing) return;
  const [x, y] = canvasPoint(evt, drawCanvas);
  drawCtx.lineTo(x, y);
  drawCtx.stroke();
});
window.addEventListener("pointerup", () => {
  drawing = false;
});

document.getElementById("clear-draw").addEventListener("click", () => {
  drawCtx.clearRect(0, 0, drawCanvas.width, drawCanvas.height);
});

// --- Signature pad: Type mode ---
const typeInput = document.getElementById("type-input");
const typeCanvas = document.getElementById("type-canvas");
const typeCtx = typeCanvas.getContext("2d");

function renderTypedSignature() {
  typeCtx.clearRect(0, 0, typeCanvas.width, typeCanvas.height);
  typeCtx.fillStyle = "#111111";
  typeCtx.font = "48px 'Dancing Script', cursive";
  typeCtx.textBaseline = "middle";
  typeCtx.fillText(typeInput.value, 10, typeCanvas.height / 2);
}
typeInput.addEventListener("input", renderTypedSignature);
document.fonts.load("48px 'Dancing Script'").then(renderTypedSignature);

// --- Overlay placement on the page image ---
function addSignatureToPage(dataUrl) {
  const el = document.createElement("div");
  el.className = "signature-overlay";
  el.style.left = "20px";
  el.style.top = "20px";
  el.style.width = "160px";
  el.style.height = "60px";

  const img = document.createElement("img");
  img.src = dataUrl;
  el.appendChild(img);

  const toolbar = document.createElement("div");
  toolbar.className = "overlay-toolbar";
  toolbar.innerHTML = `
    <span class="overlay-toolbar-grip"><svg class="icon"><use href="#icon-grip"/></svg></span>
    <span class="overlay-toolbar-divider"></span>
    <button type="button" class="overlay-toolbar-remove" aria-label="Remove this signature">
      <svg class="icon"><use href="#icon-trash"/></svg>
    </button>
  `;
  el.appendChild(toolbar);
  const removeBtn = toolbar.querySelector(".overlay-toolbar-remove");

  const handle = document.createElement("div");
  handle.className = "resize-handle";
  el.appendChild(handle);

  pageContainer.appendChild(el);
  makeDraggable(el, handle);

  const entry = { page: currentPage, el };
  signatures.push(entry);

  removeBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    el.remove();
    signatures = signatures.filter((sig) => sig !== entry);
    updateSignBtn();
  });

  updateSignBtn();
}

document.getElementById("add-signature").addEventListener("click", () => {
  const isDraw = !drawPad.hidden;
  const dataUrl = isDraw ? drawCanvas.toDataURL("image/png") : typeCanvas.toDataURL("image/png");
  addSignatureToPage(dataUrl);
});

function makeDraggable(el, handle) {
  let mode = null;
  let startX, startY, startLeft, startTop, startWidth, startHeight;

  el.addEventListener("pointerdown", (evt) => {
    if (evt.target === handle || evt.target.closest(".overlay-toolbar-remove")) return;
    mode = "drag";
    startX = evt.clientX;
    startY = evt.clientY;
    startLeft = el.offsetLeft;
    startTop = el.offsetTop;
    evt.preventDefault();
  });

  handle.addEventListener("pointerdown", (evt) => {
    mode = "resize";
    startX = evt.clientX;
    startY = evt.clientY;
    startWidth = el.offsetWidth;
    startHeight = el.offsetHeight;
    evt.preventDefault();
    evt.stopPropagation();
  });

  window.addEventListener("pointermove", (evt) => {
    if (!mode) return;
    const dx = evt.clientX - startX;
    const dy = evt.clientY - startY;
    if (mode === "drag") {
      const containerRect = pageContainer.getBoundingClientRect();
      let newLeft = startLeft + dx;
      let newTop = startTop + dy;
      newLeft = Math.max(0, Math.min(newLeft, containerRect.width - el.offsetWidth));
      newTop = Math.max(0, Math.min(newTop, containerRect.height - el.offsetHeight));
      el.style.left = `${newLeft}px`;
      el.style.top = `${newTop}px`;
    } else if (mode === "resize") {
      el.style.width = `${Math.max(30, startWidth + dx)}px`;
      el.style.height = `${Math.max(15, startHeight + dy)}px`;
    }
  });

  window.addEventListener("pointerup", () => {
    mode = null;
  });
}

signBtn.addEventListener("click", async () => {
  if (signatures.length === 0) return;
  const containerWidth = pageImage.clientWidth;
  const containerHeight = pageImage.clientHeight;

  const payload = {
    signatures: signatures.map((sig) => ({
      page: sig.page,
      x: sig.el.offsetLeft / containerWidth,
      y: sig.el.offsetTop / containerHeight,
      width: sig.el.offsetWidth / containerWidth,
      height: sig.el.offsetHeight / containerHeight,
      signature_png: sig.el.querySelector("img").src,
    })),
  };

  setStatus("Signing...");
  signBtn.disabled = true;
  try {
    const response = await fetch(`/sign/${encodeURIComponent(signFilename)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      setStatus("Signing failed", true);
      signBtn.disabled = false;
      return;
    }
    const data = await response.json();
    setStatus("Signed");
    window.location.href = `/download/${encodeURIComponent(data.pdf_filename)}`;
  } catch (err) {
    setStatus("Signing failed", true);
    signBtn.disabled = false;
  }
});
