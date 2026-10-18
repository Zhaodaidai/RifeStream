const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const callbacks = new Map(); let id = 0;
const context = {URL,performance,Event,EventTarget,window:{requestAnimationFrame(fn){callbacks.set(++id,fn);return id;},cancelAnimationFrame(i){callbacks.delete(i);}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/danmaku.js','utf8'),context);
const D=context.window.DanmakuOverlay;
let hide=0,stop=0,layout=0;
const overlay={sprites:new Map(),dirtyImages:new Set(),player:{position:()=>600},video:{paused:true},settings:{enabled:false},doc:{hidden:false},needsLayout:true,
 rebuildNow(){layout++;this.needsLayout=false;},stopClock(){stop++;},engine:{hide(){hide++;}}};
D.prototype.sync.call(overlay);D.prototype.sync.call(overlay);D.prototype.sync.call(overlay);
assert.equal(callbacks.size,1);[...callbacks.values()][0]();callbacks.clear();
assert.equal(layout,1);assert.equal(hide,1);assert.equal(stop,1);
// No measureText or sprite creation in the full-episode admission pass.
const d={player:{ui:{elements:{container:{getBoundingClientRect(){return {width:960,height:540};}}}}},
 settings:{fontSize:24,area:100},host:{style:{}},releaseSprites(){},engine:{clear(){},resize(){},speed:160},metrics:{},comments:Array.from({length:50000},()=>({time:10,text:'burst',mode:1,color:1})),sprite(){throw Error('eager sprite creation');}};
D.prototype.rebuildNow.call(d);
assert.ok(d.engine.comments.length<=96);assert.equal(d.comments.length,50000);
assert.equal(d.metrics.skipped+d.metrics.admitted,50000);assert.ok(d.needsSeek);
assert.equal(d.engine.comments[0].mode,'rtl');
// CSS-area and HiDPI custom-render dimensions are explicit, vendor change stays isolated.
const vendor=fs.readFileSync('web/vendor/danmaku.canvas.min.js','utf8');assert.ok(vendor.includes('dataset.danmakuWidth'));
const html=fs.readFileSync('web/index.html','utf8');assert.ok(html.indexOf('/vendor/danmaku.canvas.min.js')<html.indexOf('/danmaku.js'));
console.log('Mature-engine adapter: RAF coalescing, bounded 50k burst admission, lazy sprites, episode clock, pinned vendor ordering passed');
