import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const elements=new Map(),buttons=[],calls=[],downloads=[],blobs=new Map();
class Element{
  constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.events={};this.options=[];this.attrs={};}
  set id(value){this._id=value;elements.set(value,this);}get id(){return this._id;}
  set innerHTML(value){for(const m of value.matchAll(/id="([^"]+)"/g)){const e=new Element('element');e.id=m[1];}}
  append(...items){this.children.push(...items);}replaceChildren(){this.children=[];}setAttribute(k,v){this.attrs[k]=v;}removeAttribute(){}pause(){}load(){}
  addEventListener(k,fn){this.events[k]=fn;}showModal(){this.open=true;}close(){this.open=false;this.events.close?.();}
  click(){downloads.push({name:this.download,blob:blobs.get(this.href)});}
}
const run='191578de-5510-4fae-a8a7-aca16d80e31b',sha='a'.repeat(64),ref='55c5ed86-42b9-540d-acce-092f3af940f6';
const file={path:'output/ks/media/123/video.mp4',platform:'kuaishou',content_id:'123',sha256:sha,bytes:10,source_kind:'mediacrawler_api'};
const receipt={artifact_id:ref,artifact_kind:'video_object',status:'received',verification:'server_storage_bytes_sha256',manifest:{manifest_version:2,representation:'native_collected',completeness:'saved_asset_not_full_length_verified',local_run_id:run,platform:'kuaishou',content_id:'123',asset_sha256:sha,asset_bytes:10}};
let status={state:'not_saved',reference_id:ref},saved=receipt,pending=null,pendingStatus=null,responseHash=sha;
const body=new Element('body'),context=vm.createContext({Blob,token:'fixture-csrf',selectedRun:{run_id:run},idOf:r=>r.run_id,resultData:{records:[]},document:{body},node:(tag,text)=>new Element(tag,text),$:id=>elements.get(id),Option:function(text,value){this.text=text;this.value=value;},button:(text,fn)=>{const b=new Element('button',text);b.onclick=fn;buttons.push(b);return b;},api:async(route,value)=>{assert.equal(route,'/api/media-processing');calls.push(value);if(value.action==='native_video_cloud_status')return pendingStatus||status;if(value.action==='native_video_cloud_save')return pending||{receipt:saved};throw Error('unexpected action');},fetch:async(route,options)=>{const value=JSON.parse(options.body);calls.push(value);assert.equal(options.headers['X-Crowd-CSRF'],'fixture-csrf');return {ok:true,headers:{get:()=>responseHash},blob:async()=>new Blob(['full-video'])};},URL:{createObjectURL(blob){const url='blob:'+blobs.size;blobs.set(url,blob);return url;},revokeObjectURL(){}},setTimeout:()=>1,clearTimeout(){},guarded:fn=>fn(),download(){}});
vm.runInContext(fs.readFileSync('crowd-kol/server/crowd/v4/multiplatform/media-ui.js','utf8'),context);
const view=vm.runInContext('mediaView',context),dialog=body.children.find(x=>x.attrs['aria-label']==='已采视频云保存'),save=buttons.find(x=>x.textContent==='保存已采视频到云端'),download=buttons.find(x=>x.textContent==='下载云端已采视频');
await view.cloudVideo(file);assert.equal(calls.length,1);assert.equal(calls[0].action,'native_video_cloud_status');assert.equal(download.hidden,true);assert.equal(save.disabled,false);
await save.onclick();assert.equal(calls.filter(x=>x.action==='native_video_cloud_save').length,1);assert.equal(save.disabled,true);assert.equal(download.hidden,false);assert.equal(calls.at(-1).payload.asset_sha256,sha);assert.equal('path' in calls.at(-1).payload,false);
await download.onclick();assert.equal(downloads.length,1);assert.equal(await downloads[0].blob.text(),'full-video');assert.match(downloads[0].name,/\.mp4$/);
responseHash='b'.repeat(64);await download.onclick();assert.equal(downloads.length,1);responseHash=sha;
for(const change of [{bytes:50*1048576+1},{path:'cover.jpg'},{source_kind:'derived_local'},{sha256:'bad'}]){const before=calls.length;await view.cloudVideo({...file,...change});assert.equal(calls.length,before);assert.equal(save.disabled,true);}
status={state:'outcome_unknown',reference_id:ref};await view.cloudVideo(file);assert.equal(save.textContent,'核对已采视频保存结果');assert.equal(calls.filter(x=>x.action==='native_video_cloud_save').length,1);
let resolve;pending=new Promise(r=>resolve=r);const saving=save.onclick();await save.onclick();assert.equal(calls.filter(x=>x.action==='native_video_cloud_save').length,2);dialog.close();resolve({receipt});await saving;pending=null;assert.equal(dialog.open,false);
status={state:'received',receipt:{...receipt,manifest:{...receipt.manifest,platform:'weibo'}}};await view.cloudVideo(file);assert.equal(download.hidden,true);assert.equal(save.disabled,true);
status={state:'not_saved'};context.resultData.records=[{kind:'content',platform:'zhihu',content_id:'123',content_type:'zvideo'}];await view.cloudVideo({...file,platform:'zhihu',path:'output/zhihu/media/123/zvideo/video.mp4',source_content_type:'zvideo'});assert.equal(calls.at(-1).payload.entity_ref,'zhihu:content:123:zvideo');
context.resultData.records.push({kind:'content',platform:'zhihu',content_id:'123',content_type:'answer'});const before=calls.length;await view.cloudVideo({...file,platform:'zhihu',source_content_type:'zvideo'});assert.equal(calls.length,before);
context.resultData.records=[];pendingStatus=new Promise(r=>resolve=r);const opening=view.cloudVideo(file);dialog.close();resolve({state:'received',receipt});await opening;pendingStatus=null;assert.equal(download.hidden,true);
console.log(JSON.stringify({ok:true,cases:11,explicit_cloud_save_and_download:true,readonly_lookup:true,hash_and_byte_checks:true,unknown_no_automatic_upload:true,late_closed_requests_ignored:true,typed_zhihu_identity:true,source_requests:0,model_calls:0}));
