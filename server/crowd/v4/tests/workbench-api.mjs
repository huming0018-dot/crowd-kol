import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const html=fs.readFileSync(new URL('../multiplatform/dashboard.html',import.meta.url),'utf8');
const source=html.match(/^async function api\(path,body\).*$/m)?.[0];
assert.ok(source);
const notice=html.match(/^function mediaNotice\(run\).*$/m)?.[0];
assert.ok(notice);
const noticeContext=vm.createContext({});
vm.runInContext(notice,noticeContext);
assert.match(noticeContext.mediaNotice({media_status:'unavailable',media_reason:'dash_audio_unavailable'}),/没有可用音轨/);
assert.match(noticeContext.mediaNotice({media_status:'limited'}),/仅取得部分/);
assert.match(noticeContext.mediaNotice({media_status:'failed'}),/未取得媒体文件/);
for(const status of [undefined,'downloaded','not_requested','unexpected'])assert.equal(noticeContext.mediaNotice({media_status:status}),'');
const owner=fs.readFileSync(new URL('../multiplatform/owner-ui.js',import.meta.url),'utf8');
assert.match(owner,/if\(mediaNotice\(run\)\)row\.append/);
assert.match(html,/if\(mediaNotice\(run\)\)summary\.append/);
let response;
const context=vm.createContext({token:'test-only',fetch:async()=>({ok:true,json:async()=>response})});
vm.runInContext(source,context);
for(const value of [
  {state:'completed',job_id:'saved-job',result:[{kind:'transcript',text:'saved transcript'}]},
  {state:'running',job_id:'active-job'},
  {tasks:[]},
  {result:[{kind:'transcript'}],state:'cancelled'},
  {ok:true,state:'completed',job_id:'analysis-job',result:{claims:[]}},
  {ok:true,state:'authenticated',generation:1},
]){
  response=value;
  assert.equal(await context.api('/api/media-processing',{}),value);
}
response={ok:true,result:{state:'completed',run_id:'collector-run'}};
assert.equal(await context.api('/api/action',{}),response.result);
response={ok:false,error:'test_error'};
await assert.rejects(context.api('/api/action',{}),/test_error/);
console.log('Workbench API envelope and saved media result regression: PASS');
