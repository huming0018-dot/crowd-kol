import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../multiplatform/media-ui.js',import.meta.url),'utf8');
const start=source.indexOf('  async function openSaved('),end=source.indexOf("  $('media_kind').onchange",start);
assert(start>=0&&end>start);
let rendered=[],calls=[],pending=null;
const controls=new Map();
const context=vm.createContext({generation:0,jobGeneration:0,timer:null,selection:null,nativeSelectionFile:null,inputPlan:null,previewGeneration:0,job:null,
clearTimeout:()=>{},clearPlayback:()=>{},$:id=>{if(!controls.has(id))controls.set(id,{replaceChildren(){this.textContent=''}});return controls.get(id)},
qualityOutput:{hidden:false,textContent:'previous quality'},exportPanel:{hidden:false,replaceChildren(){this.cleared=true}},dialog:{open:false,showModal(){this.open=true}},call:async(action,payload)=>{calls.push({action,payload});return pending||{run_id:'run-a',job_id:'subtitle-a',kind:'subtitle',state:'completed'}},
render:state=>rendered.push(state),history:async()=>{}});
vm.runInContext(source.slice(start,end)+'\nthis.openSaved=openSaved;',context);
await context.openSaved('run-a','subtitle-a');assert.equal(rendered.length,1);assert.equal(rendered[0].kind,'subtitle');assert.equal(controls.get('media_process_start').disabled,true);
assert.deepEqual(JSON.parse(JSON.stringify(calls)),[{action:'status',payload:{job_id:'subtitle-a'}}]);
pending=Promise.resolve({run_id:'other-run'});await assert.rejects(context.openSaved('run-a','subtitle-a'),/transcript_source_binding_denied/);
let done;pending=new Promise(resolve=>done=resolve);const work=context.openSaved('run-a','subtitle-a');context.dialog.open=false;done({run_id:'run-a'});await work;assert.equal(rendered.length,1);
pending=Promise.reject(Error('read failed'));controls.get('media_process_result').textContent='previous transcript';await assert.rejects(context.openSaved('run-a','subtitle-a'),/read failed/);assert.equal(controls.get('media_process_result').textContent,'');assert.equal(context.qualityOutput.textContent,'');assert.equal(context.exportPanel.hidden,true);
const owner=fs.readFileSync(new URL('../multiplatform/owner-ui.js',import.meta.url),'utf8');assert(owner.includes('mediaView.openSaved'));assert(owner.includes("light.subtitle_jobs||[]"));
console.log(JSON.stringify({ok:true,cases:4,actual_ui_entrypoint:true,no_media_required:true,cross_run_denied:true,closed_late_guard:true}));
