// Exercise the production request/polling functions with deliberately reordered network completions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js','utf8');
const take = (from,to) => source.slice(source.indexOf(from),source.indexOf(to,source.indexOf(from)));
const calls=[],painted=[],errors=[],connections=[],timers=new Map();let id=0;
const context={AbortController,Promise,Date,retryConnectionBtn:{},connectionNotice:{contains:()=>false},document:{},paintConnection:message=>connections.push(message||""),
  setTimeout(fn){timers.set(++id,fn);return id;},clearTimeout(n){timers.delete(n);},
  fetch(path,options){return new Promise((resolve,reject)=>{
    calls.push({path,options,resolve:data=>resolve({ok:true,json:async()=>data}),fail:reject});
    options.signal.addEventListener('abort',()=>{const e=new Error('aborted');e.name='AbortError';reject(e);});
  })}, showError:e=>errors.push(e),renderState:state=>painted.push(state),
};
vm.createContext(context);
vm.runInContext(`let stateVersion=0, requestsInFlight=0, mutationQueue=Promise.resolve(), refreshing=false, errorVisibleUntil=0;\n${take('async function api(', '\nfunction showError')}\n${take('async function refresh()', '\nasync function addSources')}\nthis.api=api; this.refresh=refresh; this.count=()=>requestsInFlight;`,context);
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
(async()=>{
  const first=context.api('/api/play',{method:'POST'}), second=context.api('/api/stop',{method:'POST'});
  await flush();assert.equal(calls.length,1);assert.equal(context.count(),2);
  calls[0].resolve({id:1});await first;await flush();assert.equal(calls.length,2);
  calls[1].resolve({id:2});assert.equal((await second).id,2);assert.equal(context.count(),0);
  assert.equal(timers.size,0);
  const poll=context.refresh();context.refresh();await flush();assert.equal(calls.length,3,'polls single-flight');
  const mutation=context.api('/api/seek',{method:'POST'});await flush();
  calls[2].resolve({stale:true});await poll;assert.equal(painted.length,0,'old poll ignored after mutation');
  calls[3].resolve({id:3});await mutation;
  assert.equal(connections.length,0,'stale poll cannot change connection feedback');
  const fresh=context.refresh();calls[4].resolve({fresh:true});await fresh;assert.equal(painted[0].fresh,true);assert.equal(connections[0],'');assert.equal(context.retryConnectionBtn.disabled,false);
  const timeout=context.api('/api/play',{method:'POST'});const rejected=assert.rejects(timeout,/请求超时/);
  const after=context.api('/api/stop',{method:'POST'});await flush();assert.equal(calls.length,6);
  [...timers.values()][0]();await rejected;await flush();assert.equal(calls.length,7,'timeout does not poison queue');
  calls[6].resolve({stopped:true});await after;assert.equal(context.count(),0);assert.equal(timers.size,0);
  const failedPoll=context.refresh();await flush();
  calls.at(-1).fail(new Error('network down'));await failedPoll;
  assert.equal(connections.at(-1),'network down');assert.equal(context.retryConnectionBtn.disabled,false);
  const retry=context.refresh();context.refresh();await flush();
  assert.equal(context.retryConnectionBtn.disabled,true);
  calls.at(-1).resolve({recovered:true});await retry;
  assert.equal(connections.at(-1),'');assert.equal(painted.at(-1).recovered,true);
  assert.equal(context.retryConnectionBtn.textContent,'重新连接');
  // Production renderState must not revive an older session while Stop/another mutation is queued.
  const guard={};vm.createContext(guard);
  vm.runInContext(`let requestsInFlight=1,currentState='sentinel';${take('function renderState(state)', '\nfunction escapeHtml')}\nrenderState({});this.value=currentState;`,guard);
  assert.equal(guard.value,'sentinel');
  // A failed newer mutation must reconcile server state, never revive stale currentState.
  let reconciles=0;
  const recovery={showError(){},paintAvailability(){},refresh:async()=>{reconciles++;},
    embeddedPlayer:{update(){throw new Error('stale media revived');}}};
  vm.createContext(recovery);
  vm.runInContext(`let pendingActions=new Set(),currentState={old:true};${take('async function performAction(', '\nfunction paintAvailability')}this.action=performAction;`,recovery);
  const button={setAttribute(){},removeAttribute(){}};
  const rejectedAction=await recovery.action('play',button,async()=>{throw new Error('failed newer action');});
  assert.equal(rejectedAction,false);
  assert.equal(await recovery.action('play',button,async()=>{}),true);
  assert.equal(reconciles,1);assert.equal(button.disabled,false);
  // The actual seek function carries the UUID as well as the legacy clock token.
  let seekBody;
  const scoped={api:async(path,options)=>{seekBody=JSON.parse(options.body);return {};},renderState(){},showError(){},refresh:async()=>{}};
  vm.createContext(scoped);
  vm.runInContext(`let jumpInFlight=false,currentState={playback_id:100,session_id:'current-uuid'};${take('async function seekSeconds(', '\ndocument.getElementById')};this.jump=seekSeconds;`,scoped);
  await scoped.jump(42);
  assert.deepEqual(seekBody,{seconds:42,playback_id:100,session_id:'current-uuid'});
  console.log('PASS: seek carries session UUID while preserving the legacy playback_id field');
  console.log('PASS: ordered mutations; single-flight polls; stale response ignored; queued-stop render barrier; timeout/queue recovery; connection failure/retry and stale-status isolation');
})().catch(e=>{console.error(e);process.exitCode=1;});
