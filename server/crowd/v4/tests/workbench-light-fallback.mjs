import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../multiplatform/owner-ui.js',import.meta.url),'utf8');
const start=source.indexOf('        if(c.light_transcript)');
const snippet=source.slice(start,source.indexOf('\n',start));
assert.ok(start>=0);
async function render(light){
  const nodes=[],opens=[];
  const context=vm.createContext({c:{light_transcript:light},row:{append:value=>nodes.push(value)},
    node:(_,text)=>({text}),button:(text,onclick)=>({text,onclick}),guarded:fn=>fn(),
    mediaView:{openSaved:(run,job)=>opens.push({run,job})}});
  vm.runInContext(snippet,context);
  for(const node of nodes)if(node.onclick)await node.onclick();
  return {nodes,opens};
}
let result=await render({state:'needs_attention',reason:'native_video_over_collection_limit',run_id:'source',assets:[]});
assert.match(result.nodes[0].text,/视频超出采集限额，文字稿未生成/);
assert.equal(result.nodes[0].text.includes('原音轨保留'),false);
assert.deepEqual(result.opens,[]);
result=await render({state:'completed',run_id:'source',fallback_assets:[{state:'completed',job_id:'transcript',asr_run_id:'source'}]});
assert.deepEqual(result.opens,[{run:'source',job:'transcript'}]);
result=await render({state:'processing',run_id:'source',fallback_assets:[{state:'running',job_id:'audio'}]});
assert.deepEqual(result.opens,[]);
result=await render({state:'completed',run_id:'source',subtitle_jobs:[{state:'completed',job_id:'subtitle'}],assets:[{state:'completed',job_id:'original',asr_run_id:'source'}]});
assert.deepEqual(result.opens,[{run:'source',job:'subtitle'},{run:'source',job:'original'}]);
result=await render({state:'processing',run_id:'source',fallback_assets:[{state:'processing',phase:'audio_processing',audio_job_id:'audio'}]});
assert.match(result.nodes[0].text,/正在取得完整音轨/);
assert.deepEqual(result.opens,[]);
console.log(JSON.stringify({ok:true,cases:5,actual_owner_light_row:true,source_requests:0,model_calls:0}));
