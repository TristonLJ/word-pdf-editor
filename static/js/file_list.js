function initFileList({ inputId, listId, submitBtnId, fieldName, endpoint, minFiles = 1 }) {
  const input = document.getElementById(inputId);
  const list = document.getElementById(listId);
  const submitBtn = document.getElementById(submitBtnId);
  const statusEl = document.getElementById("status");
  let items = [];
  let nextKey = 0;

  function setStatus(msg, isError = false) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.classList.toggle("status-error", isError);
  }

  function render() {
    window.flipAnimate ? window.flipAnimate(list, ".file-list-item", "data-key", renderInner) : renderInner();
  }

  function renderInner() {
    list.innerHTML = "";
    items.forEach((file, i) => {
      const li = document.createElement("li");
      li.className = "file-list-item";
      li.dataset.key = file._key;
      li.innerHTML = `
        <span class="file-list-name">${file.name}</span>
        <span class="file-list-actions">
          <button type="button" class="btn-icon-sm" data-action="up" ${i === 0 ? "disabled" : ""}>&uarr;</button>
          <button type="button" class="btn-icon-sm" data-action="down" ${i === items.length - 1 ? "disabled" : ""}>&darr;</button>
          <button type="button" class="btn-icon-sm" data-action="remove">&times;</button>
        </span>
      `;
      li.querySelector('[data-action="up"]').addEventListener("click", () => {
        [items[i - 1], items[i]] = [items[i], items[i - 1]];
        render();
      });
      li.querySelector('[data-action="down"]').addEventListener("click", () => {
        [items[i + 1], items[i]] = [items[i], items[i + 1]];
        render();
      });
      li.querySelector('[data-action="remove"]').addEventListener("click", () => {
        items.splice(i, 1);
        render();
      });
      list.appendChild(li);
    });
    submitBtn.disabled = items.length < minFiles;
  }

  input.addEventListener("change", () => {
    Array.from(input.files).forEach((file) => {
      file._key = nextKey++;
      items.push(file);
    });
    input.value = "";
    render();
  });

  submitBtn.addEventListener("click", async () => {
    const fd = new FormData();
    items.forEach((f) => fd.append(fieldName, f));
    submitBtn.disabled = true;
    const originalLabel = submitBtn.textContent;
    submitBtn.textContent = "Processing...";
    setStatus("");
    try {
      const response = await fetch(endpoint, { method: "POST", body: fd });
      if (!response.ok) {
        setStatus("Failed - check your files and try again", true);
        return;
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="?([^";]+)"?/);
      const downloadName = match ? match[1] : "download";
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = downloadName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus("Done");
    } catch (err) {
      setStatus("Failed - check your files and try again", true);
    } finally {
      submitBtn.disabled = items.length < minFiles;
      submitBtn.textContent = originalLabel;
    }
  });

  render();
}
