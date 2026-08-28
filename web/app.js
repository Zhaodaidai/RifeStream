const nowPlaying = document.getElementById("nowPlaying");
const streamStatus = document.getElementById("streamStatus");
const errorBox = document.getElementById("errorBox");
const sourceInput = document.getElementById("sourceInput");
const playlistEl = document.getElementById("playlist");
const hlsUrlEl = document.getElementById("hlsUrl");
const hlsHint = document.getElementById("hlsHint");
const copyBtn = document.getElementById("copyBtn");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const playBtn = document.getElementById("playBtn");
const stopBtn = document.getElementById("stopBtn");

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
    empty.textContent = "列表为空，从右侧添加链接";
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

document.getElementById("addBtn").addEventListener("click", () => addSources(false));
document.getElementById("addPlayBtn").addEventListener("click", () => addSources(true));
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
setInterval(refresh, 1500);
