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
let playlistSignature = "";
let currentState = null;
let errorVisibleUntil = 0;
const pendingActions = new Set();
const settingsStatus = document.getElementById("settingsStatus");
const introError = document.getElementById("introError");

async function performAction(key, button, action) {
  if (pendingActions.has(key)) return;
  pendingActions.add(key);
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  if (currentState) paintAvailability(currentState);
  try { await action(); }
  catch (error) { showError(error.message); }
  finally {
    pendingActions.delete(key);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    if (currentState) paintAvailability(currentState);
  }
}

function paintAvailability(state) {
  prevBtn.disabled = !state.has_prev || pendingActions.has("play");
  nextBtn.disabled = !state.has_next || pendingActions.has("play");
  playBtn.disabled = !state.current || pendingActions.has("play");
  stopBtn.disabled = !state.streaming || pendingActions.has("stop");
  document.getElementById("clearBtn").disabled = !state.items.length || pendingActions.has("clear");
}
const embeddedPlayer = new EmbeddedPlayer({
  video: document.getElementById("videoPlayer"),
  progress: document.getElementById("episodeProgress"),
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
    if (modifying) { errorVisibleUntil = 0; showError(""); }
    return data;
  } finally { if (modifying) requestsInFlight--; }
}

function showError(message, fromState = false) {
  if (fromState && !message && Date.now() < errorVisibleUntil) return;
  if (message && !fromState) errorVisibleUntil = Date.now() + 6000;
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
  if (parts.length < 2 || parts.length > 3 || parts.some((part) => !/^\d+$/.test(part))) return NaN;
  const numbers = parts.map((part) => Number(part));
  if (numbers.some((part, index) => !Number.isFinite(part) || part < 0 || (index > 0 && part >= 60))) return NaN;
  if (parts.length === 2) return numbers[0] * 60 + numbers[1];
  return numbers[0] * 3600 + numbers[1] * 60 + numbers[2];
}

