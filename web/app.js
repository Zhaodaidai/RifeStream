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
const seekBar = document.getElementById("seekBar");
const timeNow = document.getElementById("timeNow");
const timeTotal = document.getElementById("timeTotal");
const introSeconds = document.getElementById("introSeconds");
const outroSeconds = document.getElementById("outroSeconds");
const skipIntro = document.getElementById("skipIntro");
const skipOutro = document.getElementById("skipOutro");

let seeking = false;
let savingSettings = false;
const clock = {
  position: 0,
  duration: 0,
  streaming: false,
  sampledAt: 0,
};

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

function livePosition() {
  if (!clock.streaming || seeking) return clock.position;
  let position = clock.position + (performance.now() - clock.sampledAt) / 1000;
  if (clock.duration > 0) position = Math.min(position, clock.duration);
  return Math.max(0, position);
}

function paintProgress() {
  if (seeking) return;
  const position = livePosition();
  seekBar.value = String(position);
  timeNow.textContent = formatTime(position);
}

function paintSettings(settings) {
  if (!settings) return;
  if (document.activeElement !== introSeconds) {
    introSeconds.value = String(Number(settings.intro) || 0);
  }
  if (document.activeElement !== outroSeconds) {
    outroSeconds.value = String(Number(settings.outro) || 0);
  }
  if (document.activeElement !== skipIntro) {
    skipIntro.checked = Boolean(settings.skip_intro);
  }
  if (document.activeElement !== skipOutro) {
    skipOutro.checked = Boolean(settings.skip_outro);
  }
}

function settingsPayload() {
  return {
    intro: Number(introSeconds.value) || 0,
    outro: Number(outroSeconds.value) || 0,
    skip_intro: skipIntro.checked,
    skip_outro: skipOutro.checked,
  };
}

async function saveSettings() {
  if (savingSettings) return;
  savingSettings = true;
  try {
    renderState(await api("/api/settings", {
      method: "POST",
      body: JSON.stringify(settingsPayload()),
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
  clock.position = Number(state.position) || 0;
  clock.duration = Number(state.duration) || 0;
  clock.streaming = Boolean(state.streaming);
  clock.sampledAt = performance.now();
  seekBar.max = String(clock.duration || 0);
  seekBar.disabled = !state.seekable;
  timeTotal.textContent = formatTime(clock.duration);
  paintProgress();
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
seekBar.addEventListener("pointerdown", () => {
  seeking = true;
});
seekBar.addEventListener("input", () => {
  seeking = true;
  timeNow.textContent = formatTime(Number(seekBar.value));
});
let seekInFlight = false;
seekBar.addEventListener("change", async () => {
  seekInFlight = true;
  try {
    renderState(await api("/api/seek", {
      method: "POST",
      body: JSON.stringify({ seconds: Number(seekBar.value) }),
    }));
  } catch (error) {
    showError(error.message);
  } finally {
    seekInFlight = false;
    seeking = false;
  }
});
["pointerup", "pointercancel"].forEach((event) => {
  seekBar.addEventListener(event, () => {
    if (!seekInFlight) seeking = false;
  });
});
[introSeconds, outroSeconds].forEach((input) => {
  input.addEventListener("change", saveSettings);
});
[skipIntro, skipOutro].forEach((input) => {
  input.addEventListener("change", saveSettings);
});

refresh();
setInterval(refresh, 1500);
setInterval(paintProgress, 250);
