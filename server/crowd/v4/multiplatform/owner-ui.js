'use strict';
// Uses the same saved tasks through HTTP and CLI; collection stays in the existing runner.
const ownerView = (() => {
  const call = (action, payload = {}) => api('/api/tasks', {action, payload});
  function entryText(record){const names={search:'关键词搜索',detail:'指定详情',creator:'作者内容',homefeed:'首页推荐页面采样',trending:'热门页面采样'};return Object.hasOwn(names,record.discovery_kind)?names[record.discovery_kind]:'未记录（unknown）';}
  const receiptDialog=node('dialog');receiptDialog.setAttribute('aria-label','云端采集结果与回执');
  const receiptClose=button('关闭',()=>receiptDialog.close()),receiptBody=node('div');receiptBody.className='dialog-body';
  receiptDialog.append(receiptClose,receiptBody);document.body.append(receiptDialog);let receiptGeneration=0;
  receiptDialog.addEventListener('close',()=>receiptGeneration++);
  async function receipts(task){const ticket=++receiptGeneration;receiptBody.replaceChildren(node('p','正在读取云端回执…'));receiptDialog.showModal();try{const value=await api('/api/cloud',{action:'results',payload:{task_id:task.task_id}});if(ticket!==receiptGeneration||!receiptDialog.open)return;receiptBody.replaceChildren(node('h2','云端已接收 '+value.items.length+' 份记录'));if(task.delivery_basis==='existing_saved')receiptBody.append(node('p','这是已有素材的云端回传，本任务没有发起新采集。'));for(const item of value.items){const record=item.record||{},article=node('article');article.className='task';article.append(node('h3',record.title||record.content_id||record.kind),node('p',record.body||record.text||''),node('small','采集入口：'+entryText(record)),node('small','机器采集 · '+(item.receipt?.status||'待核对')+' · '+(item.receipt?.capture_id||'')));const detail=node('details');detail.append(node('summary','记录与入库回执'),node('pre',JSON.stringify(item,null,2)));article.append(detail);receiptBody.append(article);}}catch(error){if(ticket===receiptGeneration&&receiptDialog.open)receiptBody.replaceChildren(node('p','云端结果读取失败：'+error.message));}}

  const names = {delivery_pending:'等待回传，尚未完成',observing:'本轮正在观察',blocked:'需要处理',budget_exhausted:'跟踪总额已用完',unknown:'结果未知，待核对',dispatching:'正在分配',scheduled:'等待下个周期',observed_only:'本轮观察已保存',queued:'等待分配',running:'正在采集',waiting:'需要处理',paused:'已暂停',stopped:'已停止',completed:'执行已结束',partial:'部分结果',failed:'需要处理',interrupted_unknown:'中断，待核对'};
  const reasons = {pro_cookiebridge_unavailable:'原浏览器登录桥暂不可用；请恢复原浏览器扩展连接，当前不能判断平台是否登出。',pro_login_verification_failed:'连接或身份核验失败，采集已暂停；不代表账号登出，请查看诊断。',pro_self_check_unsupported:'该采集引擎暂不支持此平台登录核验，原采集方式保留。',unacknowledged_delivery:'原记录已保存，请在待回传处理查看原因与恢复',same_account_resumed:'原账号核验已通过，等待按剩余额度继续。',lease_expired_source_outcome_unknown:'执行租约已过期，来源结果待核对，不会自动重发。',missing_targets:'此平台没有匹配目标；在新任务中补入本平台链接。',budget_not_allocated:'总额度不足以分配此平台；不会暗增额度。',budget_exhausted:'该平台额度已用完，已保存结果保留。',no_content_observed:'本轮没有取得可展示内容；原因见任务详情。',discovery_empty_or_unavailable:'首页尚未取得可采候选。',observed_window_partial:'已取得部分内容；需要继续时仅使用剩余额度。',result_import_failed:'已采结果尚未保存到资料库；核对本机存储后重试导入，不重新采集。',dispatch_outcome_unknown:'启动结果未知；先核对原执行进程，不会自动重开。',source_outcome_unknown:'执行状态未知；先核对原任务与文件。',upstream_search_minimum_20:'每个平台搜索至少需配置20条；总量不足时不会自动扩大。',login_required:'需要本人重新登录；已有结果保留。',session_busy:'本平台登录资料正在使用，等待空闲。',unsupported_target:'此平台没有匹配的目标。',start_outcome_unknown:'启动结果未知，请先核对，不会自动重开。',media_not_supported_by_upstream:'该平台暂不支持所选媒体下载。',watch_budget_exhausted:'跟踪计划总额已用完；已有资料保留。',insufficient_cycle_budget:'剩余额度不足以执行完整一轮；不会扩大预算。',prior_task_outcome_unknown:'上一轮结果未知；先核对原任务。',prior_task_manually_stopped:'上一轮已被本人停止；不会自动恢复。',prior_cycle_unknown:'上一轮结果未知；先核对原任务。',prior_cycle_requires_action:'上一轮需要处理；打开原任务核对具体平台。',prior_cycle_failed:'上一轮执行失败；已有资料保留。',owner_task_user_stop:'原采集任务已被本人停止，不会自动恢复。',total_request_budget_exhausted:'整个跟踪计划额度已用完；已有资料保留。',user_stop:'本人已暂停。',owner_stop_requested:'Owner已明确请求停止，系统执行；已有结果保留。',cloud_controller_error:'系统因云端控制检查失败停止，已有结果保留；不会自动重采。',cloud_dispatch_denied:'系统因云端授权不可继续而停止，已有结果保留。',cloud_worker_shutdown:'工作台关闭时系统停止，已有结果保留。',worker_shutdown:'容器关闭时系统停止，已有结果保留。',legacy_stop_requested:'旧停止记录没有调用者，不能确认是本人停止。'};
  Object.assign(reasons,{audited_terminal_unknown:'旧执行结果仍未知；已核对并保守计费封账，不会重采旧任务。',audited_executor_completed:'原执行与全部云回执已对账；正文和媒体是否完整请查看结果。',audited_executor_completed_without_content:'原执行与回执已对账，但没有取得正文。'});
  let watches = [], items = [], busy = false, preview = null, previewRequest = null, generation = 0, listPromise = null, unifiedMode = false, unresolvedKey = null;
  const pendingDispatchKey='crowd_unified_pending_dispatch';
  const unifiedCall=(action,payload={})=>api('/api/cloud',{action,payload});
  const routeNames={participant_extension:'参与者终端自动领取',machine_worker:'采集机器自动领取'};
  const dispatchReasons={participant_route_unavailable:'参与者任务通道暂不可用',participant_budget_unavailable:'参与者本轮剩余额度不足',participant_target_unavailable:'参与者任务暂不支持该目标',not_connected:'尚未连接云端',upgrade_or_access_required:'统一派发接口待升级或权限待核对'};
  const dispatchId=value=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
  const dispatchValid=value=>value?.available===true&&value.schema==='crowd-unified-dispatch-v1'&&Array.isArray(value.routes)&&typeof value.ready==='boolean';
  const section = node('section'); section.id = 'owner_tasks'; section.style.marginTop = '18px';
  $('runs').before(section);
  const dialog = node('dialog'); dialog.id = 'owner_dialog'; dialog.setAttribute('aria-labelledby','owner_title');
  dialog.innerHTML = `<div class="dialog-head"><h2 id="owner_title">新建多平台任务</h2><button type="button" id="owner_close">关闭</button></div>
  <form id="owner_form" class="dialog-body"><p class="hint">1. 采什么　2. 在哪采　3. 采多少</p><p id="owner_error" class="error" role="status"></p><button type="button" id="owner_reconcile" hidden>核对上次派发结果</button>
  <fieldset id="owner_request" style="border:0;padding:0"><label>采集方式<select id="owner_mode"><option value="search">搜索关键词</option><option value="detail">指定内容</option><option value="creator">指定博主作品</option><option value="homefeed">首页推荐内容</option><option value="trending">热门内容</option></select></label>
  <label>关键词、链接或博主名单<textarea id="owner_targets" required rows="4" placeholder="搜索关键词，每行一个"></textarea><small id="owner_target_help">搜索词共享给所选平台；链接会按所属平台分配。</small></label>
  <label>导入 CSV / 文本文件<input id="owner_file" type="file" accept=".csv,.txt,text/csv,text/plain"><small>CSV 格式为 platform,target。导入后先预览，不启动采集。</small></label>
  <fieldset style="border:0;padding:0"><legend>采集平台（可多选）</legend><div id="owner_platforms" class="choices"></div></fieldset>
  <div class="choices"><label><input id="owner_comments" type="checkbox">评论</label><label><input id="owner_replies" type="checkbox">二级回复</label><label><input id="owner_media" type="checkbox">媒体文件</label></div>
  <label><input id="owner_long_audio" type="checkbox"> B站只下载音轨，用于长视频转写（最长2小时，64MiB）</label>
  <label><input id="owner_transcript_only" type="checkbox"> 字幕优先文字稿（七平台）</label><small>先取平台字幕；无完整字幕时本地转写。B站取音轨；其他平台使用获准媒体，图片与文案不算听写。已配置Mac加速时优先使用，原有文件保留。</small>
  <label>所有平台合计内容数量配置<input id="owner_total" type="number" min="1" max="700" value="60"><small>按平台分配；机器搜索每平台至少20，参与者按预览配额。上游数量配置不保证严格的实体数上限。</small></label>
  <section id="owner_watch_options" hidden><label><input id="owner_continuous" type="checkbox"> 持续跟踪此博主名单</label><div class="grid"><label>间隔（分钟）<input id="owner_watch_interval" type="number" min="1" max="525600" value="720"></label><label>观察窗口（天）<input id="owner_watch_window" type="number" min="1" max="3650" value="3"></label><label>整个跟踪计划接口尝试总额<input id="owner_watch_budget" type="number" min="1" max="1000000" value="120"></label></div><p class="hint">总额跨周期保留，不每天清零；每轮沿用下方接口上限。观察最新作品，当前不保证平台端按日期完整筛选。</p></section><details><summary>更多选项</summary><div class="grid"><label><span id="owner_request_limit_label">所有平台合计接口尝试上限</span><input id="owner_requests" type="number" min="1" max="3500" value="60"></label><label>每篇评论数量配置<input id="owner_comment_limit" type="number" min="0" max="200" value="20"></label></div><p class="hint">自动复用工作台可用登录资料；首次登录需本人完成。浏览器资源请求不计入 Python 接口尝试。</p></details>
  <section id="owner_preview" class="notice" hidden></section></fieldset><div class="dialog-footer"><button type="button" id="owner_preview_button">预览分配</button><button id="owner_create" class="primary" disabled>按此分配开始</button></div></form>`;
  document.body.append(dialog);
  for (const [id, title] of Object.entries(platformNames)) {
    const label = node('label'), input = node('input'); input.type = 'checkbox'; input.value = id; input.checked = id === 'xhs';
    label.append(input, document.createTextNode(title)); $('owner_platforms').append(label);
  }
  function lockPending(){
    $('owner_request').disabled=Boolean(unresolvedKey)||busy;$('owner_preview_button').disabled=Boolean(unresolvedKey)||busy;
    $('owner_reconcile').hidden=!unresolvedKey;$('owner_reconcile').disabled=busy;
    $('owner_create').disabled=Boolean(unresolvedKey)||busy||!previewRequest||(unifiedMode&&!previewRequest?.interval_minutes&&preview?.ready!==true);
  }
  function rememberPending(key){const saved=localStorage.getItem(pendingDispatchKey);if(saved&&saved!==key){unresolvedKey=saved;lockPending();throw Error('prior_dispatch_outcome_unknown');}localStorage.setItem(pendingDispatchKey,key);unresolvedKey=key;lockPending();}
  function clearPending(){try{localStorage.removeItem(pendingDispatchKey);}catch(_){}unresolvedKey=null;}
  $('owner_reconcile').onclick=async()=>{
    if(busy||!unresolvedKey)return;busy=true;lockPending();
    try{const value=await unifiedCall('unified_dispatches',{idempotency_key:unresolvedKey});
      if(value.available!==true||value.schema!=='crowd-unified-dispatch-list-v1'||!Array.isArray(value.dispatches))throw Error('unified_dispatch_read_unavailable');
      const found=value.dispatches.find(row=>row.idempotency_key===unresolvedKey);
      if(!found||found.created!==true||!dispatchId(found.dispatch_id)){$('owner_error').textContent='尚未核对到上次派发结果；保留原编号，请稍后再核对。不会自动另建任务。';return;}
      clearPending();invalidate();dialog.close();message('原派发已在云端确认，编号 '+found.dispatch_id+'。');await reload();
    }catch(_error){$('owner_error').textContent='云端派发结果查询失败；原编号已保留，不会自动重建任务。';}
    finally{busy=false;lockPending();}
  };
  $('owner_close').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { generation++; $('new_task').focus(); });
  function invalidate() { preview=null; previewRequest=null; $('owner_preview').hidden=true; $('owner_create').disabled=true; generation++; }
  $('owner_form').addEventListener('input', invalidate);
  $('owner_form').addEventListener('change', invalidate);
  $('owner_long_audio').onchange=()=>{if($('owner_long_audio').checked)$('owner_media').checked=true;invalidate();};
  $('owner_transcript_only').onchange=()=>{if($('owner_transcript_only').checked){$('owner_media').checked=true;}invalidate();};
  $('owner_media').onchange=()=>{if(!$('owner_media').checked){$('owner_long_audio').checked=false;$('owner_transcript_only').checked=false;}invalidate();};
  $('owner_mode').onchange = () => {
    const mode=$('owner_mode').value, discovery=['homefeed','trending'].includes(mode);
    $('owner_watch_options').hidden=mode!=='creator'; if(mode!=='creator')$('owner_continuous').checked=false;
    $('owner_targets').required=!discovery; $('owner_targets').parentElement.hidden=discovery; $('owner_file').parentElement.hidden=discovery;
    $('owner_target_help').textContent=mode==='search'?'搜索词共享给所选平台；链接会按所属平台分配。':'链接按所属平台分配；裸ID请写平台代码,ID。';
    $('owner_targets').placeholder=mode==='search'?'搜索关键词，每行一个':'内容/博主链接，每行一个；裸ID请写成平台代码,ID';
    for(const input of $('owner_platforms').querySelectorAll('input')) { input.disabled=mode==='trending'&&input.value!=='bili'; if(input.disabled)input.checked=false; }
    if(![...$('owner_platforms').querySelectorAll('input:checked')].length) $('owner_platforms').querySelector('input:not(:disabled)').checked=true;
    if(discovery&&Number($('owner_total').value)>10)$('owner_total').value=2;
    invalidate();
  };
  $('owner_file').onchange = () => guarded(async () => {
    const file=$('owner_file').files[0]; if(!file)return;
    if(file.size>24000)throw Error('导入文件最多24KB。'); $('owner_targets').value=await file.text(); invalidate();
  });
  async function payload() {
    const p={idempotency_key:crypto.randomUUID(),platforms:[...$('owner_platforms').querySelectorAll('input:checked')].map(x=>x.value),mode:$('owner_mode').value,desired_items:Number($('owner_total').value),max_api_requests:Number($('owner_requests').value),max_comments:Number($('owner_comment_limit').value),comments:$('owner_comments').checked,replies:$('owner_replies').checked,media:$('owner_media').checked,purpose:$('purpose').value};
    if($('owner_long_audio').checked){if(!p.platforms.includes('bili'))throw Error('音轨采集需要选择B站。');p.media=true;p.platform_options_by_platform={bili:{long_audio:true}};}
    if($('owner_transcript_only').checked){if(!p.platforms.length||p.platforms.some(platform=>!['bili','dy','ks','wb','xhs','zhihu','tieba'].includes(platform)))throw Error('请选择支持的平台。');p.media=true;p.platform_options_by_platform=p.platform_options_by_platform||{};for(const platform of p.platforms)p.platform_options_by_platform[platform]={...(p.platform_options_by_platform[platform]||{}),transcript_only:true,...(platform==='bili'?{long_audio:true}:{})};}
    if($('authorization_ref').value.trim())p.authorization_ref=$('authorization_ref').value.trim();
    if(p.mode==='search')p.targets=$('owner_targets').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
    else if(!['homefeed','trending'].includes(p.mode)) {const parsed=await call('parse_batch',{text:$('owner_targets').value,mode:p.mode});if(parsed.errors?.length)throw Error(parsed.errors.map(x=>'第'+(x.line||x.row||'?')+'行：'+(x.error||x.reason||'格式错误')).join('；'));p.targets_by_platform=parsed.targets_by_platform;}
    if(p.mode==='creator'&&$('owner_continuous').checked){p.per_cycle_items=p.desired_items;p.per_cycle_requests=p.max_api_requests;delete p.desired_items;delete p.max_api_requests;delete p.mode;p.interval_minutes=Number($('owner_watch_interval').value);p.window_days=Number($('owner_watch_window').value);p.total_request_budget=Number($('owner_watch_budget').value);}
    return p;
  }
  $('owner_preview_button').onclick = async () => {
    if(unresolvedKey||busy)return;preview=null;previewRequest=null;$('owner_create').disabled=true;const ticket=++generation; $('owner_error').textContent=''; $('owner_preview_button').disabled=true;
    try { const p=await payload(), value=p.interval_minutes?await api('/api/watchlists',{action:'preview',payload:p}):unifiedMode?await unifiedCall('unified_preview',p):await call('preview',p);if(unifiedMode&&!p.interval_minutes&&!dispatchValid(value))throw Error(dispatchReasons[value.reason]||'统一派发预览不可用，尚未创建任务。');if(ticket!==generation||!dialog.open)return;preview=value;previewRequest=p;const box=$('owner_preview');box.replaceChildren(node('strong','本次分配'));const children=value.routes||value.children||value.allocations||value.platforms||[];
      for(const c of children)box.append(node('p',(platformNames[c.platform]||c.platform)+(c.execution_kind?' · '+(routeNames[c.execution_kind]||'分配方式待核对'):'')+' · 内容配置 '+(c.item_quota??c.max_items??c.desired_items??c.budget?.max_items??'见摘要')+' · '+(dispatchReasons[c.reason_code]||reasons[c.local_stop_reason||c.local_failure_reason||c.reason_code||c.reason]||names[c.state]||c.reason_code||c.reason||'可执行')));
      if(value.schema==='crowd-unified-dispatch-v1'&&children.some(c=>c.execution_kind==='participant_extension'))box.append(node('p','参与者接口频控与预算由本轮试验策略控制；上方接口尝试上限仅用于机器采集。'));
      if(value.watchlist){const w=value.watchlist;box.append(node('p','每 '+w.interval_minutes+' 分钟观察一次 · 每轮内容配置 '+w.per_cycle_items+' · 每轮接口上限 '+w.per_cycle_requests),node('p','整个计划接口总额 '+w.total_request_budget+' · 观察窗口 '+w.window_days+' 天'));for(const id of w.platforms||[])box.append(node('p',(platformNames[id]||id)+' · '+((w.blocked_platforms||[]).find(c=>c.platform===id)?'需要处理：'+(reasons[(w.blocked_platforms||[]).find(c=>c.platform===id).reason_code]||(w.blocked_platforms||[]).find(c=>c.platform===id).reason_code):'按本平台博主名单分配')));box.append(node('p','按最新作品持续观察，保留历史版本；当前不保证平台端完整按日期筛选。'));}else if(!children.length)box.append(node('p','没有可分配的平台，请核对目标与平台。'));box.append(node('p',value.schema==='crowd-unified-dispatch-v1'?(value.ready?'由云端保存统一派发，终端按能力自动领取。预览未启动采集。':dispatchReasons[value.reason]||'本次尚不可派发，请处理后重新预览。'):'不可执行的平台保留状态，其余平台按预览运行。不会扩大总接口额度。'));box.hidden=false;$('owner_create').disabled=value.schema==='crowd-unified-dispatch-v1'&&value.ready!==true;
    }catch(e){$('owner_error').textContent=errorNames[e.message]||e.message;}finally{$('owner_preview_button').disabled=false;}
  };
  $('owner_form').onsubmit = async event => {
    event.preventDefault();if(busy||unresolvedKey||!previewRequest||unifiedMode&&!previewRequest.interval_minutes&&preview?.ready!==true)return;
    const ticket=generation,request=previewRequest;busy=true;lockPending();
    if(!request.idempotency_key)request.idempotency_key=crypto.randomUUID();
    try {
      if(request.interval_minutes)await api('/api/watchlists',{action:'create',payload:request});
      else if(unifiedMode){
        // Keep the original operation identity across dialog close/reload; unknown writes are read back, never replaced.
        rememberPending(request.idempotency_key);
        const value=await unifiedCall('unified_create',request);
        if(!dispatchValid(value))throw Error('cloud_outcome_unknown');
        if(value.created===false&&value.ready===false){clearPending();preview=null;throw Error(dispatchReasons[value.reason]||'本次未派发，请重新预览。');}
        if(value.created!==true||!dispatchId(value.dispatch_id))throw Error('cloud_outcome_unknown');
        clearPending();
      }else await call('create',request);
      if(ticket===generation&&dialog.open){dialog.close();message('任务已保存，系统自动分配；需要登录时显示具体平台。');}await reload();await refresh();
    }catch(e){if(ticket===generation&&dialog.open)$('owner_error').textContent=unresolvedKey?'派发结果尚未核对。原编号已保留，请点“核对上次派发结果”，不会自动另建任务。':errorNames[e.message]||e.message;}
    finally{busy=false;lockPending();}
  };
  async function open(){
    if(busy)return;
    try{const value=await unifiedCall('status');unifiedMode=value.storage_scope==='cloud';}
    catch(_error){message('无法核对云端连接，请稍后重试；尚未创建任务。');return;}
    $('owner_request_limit_label').textContent=unifiedMode?'机器接口尝试上限（参与者沿用本轮试验频控与预算）':'所有平台合计接口尝试上限';
    try{unresolvedKey=localStorage.getItem(pendingDispatchKey);}catch(_error){unresolvedKey=null;}
    if(!configured&&!unifiedMode&&!unresolvedKey){openDialog('settings_dialog');return;}
    invalidate();$('owner_error').textContent=unresolvedKey?'上次派发结果尚未核对，保留原编号；先核对云端结果。':'';
    dialog.showModal();lockPending();if(!unresolvedKey)$('owner_targets').focus();
  }
  function render() {
    const focused=document.activeElement?.closest('#owner_tasks')?document.activeElement:null, key=focused?.dataset.taskKey;
    section.replaceChildren();const shownWatches=filter==='attention'?watches.filter(w=>['waiting','failed','paused','blocked','budget_exhausted','interrupted_unknown'].includes(w.state)):watches;for(const watch of shownWatches){const card=node('article');card.className='task';card.style.marginBottom='12px';card.append(node('h3',watch.title||'博主持续跟踪'),node('p','已观察 '+watch.cycle_count+' 轮 · 剩余接口总额 '+watch.request_budget_remaining+' · '+(names[watch.state]||watch.state)));if(watch.reason_code)card.append(node('p',reasons[watch.reason_code]||watch.reason_code));if(watch.next_due_at)card.append(node('small','下一轮计划 '+dateText(watch.next_due_at)));const actions=node('div');actions.className='actions';for(const [action,text]of [['stop','暂停跟踪'],['resume','继续跟踪']])actions.append(button(text,async()=>{await api('/api/watchlists',{action,payload:{watch_id:watch.watch_id}});await reload();}));card.append(actions);section.append(card);} const shown=filter==='attention'?items.filter(x=>['waiting','failed','partial','unknown','interrupted_unknown','delivery_pending'].includes(x.state)):items;
    for(const task of shown){const card=node('article');card.className='task';card.style.marginBottom='12px';const title=(task.display_title||task.title||task.request?.title||'多平台 '+(modeNames[task.mode||task.request?.mode]||'采集'));
      const head=node('div');head.className='task-heading';head.append(node('h3',title),node('span',names[task.state]||'状态待核对'));head.lastChild.className='pill';card.append(head);
      for(const c of task.children||[]){const row=node('p');row.append(node('strong',(platformNames[c.platform]||c.platform)+'：'),node('span',(names[c.state]||labels[c.state]||'状态待核对')+' '+(reasons[c.local_stop_reason||c.local_failure_reason||c.reason_code||c.reason]||((c.local_stop_reason||c.local_failure_reason||c.reason_code||c.reason)?'原因待核对，见分配与预算详情。':''))));
        if(task.storage_scope==='cloud'&&c.state==='waiting'&&c.reason_code==='login_required'){
          const recover=button('核验原账号以恢复此任务',async()=>{recover.disabled=true;try{
            const result=await api('/api/accounts',{action:'recover_cloud_login',payload:{task_id:task.task_id,child_id:c.child_id}});
            message(result.owner_continue_required?'已打开原账号核验；核验通过后请点继续，任务只使用剩余额度。':'已打开原账号核验；核验通过后按原运行意图自动接续，只使用剩余额度。');await reload();
          }catch(error){message(error.message);}finally{recover.disabled=false;}});row.append(recover);
        }
        if(!c.light_transcript)for(const saved of c.video_text_jobs||[])row.append(button(saved.state==='completed'?'查看画面文字（非听写）':'查看画面文字处理进度',()=>guarded(()=>mediaView.openSaved(saved.run_id,saved.job_id))));
        if(c.light_transcript){const light=c.light_transcript;const visual=light.visual_jobs||[];for(const saved of visual)row.append(button(saved.state==='completed'?'查看画面文字（非听写）':'查看画面文字处理进度',()=>guarded(()=>mediaView.openSaved(light.run_id,saved.job_id))));if(!visual.some(job=>['completed','queued','running','interrupted_unknown'].includes(job.state))){const source=(light.fallback_assets||[]).flatMap(a=>a.audio_attempt_chain||[a]).find(a=>a.job_id&&['complete_audio_codec_not_supported','complete_audio_stream_missing'].includes(a.reason));if(source)row.append(button(visual.length?'重新提取画面文字（非听写）':'提取画面文字（非听写）',()=>guarded(()=>visual.length?mediaView.retryVideoOCR(visual[0]):mediaView.openVideoOCR(light.run_id,source.job_id))));}const fallbackPhase=light.fallback_assets?.[0]?.phase;row.append(node('small',' · 轻量文字稿：'+(visual.some(job=>job.state==='completed')?'画面文字稿已保存（非听写）':light.state==='processing'&&['waiting_audio','dispatching_audio','audio_processing'].includes(fallbackPhase)?'字幕不可用，正在取得完整音轨':light.state==='needs_attention'&&light.reason==='native_video_over_collection_limit'?'视频超出采集限额，文字稿未生成':({waiting:'已排队',processing:'本机转写中',completed:'文字稿已保存，语义待校对',needs_attention:'需要处理，文字稿尚未完成',audio_unavailable:'本次未取得字幕或可转写音轨'}[light.state]||'状态待核对'))));for(const saved of [...(light.subtitle_jobs||[]),...(light.assets||[]),...(light.fallback_assets||[])])if(saved.job_id&&saved.state==='completed')row.append(button('查看已保存文字稿',()=>guarded(()=>mediaView.openSaved(saved.asr_run_id||light.run_id,saved.job_id))));}
        if(task.storage_scope==='cloud')row.append(node('small',' · 云端已收 '+(c.received_captures||0)+' 份（正文 '+(c.contents||0)+' / 评论 '+(c.comments||0)+'）'));for(const runId of (task.storage_scope==='cloud'?[c.local_run_id].filter(Boolean):c.runs||[c.active_run_id].filter(Boolean))){const run=runs.find(r=>idOf(r)===runId)||{run_id:runId,platform:c.platform,state:'interrupted_unknown'};const b=button('查看结果',()=>show(run));if(mediaNotice(run))row.append(node('small',' · '+mediaNotice(run)));b.disabled=!terminal.has(run.state);row.append(b);}if(task.storage_scope==='cloud'&&c.platform==='bili'&&c.supplemental_available===true&&c.state==='failed'&&task.mode==='detail'&&c.request_quota>c.requests_spent&&c.local_run_id){const retry=button('补采评论与长音轨（仅剩余额度）',async()=>{retry.disabled=true;const dimensions=['comments','media'];try{await call('retry_supplemental',{task_id:task.task_id,child_id:c.child_id,expected_revision:task.revision,idempotency_key:'supplement-'+task.task_id+'-'+c.child_id+'-'+task.revision,dimensions,long_audio:true});message('补采已保存；只使用原目标与剩余额度，需要登录时会提示。');await reload();}catch(error){message(error.message);}finally{retry.disabled=false;}});row.append(retry);}card.append(row);}
      const actions=node('div');actions.className='actions';for(const [name,text]of [['stop','停止任务'],['resume','继续未启动平台']]){const b=button(text,async()=>{b.disabled=true;try{await call(name,{task_id:task.task_id});await reload();}finally{b.disabled=false;}});b.dataset.taskKey=task.task_id+':'+name;b.disabled=name==='stop'?['stopped','completed'].includes(task.state):!['waiting','paused','stopped','partial','failed'].includes(task.state);actions.append(b);}card.append(actions);if(task.storage_scope==='cloud')actions.append(button('查看云端结果与回执',()=>guarded(()=>receipts(task))));const diagnostic=node('details');diagnostic.append(node('summary','分配与预算详情'),node('pre',JSON.stringify(task,null,2)));card.append(diagnostic);section.append(card);
    }
    if(key)[...section.querySelectorAll('button')].find(b=>b.dataset.taskKey===key)?.focus({preventScroll:true});
    renderRuns();
  }
  async function reload(){if(listPromise)return listPromise;listPromise=(async()=>{const [value,watchValue]=await Promise.all([call('list'),api('/api/watchlists',{action:'list',payload:{}})]);items=Array.isArray(value)?value:value.tasks||[];watches=watchValue.watchlists||watchValue.watches||[];groupedRunIds=new Set(items.flatMap(t=>(t.children||[]).flatMap(c=>t.storage_scope==='cloud'?[c.local_run_id].filter(Boolean):c.runs||[c.active_run_id].filter(Boolean))));ownerTaskCounts={all:items.length+watches.length,attention:items.filter(t=>['waiting','failed','partial','unknown','interrupted_unknown','delivery_pending'].includes(t.state)).length+watches.filter(w=>['waiting','failed','paused','blocked','budget_exhausted','interrupted_unknown'].includes(w.state)).length};render();})().finally(()=>listPromise=null);return listPromise;}
  $('new_task').onclick=open;
  for(const name of ['all','attention'])$('filter_'+name).addEventListener('click',()=>render());
  $('refresh').addEventListener('click',()=>guarded(reload));
  const advanced=button('单平台高级采集',()=>openDialog('create_dialog'));$('capability_details').append(advanced);
  // Legacy empty-state and refresh use the same primary create flow.
  const observer=new MutationObserver(()=>{for(const b of $('runs').querySelectorAll('.empty button'))if(b.textContent==='新建任务')b.onclick=open;const empty=$('runs').querySelector('.empty');if(empty)empty.hidden=items.length+watches.length>0;});observer.observe($('runs'),{childList:true});
  guarded(reload);setInterval(()=>{if(!document.hidden)guarded(reload);},5000);
  return {reload,open};
})();
