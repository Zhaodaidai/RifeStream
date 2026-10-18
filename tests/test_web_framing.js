const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.events={}; this.attributes={}; this.style={}; this.classList={add(){}}; this.value=''; }
  setAttribute(k,v) { this.attributes[k]=v; }
  addEventListener(k,fn) { this.events[k]=fn; }
  focus() { this.focused=true; }
  contains(el) { return el===this; }
  querySelector(s) { return this.fields?.[s]; }
}
const fit=new Element(),zoom=new Element(),output=new Element(),reset=new Element();
fit.value='contain';zoom.value='100';
const doc=new Element();
doc.createElement=()=>{const el=new Element();el.fields={'#videoFit':fit,'#videoZoom':zoom,'output':output,'.framing-reset':reset};return el;};
const frame={classList:{remove(){},toggle(){}},children:[],appendChild(el){this.children.push(el);}};
const controls={querySelector(){return {closest(){return {parentElement:null};}};},insertBefore(el,anchor){assert.equal(anchor,null);this.button=el;}};
const ui={elements:{controls},on(name,fn){this[name]=fn;}};
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync('web/player.js','utf8')+'\nthis.Player=EmbeddedPlayer;',context);
const owner={frame,video:{ownerDocument:doc,style:{}},ui};
context.Player.prototype.initFraming.call(owner);
const panel=frame.children[0],button=controls.button;
assert.equal(owner.video.style.transform,'scale(1)');
button.events.click();assert.equal(panel.hidden,false);assert.equal(button.attributes['aria-expanded'],'true');
for(const [input,result] of [['50','scale(0.5)'],['150','scale(1.5)'],['900','scale(2)'],['0','scale(1)'],['25','scale(0.5)']]) {
  zoom.value=input;zoom.events.input();assert.equal(owner.video.style.transform,result);
}
fit.value='cover';fit.events.change();assert.equal(owner.video.style.objectFit,'cover');
fit.value='invalid';fit.events.change();assert.equal(owner.video.style.objectFit,'contain');
reset.events.click();assert.equal(zoom.value,'100');assert.equal(output.value,'100%');
let stopped=0,prevented=0;
panel.events.keydown({key:'ArrowRight',stopPropagation(){stopped++;}});assert.equal(stopped,1);
panel.events.keydown({key:'Escape',stopPropagation(){stopped++;},preventDefault(){prevented++;}});
assert.equal(prevented,1);assert.equal(panel.hidden,true);assert.equal(button.focused,true);
button.events.click();doc.events.pointerdown({target:new Element()});assert.equal(panel.hidden,true);
button.events.click();ui.exitfullscreen();assert.equal(panel.hidden,true);
console.log('Picture framing: zoom bounds, contain/cover, reset, nested controls, keyboard, outside click and fullscreen exit passed');
