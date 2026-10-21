import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import net from 'node:net';import {Readable} from 'node:stream';import {imageURL,downloadImages} from './pro_xhs_download.mjs';
net.Socket.prototype.connect=function(){throw Error('NETWORK_FORBIDDEN')};
assert.equal(imageURL('http://ci.xhscdn.com/a?q=saved'),'http://ci.xhscdn.com/a?q=saved');
assert.equal(imageURL('https://ci.xhscdn.com/a'),'https://ci.xhscdn.com/a');
for(const u of ['http://ci.xhscdn.com:81/a','https://ci.xhscdn.com:80/a','http://user@ci.xhscdn.com/a','http://ci.xhscdn.com/a#secret','http://evil.test/a','ftp://ci.xhscdn.com/a'])assert.throws(()=>imageURL(u));
const source=process.env.CROWD_PRO_DOWNLOAD_MANAGER;if(!source)throw Error('CROWD_PRO_DOWNLOAD_MANAGER_required');
const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'g88-native-http-')));const url='http://ci.xhscdn.com/a?q=saved',bytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jC1sAAAAASUVORK5CYII=','base64'),calls=[],guards=[];
try{
 const check=opts=>{assert.equal(opts.maxRedirects,0);assert.equal(opts.proxy,false);assert.equal(opts.decompress,false);assert.equal(opts.timeout,30000)};
 const axios=async opts=>{check(opts);calls.push(['GET',opts.url]);return{status:200,headers:{'content-type':'image/png','content-length':String(bytes.length)},data:Readable.from([bytes])}};
 axios.head=async(u,opts)=>{check(opts);calls.push(['HEAD',u]);return{status:200,headers:{'content-type':'image/png','content-length':String(bytes.length)}}};axios.CancelToken={source:()=>({token:{},cancel(){}})};
 const result=await downloadImages({source,axios,items:[{content_id:'a'.repeat(24),media_id:'fixture',url}],root,guard:async row=>guards.push([row.method,row.url]),timeout:1000});
 assert.deepEqual(calls,[['HEAD',url],['GET',url]]);assert.deepEqual(guards,calls);assert.equal(result.length,1);assert.equal(result[0].transport_url,url);assert.deepEqual(fs.readFileSync(result[0].path),bytes);
 console.log('PASS_EXACT_NATIVE_HTTP_MANAGER_HEAD_GET_TWO_GUARDS_NO_NETWORK');
}finally{fs.rmSync(root,{recursive:true,force:true})}
