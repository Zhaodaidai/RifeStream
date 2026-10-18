/* Independent of HLS and video transforms. Every position is full-episode seconds. */
class DanmakuOverlay {
  static defaults = { enabled: false, opacity: 100, fontSize: 24, area: 50 };

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
      return { time, text: text.trim().slice(0, 4096), mode: [4, 5].includes(mode) ? mode : 1,
        color: Number.isFinite(color) ? Math.max(0, Math.min(16777215, Math.trunc(color))) : 16777215 };
    }).filter(Boolean).sort((a, b) => a.time - b.time);
  }

  // Never insert remote markup into the document. Only read img src/alt;
  // CSS, event handlers, srcset and arbitrary HTML are not applied.
  static parts(text) {
    const parts = [];
    const images = /<img\b(?:[^'">]|"[^"]*"|'[^']*')*>/gi;
    let cursor = 0;
    for (const match of text.matchAll(images)) {
      if (match.index > cursor) parts.push({ text: text.slice(cursor, match.index) });
      const attributes = {};
      const attrs = /([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g;
      for (const attr of match[0].slice(4).matchAll(attrs)) attributes[attr[1].toLowerCase()] = attr[2] ?? attr[3] ?? attr[4];
      let src = (attributes.src || "").replace(/&amp;/gi, "&");
      try {
        const url = new URL(src.startsWith("//") ? `https:${src}` : src);
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("unsupported image");
        parts.push({ src: url.href, alt: (attributes.alt || "□").slice(0, 16) });
      } catch { parts.push({ text: (attributes.alt || "□").slice(0, 16) }); }
      cursor = match.index + match[0].length;
    }
    if (cursor < text.length) parts.push({ text: text.slice(cursor) });
    return parts.slice(0, 32);
  }

  image(src) {
    let entry = this.images.get(src);
    if (entry) {
      this.images.delete(src); this.images.set(src, entry);
      return entry;
    }
    // LRU bounds decoded-image memory; never keep a full episode of emoji alive.
    while (this.images.size >= 128) {
      const key = this.images.keys().next().value;
      const old = this.images.get(key);
      window.clearTimeout(old.timer);
      old.image.onload = old.image.onerror = null;
      old.image.src = "";
      this.images.delete(key);
    }
    const image = new Image();
    entry = { image, ready: false, failed: false, bytes: 0 };
    this.images.set(src, entry);
    image.referrerPolicy = "no-referrer";
    image.decoding = "async";
    const finish = (failed) => {
      window.clearTimeout(entry.timer);
      if (this.images.get(src) !== entry) return;
      entry.failed = failed;
      entry.ready = !failed;
      // Update only cached sprites which use this image. Never re-layout the episode.
      this.dirtyImages.add(src);
      this.sync();
    };
    entry.timer = window.setTimeout(() => { finish(true); image.src = ""; }, 10000);
    image.onload = () => {
      const pixels = image.naturalWidth * image.naturalHeight;
      if (!pixels || pixels > 4000000) { finish(true); return; }
      entry.bytes = pixels * 4;
      // A 24 MiB decoded cache budget, independent of the sprite budget.
      let total = [...this.images.values()].reduce((sum, value) => sum + value.bytes, 0);
      for (const [key, value] of this.images) {
        if (total <= 24 * 1024 * 1024) break;
        if (key === src) continue;
        total -= value.bytes;
        window.clearTimeout(value.timer);
        value.image.onload = value.image.onerror = null; value.image.src = "";
        this.images.delete(key);
      }
      finish(false);
    };
    image.onerror = () => finish(true);
    image.src = src;
    return entry;
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
    this.images = new Map();
    this.sprites = new Map();
    this.spriteBytes = 0;
    this.dirtyImages = new Set();
    this.metrics = { layouts: 0, layoutMs: 0, sprites: 0, draws: 0, admitted: 0, skipped: 0 };
    // danmu.js reads player.currentTime in seconds and multiplies it by 1000.
    // Keep a small media-like adapter so its native scheduler never sees a stale
    // or missing clock when the host player is paused, seeking, or HLS-backed.
    this.clock = new EventTarget();
    this.activeCanvases = new Map();
    this.clock.paused = true;
    this.clock.readyState = 4;
    Object.defineProperties(this.clock, {
      currentTime: { get: () => this.seekPosition ?? (this.player.position() + 0.000001) },
      playbackRate: { get: () => Number(this.video.playbackRate) || 1 },
      duration: { get: () => Number(this.player.state?.duration) || Infinity },
    });
    this.token = 0;
    this.settings = { ...DanmakuOverlay.defaults };
    try {
      const saved = JSON.parse(window.localStorage.getItem("rife.danmaku") || "null");
      if (saved && typeof saved === "object") this.settings = {
        enabled: saved.enabled === true,
        opacity: Math.max(10, Math.min(100, Number(saved.opacity) || 100)),
        fontSize: Math.max(12, Math.min(36, Math.round(Number(saved.fontSize) || 24))),
        area: Math.max(25, Math.min(100, Math.round((Number(saved.area) || 50) / 25) * 25)),
      };
    } catch { /* Storage may be unavailable in private/embedded contexts. */ }
    this.host = this.doc.createElement("div");
    this.host.className = "danmaku-layer";
    this.host.setAttribute("aria-hidden", "true");
    (player.ui?.elements?.container || this.frame).appendChild(this.host);
    this.engine = new window.DanmuJs({
      container: this.host, player: this.clock, comments: [], defaultOff: true,
      area: { start: 0, end: this.settings.area / 100 },
      channelSize: this.settings.fontSize * 1.5 + 6,
      overlap: false, interval: 250, highScorePriority: false, chaseEffect: true,
      disableCopyDOM: true,
      hooks: {
        bulletCreateEl: (entry) => this.createBullet(entry),
        bulletDetached: (_entry, element) => this.activeCanvases.delete(element),
      },
    });
    this.buildControls();
    this.observer = new ResizeObserver(() => this.rebuild());
    this.observer.observe(player.ui?.elements?.container || this.frame);
    for (const event of ["playing", "seeked", "timeupdate", "pause", "ended", "ratechange", "loadedmetadata", "seeking", "waiting", "emptied"]) {
      this.video.addEventListener(event, () => {
        if (["waiting", "emptied"].includes(event)) this.buffering = true;
        if (["playing", "seeked"].includes(event)) this.buffering = false;
        if (["emptied", "seeking"].includes(event)) this.clear();
        if (["seeked", "ratechange"].includes(event)) this.needsSeek = true;
        this.sync();
      });
    }
    this.doc.addEventListener("visibilitychange", () => {
      this.needsSeek = true;
      this.sync();
    });
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
      <div class="danmaku-panel-head"><strong>弹幕设置</strong><label class="danmaku-switch"><span>显示弹幕</span><input id="danmakuEnabled" type="checkbox" role="switch"></label></div>
      <div class="danmaku-setting-row"><label for="danmakuOpacity">不透明度</label><input id="danmakuOpacity" type="range" min="10" max="100" step="5"><output id="danmakuOpacityValue" for="danmakuOpacity"></output></div>
      <div class="danmaku-setting-row"><label for="danmakuFontSize">字号</label><input id="danmakuFontSize" type="range" min="12" max="36" step="1"><output id="danmakuFontSizeValue" for="danmakuFontSize"></output></div>
      <div class="danmaku-setting-row"><label for="danmakuArea">显示区域</label><input id="danmakuArea" type="range" min="25" max="100" step="25"><output id="danmakuAreaValue" for="danmakuArea"></output></div>
      <p id="danmakuStatus" role="status">本集未提供弹幕地址</p>`;
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
      input.addEventListener(key === "enabled" ? "change" : "input", () => {
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
    this.updateControls();
  }

  updateControls() {
    this.panel.querySelector("#danmakuOpacityValue").value = `${this.settings.opacity}%`;
    this.panel.querySelector("#danmakuFontSizeValue").value = `${this.settings.fontSize}px`;
    this.panel.querySelector("#danmakuAreaValue").value = ({25: "1/4屏", 50: "半屏", 75: "3/4屏", 100: "全屏"})[this.settings.area];
    for (const id of ["danmakuOpacity", "danmakuFontSize", "danmakuArea"]) {
      const input = this.panel.querySelector(`#${id}`);
      const value = this.panel.querySelector(`#${id}Value`).value;
      input.setAttribute("aria-valuetext", value);
      const filled = (Number(input.value) - Number(input.min)) / (Number(input.max) - Number(input.min)) * 100;
      input.style.backgroundImage = `linear-gradient(to right, var(--accent) ${filled}%, var(--line) ${filled}%)`;
    }
    this.host.style.opacity = String(this.settings.opacity / 100);
    this.host.hidden = !this.settings.enabled;
    this.button.classList.toggle("danmaku-enabled", this.settings.enabled);
  }

  setItem(item) {
    const identity = item ? JSON.stringify([item.id, item.olink || ""]) : "";
    if (identity === this.identity) return;
    this.identity = identity;
    for (const cached of this.images.values()) {
      window.clearTimeout(cached.timer);
      cached.image.onload = null; cached.image.onerror = null; cached.image.src = "";
    }
    this.images.clear();
    this.releaseSprites();
    this.item = item;
    ++this.token;
    this.controller?.abort();
    this.loading = false; this.loaded = false;
    this.comments = []; this.layout = [];
    this.engine.updateComments([]);
    this.clear();
    this.status.textContent = item?.olink ? "已接收 olink，开启弹幕后加载" : "本集未提供 olink 弹幕地址";
    if (this.settings.enabled && item?.olink) this.load();
  }

  async load() {
    ++this.token;
    this.controller?.abort();
    this.loading = false;
    this.loaded = false; this.comments = []; this.layout = []; this.clear();
    if (!this.item?.olink) { this.status.textContent = "本集未提供 olink 弹幕地址"; return; }
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
      if (token === this.token) this.status.textContent = error.name === "AbortError" ? "弹幕加载超时，可关闭后重新开启弹幕重试" : `弹幕加载失败：${error.message}`;
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

  // Re-layout is coalesced to one task per frame, including slider drags and resize storms.
  rebuild() {
    this.needsLayout = true;
    this.sync();
  }

  releaseSprites() {
    for (const sprite of this.sprites.values()) {
      sprite.canvas.width = 0; sprite.canvas.height = 0;
    }
    this.sprites.clear(); this.spriteBytes = 0; this.dirtyImages.clear();
  }

  rebuildNow() {
    const start = performance.now();
    const surface = this.player.ui?.elements?.container || this.frame;
    const rect = surface.getBoundingClientRect();
    this.width = Math.max(1, rect.width);
    this.height = Math.max(1, rect.height * this.settings.area / 100);
    this.engine.stop();
    this.engine.clear();
    this.activeCanvases.clear();
    this.releaseSprites();
    // The host always covers the full player. Native area controls the engine's
    // channel count; no cropped host, custom row allocator, sampling or token cap.
    this.engine.setFontSize(this.settings.fontSize, this.settings.fontSize * 1.5 + 6, { reflow: false });
    this.engine.setArea({ start: 0, end: this.settings.area / 100 });
    this.engine.resize();
    this.layout = this.comments.map((item, index) => ({
      id: `episode-${this.token}-${index}`, start: Math.max(1, item.time * 1000), duration: 6000,
      mode: item.mode === 5 ? "top" : item.mode === 4 ? "bottom" : "scroll",
      elLazyInit: true, disableCopyDOM: true, style: {}, source: item,
    }));
    this.engine.updateComments(this.layout);
    this.metrics.admitted = this.layout.length;
    this.metrics.skipped = 0;
    this.metrics.layouts++;
    this.metrics.layoutMs = performance.now() - start;
    this.needsLayout = false;
    this.needsSeek = true;
  }

  createBullet(entry) {
    const sprite = this.sprite(entry.source);
    const canvas = this.doc.createElement("canvas");
    canvas.className = "danmaku-sprite";
    canvas.width = sprite.canvas.width; canvas.height = sprite.canvas.height;
    // The native engine writes cssText when attaching the node; provide CSS
    // dimensions through its own style option so HiDPI backing pixels stay sharp
    // without doubling the collision box.
    entry.style.width = `${sprite.width}px`; entry.style.height = `${sprite.height}px`;
    canvas.style.width = entry.style.width; canvas.style.height = entry.style.height;
    canvas.getContext("2d").drawImage(sprite.canvas, 0, 0);
    // Each live bullet needs its own node (including duplicate emoji/text).
    // The shared offscreen raster remains cached; untrusted HTML is never inserted.
    this.activeCanvases.set(canvas, sprite);
    return canvas;
  }

  sprite(item) {
    const key = `${this.settings.fontSize}|${item.color}|${item.text}`;
    let sprite = this.sprites.get(key);
    if (sprite) {
      this.sprites.delete(key); this.sprites.set(key, sprite);
      return sprite;
    }
    const font = this.settings.fontSize;
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const canvas = this.doc.createElement("canvas");
    const context = canvas.getContext("2d");
    context.font = `600 ${font}px sans-serif`;
    const runs = [];
    let width = 0;
    for (const part of DanmakuOverlay.parts(item.text)) {
      if (part.src) {
        const size = font * 1.2;
        runs.push({ ...part, offset: width, width: size, height: size });
        width += size + 3;
      } else {
        let text = part.text.slice(0, 120);
        // Truncate with binary search instead of repeatedly measuring one character less.
        if (context.measureText(text).width + width > this.width * 2) {
          let low = 0, high = text.length;
          while (low < high) {
            const middle = Math.ceil((low + high) / 2);
            if (context.measureText(text.slice(0, middle)).width + width <= this.width * 2) low = middle;
            else high = middle - 1;
          }
          text = text.slice(0, low);
        }
        const size = context.measureText(text).width;
        runs.push({ text, offset: width }); width += size;
      }
      if (width >= this.width * 2) break;
    }
    const height = font * 1.5;
    canvas.width = Math.max(1, Math.ceil(width + 6) * ratio);
    canvas.height = Math.ceil(height + 6) * ratio;
    sprite = { canvas, context, runs, width: width + 6, height: height + 6, ratio, color: item.color, font, bytes: canvas.width * canvas.height * 4 };
    canvas.dataset.danmakuWidth = String(sprite.width);
    canvas.dataset.danmakuHeight = String(sprite.height);
    while (this.sprites.size >= 192 || this.spriteBytes + sprite.bytes > 16 * 1024 * 1024) {
      const oldest = this.sprites.keys().next().value;
      if (oldest === undefined) break;
      const removed = this.sprites.get(oldest);
      this.spriteBytes -= removed.bytes;
      this.sprites.delete(oldest);
      // Do not mutate evicted canvases: the engine may still display that sprite.
    }
    this.sprites.set(key, sprite); this.spriteBytes += sprite.bytes;
    this.paintSprite(sprite);
    this.metrics.sprites++;
    return sprite;
  }

  paintSprite(sprite) {
    const { context: ctx, canvas, font } = sprite;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(sprite.ratio, 0, 0, sprite.ratio, 0, 0);
    ctx.font = `600 ${font}px sans-serif`;
    ctx.textBaseline = "top"; ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,0.8)";
    ctx.fillStyle = `#${sprite.color.toString(16).padStart(6, "0")}`;
    for (const run of sprite.runs) {
      const x = run.offset + 3, y = 3;
      if (run.src) {
        const cached = this.image(run.src);
        if (cached?.ready) {
          const scale = Math.min(run.width / cached.image.naturalWidth, run.height / cached.image.naturalHeight);
          const width = cached.image.naturalWidth * scale, height = cached.image.naturalHeight * scale;
          ctx.drawImage(cached.image, x + (run.width - width) / 2, y + (run.height - height) / 2, width, height);
        } else if (cached?.failed || !cached) {
          ctx.strokeText(run.alt, x, y); ctx.fillText(run.alt, x, y);
        }
      } else { ctx.strokeText(run.text, x, y); ctx.fillText(run.text, x, y); }
    }
  }

  clear() {
    this.stopClock();
    this.engine.clear();
    this.activeCanvases.clear();
    this.needsSeek = true;
  }

  stopClock() {
    this.clock.paused = true;
    this.engine.pause();
    window.cancelAnimationFrame(this.previewTask);
    this.previewTask = null;
  }

  sync() {
    const current = this.player.position();
    if (this.lastPosition !== undefined && (current < this.lastPosition || current - this.lastPosition > 1.5)) this.needsSeek = true;
    this.lastPosition = current;
    if (this.animation) return;
    const visible = this.settings.enabled && this.loaded && !this.doc.hidden && !this.player.seeking && !this.video.seeking && !this.player.reloading;
    const running = !this.video.paused && !this.video.ended && !this.buffering;
    if (!this.needsLayout && !this.needsSeek && !this.dirtyImages.size && visible && this.engineVisible &&
      (running ? !this.clock.paused : this.clock.paused && this.previewPosition === current)) return;
    this.animation = window.requestAnimationFrame(() => {
      this.animation = null;
      if (this.needsLayout) this.rebuildNow();
      const dirty = this.dirtyImages.size > 0;
      if (dirty) {
        const sprites = new Set([...this.sprites.values(), ...this.activeCanvases.values()]);
        for (const sprite of sprites) if (sprite.runs.some((run) => run.src && this.dirtyImages.has(run.src))) this.paintSprite(sprite);
        for (const [canvas, sprite] of this.activeCanvases) {
          if (!canvas.isConnected) { this.activeCanvases.delete(canvas); continue; }
          const ctx = canvas.getContext("2d"); ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.drawImage(sprite.canvas, 0, 0);
        }
        this.dirtyImages.clear();
      }
      const position = this.player.position();
      if (!this.settings.enabled || !this.loaded || this.doc.hidden || this.player.seeking || this.video.seeking || this.player.reloading) {
        this.stopClock(); this.host.hidden = true; this.engineVisible = false; return;
      }
      this.host.hidden = false; this.engineVisible = true;
      if (this.needsSeek) {
        this.stopClock(); this.engine.stop(); this.engine.clear(); this.activeCanvases.clear();
        // Native engine consumes its own pool flags; rebuild only those flags on
        // seek, without modifying timestamps or prefiltering the source sequence.
        this.engine.updateComments(this.layout.map((entry) => ({ ...entry, attached_: false })));
        this.needsSeek = false; this.previewPosition = undefined;
      }
      const playing = !this.video.paused && !this.video.ended && !this.buffering;
      const rate = Number(this.video.playbackRate) || 1;
      if (rate !== this.engineRate) {
        for (const mode of ["scroll", "top", "bottom"]) this.engine.setPlayRate(mode, rate);
        this.engineRate = rate;
      }
      if (playing || dirty || this.previewPosition !== position) {
        this.clock.paused = false;
        if (this.engine.status === "closed" || this.engine.status === "idle") this.engine.start();
        else if (this.engine.status !== "playing") this.engine.play();
        if (!playing) {
          this.previewPosition = position;
          this.previewTask = window.requestAnimationFrame(() => this.stopClock());
        }
      } else this.stopClock();
    });
  }
}
window.DanmakuOverlay = DanmakuOverlay;
