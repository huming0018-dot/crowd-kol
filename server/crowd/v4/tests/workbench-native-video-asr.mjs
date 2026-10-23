import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync('crowd-kol/server/crowd/v4/multiplatform/media-ui.js','utf8');
const code=source.slice(source.indexOf('  async function previewInput('),source.indexOf('  async function open(file)'));
const items={media_content:{value:'123',options:[{value:'123'}]},media_kind:{value:'asr',selectedOptions:[{disabled:false}]},media_process_start:{disabled:false},media_process_hint:{textContent:''}};
const requests=[];let reply;
const hash='a'.repeat(64);const file={sha256:hash,bytes:26*1048576};
const context=vm.createContext({nativeSelectionFile:file,inputPlan:null,previewGeneration:0,generation:1,dialog:{open:true},selection:{run_id:'fixture',path:'output/bili/media/BV1/video.mp4'},$:id=>items[id],
 call:(action,payload)=>{requests.push({action,payload});return reply;}});
vm.runInContext(code,context);
const good={processing_profile:'registered_native_mp4_asr_64mib_7200s',native_video_verified:true,asset_sha256:hash,input_bytes:file.bytes,max_input_bytes:64*1048576,max_audio_seconds:7200};
reply=Promise.resolve(good);await context.previewInput();assert.equal(context.inputPlan.asset_sha256,hash);assert(!items.media_process_start.disabled);assert(items.media_process_hint.textContent.includes('120分钟、64MiB'));
assert.equal(requests[0].action,'preview');assert.equal(JSON.stringify(Object.keys(requests[0].payload).sort()),JSON.stringify(['content_id','kind','path','run_id']));
for(const change of [{asset_sha256:'b'.repeat(64)},{input_bytes:1},{native_video_verified:false},{max_input_bytes:128*1048576},{max_audio_seconds:7201}]){
 reply=Promise.resolve({...good,...change});await context.previewInput();assert.equal(context.inputPlan,null);assert(items.media_process_start.disabled);
}
context.nativeSelectionFile={sha256:hash,bytes:100};reply=Promise.resolve({...good,processing_profile:'standard_25mib_3600s',input_bytes:100,max_input_bytes:25*1048576,max_audio_seconds:3600});await context.previewInput();assert(items.media_process_hint.textContent.includes('60分钟、25MiB'));
let resolve;reply=new Promise(r=>resolve=r);const late=context.previewInput();items.media_content.value='other';resolve(good);await late;assert.equal(context.inputPlan,null);
items.media_content.value='123';reply=new Promise(r=>resolve=r);const closed=context.previewInput();context.dialog.open=false;resolve(good);await closed;assert.equal(context.inputPlan,null);
context.dialog.open=true;items.media_kind.value='ocr';const before=requests.length;await context.previewInput();assert.equal(requests.length,before);assert.equal(context.inputPlan,null);
assert(source.includes('nativeSelectionFile&&$(\'media_kind\').value===\'asr\'&&!inputPlan'));
assert(source.includes("'processing_profile','native_video_context_sha256'"));
console.log(JSON.stringify({ok:true,cases:10,explicit_server_preview_only:true,source:0,model:0}));
