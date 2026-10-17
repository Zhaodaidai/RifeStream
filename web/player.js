/* HLS session lifecycle is separate from playlist rendering and its polling clock. */
class EmbeddedPlayer {
  constructor({ video, timeline, clock, hint, formatTime, seek }) {
    Object.assign(this, { video, timeline, clock, hint, formatTime, seek });
    this.key = null;
    this.state = null;
    this.hls = null;
    this.retry = null;
    this.failures = 0;
    this.dragging = false;
    timeline.addEventListener("input", () => {
      this.dragging = true;
      this.paintTime(Number(timeline.value));
    });
    timeline.addEventListener("change", () => {
      this.dragging = false;
      this.jump(Number(timeline.value));
    });
    video.addEventListener("timeupdate", () => this.paint());
    video.addEventListener("playing", () => {
      hint.textContent = "网页播放中";
      this.failures = 0;
    });
    video.addEventListener("waiting", () => { hint.textContent = "等待转码 / 缓冲中…"; });
    video.addEventListener("error", () => {
      if (!this.hls && this.key) this.retryLoad(this.key);
    });
    video.addEventListener("loadedmetadata", () => this.autoplay());
  }

  destroy() {
    clearTimeout(this.retry);
    this.retry = null;
    if (this.hls) this.hls.destroy();
    this.hls = null;
    this.video.pause();
    this.video.removeAttribute("src");
    this.video.load();
  }

  update(state) {
    this.state = state;
    const key = state.current && state.hls_ready
      ? JSON.stringify([state.current.id, state.playback_id, state.start, state.hls_url]) : null;
    if (key !== this.key) {
      this.key = key;
      this.destroy();
      this.failures = 0;
      if (key) this.load(key);
    }
    if (!key) this.hint.textContent = state.streaming ? "等待新一集 / 跳转位置生成分片…" : "选择一集后点击播放";
    this.timeline.disabled = !state.seekable;
    this.timeline.max = Number(state.duration) || 0;
    this.paint();
  }

  load(key) {
    if (this.key !== key) return;
    const url = new URL(this.state.hls_url, window.location.href);
    // Use the browser's host, not a server-selected LAN adapter (localhost/VPN).
    url.hostname = window.location.hostname;
    url.searchParams.set("session", this.state.playback_id || 0);
    this.hint.textContent = "正在加载转码视频…";
    if (window.Hls && window.Hls.isSupported()) {
      const hls = this.hls = new window.Hls({
        startPosition: 0,
        liveSyncDurationCount: 1000000,
        liveMaxLatencyDurationCount: Infinity,
        maxBufferLength: 30,
        backBufferLength: 60,
      });
      hls.on(window.Hls.Events.ERROR, (_event, data) => {
        if (data.fatal && this.key === key) this.retryLoad(key);
      });
      hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
        if (this.key === key) this.autoplay();
      });
      hls.loadSource(url.href);
      hls.attachMedia(this.video);
    } else if (this.video.canPlayType("application/vnd.apple.mpegurl")) {
      this.video.src = url.href;
      this.video.load();
    } else {
      this.hint.textContent = "此浏览器不支持 HLS，请换用支持的浏览器或复制顶部 HLS 地址。";
    }
  }

  retryLoad(key) {
    if (this.retry || this.key !== key) return;
    if (++this.failures > 8) {
      this.hint.textContent = "视频加载失败，请点击播放重试，或检查转码日志。";
      return;
    }
    this.hint.textContent = "等待转码分片，正在重试…";
    this.retry = setTimeout(() => {
      if (this.key !== key) return;
      this.destroy();
      this.load(key);
    }, 2000);
  }

  autoplay() {
    const result = this.video.play();
    if (result && result.catch) result.catch(() => {
      this.hint.textContent = "浏览器未允许自动播放，请点击视频中的播放按钮。";
    });
  }

  position() {
    return (Number(this.state?.start) || 0) + (Number(this.video.currentTime) || 0);
  }

  paintTime(position) {
    this.clock.textContent = `${this.formatTime(position)} / ${this.state?.duration ? this.formatTime(this.state.duration) : "--:--"}`;
  }

  paint() {
    if (this.dragging) return;
    const position = this.position();
    this.timeline.value = position;
    this.paintTime(position);
  }

  async jump(seconds) {
    if (!this.state?.seekable) return;
    const local = seconds - (Number(this.state.start) || 0);
    const ranges = this.video.seekable;
    for (let i = 0; this.key && i < ranges.length; i++) {
      if (local >= ranges.start(i) && local < ranges.end(i)) {
        this.video.currentTime = local;
        this.paint();
        return;
      }
    }
    this.hint.textContent = "正在跳转，等待重新生成分片…";
    await this.seek(seconds);
  }
}
