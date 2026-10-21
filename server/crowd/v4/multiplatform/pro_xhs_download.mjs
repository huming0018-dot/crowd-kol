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
 const u=new URL(value);requireValue(['http:','https:'].includes(u.protocol)&&!u.username&&!u.password&&!u.hash&&(!u.port||u.port===(u.protocol==='http:'?'80':'443'))&&(/(^|\.)xhscdn\.com$/.test(u.hostname)||/(^|\.)xhsimg\.com$/.test(u.hostname)),'xhs_media_url_invalid');return u.href;
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
 requireValue(path.resolve(root)===fs.realpathSync(root),'xhs_media_output_invalid');
 const attemptsRoot=path.join(path.dirname(root),'.'+path.basename(root)+'-attempts-'+sha(Buffer.from(root)).slice(0,16));fs.mkdirSync(attemptsRoot,{mode:0o700});
 let manager,current,active,failure=null,totalBytes=0;const streams=new Set(),writers=new Set(),tokens=new Set(),timers=new Set(),attempts=[],errorAttempt=new WeakMap();
 const syncDir=folder=>{const fd=fs.openSync(folder,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);try{fs.fsyncSync(fd)}finally{fs.closeSync(fd)}};
 const fatal=error=>{failure??=error;for(const token of tokens)token.cancel('owned_xhs_media_stopped');const task=manager?.downloads.get(current);if(task)task.status='cancelled'};
 const retryable=e=>['ECONNRESET','ENOTFOUND','EAI_AGAIN','ECONNREFUSED','ETIMEDOUT','ECONNABORTED'].includes(e?.code)&&['head','get','stream'].includes(e?.xhsMediaStage)&&!(Number.isInteger(e?.response?.status)&&e.response.status!==200);
 const observe=(error,a,stage)=>{if(a)errorAttempt.set(error,a);if(!a||a!==active||a.done||a.sealed)return error;error.xhsMediaStage??=stage;if(a.error&&error!==a.error&&stage==='write'){fatal(error);return error}if(!a.error){if(a.responseStatus!==null){error.xhsMediaResponseStatus=a.responseStatus;error.xhsMediaStreamBytes=a.bytes}a.error=error;errorAttempt.set(error,a)}if(!retryable(a.error))fatal(a.error);return a.error};
 const record=(a,state)=>{if(a.recorded)return;const data={schema:'crowd-xhs-media-attempt-v1',media_id:a.item.media_id,source_url_sha256:sha(Buffer.from(a.item.url)),attempt:a.number,state,methods:a.methods,bytes:a.bytes,...(a.error?{failure:failureDiagnostic(a.error)}:{})};const fd=fs.openSync(a.log,fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_WRONLY|fs.constants.O_NOFOLLOW,0o600);try{fs.writeFileSync(fd,JSON.stringify(data));fs.fsyncSync(fd)}finally{fs.closeSync(fd)}syncDir(attemptsRoot);a.recorded=true};
 const seal=a=>{if(a.sealPromise)return a.sealPromise;a.sealPromise=(async()=>{for(const token of a.tokens)token.cancel('owned_xhs_attempt_closed');for(const stream of a.streams)stream.destroy();if(a.writer&&!a.writer.closed){const closed=new Promise(resolve=>a.writer.once('close',resolve));a.writer.destroy();await closed}if(fs.existsSync(a.partial)){const fd=fs.openSync(a.partial,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);try{fs.fsyncSync(fd)}finally{fs.closeSync(fd)}}record(a,'failed');a.sealed=true;})();return a.sealPromise;};
 const safeOutput=file=>{requireValue(path.resolve(root)===fs.realpathSync(root)&&path.dirname(file).startsWith(root+path.sep),'xhs_media_output_invalid');for(let p=path.dirname(file);p!==root;p=path.dirname(p)){const st=fs.lstatSync(p);requireValue(st.isDirectory()&&!st.isSymbolicLink(),'xhs_media_output_invalid')}};
 const publish=a=>{stopCheck();requireValue(a===active&&!a.error&&a.finished&&a.streamComplete&&a.writer.closed&&manager.downloads.get(current)?.status!=='cancelled','xhs_media_output_invalid');safeOutput(a.destination);const fd=fs.openSync(a.partial,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);try{const st=fs.fstatSync(fd);requireValue(st.isFile()&&st.nlink===1&&st.size===a.bytes&&st.size>0&&st.size<=limit,'xhs_media_output_invalid');fs.fsyncSync(fd)}finally{fs.closeSync(fd)}fs.linkSync(a.partial,a.destination);fs.unlinkSync(a.partial);syncDir(path.dirname(a.destination));syncDir(attemptsRoot);record(a,'completed');a.done=true;};
 const bounded=async(method,url,opts)=>{const a=active;
  try{
   requireValue(a&&!a.done&&!a.error&&a===active,'xhs_media_context_changed');stopCheck();requireValue(url===a.item.url,'xhs_media_request_scope');
   await guard({method,url,media_id:current});a.methods.push(method);stopCheck();
   const config={...opts,maxRedirects:0,proxy:false,decompress:false,validateStatus:s=>s===200};
   const response=method==='HEAD'?await axios.head(url,config):await axios({...config,url,method:'GET',responseType:'stream'});
   requireValue(response.status===200,'xhs_media_http_status');
   const type=String(response.headers?.['content-type']??'').split(';')[0].trim().toLowerCase();requireValue(['image/png','image/jpeg','image/webp'].includes(type),'xhs_media_type_invalid');
   const rawLength=response.headers?.['content-length'];const length=rawLength===undefined?null:String(rawLength);requireValue(length===null||/^[1-9][0-9]*$/.test(length)&&Number(length)<=limit,'xhs_media_size_invalid');
   if(method==='HEAD')return response;
   requireValue(response.data&&typeof response.data.pipe==='function','xhs_media_stream_invalid');a.responseStatus=response.status;
   const boundedStream=new Transform({transform(chunk,encoding,callback){try{stopCheck();requireValue(a===active&&!a.error,'xhs_media_context_changed');a.bytes+=chunk.length;totalBytes+=chunk.length;requireValue(Number.isSafeInteger(totalBytes)&&a.bytes<=limit&&totalBytes<=104857600,'xhs_media_size_invalid');callback(null,chunk)}catch(e){observe(e,a,'stream');callback(a.error||e)}},flush(callback){try{requireValue(!a.error&&a.bytes>0&&(length===null||a.bytes===Number(length)),'xhs_media_length_mismatch');a.streamComplete=true;callback()}catch(e){observe(e,a,'stream');callback(a.error||e)}}});
   a.streams.push(response.data,boundedStream);streams.add(response.data);streams.add(boundedStream);
   response.data.on('error',e=>{if(a!==active||a.done||a.handling)return;observe(e,a,'stream');setImmediate(()=>boundedStream.destroy(a.error))});
   boundedStream.on('error',e=>{if(a!==active||a.done||a.handling)return;observe(e,a,'stream');response.data.destroy()});
   // Let the original caller attach its writer/error listeners before any data/error is forwarded.
   setImmediate(()=>{if(a!==active||a.done||a.handling)return;try{stopCheck();if(a.error)boundedStream.destroy(a.error);else response.data.pipe(boundedStream)}catch(e){observe(e,a,'stream');boundedStream.destroy(a.error||e)}});
   return {...response,data:boundedStream};
  }catch(e){observe(e,a,method==='HEAD'?'head':'get');throw a?.error||e}
 };
 function guarded(opts){return bounded('GET',opts.url,opts)}guarded.head=(url,opts)=>bounded('HEAD',url,opts);guarded.CancelToken={source(){const token=axios.CancelToken.source();tokens.add(token);if(active)active.tokens.push(token);return token}};
 const fsFacade={...fs,mkdirSync(folder,opts){requireValue(path.dirname(folder)===root&&/^[a-f0-9]{24}$/.test(path.basename(folder)),'xhs_media_output_invalid');return fs.mkdirSync(folder,{...opts,mode:0o700})},createWriteStream(file){const a=active;try{safeOutput(file);requireValue(a&&a===active&&!a.writer&&file===a.destination,'xhs_media_output_invalid');const w=fs.createWriteStream(a.partial,{flags:fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,mode:0o600});a.writer=w;writers.add(w);const on=w.on.bind(w);on('finish',()=>a.finished=true);on('error',e=>observe(e,a,'write'));w.on=(event,listener)=>{if(event==='finish'){let delivered=false;on('close',()=>{if(delivered)return;delivered=true;if(a!==active||a.error)return;try{if(!a.done)publish(a);listener()}catch(e){observe(e,a,'write');fatal(a.error||e)}})}else on(event,listener);return w};return w}catch(e){observe(e,a,'write');throw a?.error||e}}};
 const nativeSetTimeout=(fn,ms)=>{const t=setTimeout(()=>{timers.delete(t);fn()},ms);timers.add(t);return t};
 const context=vm.createContext({console:{log(){},warn(){},error(){}},Buffer,setTimeout:nativeSetTimeout,clearTimeout:t=>{timers.delete(t);clearTimeout(t)},process:{platform:process.platform}});
 const module=new vm.SourceTextModule(stripTypeScriptTypes(raw.toString(),{mode:'transform'}),{context,identifier:source});
 const imports={events:{EventEmitter},path,fs:fsFacade,axios:{default:guarded,CancelToken:guarded.CancelToken},child_process:{spawn(){throw Error('xhs_media_spawn_forbidden')}},electron:{BrowserWindow:class{},WebContents:class{}}};
 await module.link(spec=>{requireValue(Object.hasOwn(imports,spec),'xhs_manager_import_changed');const values=imports[spec];return new vm.SyntheticModule(Object.keys(values),function(){for(const[k,v]of Object.entries(values))this.setExport(k,v)},{context})});await module.evaluate();
 manager=new module.namespace.DownloadManager({webContents:{send(){}}});requireValue(manager.DEFAULT_MAX_RETRIES===3,'xhs_manager_changed');
 const nativePerform=manager.performDownload.bind(manager),nativeHandle=manager.handleDownloadError.bind(manager);
 manager.performDownload=async task=>{const number=(task.retryCount||0)+1,item=items.find(x=>x.media_id===task.id);requireValue(number<=4&&item&&task.id===current&&!failure,'xhs_media_guard_failed');const base=sha(Buffer.from(task.id))+'-'+number;const a={item,number,partial:path.join(attemptsRoot,base+'.part'),log:path.join(attemptsRoot,base+'.json'),destination:path.join(root,item.content_id,sha(Buffer.from(task.id))+'.png'),tokens:[],streams:[],bytes:0,responseStatus:null,methods:[],error:null,handling:false,done:false};active=a;attempts.push(a);try{return await nativePerform(task)}catch(e){observe(e,a,e.xhsMediaStage||'manager');fatal(a.error||e);return false}};
 manager.handleDownloadError=async(task,error,resolve,reject)=>{const a=errorAttempt.get(error)||active;if(!a||a!==active||a.handling||a.done)return false;a.handling=true;observe(error,a,error.xhsMediaStage||'manager');try{await seal(a);stopCheck()}catch(e){fatal(e)}if(failure||!retryable(a.error)){fatal(failure||a.error);task.status='cancelled'}return nativeHandle(task,a.error||error,resolve,reject)};
 const assets=[];
 try{
  for(const item of items){
   current=item.media_id;active=null;stopCheck();const filename=sha(Buffer.from(current))+'.png',destination=path.join(root,item.content_id,filename);requireValue(!fs.existsSync(destination),'xhs_media_output_exists');
   await manager.addDownload('xhs',current,item.url,filename,root,item.content_id);
   const deadline=Date.now()+timeout;
   while(!failure&&!(manager.downloads.get(current)?.status==='completed'&&!manager.activeDownloads.has(current))){stopCheck();requireValue(Date.now()<deadline,'xhs_media_timeout');await new Promise(resolve=>setTimeout(resolve,5))}
   if(failure)throw failure;stopCheck();
   const st=fs.lstatSync(destination);requireValue(st.isFile()&&!st.isSymbolicLink()&&st.nlink===1&&st.size>0&&st.size<=limit,'xhs_media_output_invalid');
   const bytes=fs.readFileSync(destination);assets.push({content_id:item.content_id,source_media_id:current,transport_url:item.url,path:destination,bytes:bytes.length,sha256:sha(bytes),media_engine:'native_pro_downloader',content_engine:'mediacrawler_pro',platform:'xhs',kind:'image',source_kind:'mediacrawler_api',reward_eligible:false});
  }
  return assets;
 }catch(e){fatal(e);throw e}finally{for(const token of tokens)token.cancel('owned_xhs_media_closed');for(const stream of streams)stream.destroy();for(const writer of writers)writer.destroy();for(const task of manager.downloads.values())if(task.status!=='completed')task.status='cancelled';for(const timer of timers)clearTimeout(timer);timers.clear();const cleanup=await Promise.allSettled(attempts.filter(a=>!a.done).map(seal));const failed=cleanup.find(x=>x.status==='rejected');if(failed&&!failure)throw failed.reason;}
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
