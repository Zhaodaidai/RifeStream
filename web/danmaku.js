/* Independent of HLS and video transforms. Every position is full-episode seconds. */
class DanmakuOverlay {
  static defaults = { enabled: false, opacity: 75, fontSize: 24, area: 50 };

  static normalize(entries) {
    if (!Array.isArray(entries)) throw new Error("JSON 弹幕需为数组或包含 comments 数组");
    if (entries.length > 50000) throw new Error("弹幕数量超过 50000 条限制");
    return entries.map((entry) => {
      if (!entry || typeof entry !== "object") return null;
      const p = typeof entry.p === "string" ? entry.p.split(",") : null;
      const time = Number(p ? p[0] : entry.time);
      let text = p ? entry.m : entry.text;
      const mode = Number(p ? p[1] : entry.mode ?? 1);
      const color = Number(p ? p[2] : entry.color ?? 16777215);
      if (!Number.isFinite(time) || time < 0 || typeof text !== "string" || !text.trim()) return null;
      // Canvas is text-only: omit image markup instead of exposing its src/styles.
      text = text.replace(/<img\b(?:[^'">]|"[^"]*"|'[^']*')*>/gi, "").trim();
      if (!text) return null;
      return { time, text: text.slice(0, 300), mode: [4, 5].includes(mode) ? mode : 1,
        color: Number.isFinite(color) ? Math.max(0, Math.min(16777215, Math.trunc(color))) : 16777215 };
    }).filter(Boolean).sort((a, b) => a.time - b.time);
  }

  static parse(text) {
    text = text.replace(/^\uFEFF/, "").trim();
    if (text.startsWith("<")) {
      if (/<!DOCTYPE\s+html\b|<html\b/i.test(text)) throw new Error("olink 返回的是 HTML 网页，不是弹幕文件；需要该站点的实际弹幕 XML/JSON 接口");
      // Discard document metadata, including external DTD URLs, without loading them.
      text = text.replace(/<!DOCTYPE\s+i(?:\s+SYSTEM\s+(?:"[^"<>\[\]]*"|'[^'<>\[\]]*')|\s+PUBLIC\s+(?:"[^"<>\[\]]*"|'[^'<>\[\]]*')\s+(?:"[^"<>\[\]]*"|'[^'<>\[\]]*'))?\s*>/gi, "");
      if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw new Error("不支持包含内部 DTD/自定义实体定义的弹幕文件");
      const xml = new DOMParser().parseFromString(text, "application/xml");
      if (xml.querySelector("parsererror") || xml.documentElement.tagName !== "i") {
        throw new Error("文件不是支持的弹幕 XML；网页地址需要实际弹幕接口");
      }
      const entries = [...xml.querySelectorAll("d")].map((node) => {
        const p = (node.getAttribute("p") || "").split(",");
        return { time: p[0], mode: p[1], color: p[3], text: node.textContent };
      });
      return this.normalize(entries);
    }
    let payload;
    try { payload = JSON.parse(text); } catch { throw new Error("弹幕文件必须为 XML/JSON，不支持 HTML 网页"); }
    return this.normalize(Array.isArray(payload) ? payload : payload?.comments);
  }

  constructor(player) {
    this.player = player;
    this.video = player.video;
    this.frame = player.frame;
    this.doc = this.video.ownerDocument;
    this.comments = [];
    this.layout = [];
    this.token = 0;
    this.settings = { ...DanmakuOverlay.defaults };
    try {
      const saved = JSON.parse(window.localStorage.getItem("rife.danmaku") || "null");
      if (saved && typeof saved === "object") this.settings = {
        enabled: saved.enabled === true,
        opacity: Math.max(10, Math.min(100, Number(saved.opacity) || 75)),
        fontSize: [18, 24, 30, 36].includes(Number(saved.fontSize)) ? Number(saved.fontSize) : 24,
        area: [25, 50, 75, 100].includes(Number(saved.area)) ? Number(saved.area) : 50,
      };
    } catch { /* Storage may be unavailable in private/embedded contexts. */ }
    this.canvas = this.doc.createElement("canvas");
    this.canvas.className = "danmaku-canvas";
    this.canvas.setAttribute("aria-hidden", "true");
    (player.ui?.elements?.container || this.frame).appendChild(this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.buildControls();
    this.observer = new ResizeObserver(() => { this.rebuild(); this.sync(); });
    this.observer.observe(this.canvas);
    for (const event of ["playing", "seeked", "timeupdate", "pause", "ended", "ratechange", "loadedmetadata", "seeking", "waiting", "emptied"]) {
      this.video.addEventListener(event, () => {
        if (["waiting", "emptied"].includes(event)) this.buffering = true;
        if (["playing", "seeked"].includes(event)) this.buffering = false;
        if (["emptied", "seeking"].includes(event)) this.clear();
        this.sync();
      });
    }
    this.rebuild();
  }

  buildControls() {
    const button = this.button = this.doc.createElement("button");
    button.type = "button";
    button.className = "plyr__controls__item plyr__control danmaku-toggle";
    button.textContent = "弹幕";
    button.setAttribute("aria-label", "弹幕开关与设置");
    button.setAttribute("aria-controls", "danmakuSettings");
    button.setAttribute("aria-expanded", "false");
    const panel = this.panel = this.doc.createElement("div");
    panel.id = "danmakuSettings";
    panel.className = "framing-panel danmaku-panel";
    panel.hidden = true;
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-label", "弹幕设置");
    panel.innerHTML = `
      <label class="danmaku-switch"><span>显示弹幕</span><input id="danmakuEnabled" type="checkbox"></label>
      <label for="danmakuOpacity">透明度 <output id="danmakuOpacityValue" for="danmakuOpacity"></output></label>
      <input id="danmakuOpacity" type="range" min="10" max="100" step="5">
      <label for="danmakuFontSize">字号</label>
      <select id="danmakuFontSize"><option value="18">小 · 18px</option><option value="24">中 · 24px</option><option value="30">大 · 30px</option><option value="36">特大 · 36px</option></select>
      <label for="danmakuArea">显示区域</label>
      <select id="danmakuArea"><option value="25">顶部 1/4</option><option value="50">顶部 1/2</option><option value="75">顶部 3/4</option><option value="100">全屏区域</option></select>
      <p id="danmakuStatus" role="status">本集未提供弹幕地址</p>
      <label for="danmakuFile">导入弹幕 XML / JSON</label><input id="danmakuFile" type="file" accept=".xml,.json">
      <button type="button" class="framing-reset danmaku-reload">重新加载本集弹幕</button>`;
    this.frame.appendChild(panel);
    const controls = this.player.ui?.elements?.controls;
    if (controls) controls.insertBefore(button, this.player.ui.elements.controls.querySelector(".framing-toggle"));
    else { button.classList.add("danmaku-fallback"); this.frame.appendChild(button); }
    this.status = panel.querySelector("#danmakuStatus");
    const close = (focus = false) => {
      panel.hidden = true;
      this.frame.classList.remove("danmaku-open");
      button.setAttribute("aria-expanded", "false");
      if (focus) button.focus();
    };
    button.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      this.frame.classList.toggle("danmaku-open", !panel.hidden);
      button.setAttribute("aria-expanded", String(!panel.hidden));
      if (!panel.hidden) panel.querySelector("input").focus();
    });
    const fields = { enabled: "#danmakuEnabled", opacity: "#danmakuOpacity", fontSize: "#danmakuFontSize", area: "#danmakuArea" };
    for (const [key, selector] of Object.entries(fields)) {
      const input = panel.querySelector(selector);
      if (key === "enabled") input.checked = this.settings[key]; else input.value = String(this.settings[key]);
      input.addEventListener(key === "opacity" ? "input" : "change", () => {
        this.settings[key] = key === "enabled" ? input.checked : Number(input.value);
        try { window.localStorage.setItem("rife.danmaku", JSON.stringify(this.settings)); } catch { /* optional */ }
        this.updateControls();
        if (key === "area" || key === "fontSize") this.rebuild();
        if (key === "enabled" && this.settings.enabled && !this.loaded && this.item?.olink && !this.loading) this.load();
        this.sync();
      });
    }
    for (const element of [panel, button]) element.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Escape" && !panel.hidden) { event.preventDefault(); close(true); }
    });
    this.doc.addEventListener("pointerdown", (event) => {
      if (!panel.hidden && !panel.contains(event.target) && !button.contains(event.target)) close();
    });
    this.player.ui?.on("exitfullscreen", () => close());
    panel.querySelector(".danmaku-reload").addEventListener("click", () => this.load());
    panel.querySelector("#danmakuFile").addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const token = ++this.token;
      this.controller?.abort(); this.loading = false;
      try {
        if (file.size > 8 * 1024 * 1024) throw new Error("弹幕文件超过 8 MiB 限制");
        const text = await file.text();
        if (token !== this.token) return;
        this.accept(DanmakuOverlay.parse(text), `导入 ${file.name}`);
      } catch (error) { if (token === this.token) this.status.textContent = `弹幕加载失败：${error.message}`; }
      finally { event.target.value = ""; }
    });
    this.updateControls();
  }

  updateControls() {
    this.panel.querySelector("#danmakuOpacityValue").value = `${this.settings.opacity}%`;
    this.canvas.style.opacity = String(this.settings.opacity / 100);
    this.canvas.hidden = !this.settings.enabled;
    this.button.classList.toggle("danmaku-enabled", this.settings.enabled);
  }

  setItem(item) {
    const identity = item ? JSON.stringify([item.id, item.olink || ""]) : "";
    if (identity === this.identity) return;
    this.identity = identity;
    this.item = item;
    ++this.token;
    this.controller?.abort();
    this.loading = false; this.loaded = false;
    this.comments = []; this.layout = [];
    this.panel.querySelector("#danmakuFile").value = "";
    this.clear();
    this.status.textContent = item?.olink ? "已接收 olink，开启弹幕后加载" : "本集未提供 olink，可导入弹幕 XML/JSON";
    if (this.settings.enabled && item?.olink) this.load();
  }

  async load() {
    ++this.token;
    this.controller?.abort();
    this.loading = false;
    this.loaded = false; this.comments = []; this.layout = []; this.clear();
    if (!this.item?.olink) { this.status.textContent = "本集未提供 olink，可导入弹幕 XML/JSON"; return; }
    const token = this.token;
    const controller = this.controller = new AbortController();
    this.loading = true;
    this.status.textContent = "正在加载本集弹幕…";
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(`/api/danmaku?id=${encodeURIComponent(this.item.id)}`, { signal: controller.signal });
      const data = await response.json();
      if (token !== this.token) return;
      if (!response.ok) throw new Error(data.error || "弹幕请求失败");
      this.accept(DanmakuOverlay.normalize(data.comments), "olink");
    } catch (error) {
      if (token === this.token) this.status.textContent = error.name === "AbortError" ? "弹幕加载超时，可重新加载" : `弹幕加载失败：${error.message}`;
    } finally {
      window.clearTimeout(timeout);
      if (token === this.token) this.loading = false;
    }
  }

  accept(comments, source) {
    this.comments = comments;
    this.loaded = true;
    this.status.textContent = `${source} · ${comments.length} 条弹幕`;
    this.rebuild(); this.sync();
  }

  rebuild() {
    const rect = this.canvas.getBoundingClientRect();
    this.width = Math.max(1, rect.width);
    this.height = Math.max(1, rect.height);
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    this.canvas.width = Math.round(this.width * ratio);
    this.canvas.height = Math.round(this.height * ratio);
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.ctx.font = `600 ${this.settings.fontSize}px sans-serif`;
    this.ctx.textBaseline = "top";
    this.ctx.lineWidth = 3;
    this.ctx.strokeStyle = "rgba(0,0,0,0.8)";
    const line = this.settings.fontSize * 1.4;
    const available = Math.max(0, Math.min(this.height - 52, this.height * this.settings.area / 100));
    const rows = Math.min(24, Math.max(0, Math.floor((available - this.settings.fontSize - 4) / line) + 1));
    const lanes = Array.from({ length: rows }, () => ({ scroll: 0, fixed: 0 }));
    const speed = this.width / 6 + this.settings.fontSize * 3;
    this.maxAge = 0;
    this.layout = [];
    for (const item of this.comments) {
      const fixed = item.mode === 4 || item.mode === 5;
      const order = item.mode === 4 ? [...lanes.keys()].reverse() : [...lanes.keys()];
      const lane = order.find((i) => lanes[i].fixed <= item.time && lanes[i].scroll <= item.time
        && (!fixed || (lanes[i].end || 0) <= item.time));
      if (lane === undefined) continue; // Drop excess density instead of overlapping lines.
      let text = item.text.slice(0, 120);
      while (text.length > 1 && this.ctx.measureText(text).width > this.width * 3) text = text.slice(0, -1);
      const width = this.ctx.measureText(text).width;
      const duration = fixed ? 4 : (this.width + width) / speed;
      const end = item.time + duration;
      // A fixed comment may only start once an earlier scrolling line fully leaves.
      lanes[lane].scroll = item.time + (fixed ? duration : (width + 30) / speed);
      lanes[lane].fixed = fixed ? end : item.time;
      lanes[lane].end = end;
      this.layout.push({ ...item, text, width, lane, end, speed, fixed, line });
      this.maxAge = Math.max(this.maxAge, duration);
    }
  }

  clear() {
    window.cancelAnimationFrame(this.animation);
    this.animation = null;
    if (this.ctx) this.ctx.clearRect(0, 0, this.width || this.canvas.width, this.height || this.canvas.height);
  }

  sync() {
    this.clear();
    if (!this.settings.enabled || !this.loaded || this.player.seeking || this.video.seeking || this.player.reloading) return;
    this.render();
    if (!this.video.paused && !this.video.ended && !this.buffering) this.animation = window.requestAnimationFrame(() => this.sync());
  }

  render() {
    const position = this.player.position();
    // Binary search keeps long episodes from scanning every historical comment per frame.
    let low = 0, high = this.layout.length;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (this.layout[mid].time < position - this.maxAge) low = mid + 1; else high = mid;
    }
    let visible = 0;
    for (let i = low; i < this.layout.length && this.layout[i].time <= position && visible < 300; i++) {
      const item = this.layout[i];
      if (item.end <= position) continue;
      const x = item.fixed ? (this.width - item.width) / 2 : this.width - (position - item.time) * item.speed;
      const y = item.lane * item.line + 2;
      this.ctx.fillStyle = `#${item.color.toString(16).padStart(6, "0")}`;
      this.ctx.strokeText(item.text, x, y);
      this.ctx.fillText(item.text, x, y);
      visible++;
    }
  }
}
window.DanmakuOverlay = DanmakuOverlay;
