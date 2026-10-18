const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const callbacks = new Map();
let nextId = 0;
const context = {
  URL, performance, Event, EventTarget, AbortController,
  window: {
    devicePixelRatio: 1,
    requestAnimationFrame(fn) { callbacks.set(++nextId, fn); return nextId; },
    cancelAnimationFrame(id) { callbacks.delete(id); },
    clearTimeout,
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/danmaku.js', 'utf8'), context);
const D = context.window.DanmakuOverlay;

function frame() {
  for (const id of [...callbacks.keys()]) {
    const fn = callbacks.get(id);
    if (fn) { callbacks.delete(id); fn(); }
  }
}
function settle() {
  for (let i = 0; callbacks.size && i < 10; i++) frame();
  assert.equal(callbacks.size, 0, 'no perpetual adapter RAF loop');
}
function fixture() {
  const d = Object.create(D.prototype);
  const rect = { width: 960, height: 540 };
  const video = Object.assign(new EventTarget(), { paused: true, ended: false, playbackRate: 1 });
  const doc = Object.assign(new EventTarget(), { hidden: false });
  const calls = { updates: 0, stops: 0, starts: 0, pauses: 0, plays: 0, fonts: 0, areas: 0, rates: 0 };
  const engine = {
    status: 'idle', entries: [],
    updateComments(entries) { calls.updates++; this.entries = entries.slice(); },
    stop() { calls.stops++; this.status = 'closed'; this.entries.forEach(e => e.attached_ = false); },
    start() { calls.starts++; this.status = 'playing'; },
    play() { calls.plays++; this.status = 'playing'; },
    pause() { calls.pauses++; this.status = 'paused'; },
    setFontSize() { calls.fonts++; },
    setArea(area) { calls.areas++; this.area = area; },
    setPlayRate(mode, rate) { calls.rates++; this.rate = rate; },
    clear() { throw Error('adapter must not delete native pool on seek/resize/rate change'); },
  };
  Object.assign(d, {
    player: { position: () => d.position, ui: { elements: { container: { getBoundingClientRect: () => rect } } } },
    video, doc, rect, calls, engine, position: 24, token: 7,
    settings: { enabled: true, fontSize: 24, area: 50 }, loaded: true,
    comments: [], layout: [], images: new Map(), sprites: new Map(), spriteBytes: 0,
    activeCanvases: new Map(), dirtyImages: new Set(), clock: { paused: true },
    host: { hidden: false, style: {} }, status: { textContent: '' },
    metrics: { layouts: 0, admitted: 0, skipped: 0 },
  });
  return d;
}

// Native source pool is stable: zero timestamp remains anchored at 1ms, not
// treated as an untimed/live native bullet; other timestamps are unchanged.
const d = fixture();
const comments = Array.from({ length: 50000 }, (_, i) => ({
  time: i / 10, text: 'source ' + i, mode: [5, 4, 1][i % 3],
}));
d.replaceComments(comments);
d.rebuild(); settle();
const layout = d.layout;
assert.equal(d.calls.updates, 1);
assert.equal(layout.length, 50000);
assert.equal(layout[0].start, 1);
assert.equal(layout[240].start, 24000);
assert.equal(layout[240].source, comments[240]);
assert.deepEqual(Array.from(layout.slice(0, 3), e => e.mode), ['top', 'bottom', 'scroll']);
assert.ok(layout.every(e => e.elLazyInit && e.disableCopyDOM));
assert.equal(new Set(layout.map(e => e.id)).size, 50000);
assert.equal(d.metrics.admitted, 50000);
assert.equal(d.metrics.skipped, 0);
assert.equal(d.host.style.height, undefined, 'host never crops native area');

// Unchanged observer notifications do not clear live nodes or cached rasters.
const live = {};
const raster = { canvas: { width: 8, height: 8 }, runs: [] };
d.activeCanvases.set(live, raster);
d.sprites.set('cached', raster);
const stops = d.calls.stops;
for (let i = 0; i < 3; i++) { d.rebuild(); settle(); }
assert.equal(d.calls.stops, stops);
assert.equal(d.activeCanvases.get(live), raster);
assert.equal(d.sprites.get('cached'), raster);

// Area/height affect native geometry, not source identity or text rasters.
for (const area of [25, 50, 75, 100, 25]) {
  d.settings.area = area;
  d.rebuild(); settle();
  assert.equal(d.engine.area.start, 0);
  assert.equal(d.engine.area.end, area / 100);
  assert.equal(d.layout, layout);
  assert.equal(d.sprites.get('cached'), raster);
}
d.rect.height = 600; d.rebuild(); settle();
assert.equal(d.sprites.get('cached'), raster);
assert.equal(d.calls.updates, 1);
assert.equal(d.calls.fonts, 1, 'area/height must not rewrite font styles on 50000 records');

// Font / width / DPR changes do invalidate width-dependent backing rasters.
d.settings.fontSize = 36; d.rebuild(); settle();
assert.equal(d.sprites.size, 0);
assert.equal(raster.canvas.width, 0);
assert.equal(d.calls.fonts, 2);
for (const change of [() => d.rect.width = 720, () => context.window.devicePixelRatio = 2]) {
  d.sprites.set('cached', { canvas: { width: 8, height: 8 }, runs: [] });
  change(); d.rebuild(); settle();
  assert.equal(d.sprites.size, 0);
  assert.equal(d.layout, layout);
}
context.window.devicePixelRatio = 1;

// Seek relies on native stop/start attached-flag reset, never cloned entries.
for (const position of [300, 24, 600, 24]) {
  d.engine.entries[0].attached_ = true;
  d.position = position; d.sync(); settle();
  assert.equal(d.engine.entries[0].attached_, false);
  assert.equal(d.engine.entries[0], layout[0]);
}
assert.equal(d.calls.updates, 1);
assert.equal(comments[240].time, 24, 'source times never drift');
assert.equal(comments[0].attached_, undefined, 'native flags stay out of normalized source');

// Native speed updates are not seeks and do not discard live bullets.
d.bindMediaEvents();
d.activeCanvases.set(live, raster);
const rateStops = d.calls.stops;
for (const rate of [1.5, 2, 1]) {
  d.video.playbackRate = rate; d.video.dispatchEvent(new Event('ratechange')); settle();
  assert.equal(d.engine.rate, rate);
  assert.equal(d.engine.status, 'paused');
  assert.equal(d.activeCanvases.get(live), raster);
}
assert.equal(d.calls.stops, rateStops);
assert.equal(d.calls.updates, 1);

// Image completion redraws pixels, not the paused media/animation clock.
let paints = 0, copies = 0;
const imageRaster = { runs: [{ src: 'https://example.com/image.png' }], canvas: {} };
const imageNode = { isConnected: true, width: 4, height: 4,
  getContext: () => ({ clearRect() {}, drawImage() { copies++; } }) };
d.activeCanvases.clear(); d.activeCanvases.set(imageNode, imageRaster);
d.sprites.clear(); d.sprites.set('image', imageRaster);
d.paintSprite = () => { paints++; };
const starts = d.calls.starts + d.calls.plays;
d.dirtyImages.add('https://example.com/image.png'); d.sync(); settle();
assert.equal(paints, 1); assert.equal(copies, 1);
assert.equal(d.calls.starts + d.calls.plays, starts);
assert.equal(d.engine.status, 'paused');

// A queued paused-preview callback must not pause newly resumed video.
const race = fixture();
race.replaceComments([{ time: 24, text: 'preview', mode: 1 }]);
race.rebuild(); frame();
assert.ok(race.previewTask);
race.video.paused = false;
race.video.dispatchEvent(new Event('playing'));
// Test the stale callback directly too: guard must inspect current state.
callbacks.get(race.previewTask)();
assert.equal(race.engine.status, 'playing');
race.sync(); settle();
assert.equal(race.clock.paused, false);
assert.equal(race.previewTask, null);

// The queued frame always consumes latest state, and hidden polling is inert.
race.settings.enabled = false; race.sync();
race.settings.enabled = true; frame();
assert.equal(race.host.hidden, false);
race.settings.enabled = false; race.sync(); settle();
assert.equal(race.host.hidden, true);
assert.equal(race.clock.paused, true);
const hiddenPauses = race.calls.pauses;
for (let i = 0; i < 100; i++) race.sync();
assert.equal(callbacks.size, 0);
assert.equal(race.calls.pauses, hiddenPauses);
race.settings.enabled = true; race.sync(); settle();
assert.equal(race.engine.status, 'playing');
assert.equal(race.calls.updates, 1);

// New episode replaces the pool once; old data/nodes do not leak across it.
d.activeCanvases.clear(); d.sprites.clear();
d.settings.enabled = false;
d.setItem({ id: 'next' }); settle();
assert.equal(d.comments.length, 0);
assert.equal(d.layout.length, 0);
assert.equal(d.engine.entries.length, 0);
assert.equal(d.loaded, false);
assert.equal(d.images.size, 0);
assert.equal(d.host.hidden, true);
const updatesAfterSwitch = d.calls.updates;
d.setItem({ id: 'next' }); settle();
assert.equal(d.calls.updates, updatesAfterSwitch, 'same episode is idempotent');

// Keep native collision/area engine unmodified and the reduced-motion fix.
const source = fs.readFileSync('web/danmaku.js', 'utf8');
for (const removed of ['laneLayout', 'laneOrder', 'densityOrder', 'fullAdmitted', 'fullCapacity', 'sampledWidths', 'seekPosition', 'engineVisible']) {
  assert.equal(source.includes(removed), false, removed);
}
assert.ok(source.includes('new window.DanmuJs('));
assert.ok(source.includes('overlap: false'));
const html = fs.readFileSync('web/index.html', 'utf8');
assert.ok(html.indexOf('/vendor/danmu.min.js') < html.indexOf('/danmaku.js'));
assert.equal(html.includes('/vendor/danmaku.canvas.min.js'), false);
const upstream = 'var/player-framing/native-reference/package/browser/index.js';
if (fs.existsSync(upstream)) assert.deepEqual(fs.readFileSync('web/vendor/danmu.min.js'), fs.readFileSync(upstream));
const css = fs.readFileSync('web/styles.css', 'utf8');
const reduced = css.match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/);
assert.ok(reduced);
assert.ok(reduced[1].includes('*:not(.danmaku-sprite)'));
assert.equal(/(?:^|[{},])\s*\*\s*[,\{]/.test(reduced[1]), false);
console.log('PASS: 50000 native records submitted once; stable source/timestamps; native area/collision/vendor preserved');
console.log('PASS: no-op resize; selective raster invalidation; source-preserving seek/rate; paused image repaint');
console.log('PASS: preview/play race; latest queued state; idle hidden polling; episode isolation; reduced-motion visibility');

async function loadingTests() {
  const requests = [], timers = new Map();
  let timerId = 0;
  context.window.setTimeout = fn => { timers.set(++timerId, fn); return timerId; };
  context.window.clearTimeout = id => timers.delete(id);
  context.fetch = (url, { signal }) => new Promise((resolve, reject) => requests.push({ url, signal, resolve, reject }));
  const tick = () => new Promise(resolve => setImmediate(resolve));
  const loaded = fixture();
  loaded.loaded = false;
  loaded.setItem({ id: 'old', olink: 'https://example.com/old' });
  loaded.setItem({ id: 'new', olink: 'https://example.com/new' });
  assert.equal(requests.length, 2);
  assert.equal(requests[0].signal.aborted, true);
  const newSource = [{ time: 24, text: 'new episode' }];
  requests[1].resolve({ ok: true, json: async () => ({ comments: newSource }) });
  await tick(); settle();
  assert.equal(loaded.comments[0].text, 'new episode');
  assert.equal(loaded.loading, false);
  assert.equal(loaded.controller, null);
  requests[0].resolve({ ok: true, json: async () => ({ comments: [{ time: 24, text: 'stale episode' }] }) });
  await tick(); settle();
  assert.equal(loaded.comments[0].text, 'new episode');
  assert.equal(loaded.engine.entries.length, 1);
  assert.equal(loaded.engine.entries[0].source, loaded.comments[0]);
  assert.equal(timers.size, 0);
  loaded.setItem({ id: 'new', olink: 'https://example.com/new' });
  assert.equal(requests.length, 2, 'state polling never refetches same item');

  // A failed load leaves a stopped empty pool, and a retry can recover.
  const bad = loaded.load();
  requests[2].resolve({ ok: false, json: async () => ({ error: 'fixture failure' }) });
  await bad; settle();
  assert.equal(loaded.loaded, false);
  assert.equal(loaded.engine.entries.length, 0);
  assert.match(loaded.status.textContent, /fixture failure/);
  assert.equal(loaded.loading, false);
  const retry = loaded.load();
  requests[3].resolve({ ok: true, json: async () => ({ comments: newSource }) });
  await retry; settle();
  assert.equal(loaded.loaded, true);
  assert.equal(loaded.comments[0].text, 'new episode');

  // Abort/timeout and switch-during-JSON-decoding share the same token gate.
  const timed = loaded.load();
  [...timers.values()][0]();
  assert.equal(requests[4].signal.aborted, true);
  requests[4].reject(Object.assign(new Error('timeout'), { name: 'AbortError' }));
  await timed; settle();
  assert.match(loaded.status.textContent, /超时/);
  assert.equal(loaded.controller, null);
  const pending = loaded.load();
  let finishJSON;
  requests[5].resolve({ ok: true, json: () => new Promise(resolve => { finishJSON = resolve; }) });
  await tick();
  loaded.settings.enabled = false;
  loaded.setItem({ id: 'no-olink' });
  finishJSON({ comments: newSource });
  await pending; settle();
  assert.equal(loaded.comments.length, 0);
  assert.equal(loaded.loaded, false);
  assert.equal(loaded.loading, false);
  assert.equal(loaded.controller, null);
  assert.equal(timers.size, 0, 'all completed/superseded request timers released');
  // Missing olink must auto-load and select the next episode without manual URLs.
  loaded.settings.enabled = true;
  loaded.setItem({ id: 'local-2', title: '凡人修仙传第2集', source: 'local-2.mp4' });
  assert.equal(requests.length, 7);
  assert.match(loaded.status.textContent, /自动匹配/);
  assert.equal(requests[6].url, '/api/danmaku?id=local-2');
  requests[6].resolve({ ok: true, json: async () => ({ comments: newSource, source: 'Bilibili 自动匹配 · 凡人修仙传 第2集' }) });
  await tick(); settle();
  assert.equal(loaded.loaded, true);
  assert.match(loaded.status.textContent, /第2集.*1 条弹幕/);
  loaded.setItem({ id: 'local-2', title: '凡人修仙传第2集', source: 'local-2.mp4' });
  assert.equal(requests.length, 7, 'polling does not repeat auto search');
  loaded.setItem({ id: 'local-3', title: '凡人修仙传第3集', source: 'local-3.mp4' });
  loaded.setItem({ id: 'local-4', title: '凡人修仙传第4集', source: 'local-4.mp4' });
  assert.equal(requests[7].signal.aborted, true);
  requests[7].resolve({ ok: true, json: async () => ({ comments: [{ time: 1, text: 'wrong episode 3' }] }) });
  requests[8].resolve({ ok: true, json: async () => ({ comments: [], source: 'Bilibili 自动匹配', message: '没有明确匹配' }) });
  await tick(); settle();
  assert.equal(loaded.comments.length, 0);
  assert.equal(loaded.status.textContent, '没有明确匹配');
  assert.equal(loaded.loaded, true, 'no-match must not create a polling retry loop');
  loaded.setItem(null);
  assert.equal(requests.length, 9, 'empty playlist never triggers search');
  assert.equal(timers.size, 0);
  console.log('PASS: no-olink auto search, source label, exact episode switch, stale response isolation and no-match state');
  console.log('PASS: async source replacement, late response/JSON isolation, no duplicate fetch, error/retry/timeout cleanup');
}
loadingTests().catch(error => { console.error(error); process.exitCode = 1; });
