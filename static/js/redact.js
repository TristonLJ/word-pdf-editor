const filename = window.PDF_FILENAME;
const pageCount = window.PAGE_COUNT;
let currentPage = 0;

const pageImage = document.getElementById("page-image");
const pageContainer = document.getElementById("page-container");
const pageIndicator = document.getElementById("page-indicator");
const prevBtn = document.getElementById("prev-page");
const nextBtn = document.getElementById("next-page");
const statusEl = document.getElementById("status");
const applyBtn = document.getElementById("apply-btn");

let regions = []; // { page, el }

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("status-error", isError);
}

function updateApplyBtn() {
  applyBtn.disabled = regions.length === 0;
}

function refreshRegionsForPage() {
  regions.forEach((r) => {
    r.el.style.display = r.page === currentPage ? "" : "none";
  });
}

function loadPage(page) {
  currentPage = page;
  pageImage.src = `/page-image/${encodeURIComponent(filename)}/${page}`;
  pageIndicator.textContent = `Page ${page + 1} of ${pageCount}`;
  refreshRegionsForPage();
}

prevBtn.addEventListener("click", () => {
  if (currentPage > 0) loadPage(currentPage - 1);
});
nextBtn.addEventListener("click", () => {
  if (currentPage < pageCount - 1) loadPage(currentPage + 1);
});
loadPage(0);

let drawing = false;
let startX, startY;
let drawEl = null;

function containerPoint(evt) {
  const rect = pageContainer.getBoundingClientRect();
  return [evt.clientX - rect.left, evt.clientY - rect.top];
}

pageContainer.addEventListener("pointerdown", (evt) => {
  if (evt.target.closest(".redact-region")) return;
  drawing = true;
  [startX, startY] = containerPoint(evt);
  drawEl = document.createElement("div");
  drawEl.className = "redact-region redact-drawing";
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
    if (drawEl.offsetWidth < 8 || drawEl.offsetHeight < 8) {
      drawEl.remove();
    } else {
      drawEl.classList.remove("redact-drawing");
      finalizeRegion(drawEl);
    }
  }
  drawing = false;
  drawEl = null;
});

function finalizeRegion(el) {
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "redact-region-remove";
  removeBtn.setAttribute("aria-label", "Remove this redaction");
  removeBtn.textContent = "×";
  removeBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    el.remove();
    regions = regions.filter((r) => r.el !== el);
    updateApplyBtn();
  });
  el.appendChild(removeBtn);

  regions.push({ page: currentPage, el });
  updateApplyBtn();
}

applyBtn.addEventListener("click", async () => {
  const containerWidth = pageImage.clientWidth;
  const containerHeight = pageImage.clientHeight;
  const payload = {
    regions: regions.map((r) => ({
      page: r.page,
      x: r.el.offsetLeft / containerWidth,
      y: r.el.offsetTop / containerHeight,
      width: r.el.offsetWidth / containerWidth,
      height: r.el.offsetHeight / containerHeight,
    })),
  };

  setStatus("Applying redactions...");
  applyBtn.disabled = true;
  try {
    const response = await fetch(`/tools/redact-pdf/${encodeURIComponent(filename)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      setStatus("Failed", true);
      applyBtn.disabled = false;
      return;
    }
    const data = await response.json();
    setStatus("Redacted");
    window.location.href = `/download/${encodeURIComponent(data.pdf_filename)}`;
  } catch (err) {
    setStatus("Failed", true);
    applyBtn.disabled = false;
  }
});
