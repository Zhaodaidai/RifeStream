const nowPlaying = document.getElementById("nowPlaying");
const streamStatus = document.getElementById("streamStatus");
const errorBox = document.getElementById("errorBox");
const sourceInput = document.getElementById("sourceInput");
const addDialog = document.getElementById("addDialog");
const addForm = document.getElementById("addForm");
const addError = document.getElementById("addError");
const finishAddBtn = document.getElementById("finishAddBtn");
let addingSources = false;
const playlistEl = document.getElementById("playlist");
const hlsUrlEl = document.getElementById("hlsUrl");
const hlsHint = document.getElementById("hlsHint");
const copyBtn = document.getElementById("copyBtn");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const playBtn = document.getElementById("playBtn");
const stopBtn = document.getElementById("stopBtn");
const introSeconds = document.getElementById("introSeconds");
const skipIntro = document.getElementById("skipIntro");
const anime4k = document.getElementById("anime4k");

let savingSettings = false;
let jumpInFlight = false;
let stateVersion = 0;
let requestsInFlight = 0;
const embeddedPlayer = new EmbeddedPlayer({
  video: document.getElementById("videoPlayer"),
  timeline: document.getElementById("timeline"),
  clock: document.getElementById("playbackTime"),
  hint: document.getElementById("playerHint"),
  formatTime,
  seek: seekSeconds,
});

async function api(path, options = {}) {
  const modifying = options.method && options.method !== "GET";
  if (modifying) { stateVersion++; requestsInFlight++; }
  try {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || response.statusText);
    }
    return data;
  } finally { if (modifying) requestsInFlight--; }
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
  if (document.activeElement !== anime4k) {
    anime4k.checked = Boolean(settings.anime4k);
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
    anime4k: anime4k.checked,
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
  embeddedPlayer.update(state);
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
    if (requestsInFlight) return;
    const version = stateVersion;
    const state = await api("/api/state");
    if (version === stateVersion && !requestsInFlight) renderState(state);
  } catch (error) {
    showError(error.message);
  }
}

async function addSources(event) {
  event.preventDefault();
  if (addingSources) return;
  const sources = sourceInput.value.trim();
  addError.hidden = true;
  if (!sources) {
    addError.textContent = "请输入至少一个链接";
    addError.hidden = false;
    sourceInput.focus();
    return;
  }
  addingSources = true;
  finishAddBtn.disabled = true;
  finishAddBtn.textContent = "添加中…";
  try {
    const state = await api("/api/items", {
      method: "POST",
      body: JSON.stringify({ sources, play: false }),
    });
    renderState(state);
    sourceInput.value = "";
    addDialog.close();
  } catch (error) {
    addError.textContent = error.message;
    addError.hidden = false;
  } finally {
    addingSources = false;
    finishAddBtn.disabled = false;
    finishAddBtn.textContent = "完成";
  }
}

async function play(body) {
  try {
    renderState(await api("/api/play", { method: "POST", body: JSON.stringify(body) }));
  } catch (error) { showError(error.message); }
}

async function seekSeconds(seconds) {
  if (jumpInFlight) return;
  jumpInFlight = true;
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

document.getElementById("openAddBtn").addEventListener("click", () => {
  addError.hidden = true;
  addDialog.showModal();
  sourceInput.focus();
});
document.getElementById("cancelAddBtn").addEventListener("click", () => {
  if (!addingSources) addDialog.close();
});
addDialog.addEventListener("cancel", (event) => {
  if (addingSources) event.preventDefault();
});
addForm.addEventListener("submit", addSources);
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
introSeconds.addEventListener("change", saveSettings);
introSeconds.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    introSeconds.blur();
  }
});
skipIntro.addEventListener("change", saveSettings);
anime4k.addEventListener("change", saveSettings);

refresh();
setInterval(refresh, 1500);
