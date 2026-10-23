// Execute the existing live-definition pilot regression through the new node claim adapter.
// No source calls, production writes, copied alternative allocator or fixture receipt claims.
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
const original=new URL('./pilot-cohort-db.mjs',import.meta.url);
let source=fs.readFileSync(original,'utf8');
const anchor="async function claim(id,task=null){await db.query(\"select set_config('request.jwt.claim.sub',$1,false)\",[id]);return (await db.query('select public.crowd_v4_claim($1) result',[task])).rows[0].result;}";
if(!source.includes(anchor))throw new Error('pilot_fixture_anchor_changed');
const bridge=`for(const file of ['20261007051154_crowd_v4_diagnostics.sql','20261013135950_crowd_v4_participant_health_history.sql','20261011033423_crowd_machine.sql','20261013165118_crowd_distributed_nodes.sql'])await db.exec(fs.readFileSync(path.join(migrations,file),'utf8'));
async function claim(id,task=null){await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]);await db.query('select public.crowd_v4_node_register($1,$2::jsonb)',[id,JSON.stringify({version:'4.2.60',enabled:true,login_state:'ready'})]);return (await db.query('select public.crowd_v4_node_claim($1,$2) result',[id,task])).rows[0].result;}`;
source=source.replace(anchor,bridge).replaceAll('import.meta.url',JSON.stringify(original.href));
const result=spawnSync(process.execPath,['--input-type=module','--eval',source],{encoding:'utf8',env:process.env,maxBuffer:1024*1024});
process.stdout.write(result.stdout||'');
if(result.status!==0){process.stderr.write((result.stderr||'').slice(-3000));process.exit(result.status||1);}
console.log('PASS distributed node adapter reuses entire pilot claim/guard/receipt regression with fetched production definitions; physical devices not exercised.');
