// Fixed participant RPCs in the original extension worker. Credentials stay there.
import fs from 'node:fs';
import path from 'node:path';
import cp from 'node:child_process';
import {pathToFileURL} from 'node:url';
const EXTENSION='licijehcpohikchlnkbpjdjdfkcocndg';
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const ACTIONS=new Set(['scope','verify_platform_principal','pro_claim','pro_guard','pro_submit','pro_status','pro_finish','pro_receipt','pro_comment_submit','pro_comment_commit','pro_comment_receipt']);
const SAFE=new Set(['invalid_participant_transport','invalid_participant_scope','invalid_participant_action','invalid_participant_params','invalid_platform_principal','participant_profile_invalid','participant_port_invalid','participant_listener_invalid','participant_profile_changed','participant_worker_missing','participant_worker_invalid','participant_scope_changed','participant_writer_busy']);
export function safeFailure(error){return SAFE.has(error?.message)?error.message:'participant_rpc_outcome_unknown';}
function requireValue(value,code){if(!value)throw Error(code);}
export function validate(input){
  requireValue(input&&Object.keys(input).sort().join(',')==='action,generation,installation_id,params,profile,subject','invalid_participant_transport');
  requireValue(typeof input.profile==='string'&&path.isAbsolute(input.profile)&&UUID.test(input.subject)&&UUID.test(input.installation_id),'invalid_participant_scope');
  requireValue(ACTIONS.has(input.action)&&input.params&&typeof input.params==='object'&&!Array.isArray(input.params),'invalid_participant_action');
  requireValue(input.generation===null&&input.action==='scope'||Number.isSafeInteger(input.generation)&&input.generation>=0,'invalid_participant_scope');
  const encoded=JSON.stringify(input.params);
  requireValue(encoded.length<=262144&&!/"(?:access_token|refresh_token|cookie|cookies|password|owner_key|worker_key)"\s*:/i.test(encoded),'invalid_participant_params');
  if(input.action==='verify_platform_principal')requireValue(Object.keys(input.params).join(',')==='uid'&&/^[a-f0-9]{24}$/.test(input.params.uid),'invalid_platform_principal');
  return input;
}
export function expression(input){
  validate(input);
  return `(async()=>{
    const input=${JSON.stringify(input)};
    const lock={},writing=input.action!=='scope';let held=false;
    const busy=()=>agent.active||agent.stopping||agent.stopActive||agent.pendingStop||pendingCommands>0||
      (typeof participantSession!=='undefined'&&participantSession.active)||(typeof platformHealth!=='undefined'&&platformHealth.active);
    if(writing){if(busy()||agent.maintenance)throw Error('participant_writer_busy');agent.maintenance=lock;held=true;}
    const check=async()=>{
      const owner=await runtime.owner(),session=await storage.get('session'),node=await storage.get('node-monitor:'+owner);
      if(owner!==input.subject||session?.user?.id!==owner||agent.generationOwner!==owner||node?.installation_id!==input.installation_id)throw Error('participant_scope_changed');
      const s=await storage.get('agent')||{};
      if(!Number.isSafeInteger(agent.generation)||agent.generation<0||input.generation!==null&&input.generation!==agent.generation)throw Error('participant_scope_changed');
      if(busy()||(held?agent.maintenance!==lock:agent.maintenance)||agent.recoveryUnsafe(s)||(s.outbox||[]).length)throw Error('participant_writer_busy');
      return {subject:owner,installation_id:node.installation_id,generation:agent.generation};
    };
    try{
      const scope=await check();
      if(input.action==='scope')return scope;
      if(input.action==='verify_platform_principal'){
        const expected=(await platformHealth.read()).xiaohongshu?.expected_ref;
        const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(input.subject+'\\nxiaohongshu\\n'+input.params.uid));
        const ref=Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,'0')).join('');
        await check();const current=(await platformHealth.read()).xiaohongshu?.expected_ref;
        if(agent.generationOwner!==input.subject||agent.generation!==input.generation||busy()||agent.maintenance!==lock)throw Error('participant_scope_changed');
        return {...scope,matched:/^[a-f0-9]{64}$/.test(current||'')&&expected===current&&ref===current};
      }
      const result=await api.rpc(input.action,{...input.params,p_installation_id:input.installation_id});
      try{await check();}catch{throw Error('participant_rpc_outcome_unknown');}return result;
    }finally{if(held&&agent.maintenance===lock)agent.maintenance=null;}
  })()`;
}
export function locate(profile,exec=(file,args)=>cp.execFileSync(file,args,{encoding:'utf8',timeout:5000,stdio:['ignore','pipe','pipe']})){
  const file=path.join(profile,'DevToolsActivePort'),stat=fs.lstatSync(file);
  requireValue(stat.isFile()&&!stat.isSymbolicLink()&&stat.uid===process.getuid()&&stat.size<=256,'participant_profile_invalid');
  const rows=fs.readFileSync(file,'utf8').trim().split(/\r?\n/);
  requireValue(rows.length===2&&/^[1-9][0-9]{0,4}$/.test(rows[0])&&Number(rows[0])<=65535&&/^\/devtools\/browser\/[A-Za-z0-9-]+$/.test(rows[1]),'participant_port_invalid');
  const port=Number(rows[0]),pids=[...new Set(exec('/usr/sbin/lsof',['-t','-a','-iTCP:'+port,'-sTCP:LISTEN']).trim().split(/\s+/))];
  requireValue(pids.length===1&&/^[1-9][0-9]*$/.test(pids[0]),'participant_listener_invalid');
  const pid=Number(pids[0]),command=exec('/bin/ps',['-p',String(pid),'-o','command=']).trim(),bindings=[...command.matchAll(/--user-data-dir=(.*?)(?= --|$)/g)];
  requireValue(command.startsWith('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome ')&&bindings.length===1&&bindings[0][1]===profile,'participant_profile_changed');
  const fields=exec('/usr/sbin/lsof',['-nP','-a','-p',String(pid),'-iTCP:'+port,'-sTCP:LISTEN','-Fpn']).trim().split(/\r?\n/);
  requireValue(fields.includes('p'+pid)&&fields.filter(x=>x.startsWith('n')).join('')==='n127.0.0.1:'+port,'participant_listener_invalid');
  return {pid,port};
}
export function targetFor(targets,port){
  requireValue(Array.isArray(targets),'participant_worker_missing');
  const selected=targets.filter(t=>t?.type==='service_worker'&&new RegExp('^chrome-extension://'+EXTENSION+'/src/background_v4_[0-9_]+\\.js$').test(t.url));
  requireValue(selected.length===1&&/^[A-Za-z0-9-]+$/.test(selected[0].id),'participant_worker_missing');
  const t=selected[0],u=new URL(t.webSocketDebuggerUrl);
  requireValue(u.protocol==='ws:'&&u.hostname==='127.0.0.1'&&u.port===String(port)&&!u.username&&!u.password&&!u.search&&!u.hash&&u.pathname==='/devtools/page/'+t.id,'participant_worker_invalid');
  return u.toString();
}
export async function call(input){
  validate(input);const before=locate(input.profile);
  const r=await fetch('http://127.0.0.1:'+before.port+'/json/list',{signal:AbortSignal.timeout(5000),redirect:'error'});
  requireValue(r.ok,'participant_worker_missing');const endpoint=targetFor(await r.json(),before.port),ws=new WebSocket(endpoint);let timer;
  try{
    const result=await new Promise((resolve,reject)=>{
      timer=setTimeout(()=>reject(Error('participant_rpc_outcome_unknown')),25000);
      ws.onopen=()=>ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression:expression(input),awaitPromise:true,returnByValue:true}}));
      ws.onerror=()=>reject(Error('participant_rpc_outcome_unknown'));
      ws.onmessage=e=>{try{const v=JSON.parse(String(e.data));if(v.id!==1)return;
        if(v.error||v.result?.exceptionDetails){
          const description=v.result?.exceptionDetails?.exception?.description||'';
          const code=description.match(/^Error: (participant_scope_changed|participant_writer_busy)(?:\n|$)/)?.[1];
          return reject(Error(code||'participant_rpc_outcome_unknown'));
        }
        resolve(v.result.result.value);
      }catch{reject(Error('participant_rpc_outcome_unknown'));}};
    });
    const after=locate(input.profile);
    requireValue(before.pid===after.pid&&before.port===after.port,'participant_rpc_outcome_unknown');return result;
  }finally{clearTimeout(timer);ws.close();}
}
async function main(){
  let raw='';for await(const chunk of process.stdin){raw+=chunk;requireValue(raw.length<=280000,'invalid_participant_transport');}
  const result=await call(JSON.parse(raw));process.stdout.write(JSON.stringify({ok:true,result}));
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)main().catch(error=>{process.stdout.write(JSON.stringify({ok:false,error:safeFailure(error)}));process.exitCode=1;});
