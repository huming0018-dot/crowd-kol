// Only test subprocess preloads this file; product has no fixture flag.
const fs=require('fs'),net=require('net'),https=require('https'),http=require('http'),{EventEmitter}=require('events'),{Readable}=require('stream');
net.Socket.prototype.connect=function(){throw Error('NETWORK_FORBIDDEN')};
const fixture=JSON.parse(fs.readFileSync(process.env.CROWD_XHS_HTTPS_FIXTURE,'utf8'));const image=Buffer.from(fixture.png,'base64');
http.request=()=>{throw Error('HTTP_FORBIDDEN')};
https.request=(options,callback)=>{
 if(!/^([A-Za-z0-9-]+\.)?xhscdn\.com$/.test(options.hostname)||!['HEAD','GET'].includes(options.method)||options.headers.Referer!=='https://www.xiaohongshu.com/')throw Error('FIXTURE_TRANSPORT_SCOPE');
 fs.appendFileSync(fixture.calls,JSON.stringify({method:options.method,hostname:options.hostname,path:options.path})+'\n');
 const req=new EventEmitter();req.method=options.method;req.aborted=false;req.setTimeout=()=>req;req.abort=()=>{req.aborted=true};req.end=()=>{queueMicrotask(()=>{const response=Readable.from(options.method==='HEAD'?[]:[image]);response.statusCode=200;response.headers={'content-type':'image/png','content-length':String(image.length)};response.statusMessage='OK';response.req=req;callback(response)})};return req;
};
