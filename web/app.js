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
const jumpTo = document.getElementById("jumpTo");
const jumpBtn = document.getElementById("jumpBtn");
const jumpLabel = document.getElementById("jumpLabel");
const introSeconds = document.getElementById("introSeconds");
const skipIntro = document.getElementById("skipIntro");

let savingSettings = false;
let jumpInFlight = false;

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

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
  }
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function parseTimeSeconds(value) {
  const text = String(value || "").trim();
  if (!text) return NaN;
  if (/^\d+(\.\d+)?$/.test(text)) return Number(text);
  const parts = text.split(":");
  if (parts.length < 2 || parts.length > 3) return NaN;
  const numbers = parts.map((part) => Number(part));
  if (numbers.some((part) => !Number.isFinite(part) || part < 0)) return NaN;
  if (parts.length === 2) return numbers[0] * 60 + numbers[1];
  return numbers[0] * 3600 + numbers[1] * 60 + numbers[2];
}

function paintSettings(settings) {
  if (!settings) return;
  if (document.activeElement !== introSeconds) {
    introSeconds.value = formatTime(Number(settings.intro) || 0);
  }
  if (document.activeElement !== skipIntro) {
    skipIntro.checked = Boolean(settings.skip_intro);
  }
}

function settingsPayload() {
  const text = String(introSeconds.value || "").trim();
  const intro = text ? parseTimeSeconds(text) : 0;
  if (!Number.isFinite(intro)) return null;
  return {
    intro,
    skip_intro: skipIntro.checked,
    skip_outro: false,
  };
}

async function saveSettings() {
  if (savingSettings) return;
  const payload = settingsPayload();
  if (!payload) {
    showError("片头请使用 1:30 或 1:02:03 格式");
    return;
  }
  savingSettings = true;
  try {
    renderState(await api("/api/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    }));
  } catch (error) {
    showError(error.message);
  } finally {
    savingSettings = false;
  }
}

function renderState(state) {
  const current = state.current;
  paintSettings(state.settings);
  nowPlaying.textContent = current
    ? `正在播放：${current.title}`
    : "未选择媒体";
  streamStatus.textContent = state.streaming ? "转码中" : "待机";
  streamStatus.classList.toggle("live", Boolean(state.streaming));
  hlsUrlEl.textContent = state.hls_url || "";
  prevBtn.disabled = !state.has_prev;
  nextBtn.disabled = !state.has_next;
  playBtn.disabled = !current;
  jumpBtn.disabled = !state.seekable || jumpInFlight;
  const duration = Number(state.duration) || 0;
  jumpLabel.textContent = duration > 0 ? `跳转到（总长 ${formatTime(duration)}）` : "跳转到";
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

async function jump() {
  const seconds = parseTimeSeconds(jumpTo.value);
  if (!Number.isFinite(seconds)) {
    showError("请输入秒数，或 1:30 / 1:02:03 格式");
    return;
  }
  jumpInFlight = true;
  jumpBtn.disabled = true;
  try {
    renderState(await api("/api/seek", {
      method: "POST",
      body: JSON.stringify({ seconds }),
    }));
  } catch (error) {
    showError(error.message);
  } finally {
    jumpInFlight = false;
  }
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
jumpBtn.addEventListener("click", jump);
jumpTo.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    jump();
  }
});
introSeconds.addEventListener("change", saveSettings);
introSeconds.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    introSeconds.blur();
  }
});
skipIntro.addEventListener("change", saveSettings);

refresh();
setInterval(refresh, 1500);
