import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import net from 'node:net';import * as own from './pro_xhs_download.mjs';
net.Socket.prototype.connect=function(){throw Error('NETWORK_FORBIDDEN')};
const source=process.env.CROWD_PRO_DOWNLOAD_MANAGER;if(!source)throw Error('CROWD_PRO_DOWNLOAD_MANAGER_required');
const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'g78-manager-')));let calls=[];
const axios=async opts=>{calls.push('GET');const e=Error('private URL/query must never be exposed');e.response={status:403,headers:{secret:'never-export'}};throw e};
axios.head=async()=>{calls.push('HEAD');return {status:200,headers:{'content-type':'image/png','content-length':'68'}}};axios.CancelToken={source:()=>({token:{},cancel(){}})};
try{
 let failure;try{await own.downloadImages({source,axios,items:[{content_id:'a'.repeat(24),media_id:'synthetic-image',url:'https://ci.xhscdn.com/fixture'}],root,guard:async()=>{},timeout:1000})}catch(e){failure=e}
 assert(failure);assert.deepEqual(calls,['HEAD','GET']);const attemptFolder=path.join(path.dirname(root),fs.readdirSync(path.dirname(root)).find(n=>n.startsWith('.'+path.basename(root)+'-attempts-')));const files=fs.readdirSync(attemptFolder).filter(n=>n.endsWith('.part'));assert.equal(files.length,1);assert.equal(fs.statSync(path.join(attemptFolder,files[0])).size,0);assert.equal(fs.readdirSync(path.join(root,'a'.repeat(24))).length,0);
 console.log('REPRO_ORIGINAL_MANAGER_HEAD_OK_GET_FAILED_ZERO_BYTE_NO_NETWORK');
 assert.equal(typeof own.failureDiagnostic,'function');assert.deepEqual(own.failureDiagnostic(failure),{schema:'crowd-xhs-media-failure-v2',stage:'get',reason:'xhs_media_http_rejected',http_status:403,transport_errno:null,stream_bytes:null});
 assert(!JSON.stringify(own.failureDiagnostic(failure)).includes('private'));assert(!JSON.stringify(own.failureDiagnostic(failure)).includes('secret'));
 for(const code of ['ETIMEDOUT','ECONNABORTED'])assert.equal(own.failureDiagnostic({code}).reason,'xhs_media_transport_timeout');
 assert.deepEqual(own.failureDiagnostic(Error('https://token@private')), {schema:'crowd-xhs-media-failure-v2',stage:'unknown',reason:'xhs_media_unknown_failure',http_status:null,transport_errno:null,stream_bytes:null});
 assert.equal(own.failureDiagnostic(Error('xhs_media_type_invalid')).reason,'xhs_media_type_invalid');assert.equal(own.failureDiagnostic({response:{status:true}}).http_status,null);
 console.log('PASS_FINITE_DIAGNOSTIC_NO_RAW_ERROR_NO_NETWORK');
}finally{fs.rmSync(root,{recursive:true,force:true});for(const n of fs.readdirSync(path.dirname(root)))if(n.startsWith('.'+path.basename(root)+'-attempts-'))fs.rmSync(path.join(path.dirname(root),n),{recursive:true,force:true})}
