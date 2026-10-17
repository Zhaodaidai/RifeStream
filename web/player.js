/* HLS session lifecycle is separate from playlist rendering and its polling clock. */
class EmbeddedPlayer {
  constructor({ video, progress, timeline, clock, hint, formatTime, seek }) {
    Object.assign(this, { video, progress, timeline, clock, hint, formatTime, seek });
    this.key = null;
    this.state = null;
    this.hls = null;
    this.retry = null;
    this.failures = 0;
    this.dragging = false;
    this.seeking = false;
    // Plyr owns controls only. HLS sessions and the full-episode clock stay here.
    this.ui = window.Plyr ? new window.Plyr(video, {
      iconUrl: "/vendor/plyr.svg",
      blankVideo: "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMUbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAA+gAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAj90cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAA+gAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAPoAAAAAAABAAAAAAG3bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAABAAAAAQABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABYm1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAASJzdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFUxhdmM2Mi4xMS4xMDAgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAANGF2Y0MBZAAK/+EAF2dkAAqs2V7ARAAAAwAEAAADAAg8SJZYAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAAABYoAAAAAAAAABhzdHRzAAAAAAAAAAEAAAABAABAAAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAALFAAAAAQAAABRzdGNvAAAAAAAAAAEAAANEAAAAYXVkdGEAAABZbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAsaWxzdAAAACSpdG9vAAAAHGRhdGEAAAABAAAAAExhdmY2Mi4zLjEwMAAAAAhmcmVlAAACzW1kYXQAAAKtBgX//6ncRem95tlIt5Ys2CDZI+7veDI2NCAtIGNvcmUgMTY1IHIzMjIyIGIzNTYwNWEgLSBILjI2NC9NUEVHLTQgQVZDIGNvZGVjIC0gQ29weWxlZnQgMjAwMy0yMDI1IC0gaHR0cDovL3d3dy52aWRlb2xhbi5vcmcveDI2NC5odG1sIC0gb3B0aW9uczogY2FiYWM9MSByZWY9MyBkZWJsb2NrPTE6MDowIGFuYWx5c2U9MHgzOjB4MTEzIG1lPWhleCBzdWJtZT03IHBzeT0xIHBzeV9yZD0xLjAwOjAuMDAgbWl4ZWRfcmVmPTEgbWVfcmFuZ2U9MTYgY2hyb21hX21lPTEgdHJlbGxpcz0xIDh4OGRjdD0xIGNxbT0wIGRlYWR6b25lPTIxLDExIGZhc3RfcHNraXA9MSBjaHJvbWFfcXBfb2Zmc2V0PS0yIHRocmVhZHM9MSBsb29rYWhlYWRfdGhyZWFkcz0xIHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9MCBibHVyYXlfY29tcGF0PTAgY29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVzPTMgYl9weXJhbWlkPTIgYl9hZGFwdD0xIGJfYmlhcz0wIGRpcmVjdD0xIHdlaWdodGI9MSBvcGVuX2dvcD0wIHdlaWdodHA9MiBrZXlpbnQ9MjUwIGtleWludF9taW49MSBzY2VuZWN1dD00MCBpbnRyYV9yZWZyZXNoPTAgcmNfbG9va2FoZWFkPTQwIHJjPWNyZiBtYnRyZWU9MSBjcmY9MjMuMCBxY29tcD0wLjYwIHFwbWluPTAgcXBtYXg9NjkgcXBzdGVwPTQgaXBfcmF0aW89MS40MCBhcT0xOjEuMDAAgAAAABBliIQAFf/+98nvwKbr29+B",
      controls: ["play-large", "play", "mute", "volume", "settings", "pip", "fullscreen"],
      settings: ["speed"],
      speed: { selected: 1, options: [0.5, 0.75, 1, 1.25, 1.5, 2] },
      keyboard: { focused: true, global: false },
      tooltips: { controls: true, seek: false },
      i18n: {
        play: "播放", pause: "暂停", mute: "静音", unmute: "取消静音", volume: "音量",
        settings: "设置", speed: "播放速度", normal: "正常", pip: "画中画",
        enterFullscreen: "进入全屏", exitFullscreen: "退出全屏", menuBack: "返回上一级",
        seek: "整集进度", seekLabel: "{currentTime} / {duration}",
        currentTime: "整集播放时间", duration: "整集时长", buffered: "已缓冲", played: "已播放",
      },
    }) : null;
    // Move the real episode timeline into Plyr's controls (also inside fullscreen).
    // Do not use Plyr's native seek input: its clock only knows the HLS segment window.
    if (this.ui?.elements?.controls) {
      const controls = this.ui.elements.controls;
      controls.insertBefore(progress, controls.querySelector('.plyr__volume'));
    }
    timeline.addEventListener("keydown", (event) => event.stopPropagation());
    timeline.addEventListener("pointercancel", () => { this.dragging = false; this.paint(); });
    timeline.addEventListener("blur", () => { this.dragging = false; this.paint(); });
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
    if (this.ui) this.ui.config.title = state.current?.title || "RIFE 视频播放器";
    const key = state.current && state.hls_ready
      ? JSON.stringify([state.current.id, state.playback_id, state.start, state.hls_url]) : null;
    if (key !== this.key) {
      this.key = key;
      this.destroy();
      this.failures = 0;
      if (key) this.load(key);
    }
    if (!key) this.hint.textContent = state.streaming ? "等待新一集 / 跳转位置生成分片…" : "选择一集后点击播放";
    this.timeline.disabled = this.seeking || !state.seekable || !(Number(state.duration) > 0);
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
      this.hint.textContent = "此浏览器不支持 HLS，请换用支持 HLS 的浏览器。";
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
    const time = this.formatTime(position);
    const duration = this.state?.duration ? this.formatTime(this.state.duration) : "--:--";
    this.clock.textContent = `${time} / ${duration}`;
    this.timeline.setAttribute("aria-valuetext", `${time} / ${duration}`);
    this.timeline.style.setProperty("--episode-progress", `${Math.min(100, Math.max(0, position / (Number(this.state?.duration) || 1) * 100))}%`);
  }

  paint() {
    if (this.dragging || this.seeking) return;
    const position = this.position();
    this.timeline.value = position;
    this.paintTime(position);
  }

  async jump(seconds) {
    if (!this.state?.seekable || this.seeking || !(Number(this.state.duration) > 0) || !Number.isFinite(seconds)) return;
    seconds = Math.min(Number(this.state.duration), Math.max(0, seconds));
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
    this.seeking = true;
    this.timeline.disabled = true;
    this.progress.setAttribute("aria-busy", "true");
    this.paintTime(seconds);
    try { await this.seek(seconds); }
    finally {
      this.seeking = false;
      this.progress.removeAttribute("aria-busy");
      this.timeline.disabled = !this.state?.seekable || !(Number(this.state?.duration) > 0);
      this.paint();
    }
  }
}
