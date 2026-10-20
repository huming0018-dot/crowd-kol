import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import net from 'node:net';import {Readable} from 'node:stream';import {downloadImages,imageURL} from '../../pro_xhs_download.mjs';
net.Socket.prototype.connect=function(){throw Error('NETWORK_FORBIDDEN')};
const source=process.env.CROWD_PRO_DOWNLOAD_MANAGER;if(!source)throw Error('CROWD_PRO_DOWNLOAD_MANAGER_required');
const bytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jC1sAAAAASUVORK5CYII=','base64');const temp=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'g63-native-manager-')));
const items=Array.from({length:4},(_,i)=>({content_id:'a'.repeat(24),media_id:'image-'+i,url:'https://ci.xhscdn.com/gold-'+i}));let tests=0;
async function scenario(name,{count=1,guardError,stopAt=Infinity,status=200,type='image/png',length=bytes.length,chunks=[bytes],streamError=false}={}){
 const root=path.join(temp,name);fs.mkdirSync(root);const calls=[];let stopChecks=0;
 const headers={'content-type':type};if(length!==null)headers['content-length']=String(length);
 const fake=async opts=>{assert.equal(opts.maxRedirects,0);assert.equal(opts.proxy,false);assert.equal(opts.decompress,false);assert.equal(opts.headers.Referer,'https://www.xiaohongshu.com/');calls.push(['GET',opts.url]);let data=Readable.from(chunks);if(streamError)data=new Readable({read(){this.destroy(Error('synthetic_stream_failure'))}});return{status,headers,data}};
 fake.head=async(url,opts)=>{assert.equal(opts.maxRedirects,0);assert.equal(opts.proxy,false);calls.push(['HEAD',url]);return{status,headers}};fake.CancelToken={source:()=>({token:{},cancel(){}})};
 const operation=()=>downloadImages({source,axios:fake,items:items.slice(0,count),root,guard:async row=>{if(guardError)throw Error(guardError);assert.equal(row.url,items.find(x=>x.media_id===row.media_id).url)},stopCheck:()=>{if(++stopChecks>=stopAt)throw Error('stop_requested')},timeout:1000});
 return{operation,calls,root};
}
try{
 let s=await scenario('four',{count:4});let out=await s.operation();assert.equal(out.length,4);assert.equal(s.calls.length,8);for(const item of out){assert.deepEqual(fs.readFileSync(item.path),bytes);assert.equal(item.media_engine,'native_pro_downloader')}tests++;
 s=await scenario('chunked',{length:null});assert.equal((await s.operation()).length,1);tests++;
 for(const [name,opts,code]of [['budget',{guardError:'request_budget_exhausted'},'request_budget_exhausted'],['stop',{stopAt:2},'stop_requested'],['midstreamstop',{stopAt:7},'stop_requested'],['status',{status:302},'xhs_media_http_status'],['mime',{type:'text/html'},'xhs_media_type_invalid'],['oversize',{length:2097153},'xhs_media_size_invalid'],['short',{length:bytes.length+1},'xhs_media_length_mismatch'],['overstream',{chunks:[Buffer.alloc(2097153)]},'xhs_media_size_invalid'],['streamerror',{streamError:true},'synthetic_stream_failure']]){s=await scenario(name,opts);await assert.rejects(s.operation(),new RegExp(code));assert.ok(s.calls.length<=2,'no automatic retry');if(name==='budget')assert.equal(s.calls.length,0);tests++}
 for(const url of ['http://ci.xhscdn.com/a','https://xhscdn.com.evil.invalid/a','https://u:p@ci.xhscdn.com/a','https://ci.xhscdn.com/a#x']){assert.throws(()=>imageURL(url));tests++}
 const root=path.join(temp,'bad');fs.mkdirSync(root);await assert.rejects(()=>downloadImages({source,axios:{},items:[{...items[0],media_id:'../x'}],root,guard:async()=>{}}),/plan_invalid/);tests++;
 console.log(JSON.stringify({status:'PASS',tests,original_manager:true,images:4,head_get_calls:8,socket_network:false,electron:false,source:false}));
}finally{fs.rmSync(temp,{recursive:true,force:true})}
