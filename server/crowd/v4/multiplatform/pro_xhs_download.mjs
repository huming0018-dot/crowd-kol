// Own glue only. Licensed DownloadManager TypeScript is loaded in memory.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import vm from 'node:vm';
import {EventEmitter} from 'node:events';
import {Transform} from 'node:stream';
import {stripTypeScriptTypes} from 'node:module';
import {fileURLToPath} from 'node:url';
export const MANAGER_SHA='8fe88ee05ac91fa7e256be921b67e6fcb9396f337fed0a92f8ca12ea45e5c84e';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
function requireValue(ok,code){if(!ok)throw Error(code)}
export function imageURL(value){
 requireValue(typeof value==='string'&&value.length<=8192,'xhs_media_url_invalid');
 const u=new URL(value);requireValue(u.protocol==='https:'&&!u.username&&!u.password&&!u.hash&&(!u.port||u.port==='443')&&(/(^|\.)xhscdn\.com$/.test(u.hostname)||/(^|\.)xhsimg\.com$/.test(u.hostname)),'xhs_media_url_invalid');return u.href;
}
// Finite metadata only: never serialize raw errors, URLs, headers or response bodies.
export function failureDiagnostic(error){
 const allowed=new Set(['xhs_media_http_status','xhs_media_type_invalid','xhs_media_size_invalid','xhs_media_stream_invalid','xhs_media_length_mismatch','xhs_media_timeout','xhs_media_output_invalid','xhs_media_output_exists','xhs_media_context_changed','xhs_media_budget_exhausted','xhs_media_stopped','xhs_media_guard_failed','xhs_manager_changed','xhs_manager_import_changed']);
 const validStatus=value=>Number.isInteger(value)&&value>=100&&value<=599;
 const status=validStatus(error?.response?.status)?error.response.status:validStatus(error?.xhsMediaResponseStatus)?error.xhsMediaResponseStatus:null;
 const transport_errno=['ETIMEDOUT','ECONNABORTED','ECONNRESET','ENOTFOUND','EAI_AGAIN','ECONNREFUSED'].includes(error?.code)?error.code:null;
 const stream_bytes=Number.isSafeInteger(error?.xhsMediaStreamBytes)&&error.xhsMediaStreamBytes>=0?error.xhsMediaStreamBytes:null;
 let reason=allowed.has(error?.message)?error.message:'xhs_media_unknown_failure';
 if(status!==null&&status!==200)reason='xhs_media_http_rejected';
 else if(['ETIMEDOUT','ECONNABORTED'].includes(error?.code))reason='xhs_media_transport_timeout';
 else if(['ECONNRESET','ENOTFOUND','EAI_AGAIN','ECONNREFUSED'].includes(error?.code))reason='xhs_media_transport_failed';
 const stage=['head','get','stream','write','manager'].includes(error?.xhsMediaStage)?error.xhsMediaStage:'unknown';
 return {schema:'crowd-xhs-media-failure-v2',stage,reason,http_status:status,transport_errno,stream_bytes};
}
export async function downloadImages({source,axios,items,root,guard,stopCheck=()=>{},limit=2097152,timeout=30000}){
 requireValue(typeof guard==='function'&&typeof stopCheck==='function'&&limit===2097152&&Number.isInteger(timeout)&&timeout>0&&timeout<=30000,'xhs_media_contract_invalid');
 const raw=fs.readFileSync(source);requireValue(sha(raw)===MANAGER_SHA,'xhs_manager_changed');
 requireValue(Array.isArray(items)&&items.length>0&&fs.lstatSync(root).isDirectory()&&!fs.lstatSync(root).isSymbolicLink(),'xhs_media_plan_invalid');
 const ids=new Set();for(const item of items){requireValue(item&&Object.keys(item).sort().join(',')==='content_id,media_id,url'&&/^[0-9a-f]{24}$/.test(item.content_id)&&typeof item.media_id==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(item.media_id)&&!ids.has(item.media_id),'xhs_media_plan_invalid');ids.add(item.media_id);imageURL(item.url)}
 let manager,current,currentStream=null,failure=null;const streams=new Set(),writers=new Set(),tokens=new Set(),updates=[];
 const fail=error=>{if(!failure&&currentStream){const observation=currentStream();error.xhsMediaResponseStatus=observation.status;error.xhsMediaStreamBytes=observation.bytes}error.xhsMediaStage??='manager';failure??=error;for(const token of tokens)token.cancel('owned_xhs_media_stopped');const task=manager?.downloads.get(current);if(task)task.status='cancelled'};
 const bounded=async(method,url,opts)=>{
  try{
   stopCheck();requireValue(url===items.find(x=>x.media_id===current)?.url,'xhs_media_request_scope');
   await guard({method,url,media_id:current});stopCheck();
   const config={...opts,maxRedirects:0,proxy:false,decompress:false,validateStatus:s=>s===200};
   const response=method==='HEAD'?await axios.head(url,config):await axios({...config,url,method:'GET',responseType:'stream'});
   requireValue(response.status===200,'xhs_media_http_status');
   const type=String(response.headers?.['content-type']??'').split(';')[0].trim().toLowerCase();requireValue(['image/png','image/jpeg','image/webp'].includes(type),'xhs_media_type_invalid');
   const rawLength=response.headers?.['content-length'];const length=rawLength===undefined?null:String(rawLength);requireValue(length===null||/^[1-9][0-9]*$/.test(length)&&Number(length)<=limit,'xhs_media_size_invalid');
   if(method==='HEAD')return response;
   requireValue(response.data&&typeof response.data.pipe==='function','xhs_media_stream_invalid');
   let count=0;const boundedStream=new Transform({transform(chunk,encoding,callback){try{stopCheck();count+=chunk.length;requireValue(count<=limit,'xhs_media_size_invalid');callback(null,chunk)}catch(e){e.xhsMediaStage='stream';fail(e);callback(e)}},flush(callback){try{requireValue(count>0&&(length===null||count===Number(length)),'xhs_media_length_mismatch');callback()}catch(e){e.xhsMediaStage='stream';fail(e);callback(e)}}});
   const responseStatus=response.status;currentStream=()=>({status:responseStatus,bytes:count});
   streams.add(response.data);streams.add(boundedStream);response.data.on('error',e=>{e.xhsMediaStage='stream';fail(e);boundedStream.destroy(e)});boundedStream.on('error',e=>{fail(e);response.data.destroy()});
   return {...response,data:response.data.pipe(boundedStream)};
  }catch(e){e.xhsMediaStage=method==='HEAD'?'head':'get';fail(e);throw e}
 };
 function guarded(opts){return bounded('GET',opts.url,opts)}guarded.head=(url,opts)=>bounded('HEAD',url,opts);guarded.CancelToken={source(){const token=axios.CancelToken.source();tokens.add(token);return token}};
 const safeOutput=file=>{requireValue(path.resolve(root)===fs.realpathSync(root)&&path.dirname(file).startsWith(root+path.sep),'xhs_media_output_invalid');for(let p=path.dirname(file);p!==root;p=path.dirname(p)){const st=fs.lstatSync(p);requireValue(st.isDirectory()&&!st.isSymbolicLink(),'xhs_media_output_invalid')}};
 const fsFacade={...fs,mkdirSync(folder,opts){requireValue(path.dirname(folder)===root&&/^[a-f0-9]{24}$/.test(path.basename(folder)),'xhs_media_output_invalid');return fs.mkdirSync(folder,{...opts,mode:0o700})},createWriteStream(file,...args){safeOutput(file);const w=fs.createWriteStream(file,{flags:fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,mode:0o600});writers.add(w);w.on('error',e=>{e.xhsMediaStage='write';fail(e)});return w}};
 const context=vm.createContext({console:{log(){},warn(){},error(){}},Buffer,setTimeout,clearTimeout,process:{platform:process.platform}});
 const module=new vm.SourceTextModule(stripTypeScriptTypes(raw.toString(),{mode:'transform'}),{context,identifier:source});
 const imports={events:{EventEmitter},path,fs:fsFacade,axios:{default:guarded,CancelToken:guarded.CancelToken},child_process:{spawn(){throw Error('xhs_media_spawn_forbidden')}},electron:{BrowserWindow:class{},WebContents:class{}}};
 await module.link(spec=>{requireValue(Object.hasOwn(imports,spec),'xhs_manager_import_changed');const values=imports[spec];return new vm.SyntheticModule(Object.keys(values),function(){for(const[k,v]of Object.entries(values))this.setExport(k,v)},{context})});await module.evaluate();
 manager=new module.namespace.DownloadManager({webContents:{send(channel,data){updates.push(structuredClone(data))}}});manager.DEFAULT_MAX_RETRIES=0;
 const assets=[];
 try{
  for(const item of items){
   current=item.media_id;currentStream=null;stopCheck();const filename=sha(Buffer.from(current))+'.png';const destination=path.join(root,item.content_id,filename);requireValue(!fs.existsSync(destination),'xhs_media_output_exists');
   await manager.addDownload('xhs',current,item.url,filename,root,item.content_id);
   const deadline=Date.now()+timeout;
   while(!failure&&!updates.some(x=>x.id===current&&x.status==='completed')){stopCheck();requireValue(Date.now()<deadline,'xhs_media_timeout');await new Promise(resolve=>setTimeout(resolve,5))}
   if(failure)throw failure;stopCheck();
   const st=fs.lstatSync(destination);requireValue(st.isFile()&&!st.isSymbolicLink()&&st.size>0&&st.size<=limit,'xhs_media_output_invalid');
   const bytes=fs.readFileSync(destination);assets.push({content_id:item.content_id,source_media_id:current,transport_url:item.url,path:destination,bytes:bytes.length,sha256:sha(bytes),media_engine:'native_pro_downloader',content_engine:'mediacrawler_pro',platform:'xhs',kind:'image',source_kind:'mediacrawler_api',reward_eligible:false});
  }
  return assets;
 }catch(e){fail(e);throw e}finally{for(const token of tokens)token.cancel('owned_xhs_media_closed');for(const stream of streams)stream.destroy();for(const writer of writers)writer.destroy();for(const task of manager.downloads.values())if(task.status!=='completed')task.status='cancelled'}
}

