const quill = new Quill("#editor-container", {
  theme: "snow",
  modules: {
    toolbar: [
      [{ header: [1, 2, 3, false] }],
      ["bold", "italic", "underline", "strike"],
      [{ list: "ordered" }, { list: "bullet" }],
      [{ align: [] }],
      ["link", "image"],
      ["clean"],
    ],
  },
});

const statusEl = document.getElementById("status");
const saveBtn = document.getElementById("save-btn");
const exportBtn = document.getElementById("export-btn");
const filename = window.DOC_FILENAME;

let dirty = false;
quill.on("text-change", (delta, oldDelta, source) => {
  if (source === "user") {
    dirty = true;
  }
});

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("status-error", isError);
}

function getExportHtml() {
  // Quill represents both bullet and ordered lists as <ol data-list="bullet|ordered">,
  // distinguishing them via CSS counters. Pandoc only understands <ul> vs <ol>, so
  // rewrite bullet-only lists to <ul> before handing the HTML off to the backend.
  const clone = quill.root.cloneNode(true);
  clone.querySelectorAll("ol").forEach((ol) => {
    const items = Array.from(ol.children);
    if (items.length > 0 && items.every((li) => li.getAttribute("data-list") === "bullet")) {
      const ul = document.createElement("ul");
      while (ol.firstChild) ul.appendChild(ol.firstChild);
      ol.replaceWith(ul);
    }
  });
  clone.querySelectorAll("[data-list]").forEach((li) => li.removeAttribute("data-list"));
  clone.querySelectorAll(".ql-ui").forEach((el) => el.remove());
  return clone.innerHTML;
}

async function saveDocument() {
  setStatus("Saving...");
  const html = getExportHtml();
  const response = await fetch(`/save/${encodeURIComponent(filename)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ html }),
  });
  if (!response.ok) {
    setStatus("Save failed", true);
    throw new Error(`Save failed: ${response.status}`);
  }
  dirty = false;
  setStatus("Saved");
  return response;
}

saveBtn.addEventListener("click", () => {
  saveDocument().catch(() => {});
});

exportBtn.addEventListener("click", async () => {
  if (dirty) {
    setStatus("Save your edits before exporting", true);
    return;
  }
  try {
    setStatus("Exporting PDF...");
    const response = await fetch(`/export/${encodeURIComponent(filename)}`, {
      method: "POST",
    });
    if (!response.ok) {
      setStatus("Export failed", true);
      return;
    }
    const data = await response.json();
    setStatus("Exported");
    window.location.href = `/download/${encodeURIComponent(data.pdf_filename)}`;
  } catch (err) {
    setStatus("Export failed", true);
  }
});
