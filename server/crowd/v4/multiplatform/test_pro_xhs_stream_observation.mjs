import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import net from 'node:net';import {Readable} from 'node:stream';
import {downloadImages,failureDiagnostic} from './pro_xhs_download.mjs';
net.Socket.prototype.connect=function(){throw Error('NETWORK_FORBIDDEN')};
const source=process.env.CROWD_PRO_DOWNLOAD_MANAGER;if(!source)throw Error('CROWD_PRO_DOWNLOAD_MANAGER_required');
const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'g85-stream-')));
try {
 const calls=[];const axios=async()=>{calls.push('GET');return {status:200,headers:{'content-type':'image/png'},data:Readable.from((async function*(){yield Buffer.from('1234567');await new Promise(r=>setTimeout(r,5));throw Object.assign(Error('private url token body'),{code:'ECONNRESET'});})())}};
 axios.head=async()=>{calls.push('HEAD');return {status:200,headers:{'content-type':'image/png'}}};axios.CancelToken={source:()=>({token:{},cancel(){}})};
 let failure;try{await downloadImages({source,axios,items:[{content_id:'a'.repeat(24),media_id:'fixture',url:'https://ci.xhscdn.com/test'}],root,guard:async()=>{},timeout:10000})}catch(e){failure=e}
 assert(failure);assert.deepEqual(calls,['HEAD','GET','HEAD','GET','HEAD','GET','HEAD','GET']);
 assert.deepEqual(failureDiagnostic(failure),{schema:'crowd-xhs-media-failure-v2',stage:'stream',reason:'xhs_media_transport_failed',http_status:200,transport_errno:'ECONNRESET',stream_bytes:7});
 for(const code of ['ECONNRESET','ENOTFOUND','EAI_AGAIN','ECONNREFUSED','ETIMEDOUT','ECONNABORTED'])assert.equal(failureDiagnostic({code}).transport_errno,code);
 for(const code of ['SECRET','EPIPE',{},true])assert.equal(failureDiagnostic({code}).transport_errno,null);
 assert.equal(failureDiagnostic({response:{status:403},xhsMediaResponseStatus:200}).http_status,403);
 for(const count of [-1,1.5,true,Number.MAX_SAFE_INTEGER+1])assert.equal(failureDiagnostic({xhsMediaStreamBytes:count}).stream_bytes,null);
 assert(!JSON.stringify(failureDiagnostic(failure)).includes('private'));
 console.log('PASS_STREAM_METADATA_NO_NETWORK');
}finally{fs.rmSync(root,{recursive:true,force:true});for(const n of fs.readdirSync(path.dirname(root)))if(n.startsWith('.'+path.basename(root)+'-attempts-'))fs.rmSync(path.join(path.dirname(root),n),{recursive:true,force:true})}
