const dropzone = document.getElementById("dropzone");
if (dropzone) {
  const dropzoneInput = document.getElementById("dropzone-input");
  const dropzoneBtn = document.getElementById("dropzone-btn");
  const uploadForm = document.getElementById("upload-form");

  const openPicker = () => dropzoneInput.click();
  dropzone.addEventListener("click", openPicker);
  dropzoneBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    openPicker();
  });

  dropzoneInput.addEventListener("change", () => {
    if (dropzoneInput.files.length > 0) uploadForm.submit();
  });

  ["dragenter", "dragover"].forEach((evtName) => {
    dropzone.addEventListener(evtName, (evt) => {
      evt.preventDefault();
      dropzone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((evtName) => {
    dropzone.addEventListener(evtName, (evt) => {
      evt.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });

  dropzone.addEventListener("drop", (evt) => {
    const files = evt.dataTransfer.files;
    if (files.length > 0) {
      dropzoneInput.files = files;
      uploadForm.submit();
    }
  });
}

document.querySelectorAll(".export-btn").forEach((btn) => {
  const label = btn.querySelector(".btn-label") || btn;
  btn.addEventListener("click", async () => {
    const filename = btn.dataset.filename;
    const original = label.textContent;
    btn.disabled = true;
    label.textContent = "Exporting...";
    try {
      const response = await fetch(`/export/${encodeURIComponent(filename)}`, {
        method: "POST",
      });
      if (!response.ok) {
        label.textContent = "Export failed";
        return;
      }
      const data = await response.json();
      window.location.href = `/download/${encodeURIComponent(data.pdf_filename)}`;
    } finally {
      btn.disabled = false;
      label.textContent = original;
    }
  });
});

function adjustCount(countEl, delta) {
  if (!countEl) return;
  countEl.textContent = String(Math.max(0, parseInt(countEl.textContent, 10) + delta));
}

function closePopover() {
  const existing = document.querySelector(".confirm-popover");
  if (existing) {
    existing.classList.remove("is-visible");
    setTimeout(() => existing.remove(), 150);
  }
  document.removeEventListener("click", onDocumentClick, true);
  document.removeEventListener("keydown", onKeydown, true);
  window.removeEventListener("scroll", closePopover, true);
  window.removeEventListener("resize", closePopover);
}

function onDocumentClick(evt) {
  const popover = document.querySelector(".confirm-popover");
  if (popover && !popover.contains(evt.target) && !evt.target.closest(".delete-btn")) {
    closePopover();
  }
}

function onKeydown(evt) {
  if (evt.key === "Escape") closePopover();
}

function positionPopover(popover, anchorBtn) {
  const margin = 8;
  const rect = anchorBtn.getBoundingClientRect();
  const popoverRect = popover.getBoundingClientRect();
  const viewportWidth = document.documentElement.clientWidth;
  const viewportHeight = document.documentElement.clientHeight;

  let left = rect.right - popoverRect.width;
  left = Math.max(margin, Math.min(left, viewportWidth - popoverRect.width - margin));

  const spaceBelow = viewportHeight - rect.bottom;
  const openAbove = spaceBelow < popoverRect.height + margin && rect.top > popoverRect.height + margin;
  const top = openAbove ? rect.top - popoverRect.height - margin : rect.bottom + margin;

  popover.style.left = `${left}px`;
  popover.style.top = `${Math.max(margin, top)}px`;
}

async function performDelete(filename, btn) {
  const row = btn.closest(".doc-row");
  const rowsContainer = row.parentElement;

  const response = await fetch(`/delete/${encodeURIComponent(filename)}`, { method: "POST" });
  if (!response.ok) {
    throw new Error("Delete failed");
  }

  await new Promise((resolve) => {
    row.classList.add("removing");
    row.addEventListener("transitionend", resolve, { once: true });
    setTimeout(resolve, 400);
  });
  row.remove();
  if (rowsContainer.id === "docx-rows") {
    adjustCount(document.getElementById("docx-count"), -1);
    if (!rowsContainer.querySelector(".doc-row")) {
      document.getElementById("docx-empty").hidden = false;
    }
  } else if (rowsContainer.id === "pdf-rows") {
    adjustCount(document.getElementById("pdf-count"), -1);
    if (!rowsContainer.querySelector(".doc-row")) {
      document.getElementById("pdf-library").hidden = true;
    }
  } else if (rowsContainer.id === "xlsx-rows") {
    adjustCount(document.getElementById("xlsx-count"), -1);
    if (!rowsContainer.querySelector(".doc-row")) {
      document.getElementById("xlsx-library").hidden = true;
    }
  }
}

document.querySelectorAll(".delete-btn").forEach((btn) => {
  const filename = btn.dataset.filename;

  btn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    closePopover();

    const popover = document.createElement("div");
    popover.className = "confirm-popover";
    popover.innerHTML = `
      <div class="confirm-popover-header">
        <span class="confirm-popover-icon"><svg class="icon"><use href="#icon-trash"/></svg></span>
        <div>
          <p class="confirm-popover-title">Delete this file?</p>
          <p class="confirm-popover-name">${filename}</p>
        </div>
      </div>
      <p class="confirm-popover-desc">This can't be undone.</p>
      <div class="confirm-popover-actions">
        <button type="button" class="btn btn-secondary confirm-cancel">Cancel</button>
        <button type="button" class="btn btn-danger confirm-delete">
          <svg class="icon"><use href="#icon-trash"/></svg> Delete
        </button>
      </div>
    `;
    document.body.appendChild(popover);
    positionPopover(popover, btn);
    requestAnimationFrame(() => {
      positionPopover(popover, btn);
      popover.classList.add("is-visible");
    });

    popover.querySelector(".confirm-cancel").addEventListener("click", closePopover);
    popover.querySelector(".confirm-delete").addEventListener("click", async () => {
      const deleteBtn = popover.querySelector(".confirm-delete");
      deleteBtn.disabled = true;
      deleteBtn.textContent = "Deleting...";
      try {
        await performDelete(filename, btn);
        closePopover();
      } catch (err) {
        deleteBtn.disabled = false;
        deleteBtn.innerHTML = `<svg class="icon"><use href="#icon-trash"/></svg> Delete failed — retry`;
      }
    });

    setTimeout(() => {
      document.addEventListener("click", onDocumentClick, true);
      document.addEventListener("keydown", onKeydown, true);
      window.addEventListener("scroll", closePopover, true);
      window.addEventListener("resize", closePopover);
    }, 0);
  });
});
