// Test transport only: original manager stays real, all sockets forbidden.
import fs from 'node:fs';import net from 'node:net';import {Readable} from 'node:stream';import {execFileSync} from 'node:child_process';import {downloadImages} from '../../pro_xhs_download.mjs';
net.Socket.prototype.connect=function(){throw Error('NETWORK_FORBIDDEN')};let raw='';for await(const chunk of process.stdin)raw+=chunk;const p=JSON.parse(raw);
const image=Buffer.from(p.fixture_png,'base64');const headers={'content-type':'image/png','content-length':String(image.length)};
const fake=async opts=>({status:200,headers,data:Readable.from([image])});fake.head=async()=>({status:200,headers});fake.CancelToken={source:()=>({token:{},cancel(){}})};
try{const assets=await downloadImages({source:p.source,axios:fake,items:p.items,root:p.root,guard:row=>execFileSync(p.python,['-B',p.guard_module,'--guard',p.run],{input:JSON.stringify(row),maxBuffer:1024,stdio:['pipe','pipe','ignore']}),stopCheck:()=>{if(fs.existsSync(p.run+'/stop.json'))throw Error('stopped')}});process.stdout.write(JSON.stringify(assets))}catch(e){process.stderr.write('fixture_chain_failed\n');process.exitCode=87}
