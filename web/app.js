const nowPlaying = document.getElementById("nowPlaying");
const streamStatus = document.getElementById("streamStatus");
const errorBox = document.getElementById("errorBox");
const sourceInput = document.getElementById("sourceInput");
const playlistEl = document.getElementById("playlist");
const browserEl = document.getElementById("browser");
const crumbsEl = document.getElementById("crumbs");
const drivesEl = document.getElementById("drives");
const hlsUrlEl = document.getElementById("hlsUrl");
const hlsHint = document.getElementById("hlsHint");
const copyBtn = document.getElementById("copyBtn");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const playBtn = document.getElementById("playBtn");
const stopBtn = document.getElementById("stopBtn");

let browsePath = "";
const selectedFiles = new Set();

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

function showError(message) {
  errorBox.hidden = !message;
  errorBox.textContent = message || "";
}

function renderState(state) {
  const current = state.current;
  nowPlaying.textContent = current
    ? `正在播放：${current.title}`
    : "未选择媒体";
  streamStatus.textContent = state.streaming ? "转码中" : "待机";
  streamStatus.classList.toggle("live", Boolean(state.streaming));
  hlsUrlEl.textContent = state.hls_url || "";
  prevBtn.disabled = !state.has_prev;
  nextBtn.disabled = !state.has_next;
  playBtn.disabled = !current;
  showError(state.last_error);

  playlistEl.innerHTML = "";
  if (!state.items.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "列表为空，从下方添加链接或本机文件";
    playlistEl.appendChild(empty);
    return;
  }
  state.items.forEach((item, index) => {
    const li = document.createElement("li");
    if (item.id === state.current_id) li.classList.add("current");
    li.innerHTML = `
      <span class="index">${index + 1}</span>
      <button type="button" class="name">${escapeHtml(item.title)}</button>
      <span class="kind">${item.kind === "url" ? "链接" : "文件"}</span>
      <button type="button" class="remove">删除</button>
    `;
    li.querySelector(".name").addEventListener("click", () => play({ id: item.id }));
    li.querySelector(".remove").addEventListener("click", async (event) => {
      event.stopPropagation();
      renderState(await api(`/api/items/${item.id}`, { method: "DELETE" }));
    });
    playlistEl.appendChild(li);
  });
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function refresh() {
  try {
    renderState(await api("/api/state"));
  } catch (error) {
    showError(error.message);
  }
}

async function addSources(play) {
  const sources = sourceInput.value;
  if (!sources.trim()) return;
  const state = await api("/api/items", {
    method: "POST",
    body: JSON.stringify({ sources, play }),
  });
  sourceInput.value = "";
  renderState(state);
}

async function play(body) {
  renderState(await api("/api/play", { method: "POST", body: JSON.stringify(body) }));
}

async function loadBrowse(path = "") {
  const data = await api(`/api/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`);
  browsePath = data.path;
  crumbsEl.innerHTML = "";
  const crumb = document.createElement("button");
  crumb.className = "crumb";
  crumb.textContent = data.path;
  crumb.addEventListener("click", () => loadBrowse(data.path));
  crumbsEl.appendChild(crumb);
  if (data.parent) {
    const up = document.createElement("button");
    up.className = "crumb";
    up.textContent = "上级目录";
    up.addEventListener("click", () => loadBrowse(data.parent));
    crumbsEl.appendChild(up);
  }

  drivesEl.innerHTML = "";
  (data.drives || []).forEach((drive) => {
    const button = document.createElement("button");
    button.className = "drive";
    button.textContent = drive;
    button.addEventListener("click", () => loadBrowse(drive));
    drivesEl.appendChild(button);
  });

  browserEl.innerHTML = "";
  data.entries.forEach((entry) => {
    const row = document.createElement("div");
    row.className = "entry";
    if (entry.file) {
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = selectedFiles.has(entry.path);
      box.addEventListener("change", () => {
        if (box.checked) selectedFiles.add(entry.path);
        else selectedFiles.delete(entry.path);
      });
      row.appendChild(box);
    }
    const button = document.createElement("button");
    button.className = "name";
    button.type = "button";
    button.textContent = entry.dir ? `📁 ${entry.name}` : entry.name;
    button.addEventListener("click", () => {
      if (entry.dir) loadBrowse(entry.path);
      else {
        const box = row.querySelector("input");
        if (box) {
          box.checked = !box.checked;
          box.dispatchEvent(new Event("change"));
        }
      }
    });
    row.appendChild(button);
    browserEl.appendChild(row);
  });
}

async function addSelected(play) {
  const sources = Array.from(selectedFiles);
  if (!sources.length) return;
  const state = await api("/api/items", {
    method: "POST",
    body: JSON.stringify({ sources, play }),
  });
  selectedFiles.clear();
  renderState(state);
  loadBrowse(browsePath);
}

document.getElementById("addBtn").addEventListener("click", () => addSources(false));
document.getElementById("addPlayBtn").addEventListener("click", () => addSources(true));
document.getElementById("addFilesBtn").addEventListener("click", () => addSelected(false));
document.getElementById("addFilesPlayBtn").addEventListener("click", () => addSelected(true));
document.getElementById("clearBtn").addEventListener("click", async () => {
  renderState(await api("/api/clear", { method: "POST", body: "{}" }));
});
copyBtn.addEventListener("click", async () => {
  const url = hlsUrlEl.textContent;
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    copyBtn.classList.add("copied");
    hlsHint.textContent = "已复制";
    setTimeout(() => {
      copyBtn.classList.remove("copied");
      hlsHint.textContent = "HLS";
    }, 1200);
  } catch {
    showError("无法复制，请手动选择地址");
  }
});
prevBtn.addEventListener("click", () => play({ offset: -1 }));
nextBtn.addEventListener("click", () => play({ offset: 1 }));
playBtn.addEventListener("click", () => play({}));
stopBtn.addEventListener("click", async () => {
  renderState(await api("/api/stop", { method: "POST", body: "{}" }));
});

refresh();
loadBrowse();
setInterval(refresh, 1500);
