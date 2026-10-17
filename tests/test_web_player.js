const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const events = {};
const video = {
  currentTime: 0, seekable: {length: 0}, pauses: 0,
  addEventListener: (n, fn) => { events[n] = fn; },
  pause() { this.pauses++; }, load() { this.currentTime = 0; },
  removeAttribute() {}, play() { return Promise.reject(new Error('blocked')); },
};
const rangeEvents = {};
const timeline = {
  addEventListener: (n, fn) => { rangeEvents[n] = fn; },
  setAttribute(n, value) { this[n] = value; },
  style: { setProperty() {} },
};
const progress = { setAttribute() {}, removeAttribute() {} };
const clock = {}, hint = {}, instances = [], seeks = [];
class Hls {
  static Events = { ERROR: 'error', MANIFEST_PARSED: 'manifest' };
  static isSupported() { return true; }
  constructor(config) { this.config = config; this.events = {}; instances.push(this); }
  on(n, f) { this.events[n] = f; }
  loadSource(url) { this.url = url; }
  attachMedia() {} destroy() { this.destroyed = true; }
}
const uiInstances = [];
class Plyr {
  constructor(media, config) { this.media = media; this.config = config; this.elements = {controls: {querySelector: () => "mute", insertBefore: (node, anchor) => { this.progress = node; this.anchor = anchor; }}}; uiInstances.push(this); }
}
const context = { window: { Plyr, Hls, location: {href: 'http://localhost:10000', hostname: 'localhost'} }, URL, setTimeout, clearTimeout };
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/player.js', 'utf8') + '\nthis.Player = EmbeddedPlayer;', context);
const player = new context.Player({video, progress, timeline, clock, hint, formatTime: String, seek: s => seeks.push(s)});
const state = {current: {id: 'ep1'}, hls_ready: true, playback_id: 10, start: 0, duration: 1200, seekable: true, hls_url: 'http://192.168.1.8:8888/rife/index.m3u8'};
(async () => {
  assert.equal(uiInstances.length, 1);
  assert.equal(uiInstances[0].media, video);
  assert.equal(player.ui.progress, progress, "episode timeline moved into Plyr controls");
  assert.equal(player.ui.config.iconUrl, "/vendor/plyr.svg");
  assert.equal(player.ui.config.keyboard.global, false);
  assert.equal(player.ui.config.controls.includes("progress"), false, "native segment timeline must not compete with episode timeline");
  assert.equal(player.ui.config.settings.join(","), "speed");
  assert.match(player.ui.config.blankVideo, /^data:video\/mp4;base64,/);
  player.update(state);
  assert.equal(instances.length, 1);
  assert.match(instances[0].url, /^http:\/\/localhost:8888/);
  assert.equal(instances[0].config.startPosition, 0);
  player.update({...state, position: 400});
  assert.equal(instances.length, 1, 'polling must not reload');
  video.currentTime = 12; events.timeupdate();
  assert.equal(clock.textContent, '12 / 1200', 'watch clock, not transcode wall clock');
  player.update({...state, current: {id: 'ep2'}, playback_id: 20});
  assert.equal(instances.length, 2); assert.equal(instances[0].destroyed, true);
  player.update({...state, start: 300, playback_id: 30});
  assert.equal(instances.length, 3, 'server seek reloads fixed URL');
  video.currentTime = 8; events.timeupdate();
  assert.equal(clock.textContent, '308 / 1200');
  video.seekable = {length: 1, start: () => 0, end: () => 30};
  await player.jump(315); assert.equal(video.currentTime, 15); assert.equal(seeks.length, 0);
  await player.jump(900); assert.deepEqual(seeks, [900]);
  await player.autoplay(); await Promise.resolve();
  assert.match(hint.textContent, /播放按钮/);
  instances[2].events.error(null, {fatal: true}); assert.ok(player.retry);
  player.update({...state, hls_ready: false, streaming: true});
  assert.equal(player.retry, null); assert.equal(instances[2].destroyed, true);
  assert.match(hint.textContent, /等待/);
  player.update({...state, streaming: false});
  assert.equal(instances.length, 4, 'finished transcoding can still be watched');
  player.update({...state, current: null, hls_ready: false, streaming: false});
  assert.equal(player.key, null); assert.equal(instances[3].destroyed, true);
  assert.equal(uiInstances.length, 1, 'switch/seek/stop reuse the same Plyr UI');
  player.update({...state, start: 300, playback_id: 100});
  video.currentTime = 8;
  timeline.value = 700; rangeEvents.input();
  assert.equal(clock.textContent, '700 / 1200', 'drag previews full episode position');
  player.paint(); assert.equal(clock.textContent, '700 / 1200', 'timeupdate does not overwrite drag');
  rangeEvents.pointercancel(); assert.equal(clock.textContent, '308 / 1200');
  let stopped = false; rangeEvents.keydown({stopPropagation() {stopped=true;}}); assert.ok(stopped);
  const oldSeek = player.seek;
  let resolveSeek;
  player.seek = () => new Promise(resolve => {resolveSeek=resolve;});
  const pending = player.jump(900);
  assert.equal(timeline.disabled, true);
  assert.equal(clock.textContent, '900 / 1200');
  player.update({...state, start: 300, playback_id: 100});
  assert.equal(clock.textContent, '900 / 1200', 'polling must not overwrite pending seek preview');
  resolveSeek(); await pending; assert.equal(timeline.disabled, false);
  player.seek = async () => {throw new Error('seek failure');};
  await assert.rejects(player.jump(900), /seek failure/); assert.equal(timeline.disabled, false);
  player.seek = oldSeek;
  player.update({...state, seekable:false, duration:0}); assert.equal(timeline.disabled,true);
  console.log('PASS: embedded episode timeline/drag/keyboard isolation/pending seek/failure/disabled state');
  console.log('PASS: Plyr initialization/local icons/theme-independent controls/UI reuse;') ;
  console.log('PASS: start, polling, episode, seek, clock, local/server seek, autoplay, retry cancellation, finished stream, stop');
})().catch(e => {console.error(e); process.exitCode = 1;});