function paintSettings(settings) {
  if (!settings) return;
  if (document.activeElement !== introSeconds && introSeconds.getAttribute("aria-invalid") !== "true") {
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
    introSeconds.setAttribute("aria-invalid", "true");
    introError.textContent = "片头请使用秒数、1:30 或 1:02:03 格式";
    introError.hidden = false;
    settingsStatus.textContent = "";
    return;
  }
  introSeconds.removeAttribute("aria-invalid");
  introError.hidden = true;
  savingSettings = true;
  settingsStatus.textContent = "正在保存设置…";
  skipIntro.disabled = anime4k.disabled = introSeconds.disabled = true;
  try {
    renderState(await api("/api/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    }));
    settingsStatus.textContent = "设置已保存";
  } catch (error) {
    settingsStatus.textContent = "保存失败，请重试";
    showError(error.message);
  } finally {
    savingSettings = false;
    skipIntro.disabled = anime4k.disabled = introSeconds.disabled = false;
  }
}

function renderState(state) {
  currentState = state;
  embeddedPlayer.update(state);
  document.getElementById("playerEmpty").hidden = Boolean(state.hls_ready || state.streaming);
  document.getElementById("playlistCount").textContent = state.items.length;
  paintAvailability(state);
  const current = state.current;
  document.querySelector("#playerEmpty h3").textContent = current ? "已就绪，开始播放吧" : "好画面，从这里开始";
  document.querySelector("#playerEmpty p").textContent = current ? "点击播放，启动补帧与视频转码" : "添加媒体链接，开启流畅观影";
  document.getElementById("playerAddBtn").lastChild.textContent = current ? "播放所选媒体" : "添加媒体";
  document.querySelector("#playerAddBtn path").setAttribute("d", current ? "m9 5 11 7-11 7z" : "M12 5v14M5 12h14");
  paintSettings(state.settings);
  nowPlaying.textContent = current
    ? `${state.streaming ? "正在播放" : "已选择"}：${current.title}`
    : "未选择媒体";
  streamStatus.textContent = state.streaming ? "转码中" : "待机";
  streamStatus.classList.toggle("live", Boolean(state.streaming));
  showError(state.last_error, true);

  const signature = JSON.stringify([state.items, state.current_id]);
  if (signature === playlistSignature) return;
  playlistSignature = signature;
  const focused = document.activeElement;
  const focusRow = focused?.closest("li[data-id]")?.dataset.id;
  const focusClass = focused?.className;
  const scrollTop = playlistEl.scrollTop;
  playlistEl.innerHTML = "";
  if (!state.items.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.innerHTML = '<span class="empty-list-icon" aria-hidden="true">＋</span><span class="empty-title">你的播放列表，等你填满</span><span class="empty-caption">添加媒体链接<br>喜欢的内容，一处收好</span>';
    playlistEl.appendChild(empty);
    if (focusRow) document.getElementById("openAddBtn").focus({ preventScroll: true });
    return;
  }
  state.items.forEach((item, index) => {
    const li = document.createElement("li");
    li.dataset.id = item.id;
    if (item.id === state.current_id) { li.classList.add("current"); li.setAttribute("aria-current", "true"); }
    li.innerHTML = `
      <span class="index">${index + 1}</span>
      <button type="button" class="name">${escapeHtml(item.title)}</button>
      <span class="kind">${item.kind === "url" ? "链接" : "文件"}</span>
      <button type="button" class="remove" title="删除此媒体" aria-label="删除 ${escapeHtml(item.title)}">×</button>
    `;
    li.querySelector(".name").title = item.title;
    li.querySelector(".name").addEventListener("click", () => play({ id: item.id }));
    li.querySelector(".remove").addEventListener("click", async (event) => {
      event.stopPropagation();
      await performAction(`delete:${item.id}`, event.currentTarget, async () => {
        renderState(await api(`/api/items/${item.id}`, { method: "DELETE" }));
      });
    });
    playlistEl.appendChild(li);
  });
  playlistEl.scrollTop = scrollTop;
  if (focusRow) {
    const row = Array.from(playlistEl.children).find((node) => node.dataset.id === focusRow);
    const replacement = row?.querySelector(focusClass === "remove" ? ".remove" : ".name");
    (replacement || document.getElementById("openAddBtn")).focus({ preventScroll: true });
  }
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
  sourceInput.removeAttribute("aria-invalid");
  addingSources = true;
  sourceInput.readOnly = true;
  addForm.setAttribute("aria-busy", "true");
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
    sourceInput.setAttribute("aria-invalid", "true");
    addError.textContent = error.message;
    addError.hidden = false;
  } finally {
    addingSources = false;
    sourceInput.readOnly = false;
    addForm.removeAttribute("aria-busy");
    finishAddBtn.disabled = false;
    finishAddBtn.textContent = "完成";
  }
}

async function play(body) {
  await performAction("play", playBtn, async () => {
    renderState(await api("/api/play", { method: "POST", body: JSON.stringify(body) }));
  });
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
  sourceInput.removeAttribute("aria-invalid");
  addDialog.showModal();
  sourceInput.focus();
});
document.getElementById("playerAddBtn").addEventListener("click", () => currentState?.current ? play({}) : document.getElementById("openAddBtn").click());
document.getElementById("cancelAddBtn").addEventListener("click", () => {
  if (!addingSources) addDialog.close();
});
addDialog.addEventListener("cancel", (event) => {
  if (addingSources) event.preventDefault();
});
addForm.addEventListener("submit", addSources);
document.getElementById("clearBtn").addEventListener("click", async () => {
  await performAction("clear", document.getElementById("clearBtn"), async () => {
    renderState(await api("/api/clear", { method: "POST", body: "{}" }));
  });
});
prevBtn.addEventListener("click", () => play({ offset: -1 }));
nextBtn.addEventListener("click", () => play({ offset: 1 }));
playBtn.addEventListener("click", () => play({}));
stopBtn.addEventListener("click", async () => {
  await performAction("stop", stopBtn, async () => {
    renderState(await api("/api/stop", { method: "POST", body: "{}" }));
  });
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
