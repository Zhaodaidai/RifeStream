const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const events = {}, rangeEvents = {}, instances = [], seeks = [], timers = new Map();
let timerId = 0, plays = 0, failSeek = false, resolveSeek, ends = 0;
const video = {
  currentTime: 0, seekable: {length: 0}, pauses: 0, ended: false,
  addEventListener: (n, fn) => { events[n] = fn; },
  pause() { this.pauses++; events.pause?.(); }, load() { this.currentTime = 0; },
  removeAttribute() {}, play() { plays++; return Promise.reject(new Error('blocked')); },
};
const timeline = {addEventListener(n, f) {rangeEvents[n] = f;}, setAttribute(n,v) {this[n]=v;}, style:{setProperty(){}}};
const progress = {setAttribute(n,v){this[n]=v;}, removeAttribute(n){delete this[n];}};
const clock = {}, hint = {}, uiInstances = [];
class Hls {
  static Events = {ERROR:'error', MANIFEST_PARSED:'manifest'};
  static isSupported() { return true; }
  constructor(config) {this.config=config; this.events={};instances.push(this);}
  on(n,f){this.events[n]=f;} loadSource(url){this.url=url;} attachMedia(){} destroy(){this.destroyed=true;}
}
class Plyr {
  constructor(media,config){this.media=media;this.config=config;this.elements={controls:{querySelector:()=> 'volume',insertBefore:(node)=>{this.progress=node;}}};uiInstances.push(this);}
}
const context = {window:{Plyr,Hls,location:{href:'http://localhost:10000',hostname:'localhost'}}, URL,
  setTimeout(fn, delay){const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/player.js','utf8')+'\nthis.Player=EmbeddedPlayer;',context);
let player;
player = new context.Player({video,progress,timeline,clock,hint,formatTime:String,onEnded:()=>ends++, seek:async seconds=>{
  seeks.push(seconds);
  if(failSeek)throw new Error('seek failure');
  if(resolveSeek === null)await new Promise(resolve=>{resolveSeek=resolve;});
  player.update({...player.state,start:seconds,playback_id:player.state.playback_id+1,hls_ready:false,streaming:true});
}});
const base={current:{id:'ep1',title:'one'},hls_ready:true,playback_id:10,start:0,duration:1200,seekable:true,hls_url:'http://192.168.1.8:8888/rife/index.m3u8'};
const flush = async()=>{await Promise.resolve();await Promise.resolve();};
(async()=>{
  assert.equal(uiInstances.length,1);assert.equal(player.ui.progress,progress);
  assert.equal(player.ui.config.iconUrl,'/vendor/plyr.svg');assert.equal(player.ui.config.keyboard.global,false);
  assert.equal(player.ui.config.controls.includes('progress'),false);assert.equal(player.ui.config.settings.join(','),'speed');
  assert.match(player.ui.config.blankVideo,/^data:video\/mp4;base64,/);
  player.update(base);const first=player.hls;
  assert.match(first.url,/^http:\/\/localhost:8888/);assert.equal(first.config.startPosition,0);
  player.update({...base,position:400});assert.equal(player.hls,first,'poll does not reload');
  video.currentTime=12;events.timeupdate();assert.equal(clock.textContent,'12 / 1200');
  events.loadedmetadata();await flush();assert.match(hint.textContent,/播放按钮/);
  const before=plays;first.events.manifest();assert.equal(plays,before,'one autoplay attempt per load');
  video.play=()=>{plays++;return Promise.resolve();};events.playing();events.pause();
  assert.equal(player.wantsPlayback,false);
  video.seekable={length:1,start:()=>0,end:()=>30};await player.jump(15);
  assert.equal(video.currentTime,15);assert.equal(plays,before,'local seek preserves pause');
  await player.jump(900);assert.deepEqual(seeks,[900]);assert.equal(first.destroyed,true);
  assert.equal(player.hls,null);assert.equal(clock.textContent,'900 / 1200');
  player.update({...player.state,hls_ready:true});events.loadedmetadata();
  assert.equal(plays,before,'server seek preserves pause');
  const stale=player.hls;player.update({...base,current:{id:'ep2'},playback_id:20});
  assert.equal(player.wantsPlayback,true);assert.equal(stale.destroyed,true);
  stale.events.error(null,{fatal:true});assert.equal(player.retry,null,'old HLS cannot retry new session');
  stale.events.manifest();assert.equal(plays,before,'old manifest cannot autoplay');
  events.loadedmetadata();await flush();assert.equal(plays,before+1);
  video.currentTime=23;player.hls.events.error(null,{fatal:true});
  const retry=player.retry;assert.equal(timers.get(retry).delay,1000);timers.get(retry).fn();timers.delete(retry);
  assert.equal(player.hls.config.startPosition,23,'retry resumes same fragment position');
  assert.equal(player.retry,null);
  player.hls.events.error(null,{fatal:true});player.update({...base,hls_ready:false,streaming:true});
  assert.equal(timers.size,0,'switch cancels retries');assert.match(hint.textContent,/等待/);
  player.update({...base,streaming:false});assert.ok(player.hls,'completed encode remains playable');
  player.update({...base,current:null,hls_ready:false,streaming:false});assert.equal(player.key,null);
  player.update({...base,start:300,playback_id:100});video.currentTime=8;
  timeline.value=700;rangeEvents.input();player.paint();assert.equal(clock.textContent,'700 / 1200');
  rangeEvents.pointercancel();assert.equal(clock.textContent,'308 / 1200');
  let stopped=false;rangeEvents.keydown({stopPropagation(){stopped=true;}});assert.ok(stopped);
  video.seekable={length:0};resolveSeek=null;const pending=player.jump(900);
  assert.equal(timeline.disabled,true);assert.equal(clock.textContent,'900 / 1200');
  player.update({...player.state});assert.equal(clock.textContent,'900 / 1200');
  resolveSeek();await pending;resolveSeek=undefined;assert.equal(timeline.disabled,false);assert.equal(progress['aria-busy'],undefined);
  player.update({...player.state,hls_ready:true});video.currentTime=8;failSeek=true;
  await assert.rejects(player.jump(1000),/seek failure/);assert.equal(timeline.disabled,false);
  assert.equal(player.hls.config.startPosition,8,'failed seek resumes old session position');failSeek=false;
  events.loadedmetadata();events.ended();assert.equal(ends,1);player.suspend(false);events.ended();assert.equal(ends,1,'no ended transition after stop');
  player.update({...base,playback_id:150});let rejectSeek;
  const savedSeek=player.seek;player.seek=()=>new Promise((_,reject)=>{rejectSeek=reject;});
  const staleSeek=player.jump(900);player.suspend(false);const loads=instances.length;
  rejectSeek(new Error('cancelled session'));await assert.rejects(staleSeek,/cancelled session/);
  assert.equal(player.key,null);assert.equal(instances.length,loads,'late seek failure must not revive stopped media');player.seek=savedSeek;
  // An asynchronous autoplay rejection from the previous load must not replace new-session feedback.
  player.update({...base,playback_id:200});let rejectPlay;video.play=()=>new Promise((_,reject)=>{rejectPlay=reject;});
  player.wantsPlayback=true;player.autoplay();player.update({...base,playback_id:201});hint.textContent='new session';rejectPlay(new Error('old rejection'));await flush();assert.equal(hint.textContent,'new session');
  player.update({...base,seekable:false,duration:0});assert.equal(timeline.disabled,true);
  assert.equal(uiInstances.length,1);
  console.log('PASS: Plyr reuse/local icons/full-episode timeline; polling no reload; start/switch/stop/finished encode');
  console.log('PASS: local/server seek preserves pause; failed seek restores session; retry resumes position; stale HLS/play promises ignored');
  console.log('PASS: autoplay once per load, retry cancellation/backoff, drag/keyboard/pending seek/disabled/busy/ended isolation');
})().catch(error=>{console.error(error);process.exitCode=1;});
