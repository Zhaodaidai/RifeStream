const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const callbacks=new Map();let id=0;
const context={URL,performance,window:{requestAnimationFrame(fn){callbacks.set(++id,fn);return id;},cancelAnimationFrame(i){callbacks.delete(i);}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/danmaku.js','utf8'),context);
const D=context.window.DanmakuOverlay;
const calls=[];
const d={player:{ui:{elements:{container:{getBoundingClientRect:()=>({width:960,height:540})}}}},settings:{fontSize:24,area:50},token:7,host:{style:{}},activeCanvases:new Map(),releaseSprites(){},metrics:{},engine:{stop(){calls.push('stop')},clear(){calls.push('clear')},setFontSize(...args){calls.push(['font',...args])},setArea(area){this.area=area},resize(){calls.push('resize')},updateComments(entries){this.entries=entries}},comments:Array.from({length:50000},(_,i)=>({time:24,text:'source '+i,mode:i%3===0?5:i%3===1?4:1})),sprite(){throw Error('must remain lazy')}};
for(const area of [25,50,75,100,25]){
 d.settings.area=area;D.prototype.rebuildNow.call(d);
 assert.equal(d.engine.area.start,0);assert.equal(d.engine.area.end,area/100);
 assert.equal(d.engine.entries.length,50000);assert.equal(d.metrics.admitted,50000);assert.equal(d.metrics.skipped,0);
 assert.equal(d.layout[0].start,24000);assert.equal(d.layout[0].source,d.comments[0]);assert.equal(d.layout[0].mode,'top');assert.equal(d.layout[1].mode,'bottom');assert.equal(d.layout[2].mode,'scroll');
 assert.ok(d.layout.every(c=>c.elLazyInit&&c.disableCopyDOM));assert.equal(new Set(d.layout.map(c=>c.id)).size,50000);
 assert.equal(d.host.style.height,undefined,'host must not crop the native area');
}
assert.equal(typeof D.laneOrder,'undefined');
const source=fs.readFileSync('web/danmaku.js','utf8');
for(const removed of ['laneLayout','laneOrder','densityOrder','fullAdmitted','fullCapacity','sampledWidths'])assert.equal(source.includes(removed),false);
assert.ok(source.includes('new window.DanmuJs('));assert.ok(source.includes('overlap: false'));
const html=fs.readFileSync('web/index.html','utf8');assert.ok(html.indexOf('/vendor/danmu.min.js')<html.indexOf('/danmaku.js'));assert.equal(html.includes('/vendor/danmaku.canvas.min.js'),false);
const vendor=fs.readFileSync('web/vendor/danmu.min.js');const upstream=fs.existsSync('var/player-framing/native-reference/package/browser/index.js')?fs.readFileSync('var/player-framing/native-reference/package/browser/index.js'):null;
if(upstream)assert.deepEqual(vendor,upstream);
let rebuilds=0,pauses=0;
const overlay={player:{position:()=>24},video:{paused:true},settings:{enabled:false},doc:{hidden:false},dirtyImages:new Set(),sprites:new Map(),activeCanvases:new Map(),host:{hidden:false},needsLayout:true,rebuildNow(){rebuilds++;this.needsLayout=false},stopClock(){pauses++}};
D.prototype.sync.call(overlay);D.prototype.sync.call(overlay);D.prototype.sync.call(overlay);assert.equal(callbacks.size,1);[...callbacks.values()][0]();callbacks.clear();assert.equal(rebuilds,1);assert.equal(pauses,1);assert.equal(overlay.host.hidden,true);
console.log('Native danmu.js: setArea25/50/75/100, all50k retained without sampling/caps, lazy render, original times, no patched lanes, pinned unmodified vendor, RAF coalescing passed');

// Native bullets use CSS transitions for motion and fixed-mode lifetime.
// Reduced-motion UI rules must not teleport explicitly enabled media offscreen.
const css=fs.readFileSync('web/styles.css','utf8');
const reduced=css.match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/);
assert.ok(reduced,'reduced-motion accessibility rule remains');
assert.ok(reduced[1].includes('*:not(.danmaku-sprite)'),'native bullet transitions remain engine-owned');
assert.equal(/(?:^|[{},])\s*\*\s*[,\{]/.test(reduced[1]),false,'no universal transition:none on bullets');
console.log('Reduced-motion UI keeps native danmaku CSS transitions enabled');
