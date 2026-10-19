const filename = window.PDF_FILENAME;
const pageCount = window.PAGE_COUNT;
const mode = window.FORM_MODE;
const existingFields = window.EXISTING_FIELDS || [];
let currentPage = 0;

const pageImage = document.getElementById("page-image");
const pageContainer = document.getElementById("page-container");
const pageIndicator = document.getElementById("page-indicator");
const prevBtn = document.getElementById("prev-page");
const nextBtn = document.getElementById("next-page");
const statusEl = document.getElementById("status");
const saveBtn = document.getElementById("save-btn");

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("status-error", isError);
}

// ---------- Fill mode: overlay real inputs on top of existing fields ----------
const fieldOverlays = []; // { page, name, wrap, input }
let fieldOverlaysBuilt = false;

function buildFieldOverlaysIfNeeded() {
  if (fieldOverlaysBuilt) return;
  fieldOverlaysBuilt = true;
  const containerWidth = pageImage.clientWidth;
  const containerHeight = pageImage.clientHeight;

  existingFields.forEach((field) => {
    const wrap = document.createElement("div");
    wrap.className = "form-field-overlay";
    wrap.style.left = `${field.x * containerWidth}px`;
    wrap.style.top = `${field.y * containerHeight}px`;
    wrap.style.width = `${field.width * containerWidth}px`;
    wrap.style.height = `${field.height * containerHeight}px`;

    let input;
    if (field.type === "CheckBox") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!field.value && field.value !== "Off";
    } else if (field.type === "ComboBox" || field.type === "ListBox") {
      input = document.createElement("select");
      (field.options || []).forEach((opt) => {
        const option = document.createElement("option");
        option.value = opt;
        option.textContent = opt;
        if (opt === field.value) option.selected = true;
        input.appendChild(option);
      });
    } else {
      input = document.createElement("input");
      input.type = "text";
      input.value = field.value || "";
    }
    wrap.appendChild(input);
    pageContainer.appendChild(wrap);
    fieldOverlays.push({ page: field.page, name: field.name, wrap, input });
  });
}

function refreshFillOverlays() {
  fieldOverlays.forEach((f) => {
    f.wrap.style.display = f.page === currentPage ? "" : "none";
  });
}

// ---------- Create mode: draw new field boxes ----------
let placedFields = []; // { page, el, type, name, options }
let drawing = false;
let startX, startY;
let drawEl = null;

function containerPoint(evt) {
  const rect = pageContainer.getBoundingClientRect();
  return [evt.clientX - rect.left, evt.clientY - rect.top];
}

if (mode === "create") {
  const fieldTypeSelect = document.getElementById("field-type");
  fieldTypeSelect.addEventListener("change", (evt) => {
    document.getElementById("dropdown-options-wrap").hidden = evt.target.value !== "dropdown";
  });

  pageContainer.addEventListener("pointerdown", (evt) => {
    if (evt.target.closest(".editable-item")) return;
    drawing = true;
    [startX, startY] = containerPoint(evt);
    drawEl = document.createElement("div");
    drawEl.className = "editable-item rect-item";
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
      if (drawEl.offsetWidth < 15 || drawEl.offsetHeight < 12) {
        drawEl.remove();
      } else {
        finalizeField(drawEl);
      }
    }
    drawing = false;
    drawEl = null;
  });
}

function finalizeField(el) {
  const type = document.getElementById("field-type").value;
  const name = document.getElementById("field-name").value.trim() || `field_${placedFields.length + 1}`;
  const options = document
    .getElementById("field-options")
    .value.split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const label = document.createElement("span");
  label.className = "form-field-label";
  label.textContent = `${name} (${type})`;
  el.appendChild(label);

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "redact-region-remove";
  removeBtn.setAttribute("aria-label", "Remove field");
  removeBtn.textContent = "×";
  removeBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    el.remove();
    placedFields = placedFields.filter((f) => f.el !== el);
  });
  el.appendChild(removeBtn);

  el.addEventListener("pointerdown", (evt) => {
    if (evt.target.closest(".redact-region-remove")) return;
    evt.stopPropagation();
    const containerRect = pageContainer.getBoundingClientRect();
    const startLeft = el.offsetLeft;
    const startTop = el.offsetTop;
    const sX = evt.clientX;
    const sY = evt.clientY;
    function onMove(e2) {
      const dx = e2.clientX - sX;
      const dy = e2.clientY - sY;
      el.style.left = `${Math.max(0, Math.min(startLeft + dx, containerRect.width - el.offsetWidth))}px`;
      el.style.top = `${Math.max(0, Math.min(startTop + dy, containerRect.height - el.offsetHeight))}px`;
    }
    function onUp() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });

  placedFields.push({ page: currentPage, el, type, name, options });
}

function refreshCreateOverlays() {
  placedFields.forEach((f) => {
    f.el.style.display = f.page === currentPage ? "" : "none";
  });
}

// ---------- shared page loading ----------
function loadPage(page) {
  currentPage = page;
  pageIndicator.textContent = `Page ${page + 1} of ${pageCount}`;
  pageImage.onload = () => {
    if (mode === "fill") {
      buildFieldOverlaysIfNeeded();
      refreshFillOverlays();
    } else {
      refreshCreateOverlays();
    }
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

// ---------- save ----------
saveBtn.addEventListener("click", async () => {
  setStatus("Saving...");
  saveBtn.disabled = true;
  try {
    let payload;
    if (mode === "fill") {
      const values = {};
      fieldOverlays.forEach((f) => {
        values[f.name] = f.input.type === "checkbox" ? (f.input.checked ? "Yes" : "Off") : f.input.value;
      });
      payload = { mode: "fill", values };
    } else {
      if (placedFields.length === 0) {
        setStatus("Place at least one field first", true);
        saveBtn.disabled = false;
        return;
      }
      const containerWidth = pageImage.clientWidth;
      const containerHeight = pageImage.clientHeight;
      payload = {
        mode: "create",
        fields: placedFields.map((f) => ({
          page: f.page,
          x: f.el.offsetLeft / containerWidth,
          y: f.el.offsetTop / containerHeight,
          width: f.el.offsetWidth / containerWidth,
          height: f.el.offsetHeight / containerHeight,
          type: f.type,
          name: f.name,
          options: f.options,
        })),
      };
    }

    const response = await fetch(`/tools/pdf-forms/${encodeURIComponent(filename)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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
