// A new machine-only contract. Existing participant/DOM envelopes remain unchanged.
export const PLATFORMS = {xhs:'xiaohongshu',dy:'douyin',ks:'kuaishou',bili:'bilibili',wb:'weibo',tieba:'tieba',zhihu:'zhihu'};
export const hex = v => typeof v==='string' && /^[a-f0-9]{64}$/.test(v);
export const uuid = v => typeof v==='string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
const plain = v => v && typeof v==='object' && !Array.isArray(v);
const secret = v => /(?:cookie|authorization|password|access_token|refresh_token|private_key)\s*[=:]/i.test(v);
export function assert(condition, code='invalid_request') { if(!condition) throw new Error(code); }
const compare = (a,b) => { const x=Array.from(a,c=>c.codePointAt(0)),y=Array.from(b,c=>c.codePointAt(0)); for(let i=0;i<Math.min(x.length,y.length);i++)if(x[i]!==y[i])return x[i]-y[i]; return x.length-y.length; };
function string(v) {
  let output='"';
  for(const c of v) { const n=c.codePointAt(0); assert(n<0xd800||n>0xdfff,'invalid_unicode'); output+=c==='"'?'\\"':c==='\\'?'\\\\':n<32?'\\u'+n.toString(16).padStart(4,'0'):c; }
  return output+'"';
}
export function canonical(value, depth=0, budget={nodes:0}) {
  assert(depth<=12 && ++budget.nodes<=5000,'encoding_limit');
  if(value===null)return 'null';
  if(typeof value==='string')return string(value);
  if(typeof value==='boolean')return value?'true':'false';
  if(typeof value==='number'){assert(Number.isSafeInteger(value),'integer_required');return String(value===0?0:value);}
  if(Array.isArray(value))return '['+value.map(v=>canonical(v,depth+1,budget)).join(',')+']';
  assert(plain(value),'invalid_encoding');
  return '{'+Object.keys(value).sort(compare).map(k=>string(k)+':'+canonical(value[k],depth+1,budget)).join(',')+'}';
}
export async function sha(value) { const bytes=new TextEncoder().encode(value); return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join(''); }
export async function captureHash(envelope) { return sha('crowd-machine-capture-v1\n'+canonical(envelope)); }

