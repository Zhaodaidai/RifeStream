/* HLS session lifecycle is separate from playlist rendering and its polling clock. */
class EmbeddedPlayer {
  constructor({ video, progress, timeline, clock, hint, formatTime, seek, onEnded }) {
    Object.assign(this, { video, progress, timeline, clock, hint, formatTime, seek, onEnded });
    this.key = null;
    this.state = null;
    this.hls = null;
    this.retry = null;
    this.failures = 0;
    this.dragging = false;
    this.seeking = false;
    this.session = null;
    this.epoch = 0;
    this.resumeAt = 0;
    this.wantsPlayback = true;
    this.reloading = false;
    this.autoplayEpoch = -1;
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
    // Only desktop needs fitting: the mobile layout already follows the video's ratio.
    this.frame = video.closest?.(".video-stage");
    if (this.frame) {
      const queueFit = () => {
        if (this.frameTask) return;
        this.frameTask = window.requestAnimationFrame(() => {
          this.frameTask = null;
          this.fitFrame();
        });
      };
      this.frameObserver = new window.ResizeObserver(queueFit);
      this.frameObserver.observe(this.frame.parentElement);
      this.frameObserver.observe(this.frame.parentElement.querySelector(".playback-controls"));
      window.addEventListener("resize", queueFit);
      video.addEventListener("loadedmetadata", queueFit);
      video.addEventListener("resize", queueFit);
      queueFit();
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
      this.jump(Number(timeline.value)).catch((error) => { hint.textContent = `跳转失败：${error.message}`; });
    });
    video.addEventListener("timeupdate", () => this.paint());
    video.addEventListener("play", () => { if (this.key) this.wantsPlayback = true; });
    video.addEventListener("pause", () => {
      if (this.key && !this.reloading && !video.ended) this.wantsPlayback = false;
    });
    video.addEventListener("playing", () => {
      if (!this.key) return;
      hint.textContent = "网页播放中";
      this.failures = 0;
    });
    video.addEventListener("waiting", () => {
      if (this.key && this.wantsPlayback) hint.textContent = "等待转码 / 缓冲中…";
    });
    video.addEventListener("error", () => {
      if (!this.hls && this.key) this.retryLoad(this.key);
    });
    video.addEventListener("loadedmetadata", () => {
      if (!this.key) return;
      if (!this.hls && this.resumeAt > 0) video.currentTime = this.resumeAt;
      this.reloading = false;
      this.autoplay();
    });
    video.addEventListener("ended", () => {
      if (this.key && !this.reloading && !this.seeking) this.onEnded?.(this.state);
    });
  }

  fitFrame() {
    const frame = this.frame;
    if (!frame) return;
    if (!window.matchMedia("(min-width: 861px)").matches) {
      frame.style.removeProperty("--frame-width");
      frame.style.removeProperty("--frame-height");
      return;
    }
    const viewer = frame.parentElement;
    const main = viewer.closest("main");
    const styles = (element) => window.getComputedStyle(element);
    const sum = (style, names) => names.reduce((total, name) => total + (parseFloat(style[name]) || 0), 0);
    const horizontal = ["paddingLeft", "paddingRight"];
    const vertical = ["paddingTop", "paddingBottom", "borderTopWidth", "borderBottomWidth"];
    const frameStyle = styles(frame);
    const borderX = sum(frameStyle, ["borderLeftWidth", "borderRightWidth"]);
    const borderY = sum(frameStyle, ["borderTopWidth", "borderBottomWidth"]);
    const ratio = this.video.videoWidth > 0 && this.video.videoHeight > 0
      ? this.video.videoWidth / this.video.videoHeight : 16 / 9;
    const chrome = sum(styles(main), vertical) + sum(styles(viewer), vertical)
      + main.ownerDocument.querySelector(".top").getBoundingClientRect().height
      + viewer.querySelector(".viewer-head").getBoundingClientRect().height
      + viewer.querySelector(".playback-controls").getBoundingClientRect().height;
    const availableWidth = viewer.clientWidth - sum(styles(viewer), horizontal) - borderX;
    const availableHeight = Math.max(120, window.innerHeight - chrome - borderY);
    const width = Math.max(1, Math.min(availableWidth, availableHeight * ratio));
    // Size the content box to the source ratio; include the stage border in its outer dimensions.
    frame.style.setProperty("--frame-width", `${width + borderX}px`);
    frame.style.setProperty("--frame-height", `${width / ratio + borderY}px`);
  }

  destroy() {
    this.epoch++;
    this.reloading = true;
    clearTimeout(this.retry);
    this.retry = null;
    if (this.hls) this.hls.destroy();
    this.hls = null;
    this.video.pause();
    this.video.removeAttribute("src");
    this.video.load();
  }

  suspend(autoplay = this.wantsPlayback) {
    this.resumeAt = Number(this.video.currentTime) || 0;
    this.wantsPlayback = autoplay;
    this.key = null;  // Invalidate old HLS callbacks before destroying their media.
    this.destroy();
  }

  update(state) {
    const session = state.current ? JSON.stringify([state.current.id, state.playback_id, state.start]) : null;
    if (session !== this.session) {
      if (state.current?.id !== this.state?.current?.id) this.wantsPlayback = true;
      this.resumeAt = 0;
      this.dragging = false;
      this.session = session;
    }
    this.state = state;
    if (this.ui) this.ui.config.title = state.current?.title || "RIFE 视频播放器";
    const key = state.current && state.hls_ready
      ? JSON.stringify([state.current.id, state.playback_id, state.start, state.hls_url]) : null;
    if (key !== this.key) {
      this.key = key;
      this.destroy();
      this.failures = 0;
      if (key) this.load(key, this.resumeAt);
    }
    if (!key) this.hint.textContent = state.streaming ? "等待新一集 / 跳转位置生成分片…" : "选择一集后点击播放";
    this.timeline.disabled = this.seeking || !state.seekable || !(Number(state.duration) > 0);
    this.timeline.max = Number(state.duration) || 0;
    this.paint();
  }

  load(key, position = 0) {
    if (this.key !== key) return;
    const epoch = this.epoch;
    this.resumeAt = position;
    const url = new URL(this.state.hls_url, window.location.href);
    // Use the browser's host, not a server-selected LAN adapter (localhost/VPN).
    url.hostname = window.location.hostname;
    url.searchParams.set("session", this.state.playback_id || 0);
    this.hint.textContent = "正在加载转码视频…";
    if (window.Hls && window.Hls.isSupported()) {
      const hls = this.hls = new window.Hls({
        startPosition: position,
        liveSyncDurationCount: 1000000,
        liveMaxLatencyDurationCount: Infinity,
        maxBufferLength: 30,
        backBufferLength: 60,
      });
      hls.on(window.Hls.Events.ERROR, (_event, data) => {
        if (data.fatal && this.key === key && this.hls === hls) this.retryLoad(key);
      });
      hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
        if (this.key === key && this.hls === hls && this.epoch === epoch) this.autoplay();
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
      const position = Number(this.video.currentTime) || this.resumeAt;
      this.destroy();
      this.load(key, position);
    }, Math.min(8000, 1000 * 2 ** (this.failures - 1)));
  }

  autoplay() {
    if (!this.key || !this.wantsPlayback || this.autoplayEpoch === this.epoch) return;
    const epoch = this.epoch;
    this.autoplayEpoch = epoch;
    const result = this.video.play();
    if (result && result.catch) result.catch(() => {
      if (this.epoch !== epoch || !this.key || !this.wantsPlayback) return;
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
    this.suspend();
    const seekEpoch = this.epoch;
    this.hint.textContent = "正在跳转，等待重新生成分片…";
    this.seeking = true;
    this.timeline.disabled = true;
    this.progress.setAttribute("aria-busy", "true");
    this.paintTime(seconds);
    try { await this.seek(seconds); }
    catch (error) {
      // A rejected seek leaves the server session unchanged; resume its previous buffered position.
      if (this.state && this.epoch === seekEpoch) this.update(this.state);
      throw error;
    } finally {
      this.seeking = false;
      this.progress.removeAttribute("aria-busy");
      this.timeline.disabled = !this.state?.seekable || !(Number(this.state?.duration) > 0);
      this.paint();
    }
  }
}
