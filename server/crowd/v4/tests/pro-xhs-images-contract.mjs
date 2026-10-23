import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const root=process.env.CROWD_XHS_EDGE_ROOT?pathToFileURL(process.env.CROWD_XHS_EDGE_ROOT+'/'):new URL('../supabase/functions/crowd-machine/',import.meta.url);
const {taskPlan}=await import(new URL('contract.mjs',root));
const {unifiedPlan}=await import(new URL('unified_dispatch.mjs',root));
const base={source_executor:'pro',platforms:['xhs'],mode:'detail',targets_by_platform:{xhs:['a'.repeat(24)]},desired_items:1,max_api_requests:30,max_comments:20,comments:true,replies:true,media:true,wordcloud:false,purpose:'noncommercial_research',timeout_seconds:120,idempotency_key:'synthetic-pro-xhs-images'};
let positive=0,negative=0;
for(const mode of ['detail','creator','search']){
 const input={...base,mode};if(mode==='search'){delete input.targets_by_platform;input.targets=['synthetic keyword'];input.desired_items=20;}
 const plan=await unifiedPlan(input);assert.equal(plan.participant,null);assert.equal(plan.machine_proposal.children.length,1);const child=plan.machine_proposal.children[0];assert.equal(child.platform,'xhs');assert.equal(child.request.source_executor,'pro');assert.equal(child.request.media,true);assert.equal(child.request.comments,true);assert.equal(child.request.replies,true);assert.equal(child.request.max_comments,20);assert.equal(child.request.max_api_requests,30);assert.equal(child.request.mode,mode);assert.equal(plan.machine_proposal.reward_eligible,false);positive++;
}
for(const [changes,code]of [[{wordcloud:true},'pro_media_pipeline_unavailable'],[{platform_options_by_platform:{xhs:{transcript_only:true}}},'pro_media_pipeline_unavailable'],[{comments:true,max_comments:0},'pro_zero_comments_means_unlimited'],[{max_comments:201},'invalid_execution_limits'],[{replies:true,comments:false},'replies_require_comments'],[{platforms:['ks'],targets_by_platform:{ks:['abc']}},'pro_operation_platform_not_adapted'],[{platforms:['zhihu'],targets_by_platform:{zhihu:['https://www.zhihu.com/question/1/answer/2']}},'pro_zhihu_scope_unsupported']]){await assert.rejects(()=>taskPlan({...base,...changes}),error=>error.message===code);negative++;}
const legacy=await unifiedPlan({...base,source_executor:'mc'});assert.equal(legacy.machine_proposal.children[0].request.source_executor,'mc');assert.equal(legacy.machine_proposal.children[0].request.media,true);
const body={...base,mode:'search',targets:['synthetic'],desired_items:20,media:false};delete body.targets_by_platform;const original=await unifiedPlan(body);assert.equal(original.participant.required_capability,'crowd-participant-pro-comment-options-v1');assert.equal(original.machine_proposal,null);
console.log(JSON.stringify({status:'PASS',positive,negative,legacy_mc_and_original_participant_route_preserved:true,network:false,backend_writes:false,scope:'Pro XHS image requests on machine worker; native media route not enabled'}));