// Only own Python child can supply this pipe. No socket, listener or Electron app.
if(process.argv[1]&&path.resolve(process.argv[1])===path.resolve(fileURLToPath(import.meta.url))){
 try{
  const {createRequire}=await import('node:module');const {execFileSync}=await import('node:child_process');
  let raw=Buffer.alloc(0);for await(const chunk of process.stdin){raw=Buffer.concat([raw,chunk]);requireValue(raw.length<=131072,'xhs_media_input_limit')}
  const payload=JSON.parse(raw.toString());const binding=payload.binding;
  const stable=(file,hash)=>{const info=fs.lstatSync(file);requireValue(info.isFile()&&!info.isSymbolicLink()&&info.size<=8388608&&sha(fs.readFileSync(file))===hash,'xhs_media_context_changed')};
  const stopCheck=()=>{requireValue(!fs.existsSync(path.join(payload.run,'stop.json')),'xhs_media_stopped');for(const name of ['state','identity','binding'])stable(payload.identity[name+'_path'],payload.identity[name+'_sha256']);stable(binding.binding_path,binding.binding_sha256)};
  stopCheck();stable(binding.manager_path,binding.manager_sha256);for(const[name,hash]of Object.entries(binding.axios_files))stable(path.join(binding.axios_root,name),hash);
  const require=createRequire(import.meta.url);const axios=require(path.join(binding.axios_root,'node_modules/axios'));
  const assets=await downloadImages({source:binding.manager_path,axios,items:payload.items,root:payload.root,timeout:payload.timeout,stopCheck,guard:row=>{try{execFileSync(payload.python,['-B',payload.guard_module,'--guard',payload.run],{input:JSON.stringify(row),stdio:['pipe','pipe','ignore'],timeout:5000,maxBuffer:1024})}catch(e){if(e.status===73)throw Error('xhs_media_budget_exhausted');if(e.status===74)throw Error('xhs_media_stopped');throw Error('xhs_media_guard_failed')}}});
  process.stdout.write(JSON.stringify(assets));
 }catch(e){process.stdout.write(JSON.stringify(failureDiagnostic(e)));process.exitCode=e.message==='xhs_media_budget_exhausted'?73:e.message==='xhs_media_stopped'?74:87}
}
