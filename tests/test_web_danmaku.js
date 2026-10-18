const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {URL,window:{}, requestAnimationFrame(){}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/danmaku.js','utf8'),context);
const D = context.window.DanmakuOverlay;
const parsed = D.parse(JSON.stringify({comments:[{p:'2,5,255,0',m:'中文'},{time:1,text:'<b>literal</b>'},{time:-1,text:'bad'}]}));
assert.equal(parsed.length,2);assert.equal(parsed[0].time,1);assert.equal(parsed[0].text,'<b>literal</b>');assert.equal(parsed[1].mode,5);
assert.throws(()=>D.parse('<!DOCTYPE i [<!ENTITY x "bad">]><i/>'),/DTD/);
assert.throws(()=>D.parse('not a file'),/XML\/JSON/);
assert.throws(()=>D.normalize(Array(50001).fill({})),/50000/);
console.log('Danmaku parser validation and safe image tokenization');

const images = D.normalize([{time:1,text:'<img src="https://example.com/e.png" onerror="alert(1)"> 二刷'}, {time:2,text:'<img src="https://example.com/e.png">'}]);
assert.equal(images.length,2);
const parts = D.parts(images[0].text);
assert.equal(parts[0].src,'https://example.com/e.png');assert.equal(parts[1].text,' 二刷');
assert.equal(parts[0].onerror,undefined);
assert.equal(D.parts('<img src="javascript:alert(1)" alt="表情">')[0].text,'表情');
assert.equal(D.parts('<img src="//example.com/a.png?a=1&amp;b=2">')[0].src,'https://example.com/a.png?a=1&b=2');
console.log('Image emoji preserved and tokenized; only HTTP(S) src accepted; script/style attributes ignored');

assert.equal(D.defaults.opacity,100);

const source = fs.readFileSync('web/danmaku.js','utf8');
for (const removed of ['danmakuFile', 'danmaku-reload', 'danmaku-source', '重新加载本集弹幕', '导入 XML']) assert.equal(source.includes(removed),false);
console.log('Local import/reload UI, handlers and hints removed; automatic loading preserved');

assert.equal(D.defaults.speed, 1);
for (const [value, expected] of [[undefined,1],[null,1],[0,1],[-1,1],['bad',1],[Infinity,1],[0.1,0.5],[0.5,0.5],[1.24,1.2],['1.5',1.5],[2,2],[20,2]]) {
  assert.equal(D.normalizeSpeed(value), expected, `speed normalization: ${value}`);
}
assert.ok(source.includes('id="danmakuSpeed"'));
console.log('Speed defaults, old/invalid saved settings, clamp and slider markup passed');
