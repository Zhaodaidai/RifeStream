const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window:{}, requestAnimationFrame(){}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/danmaku.js','utf8'),context);
const D = context.window.DanmakuOverlay;
const parsed = D.parse(JSON.stringify({comments:[{p:'2,5,255,0',m:'中文'},{time:1,text:'<b>literal</b>'},{time:-1,text:'bad'}]}));
assert.equal(parsed.length,2);assert.equal(parsed[0].time,1);assert.equal(parsed[0].text,'<b>literal</b>');assert.equal(parsed[1].mode,5);
assert.throws(()=>D.parse('<!DOCTYPE i [<!ENTITY x "bad">]><i/>'),/DTD/);
assert.throws(()=>D.parse('not a file'),/XML\/JSON/);
assert.throws(()=>D.normalize(Array(50001).fill({})),/50000/);
const calls=[];
const overlay={player:{position:()=>12},ctx:{strokeText(){},fillText:(...a)=>calls.push(a)},width:600,maxAge:10,
 layout:[{time:10,end:18,text:'scroll',speed:100,lane:0,line:30,color:16777215}, {time:11,end:15,text:'fixed',fixed:true,width:100,lane:1,line:30,color:255}]};
D.prototype.render.call(overlay);
assert.equal(calls.length,2);assert.equal(calls[0][1],400);assert.equal(calls[1][1],250);
calls.length=0;overlay.player.position=()=>50;D.prototype.render.call(overlay);assert.equal(calls.length,0);
calls.length=0;overlay.player.position=()=>10.5;D.prototype.render.call(overlay);assert.equal(calls.length,1);assert.equal(calls[0][1],550);
console.log('Danmaku JSON normalization, bounds, literal text, episode-time rendering, seek forward/backward passed');

const images = D.normalize([{time:1,text:'<img src="x>y" style="height:1rem"> 二刷'}, {time:2,text:'<IMG SRC=x onerror="alert(1)">'}, {time:3,text:'正常 1 < 2'}]);
assert.equal(images.length,2);assert.equal(images[0].text,'二刷');assert.equal(images[1].text,'正常 1 < 2');
console.log('Image markup filtered; text retained; image-only comments skipped');
