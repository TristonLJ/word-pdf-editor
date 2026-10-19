const filename = window.PDF_FILENAME;
const pageCount = window.PAGE_COUNT;
const grid = document.getElementById("page-grid");
const statusEl = document.getElementById("status");
const saveBtn = document.getElementById("save-btn");

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("status-error", isError);
}

let pages = [];
for (let i = 0; i < pageCount; i++) {
  pages.push({ index: i, rotation: 0, deleted: false });
}

function render() {
  window.flipAnimate ? window.flipAnimate(grid, ".page-card", "data-key", renderInner) : renderInner();
}

function renderInner() {
  grid.innerHTML = "";
  let displayNumber = 0;
  pages.forEach((page) => {
    if (page.deleted) return;
    displayNumber += 1;

    const card = document.createElement("div");
    card.className = "page-card";
    card.dataset.key = page.index;
    card.draggable = true;

    const img = document.createElement("img");
    img.src = `/page-image/${encodeURIComponent(filename)}/${page.index}`;
    img.style.transform = `rotate(${page.rotation}deg)`;
    card.appendChild(img);

    const toolbar = document.createElement("div");
    toolbar.className = "page-card-toolbar";

    const rotateBtn = document.createElement("button");
    rotateBtn.type = "button";
    rotateBtn.innerHTML = '<svg class="icon"><use href="#icon-refresh"/></svg>';
    rotateBtn.addEventListener("click", () => {
      page.rotation = (page.rotation + 90) % 360;
      render();
    });

    const number = document.createElement("span");
    number.className = "page-card-number";
    number.textContent = displayNumber;

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.innerHTML = '<svg class="icon"><use href="#icon-trash"/></svg>';
    deleteBtn.addEventListener("click", () => {
      page.deleted = true;
      render();
    });

    toolbar.appendChild(rotateBtn);
    toolbar.appendChild(number);
    toolbar.appendChild(deleteBtn);
    card.appendChild(toolbar);

    card.addEventListener("dragstart", (evt) => {
      evt.dataTransfer.setData("text/plain", String(page.index));
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));
    card.addEventListener("dragover", (evt) => evt.preventDefault());
    card.addEventListener("drop", (evt) => {
      evt.preventDefault();
      const fromIndex = Number(evt.dataTransfer.getData("text/plain"));
      if (fromIndex === page.index) return;
      const fromPos = pages.findIndex((p) => p.index === fromIndex);
      const toPos = pages.findIndex((p) => p.index === page.index);
      const [moved] = pages.splice(fromPos, 1);
      pages.splice(toPos, 0, moved);
      render();
    });

    grid.appendChild(card);
  });
}
render();

saveBtn.addEventListener("click", async () => {
  const surviving = pages.filter((p) => !p.deleted);
  if (surviving.length === 0) {
    setStatus("Keep at least one page", true);
    return;
  }
  setStatus("Saving...");
  saveBtn.disabled = true;
  try {
    const response = await fetch(`/tools/organize-pdf/${encodeURIComponent(filename)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pages: surviving.map((p) => ({ index: p.index, rotation: p.rotation })),
      }),
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