// Reject duplicate keys and non-integral lexical numbers before JSON.parse loses information.
export function strictJSON(text) {
  let index=0,nodes=0;
  const ws=()=>{while(/\s/.test(text[index]||'') && index<text.length)index++;};
  function tokenString(){const start=index++;for(;;){assert(index<text.length,'invalid_json');const c=text[index++];if(c==='"')break;if(c==='\\'){assert(index<text.length,'invalid_json');index++;}else assert(c.charCodeAt(0)>=32,'invalid_json');}const value=JSON.parse(text.slice(start,index));canonical(value);return value;}
  function parse(depth=0){ws();assert(depth<=12&&++nodes<=5000,'encoding_limit');const c=text[index];
    if(c==='"')return tokenString();
    if(c==='{'||c==='['){index++;ws();const object=c==='{',end=object?'}':']',value=object?Object.create(null):[],keys=new Set();if(text[index]===end){index++;return value;}for(;;){let key;if(object){assert(text[index]==='"','invalid_json');key=tokenString();assert(!keys.has(key),'duplicate_json_key');keys.add(key);ws();assert(text[index++]===':','invalid_json');}const v=parse(depth+1);if(object)value[key]=v;else value.push(v);ws();if(text[index]===end){index++;break;}assert(text[index++ ]===',','invalid_json');ws();}return value;}
    const tail=text.slice(index),literal=/^(true|false|null)/.exec(tail);if(literal){index+=literal[0].length;return JSON.parse(literal[0]);}
    const match=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(tail);assert(match,'invalid_json');index+=match[0].length;
    const [mantissa,exponent='0']=match[0].toLowerCase().split('e'), parts=mantissa.split('.');const fraction=parts[1]||'',exp=Number(exponent);assert(Number.isSafeInteger(exp)&&Math.abs(exp)<=1000,'integer_required');
    let digits=parts[0]+fraction,scale=exp-fraction.length; if(scale<0){assert(/^[0]+$/.test(digits.slice(scale))&&digits.length>=-scale,'integer_required');digits=digits.slice(0,scale)||'0';}else{assert(scale<=20||/^[-]?0+$/.test(digits),'integer_required');if(scale<=20)digits+='0'.repeat(scale);}
    let number;try{number=BigInt(digits);}catch{throw new Error('invalid_json');}assert(number<=9007199254740991n&&number>=-9007199254740991n,'integer_required');return Number(number);
  }
  const value=parse();ws();assert(index===text.length,'invalid_json');return value;
}
const integer=(v,low,high)=>Number.isSafeInteger(v)&&v>=low&&v<=high;
const fields=new Set(['platforms','mode','targets','targets_by_platform','desired_items','max_api_requests','comments','replies','media','purpose','authorization_ref','session_by_platform','timeout_seconds','max_comments','headless','idempotency_key','delivery_basis','record_refs_by_platform','start_page','interval_seconds','platform_options_by_platform','wordcloud']);
function target(platform,mode,value){
  assert(typeof value==='string'&&value.trim()&&value.length<=1000&&!value.includes(',')&&!value.includes('\0')&&!secret(value),'invalid_targets');
  if(mode==='search')return;
  const patterns={xhs:/^[a-f0-9]{24}$/,dy:mode==='detail'?/^[0-9]{1,20}$/:/^[A-Za-z0-9_-]{1,200}$/,ks:/^[A-Za-z0-9_-]{1,200}$/,bili:mode==='detail'?/^BV[A-Za-z0-9]{10}$/:/^[0-9]{1,20}$/,wb:mode==='detail'?/^[A-Za-z0-9]{1,200}$/:/^[0-9]{1,20}$/,tieba:mode==='detail'?/^[0-9]{1,20}$/:/^[A-Za-z0-9_.-]{1,200}$/,zhihu:/^[A-Za-z0-9_-]{1,200}$/};
  if(!value.includes('://')){assert(!(platform==='zhihu'&&mode==='detail')&&patterns[platform].test(value),'invalid_platform_target');return;}
  let u;try{u=new URL(value);}catch{throw new Error('invalid_platform_target');}assert(u.protocol==='https:'&&!u.port&&!u.username&&!u.password&&!u.hash,'invalid_platform_target');
  const h=u.hostname,p=u.pathname.replace(/\/$/,''),host=(...hosts)=>hosts.includes(h);let candidate;
  for(const [key,v]of u.searchParams) assert(!/^(cookie|authorization|token|access_token|refresh_token|password)$/i.test(key)&&!secret(key+'='+v),'credential_target_not_allowed');
  if(platform==='xhs'&&host('xiaohongshu.com','www.xiaohongshu.com'))candidate=p.match(mode==='detail'?/^\/(?:explore|discovery\/item)\/([a-f0-9]{24})$/:/^\/user\/profile\/([a-f0-9]{24})$/)?.[1];
  if(platform==='dy'&&host('douyin.com','www.douyin.com'))candidate=mode==='detail'&&u.searchParams.get('modal_id')||p.match(mode==='detail'?/^\/video\/([0-9]{1,20})$/:/^\/user\/([A-Za-z0-9_-]{1,200})$/)?.[1];
  if(platform==='dy'&&mode==='detail'&&h==='v.douyin.com'&&/^\/[A-Za-z0-9_-]+$/.test(p))return;
  if(platform==='ks'&&host('kuaishou.com','www.kuaishou.com')){candidate=p.match(mode==='detail'?/^\/short-video\/([A-Za-z0-9_-]{1,200})$/:/^\/profile\/([A-Za-z0-9_-]{1,200})$/)?.[1];if(mode==='detail'&&/^\/f\/[A-Za-z0-9_-]+$/.test(p))return;}
  if(platform==='bili')candidate=mode==='detail'&&host('bilibili.com','www.bilibili.com')?p.match(/^\/video\/(BV[A-Za-z0-9]{10})$/)?.[1]:mode==='creator'&&h==='space.bilibili.com'?p.match(/^\/([0-9]{1,20})$/)?.[1]:null;
  if(platform==='wb')candidate=mode==='detail'&&host('weibo.com','www.weibo.com')?p.match(/^\/[0-9]{1,20}\/([A-Za-z0-9]{1,200})$/)?.[1]:mode==='detail'&&h==='m.weibo.cn'?p.match(/^\/(?:detail|status)\/([A-Za-z0-9]{1,200})$/)?.[1]:mode==='creator'&&host('weibo.com','www.weibo.com')?p.match(/^\/(?:u\/)?([0-9]{1,20})$/)?.[1]:mode==='creator'&&h==='m.weibo.cn'?p.match(/^\/profile\/([0-9]{1,20})$/)?.[1]:null;
  if(platform==='tieba'&&h==='tieba.baidu.com'){candidate=mode==='detail'?p.match(/^\/p\/([0-9]{1,20})$/)?.[1]:null;if(mode==='creator'&&p==='/home/main'){const values=['id','portrait'].map(k=>u.searchParams.get(k)).filter(Boolean);if(values.length===1)candidate=values[0];}}
  if(platform==='zhihu'){if(mode==='detail'){assert(host('zhihu.com','www.zhihu.com')&&(/^\/question\/[0-9]+\/answer\/[0-9]+$/.test(p)||/^\/zvideo\/[0-9]+$/.test(p))||h==='zhuanlan.zhihu.com'&&/^\/p\/[0-9]+$/.test(p),'invalid_platform_target');return;}if(host('zhihu.com','www.zhihu.com'))candidate=p.match(/^\/people\/([A-Za-z0-9_-]{1,200})$/)?.[1];}
  assert(candidate&&patterns[platform].test(candidate),'invalid_platform_target');
}
export async function taskPlan(input){
  assert(plain(input)&&Object.keys(input).every(k=>fields.has(k)),'invalid_owner_task_request');
  const platforms=input.platforms,mode=input.mode,basis=input.delivery_basis||'live_capture';assert(Array.isArray(platforms)&&platforms.length>=1&&platforms.length<=7&&platforms.every(p=>Object.hasOwn(PLATFORMS,p))&&new Set(platforms).size===platforms.length,'invalid_platforms');
  assert(['search','detail','creator','homefeed','trending'].includes(mode),'invalid_mode');assert(['live_capture','existing_saved'].includes(basis),'invalid_delivery_basis');
  assert(typeof input.idempotency_key==='string'&&input.idempotency_key.length>=1&&input.idempotency_key.length<=160&&!secret(input.idempotency_key),'idempotency_key_required');
  assert(['noncommercial_research','licensed_use'].includes(input.purpose),'license_basis_required');if(input.purpose==='licensed_use')assert(typeof input.authorization_ref==='string'&&input.authorization_ref.length>=1&&input.authorization_ref.length<=200&&!secret(input.authorization_ref),'authorization_ref_required');
  const total=input.desired_items??20,requests=input.max_api_requests??100;assert(integer(total,1,700)&&integer(requests,basis==='existing_saved'?0:1,3500),'invalid_budget');
  for(const field of ['comments','replies','media','headless','wordcloud'])if(field in input)assert(typeof input[field]==='boolean','invalid_'+field);
  assert(!input.replies||input.comments!==false,'replies_require_comments');assert(!input.wordcloud||input.comments!==false,'wordcloud_requires_comments');
  const timeout=input.timeout_seconds??600,comments=input.max_comments??20,page=input.start_page??1;assert(integer(timeout,30,1800)&&integer(comments,0,200)&&integer(page,1,10000),'invalid_execution_limits');if('interval_seconds'in input)assert(integer(input.interval_seconds,0,300),'integer_interval_required');
  const sessions=input.session_by_platform||{};assert(plain(sessions)&&Object.keys(sessions).every(p=>platforms.includes(p))&&Object.values(sessions).every(uuid),'invalid_session_mapping');
  const discovery=['homefeed','trending'].includes(mode),support={homefeed:Object.keys(PLATFORMS),trending:['bili']};if(discovery)assert(platforms.every(p=>support[mode].includes(p))&&!input.targets&&!input.targets_by_platform,'discovery_not_supported_for_platform');
  const targets=discovery?{}:mode==='search'?Object.fromEntries(platforms.map(p=>[p,input.targets])):input.targets_by_platform;assert(discovery||plain(targets)&&Object.keys(targets).every(p=>platforms.includes(p)),'platform_targets_required');if(mode==='search')assert(!input.targets_by_platform,'search_requires_shared_targets');else if(!discovery)assert(!input.targets,'platform_targets_required');
  const refs=input.record_refs_by_platform||{};assert(plain(refs)&&Object.keys(refs).every(p=>platforms.includes(p)),'invalid_record_refs');if(basis==='live_capture')assert(!Object.keys(refs).length,'existing_refs_require_existing_saved');
  const options=input.platform_options_by_platform||{};assert(plain(options)&&Object.keys(options).every(p=>platforms.includes(p)),'invalid_platform_options');
  const children=platforms.map((platform,index)=>{const count=Math.floor(total/platforms.length)+(index<total%platforms.length?1:0),budget=Math.floor(requests/platforms.length)+(index<requests%platforms.length?1:0);assert(count<=100&&budget<=500,'per_platform_budget_limit');
    const values=targets?.[platform]||[];assert(Array.isArray(values)&&values.length<=10,'invalid_targets');for(const v of values)target(platform,mode,v);
    const selected=refs[platform]||[];assert(Array.isArray(selected)&&selected.length<=200&&selected.every(v=>plain(v)&&Object.keys(v).every(k=>['platform','content_id','kind','version_hash','results_revision','record_sha256'].includes(k))&&typeof v.content_id==='string'&&/^[A-Za-z0-9_.:-]{1,200}$/.test(v.content_id)&&['content','dynamic','comment','author','media'].includes(v.kind||'content')&&(!v.platform||v.platform===PLATFORMS[platform])&&(!v.version_hash||hex(v.version_hash))&&(!Object.hasOwn(v,'results_revision')||integer(v.results_revision,1,Number.MAX_SAFE_INTEGER)&&hex(v.version_hash))&&(!Object.hasOwn(v,'record_sha256')||hex(v.record_sha256)&&integer(v.results_revision,1,Number.MAX_SAFE_INTEGER)&&hex(v.version_hash))),'invalid_record_refs');
    const po=options[platform]||{};assert(plain(po)&&Object.keys(po).every(k=>['creator_sections','search_mode','start_day','end_day','quality','long_audio','transcript_only'].includes(k)),'invalid_platform_options');assert(platform==='bili'||['dy','ks','wb','xhs','zhihu','tieba'].includes(platform)&&Object.keys(po).every(key=>key==='transcript_only')||!Object.keys(po).length,'unsupported_platform_options');if('long_audio'in po)assert(typeof po.long_audio==='boolean'&&(!po.long_audio||input.media===true),'invalid_long_audio');if('transcript_only'in po)assert(typeof po.transcript_only==='boolean'&&(!po.transcript_only||(input.media===true&&platforms.every(value=>Object.hasOwn(PLATFORMS,value))&&(platform!=='bili'||po.long_audio===true))),'invalid_transcript_only');if(po.creator_sections)assert(mode==='creator'&&Array.isArray(po.creator_sections)&&po.creator_sections.length>0&&po.creator_sections.every(x=>['videos','dynamics'].includes(x))&&new Set(po.creator_sections).size===po.creator_sections.length,'invalid_creator_sections');if(po.creator_sections?.length===1&&po.creator_sections[0]==='dynamics')assert(!input.comments&&!input.replies&&!input.media,'bilibili_dynamics_features_unavailable');if(po.search_mode)assert(mode==='search'&&['normal','all_in_time_range','daily_limit_in_time_range'].includes(po.search_mode),'invalid_bilibili_search_mode');if(po.search_mode&&po.search_mode!=='normal')assert(/^\d{4}-\d{2}-\d{2}$/.test(po.start_day||'')&&/^\d{4}-\d{2}-\d{2}$/.test(po.end_day||'')&&po.start_day<=po.end_day,'invalid_bilibili_date_range');else assert(!po.start_day&&!po.end_day,'date_range_requires_search_mode');if(po.quality)assert([16,32,64,80,112,116,120].includes(po.quality),'invalid_bilibili_quality');
    const request={platform,mode,targets:values,max_items:count,max_api_requests:budget,comments:input.comments??true,replies:input.replies??false,media:input.media??false,purpose:input.purpose,timeout_seconds:timeout,max_comments:comments,headless:input.headless??false,wordcloud:input.wordcloud??false,start_page:page,platform_options:po};if(input.authorization_ref)request.authorization_ref=input.authorization_ref;if(sessions[platform])request.session_id=sessions[platform];if('interval_seconds'in input)request.interval_seconds=input.interval_seconds;
    let reason=basis==='existing_saved'?!selected.length?'missing_saved_records':null:!discovery&&!values.length?'missing_targets':input.media&&!['xhs','dy','ks','bili','wb','tieba','zhihu'].includes(platform)?'media_not_supported_by_upstream':!count||!budget?'budget_not_allocated':mode==='search'&&count<20?'upstream_search_minimum_20':null;
    if(!count)reason='budget_not_allocated';return {child_id:crypto.randomUUID(),platform,request,record_refs:selected,item_quota:count,request_quota:basis==='existing_saved'?0:budget,state:reason?'waiting':'queued',reason_code:reason};});
  const request={...input,delivery_basis:basis,desired_items:total,max_api_requests:basis==='existing_saved'?0:requests};
  return {request,request_hash:await sha(canonical(request)),children,desired_items:total,max_api_requests:request.max_api_requests,mode,delivery_basis:basis,storage_scope:'cloud',source_kind:'machine_api',reward_eligible:false,coverage:'unverified',quantity_semantics:'expected_entities_not_hard_source_limit',request_limit_scope:'Python httpx/requests attempts; browser resources excluded'};
}
const sensitiveKey=/^(cookie|authorization|access_token|refresh_token|xsec_token|token|password|passwd|secret|sessionid|api_key|private_key)$/i;
export function validateCapture(envelope){
  assert(plain(envelope)&&Object.keys(envelope).every(k=>['schema','capture_id','task_id','child_id','run_id','lease_epoch','platform','delivery_basis','source_kind','record','adapter_version','normalizer_version','packaged_at'].includes(k)),'invalid_capture');
  assert(envelope.schema==='crowd-machine-capture-v1'&&['capture_id','task_id','child_id','run_id'].every(k=>uuid(envelope[k]))&&integer(envelope.lease_epoch,1,2147483647)&&Object.values(PLATFORMS).includes(envelope.platform)&&['existing_saved','live_capture'].includes(envelope.delivery_basis)&&envelope.source_kind==='machine_api','invalid_capture');
  assert(typeof envelope.packaged_at==='string'&&/^\d{4}-\d{2}-\d{2}T/.test(envelope.packaged_at)&&Number.isFinite(Date.parse(envelope.packaged_at)),'invalid_capture');const record=envelope.record;
  assert(plain(record)&&record.platform===envelope.platform&&['content','dynamic','comment','author','media'].includes(record.kind)&&typeof record.content_id==='string'&&/^[A-Za-z0-9_.:-]{1,200}$/.test(record.content_id)&&record.source_kind==='mediacrawler_api'&&record.reward_eligible===false,'invalid_capture_record');
  if('discovery_kind' in record)assert(typeof record.discovery_kind==='string'&&['search','detail','creator','homefeed','trending'].includes(record.discovery_kind)&&(record.discovery_kind!=='trending'||record.platform==='bilibili'),'invalid_capture_record');
  function walk(v){if(typeof v==='string')assert(v.length<=100000&&!secret(v),'sensitive_capture');else if(Array.isArray(v))v.forEach(walk);else if(plain(v))for(const [k,x]of Object.entries(v)){assert(!sensitiveKey.test(k)&&!['owner_evaluations','source','source_info'].includes(k),'sensitive_capture');walk(x);}}walk(record);
  assert(new TextEncoder().encode(canonical(envelope)).length<=262144,'capture_size_limit');
}
