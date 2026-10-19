const filename = window.PDF_FILENAME;
const pageImage = document.getElementById("page-image");
const pageContainer = document.getElementById("page-container");
const statusEl = document.getElementById("status");
const applyBtn = document.getElementById("apply-btn");

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("status-error", isError);
}

let overlay = null;
let drawing = false;
let startX, startY;

function containerPoint(evt) {
  const rect = pageContainer.getBoundingClientRect();
  return [evt.clientX - rect.left, evt.clientY - rect.top];
}

pageContainer.addEventListener("pointerdown", (evt) => {
  if (evt.target.closest(".signature-overlay, .resize-handle")) return;
  drawing = true;
  [startX, startY] = containerPoint(evt);
  if (overlay) overlay.remove();

  overlay = document.createElement("div");
  overlay.className = "signature-overlay";
  overlay.style.left = `${startX}px`;
  overlay.style.top = `${startY}px`;
  overlay.style.width = "0px";
  overlay.style.height = "0px";

  const handle = document.createElement("div");
  handle.className = "resize-handle";
  overlay.appendChild(handle);

  pageContainer.appendChild(overlay);
  makeAdjustable(overlay, handle);
});

pageContainer.addEventListener("pointermove", (evt) => {
  if (!drawing || !overlay) return;
  const [x, y] = containerPoint(evt);
  const left = Math.min(startX, x);
  const top = Math.min(startY, y);
  overlay.style.left = `${left}px`;
  overlay.style.top = `${top}px`;
  overlay.style.width = `${Math.abs(x - startX)}px`;
  overlay.style.height = `${Math.abs(y - startY)}px`;
});

window.addEventListener("pointerup", () => {
  if (drawing && overlay) {
    applyBtn.disabled = overlay.offsetWidth < 10 || overlay.offsetHeight < 10;
  }
  drawing = false;
});

function makeAdjustable(el, handle) {
  let mode = null;
  let sX, sY, sLeft, sTop, sWidth, sHeight;

  el.addEventListener("pointerdown", (evt) => {
    if (evt.target === handle) return;
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

applyBtn.addEventListener("click", async () => {
  if (!overlay) return;
  const containerWidth = pageImage.clientWidth;
  const containerHeight = pageImage.clientHeight;
  const payload = {
    x: overlay.offsetLeft / containerWidth,
    y: overlay.offsetTop / containerHeight,
    width: overlay.offsetWidth / containerWidth,
    height: overlay.offsetHeight / containerHeight,
  };

  setStatus("Applying...");
  applyBtn.disabled = true;
  try {
    const response = await fetch(`/tools/crop-pdf/${encodeURIComponent(filename)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      setStatus("Crop failed", true);
      applyBtn.disabled = false;
      return;
    }
    const data = await response.json();
    setStatus("Cropped");
    window.location.href = `/download/${encodeURIComponent(data.pdf_filename)}`;
  } catch (err) {
    setStatus("Crop failed", true);
    applyBtn.disabled = false;
  }
});
