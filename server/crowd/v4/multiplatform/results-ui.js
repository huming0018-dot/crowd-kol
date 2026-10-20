'use strict';
const resultsView = (() => {
  const call=(action,payload={})=>api('/api/results',{action,payload});
  function entryText(record){const names={search:'关键词搜索',detail:'指定详情',creator:'作者内容',homefeed:'首页推荐页面采样',trending:'热门页面采样'};return Object.hasOwn(names,record.discovery_kind)?names[record.discovery_kind]:'未记录（unknown）';}
  const sourceNames={xiaohongshu:'小红书',douyin:'抖音',kuaishou:'快手',bilibili:'B站',weibo:'微博',tieba:'百度贴吧',zhihu:'知乎'},recordNames={content:'正文',comment:'评论',dynamic:'动态',author:'作者资料',media:'媒体'};
  const launch=button('资料库',()=>open());$('open_settings').before(launch);
  const dialog=node('dialog');dialog.id='library_dialog';dialog.style.width='min(920px,calc(100% - 28px))';dialog.setAttribute('aria-labelledby','library_title');
  dialog.innerHTML=`<div class="dialog-head"><h2 id="library_title">已保存资料</h2><button type="button" id="library_close">关闭</button></div><div class="dialog-body"><p class="hint">保存已采结果、比较正文版本、评价和导出；不重新访问平台。</p><p id="library_error" class="error" role="status"></p><div class="grid"><label>平台<select id="library_platform"><option value="">全部平台</option></select></label><label>业务标签<input id="library_tag" type="text" maxlength="80" placeholder="按已保存标签筛选"></label></div><details><summary>作者、发布时间与记录类型</summary><div class="grid"><label>作者标识<input id="library_author" type="text" maxlength="200" placeholder="原平台ID或明确标注的匿名ID"></label><label>记录类型<select id="library_kind"><option value="">全部记录</option><option value="content">正文</option><option value="comment">评论</option><option value="dynamic">动态</option><option value="author">作者资料</option><option value="media">媒体</option></select></label><label>发布时间从<input id="library_after" type="datetime-local"></label><label>发布时间至<input id="library_before" type="datetime-local"></label></div></details><div class="actions"><button id="library_search" class="primary">查询</button><select id="library_format" aria-label="导出格式"><option value="json">JSON</option><option value="jsonl">JSONL</option><option value="csv">CSV</option><option value="xlsx">Excel</option></select><button id="library_export">导出当前筛选结果</button></div><p id="library_summary" class="hint"></p><div id="library_records"></div><div class="actions"><button id="library_previous">上一页</button><button id="library_next">下一页</button></div></div>`;
  document.body.append(dialog);for(const [id,title]of Object.entries(platformNames))$('library_platform').append(new Option(title,id));
  const domainLink=node('a','查看领域发现');domainLink.href='/data-product';domainLink.target='_blank';domainLink.rel='noopener';
  const domainExports=node('details');domainExports.append(node('summary','导出领域发现'),node('p','导出当前已审领域发布快照；未核事实和候选状态保留。'));
  for(const [format,path]of [['JSON','report.json'],['JSONL','items.jsonl'],['CSV','items.csv']]){const link=node('a',format);link.href='/data-product/'+path;link.download='data-product.'+format.toLowerCase();domainExports.append(link,document.createTextNode(' '));}
  dialog.querySelector('#library_export').after(domainLink,domainExports);
  // Explicit Owner action; the bearer URL exists only in this dialog's memory until expiry/close.
  function attachPublicationShare(parent, ownerDialog, selectedSource=null) {
    const generate=node('button','生成15分钟查看链接'),copy=node('button','复制查看链接'),status=node('p',selectedSource?'请选择已处理批次；点击才保存和签发。':'仅分享当前领域发现快照；点击才签发，持有人15分钟内免登录查看。不会自动续签。');
    generate.type=copy.type='button';copy.disabled=true;status.setAttribute('role','status');
    parent.append(generate,copy,status);
    const verify=node('button','核对云保存');verify.type='button';verify.hidden=true;if(selectedSource)parent.append(verify,node('p','点击会把所选批次的正文、来源引用和跟踪编号保存到本项目私有云，并签发15分钟链接。持有人可免登录查看和下载；不含媒体文件。'));
    let epoch=0,link=null,timer=null;const saved=new Map(),unknown=new Map();
    const current=()=>selectedSource?selectedSource():null;
    const clear=()=>{++epoch;link=null;clearTimeout(timer);copy.disabled=true;generate.disabled=Boolean(unknown.get(current()?.pro_key));verify.hidden=!unknown.get(current()?.pro_key);verify.disabled=false;};
    const validSaved=(value,scope)=>value?.schema==='crowd-owner-pro-publication-v1'&&value.status==='verified'&&value.verified===true&&value.pro_key===scope.pro_key&&value.items===scope.items&&value.media_bytes_included===false&&/^confirmed-pro-[a-f0-9]{24}$/.test(value.project_id)&&/^[a-f0-9]{64}$/.test(value.report_hash)&&Object.keys(value.formats||{}).sort().join(',')==='csv,html,json,jsonl';
    const request=(scope,operation)=>api('/api/cloud',{action:'publication_share',payload:{request_id:crypto.randomUUID(),pro_key:scope.pro_key,operation}});
    const still=(ticket,scope)=>ticket===epoch&&ownerDialog.open&&(!selectedSource||current()?.pro_key===scope?.pro_key);
    ownerDialog.addEventListener('close',()=>{clear();status.textContent='链接已从本页清除。此前复制的链接仍到原有效期结束。';});
    generate.onclick=async()=>{
      if(generate.disabled||!ownerDialog.open)return;
      const scope=current();if(selectedSource&&!scope){status.textContent='暂无可分享的已处理批次。';return;}
      clear();generate.disabled=true;const ticket=epoch;let operation='links';
      status.textContent='正在生成；结果未知时不会自动重发。';
      try {
        let snapshot=scope?saved.get(scope.pro_key):null;
        if(scope&&!snapshot){
          operation='publish';snapshot=await request(scope,operation);
          if(!validSaved(snapshot,scope))throw Error('publication_share_invalid_response');
          saved.set(scope.pro_key,snapshot);
          if(!still(ticket,scope))return;
        }
        operation='links';
        const value=scope?await request(scope,operation):await api('/api/cloud',{action:'publication_share',payload:{request_id:crypto.randomUUID()}});
        if(!still(ticket,scope))return;
        if(value.schema!=='crowd-owner-publication-share-v1'||typeof value.page_url!=='string'||!value.page_url.startsWith('https://app-lyart-eta-22.vercel.app/materials#publication=')||!value.page_url.match(/#publication=[A-Za-z0-9_-]+$/)||!Number.isFinite(Date.parse(value.expires_at))||Date.parse(value.expires_at)<=Date.now()||(scope&&(value.report_hash!==snapshot.report_hash||value.project_id!==snapshot.project_id)))throw Error('publication_share_invalid_response');
        link={url:value.page_url,expires:Date.parse(value.expires_at)};copy.disabled=false;
        status.textContent='链接已生成，有效期至 '+new Date(link.expires).toLocaleString()+'。点击复制后可发给接收者；原未知项保留。';
        timer=setTimeout(()=>{if(ticket===epoch){link=null;copy.disabled=true;status.textContent='链接已到期，已从本页清除；不会自动续签。';}},Math.max(0,link.expires-Date.now()));
      }catch(error){
        if(scope&&operation==='publish'&&(!error.message||error.message.includes('unknown')||error.message==='publication_share_invalid_response'||error instanceof TypeError))unknown.set(scope.pro_key,true);
        if(still(ticket,scope)){
          if(scope&&unknown.get(scope.pro_key)){verify.hidden=false;status.textContent='云保存结果未确认。先点“核对云保存”，只读取核对，不重新上传。';}
          else status.textContent='生成未确认，请先核对结果。不会自动重试；关闭后重新打开可显式准备新一次操作。';
        }
      }
    };
    verify.onclick=async()=>{
      const scope=current();if(!scope||verify.disabled||!ownerDialog.open)return;
      clear();verify.disabled=true;generate.disabled=true;const ticket=epoch;status.textContent='只读核对云保存，不重新上传。';
      try{
        const value=await request(scope,'verify');if(!validSaved(value,scope))throw Error('publication_share_invalid_response');
        saved.set(scope.pro_key,value);unknown.delete(scope.pro_key);
        if(still(ticket,scope)){verify.hidden=true;generate.disabled=false;status.textContent='四格式云保存已核对。现在可点击生成查看链接。';}
      }catch{if(still(ticket,scope))status.textContent='云保存仍未确认，未重新上传或签发链接。';}
      finally{if(still(ticket,scope))verify.disabled=false;}
    };
    copy.onclick=async()=>{
      const ticket=epoch,value=link;
      if(!value||copy.disabled||!ownerDialog.open||value.expires<=Date.now()){link=null;copy.disabled=true;return;}
      try{await navigator.clipboard.writeText(value.url);if(ticket===epoch&&ownerDialog.open)status.textContent='查看链接已复制，请仅发给需要查看的人。';}
      catch{if(ticket===epoch&&ownerDialog.open)status.textContent='浏览器未允许复制；链接未重新生成。请允许本页使用剪贴板后再点复制。';}
    };
    return {selectionChanged(){clear();status.textContent='已切换批次。点击才保存和签发；原链接仍到原有效期结束。';}};
  }
  attachPublicationShare(domainExports,dialog);

  const materialLink=node('a','查看当前已审素材');materialLink.href='/materials';materialLink.target='_blank';materialLink.rel='noopener';
  const materialExports=node('details');materialExports.append(node('summary','导出当前已审素材'),node('p','导出当前发布批次的全部已审素材。'));
  for(const [format,path]of [['JSON','report.json'],['JSONL','materials.jsonl'],['CSV','materials.csv']]){const link=node('a',format);link.href='/materials/'+path;link.download='materials.'+format.toLowerCase();materialExports.append(link,document.createTextNode(' '));}
  const participantMaterialLink=node('a','查看参与者自动处理素材');participantMaterialLink.href='/materials/participants';participantMaterialLink.target='_blank';participantMaterialLink.rel='noopener';
  function attachMaterialFeedback(parent,ownerDialog,selectedSource){
    const panel=node('details');panel.append(node('summary','提交素材反馈'),node('p','反馈由Owner服务（central_owner_service；human_uid:null）保存到原授权私有反馈空间，保留真实素材项目、回执与知识包。待处理反馈不等于真人审核、知识发布或评分；不重新采集。'));
    const items=node('select'),kind=node('select'),reason=node('textarea'),quote=node('textarea'),experienced=node('input'),consent=node('input'),status=node('p'),history=node('ul');
    items.setAttribute('aria-label','反馈哪条素材');kind.setAttribute('aria-label','反馈类型');reason.setAttribute('aria-label','反馈理由');quote.setAttribute('aria-label','原文引用（可选，必须与原文一致）');reason.maxLength=quote.maxLength=2000;experienced.type=consent.type='checkbox';
    for(const [value,label]of [['preference','偏好'],['ignore','不感兴趣'],['want_to_know','进一步了解'],['experienced','已体验（需本人明确确认）']])kind.append(new Option(label,value));
    const experienceLabel=node('label','我确认这条“已体验”描述确实发生（否则不要勾选）'),consentLabel=node('label','明确提交并仅在原私有反馈空间保存');experienceLabel.prepend(experienced);consentLabel.prepend(consent);
    let ticket=0,view=null,busy=false;
    const savedKey=key=>'crowd:material-feedback:'+key;
    const call=(action,payload)=>api('/api/cloud',{action,payload});
    function saved(key){try{return localStorage.getItem(savedKey(key));}catch{return null;}}
    const submit=button('提交待处理反馈',async()=>{
      const scope=selectedSource(),v=view,version=ticket,item=v?.items.find(i=>i.request===items.value);if(!scope||!v||!item||busy||submit.disabled||saved(scope.pro_key))return;
      if(!reason.value.trim()||!consent.checked||(kind.value==='experienced'&&!experienced.checked)||(quote.value&&!item.body.includes(quote.value))){status.textContent='请填写理由、明确私有保存同意，并核对原文引用；已体验需单独确认。未提交。';return;}
      const id=crypto.randomUUID();try{localStorage.setItem(savedKey(scope.pro_key),id);}catch{status.textContent='无法保存原请求，未提交。';return;}
      busy=true;submit.disabled=true;status.textContent='已保存原请求，正在提交；不会自动重发。';
      try{const r=await call('material_feedback_submit',{intent_id:id,pro_key:scope.pro_key,expected_job:v.expected_job,request:item.request,record_hash:item.record_hash,kind:kind.value,reason:reason.value,quote:quote.value,experience_confirmed:experienced.checked,consent_private:consent.checked});
        if(r.intent_id&&r.intent_id!==id)localStorage.setItem(savedKey(scope.pro_key),r.intent_id);
        if(r.state==='not_submitted'){localStorage.removeItem(savedKey(scope.pro_key));if(version===ticket&&ownerDialog.open){status.textContent='本次未提交，请刷新素材与反馈前置；原反馈保持。';submit.disabled=false;}return;}
        if(version!==ticket||!ownerDialog.open)return;status.textContent=r.state==='pending_feedback'?'反馈已入库，待后续处理；未审核、发布或改分。原ID：'+id:'结果待核对，保留原ID，不自动重发。';
      }catch{if(version===ticket&&ownerDialog.open)status.textContent='结果待核对；请查询原ID，不要换ID重发。';}
      finally{if(version===ticket)busy=false;}
    });
    const check=button('查询原反馈',async()=>{
      const scope=selectedSource(),version=ticket;if(!scope||busy)return;const id=saved(scope.pro_key)||view?.feedback?.find(r=>r.state==='outcome_unknown')?.intent_id;if(!id)return;
      busy=true;try{const r=await call('material_feedback_status',{intent_id:id});if(version!==ticket||!ownerDialog.open)return;status.textContent='原反馈 '+id+'：'+r.state+'；未审核/发布。';if(r.state==='pending_feedback'){localStorage.removeItem(savedKey(scope.pro_key));await load();}}
      catch{if(version===ticket&&ownerDialog.open)status.textContent='原反馈尚待核对，不自动重发。';}finally{if(version===ticket)busy=false;}
    });
    async function load(){
      const version=++ticket,scope=selectedSource();view=null;busy=false;items.replaceChildren();history.replaceChildren();submit.disabled=true;reason.value=quote.value='';experienced.checked=consent.checked=false;if(!scope)return;
      try{const r=await call('material_feedback_preview',{pro_key:scope.pro_key});if(version!==ticket||!ownerDialog.open)return;if(r.state!=='feedback_preview'||r.pro_key!==scope.pro_key||!Array.isArray(r.items)||!Array.isArray(r.feedback))throw Error('invalid_preview');view=r;
        for(const item of r.items)items.append(new Option(item.title||item.request,item.request));
        for(const row of r.feedback)history.append(node('li',row.intent_id+' · '+row.kind+' · '+row.state+' · 未审核'));
        submit.disabled=!r.items.length||!!saved(scope.pro_key)||r.feedback.some(row=>row.state==='outcome_unknown');status.textContent=submit.disabled?'有原请求待核对，禁止换ID提交。':'请选择素材并填写反馈；点击才提交，未发起体验不会记为已体验。';
      }catch{if(version===ticket&&ownerDialog.open)status.textContent='反馈前置未接通，未提交。';}
    }
    panel.append(items,kind,reason,quote,experienceLabel,consentLabel,submit,check,button('刷新反馈记录',()=>load()),status,history);parent.append(panel);ownerDialog.addEventListener('close',()=>{ticket++;view=null;busy=false;});
    return {selectionChanged:load};
  }
  const participantShare=node('details');participantShare.append(node('summary','分享参与者素材'));
  const scopeSelect=node('select');scopeSelect.setAttribute('aria-label','分享哪批参与者素材');participantShare.append(scopeSelect);
  let shareScopes=new Map(),shareGeneration=0;
  const proShare=attachPublicationShare(participantShare,dialog,()=>shareScopes.get(scopeSelect.value)||null);
  const materialFeedback=attachMaterialFeedback(participantShare,dialog,()=>shareScopes.get(scopeSelect.value)||null);
  scopeSelect.onchange=()=>{proShare.selectionChanged();void materialFeedback.selectionChanged();};
  dialog.addEventListener('close',()=>{shareGeneration++;});
  async function loadShareScopes(){
    const ticket=++shareGeneration;shareScopes=new Map();scopeSelect.replaceChildren(new Option('正在读取已处理批次',''));proShare.selectionChanged();
    try{
      const response=await fetch('/materials/participants.json',{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error('publication_index_unavailable');
      const value=await response.json();if(ticket!==shareGeneration||!dialog.open)return;
      if(!Array.isArray(value.publications)||value.publications.length>2000)throw Error('publication_index_unavailable');
      for(const item of value.publications){
        const match=typeof item.url==='string'&&item.url.match(/^\/materials\/pro\/(pro-[a-f0-9]{64})$/);
        if(item.state==='ready'&&match&&Number.isSafeInteger(item.items)&&item.items>0&&Number.isSafeInteger(item.task_id))shareScopes.set(match[1],{pro_key:match[1],items:item.items,task_id:item.task_id});
      }
      scopeSelect.replaceChildren();for(const scope of shareScopes.values())scopeSelect.append(new Option('任务 '+scope.task_id+' · '+scope.items+' 条',scope.pro_key));
      if(!shareScopes.size)scopeSelect.append(new Option('暂无已处理批次',''));
    }catch{if(ticket===shareGeneration&&dialog.open)scopeSelect.replaceChildren(new Option('批次读取失败，请重新打开资料库',''));}
    if(ticket===shareGeneration&&dialog.open){proShare.selectionChanged();void materialFeedback.selectionChanged();}
  }
  const recompute=node('details');recompute.append(node('summary','同一批回执重新处理与版本选择'),node('p','只读取原ACK；可按当前处理器重建，或选择本知识作用域已发布的同类包。不自动审核、采集或切换云端发布。'));
  const releaseSelect=node('select'),versionSelect=node('select'),recomputeStatus=node('p');releaseSelect.setAttribute('aria-label','已发布知识版本');versionSelect.setAttribute('aria-label','已处理素材版本');
  let materialView=null,materialTicket=0;const materialCall=(action,payload)=>api('/api/cloud',{action,payload});
  const pendingKey=key=>'crowd:material-recompute:'+key;
  const pending=key=>{try{return localStorage.getItem(pendingKey(key));}catch{return null;}};
  const create=button('按选中版本重新处理',()=>submitRecompute('release'));
  const engineCreate=button('按当前处理器重建',()=>submitRecompute('current_engine'));
  async function submitRecompute(mode){
    const scope=shareScopes.get(scopeSelect.value),view=materialView;if(!scope||!view||pending(scope.pro_key)||(mode==='current_engine'?view.current_engine?.available!==true:!releaseSelect.value))return;
    const ticket=materialTicket,id=crypto.randomUUID();try{localStorage.setItem(pendingKey(scope.pro_key),id);}catch{recomputeStatus.textContent='无法保存原请求，请先恢复本地存储；未提交。';return;}
    create.disabled=engineCreate.disabled=true;recomputeStatus.textContent='已保留原请求，等待处理；旧四格式仍可读。';
    try{const result=await materialCall('material_recompute',{request_id:id,pro_key:scope.pro_key,expected_job:view.current_job,...(mode==='current_engine'?{mode}:{release:JSON.parse(releaseSelect.value)})});if(result.state==='not_submitted'){localStorage.removeItem(pendingKey(scope.pro_key));if(ticket===materialTicket&&dialog.open){recomputeStatus.textContent='本次未排队，请刷新版本记录；原产物保留。';create.disabled=!view.releases?.length;engineCreate.disabled=view.current_engine?.available!==true;}return;}if(ticket===materialTicket&&dialog.open)recomputeStatus.textContent='已排入原处理队列；请核对原请求，不会自动切换版本。';}
    catch{if(ticket===materialTicket&&dialog.open)recomputeStatus.textContent='结果待核对；保留原请求，不自动重发。';}
  }
  const check=button('核对原重算请求',async()=>{
    const scope=shareScopes.get(scopeSelect.value);if(!scope)return;const id=pending(scope.pro_key),ticket=materialTicket;if(!id)return;
    try{const value=await materialCall('material_recompute_status',{request_id:id});if(ticket!==materialTicket||!dialog.open)return;recomputeStatus.textContent='原请求状态：'+value.state;
      if(value.state==='ready'){localStorage.removeItem(pendingKey(scope.pro_key));await loadMaterialVersions();}
    }catch{if(ticket===materialTicket&&dialog.open)recomputeStatus.textContent='核对尚不可用；原请求保留。';}
  });
  const select=button('选择此素材版本（或切回旧版）',async()=>{
    if(select.disabled)return;
    const scope=shareScopes.get(scopeSelect.value),view=materialView,ticket=materialTicket;if(!scope||!view||!versionSelect.value)return;select.disabled=true;
    try{await materialCall('material_select_version',{pro_key:scope.pro_key,expected_job:view.current_job,job_id:versionSelect.value});if(ticket!==materialTicket||!dialog.open)return;recomputeStatus.textContent='素材版本已选择；knowledge pin和云端发布保持不变。';await loadMaterialVersions();}
    catch{if(ticket===materialTicket&&dialog.open)recomputeStatus.textContent='选择结果待核对，请刷新版本记录；不自动再发。';}
  });
  const versionLinks=node('div');
  async function loadMaterialVersions(){
    const ticket=++materialTicket,scope=shareScopes.get(scopeSelect.value);materialView=null;releaseSelect.replaceChildren();versionSelect.replaceChildren();versionLinks.replaceChildren();create.disabled=engineCreate.disabled=select.disabled=true;if(!scope)return;
    try{const value=await materialCall('material_versions',{pro_key:scope.pro_key});if(ticket!==materialTicket||!dialog.open)return;
      materialView=value;for(const r of value.releases||[])releaseSelect.append(new Option(r.pack_id+' '+r.version,JSON.stringify(r)));
      for(const v of value.versions||[]){versionSelect.append(new Option((v.selected?'当前 · ':'')+v.job_id.slice(0,12),v.job_id));for(const [label,suffix]of [['HTML',''],['JSON','/report.json'],['JSONL','/materials.jsonl'],['CSV','/materials.csv']]){const link=node('a',v.job_id.slice(0,8)+' '+label);link.href='/materials/pro/'+scope.pro_key+'/versions/'+v.job_id+suffix;versionLinks.append(link,document.createTextNode(' '));}}
      recomputeStatus.textContent=value.current_engine?.available===true?'当前处理器已变化，可按原包重建；不涉及知识批准，完成后需要单独选择。':value.releases?.length?'新处理不会覆盖旧产物；完成后需要单独选择。':'该知识作用域暂无同类已发布包；不会把候选或其他领域包当成已批准版本。';create.disabled=!value.releases?.length||!!pending(scope.pro_key);engineCreate.disabled=value.current_engine?.available!==true||!!pending(scope.pro_key);select.disabled=!value.versions?.length;
    }catch{if(ticket===materialTicket&&dialog.open)recomputeStatus.textContent='版本前置未接通；原素材保持可读。';}
  }
  const refresh=button('刷新版本记录',()=>loadMaterialVersions());recompute.append(releaseSelect,create,engineCreate,check,refresh,versionSelect,select,recomputeStatus,versionLinks);participantShare.append(recompute);
  const originalSelection=scopeSelect.onchange;scopeSelect.onchange=()=>{originalSelection();void loadMaterialVersions();};dialog.addEventListener('close',()=>{materialTicket++;materialView=null;});
  $('library_export').after(materialLink,materialExports,participantMaterialLink,participantShare);
  let revision=null,offset=0,filters={},total=0,generation=0,loading=false;
  $('library_close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{generation++;loading=false;launch.focus();});
  function getFilters(){const result={};if($('library_platform').value)result.platform=$('library_platform').value;if($('library_tag').value.trim())result.tags=[$('library_tag').value.trim()];if($('library_author').value.trim())result.author_id=$('library_author').value.trim();if($('library_kind').value)result.kind=$('library_kind').value;for(const [id,key]of [['library_after','published_after'],['library_before','published_before']])if($(id).value)result[key]=new Date($(id).value).toISOString();return result;}
  async function load(reset=false){if(loading)return;loading=true;const ticket=++generation;$('library_error').textContent='';if(reset){revision=null;offset=0;filters=getFilters();}
    try{const value=await call('list',{filters,revision,limit:50,offset});if(ticket!==generation||!dialog.open)return;revision=value.results_revision??value.revision;const rows=value.records||value.items||value.results||[];total=value.total??value.total_count??rows.length;$('library_summary').textContent=`固定资料版本 ${revision??'未报告'} · ${total} 条 · 第 ${Math.floor(offset/50)+1} 页`;$('library_records').classList.remove('detail');$('library_records').replaceChildren();
      for(const item of rows){const row=item.record||item.data||item;const card=node('article');card.className='record';card.append(node('h3',(row.platform==='zhihu'?({answer:'回答 · ',article:'文章 · ',zvideo:'视频 · '}[row.content_type]||''):'')+(row.title||row.author?.nickname||'已保存记录')),node('p',row.body||row.text||'没有可展示文字'),node('small',(platformNames[row.platform]||sourceNames[row.platform]||row.platform||'')+' · '+(recordNames[row.kind]||row.kind||'')+' · '+(row.published_at_utc?dateText(row.published_at_utc):'未报告发布时间')));card.querySelector('p').className='body';card.append(node('small','采集入口：'+entryText(row)));if(['content','dynamic'].includes(row.kind))card.append(button('查看版本、评论与评价',()=>detail(row)));$('library_records').append(card);}
      if(!rows.length)$('library_records').append(node('p','暂无匹配资料。先在任务中读取结果，资料会保存到本机。'));$('library_previous').disabled=offset===0;$('library_next').disabled=offset+rows.length>=total;
    }catch(e){$('library_error').textContent=errorNames[e.message]||e.message;}finally{if(ticket===generation)loading=false;}}
  async function open(){dialog.showModal();$('library_platform').focus();await Promise.all([load(true),loadShareScopes()]);if(dialog.open)await loadMaterialVersions();}
  async function detail(row){const ticket=++generation,selector=row.entity_ref?{entity_ref:row.entity_ref}:{};const value=await call('detail',{platform:row.platform,content_id:row.content_id,revision,...selector});if(ticket!==generation||!dialog.open)return;$('library_records').classList.add('detail');$('library_records').replaceChildren();const back=button('返回列表',()=>load());$('library_records').append(back,node('h3',row.title||'内容详情'));
    const ambiguous=value.content_identity_status==='ambiguous_types'||value.contents?.length!==1;if(ambiguous)$('library_records').append(node('p','同一标识包含多种正文，暂不能评价。请返回列表选择具体回答或文章。'));const score=node('select');score.setAttribute('aria-label','内容质量评分');for(let i=0;i<=5;i++)score.append(new Option(i+' 分',i));const savedEvaluation=(value.contents?.[0]?.owner_evaluations||[]).filter(e=>e.evaluator_ref==='local-owner').at(-1);score.value=String(savedEvaluation?.value??3);const tags=node('input');tags.type='text';tags.placeholder='业务标签，逗号分隔';tags.maxLength=400;tags.setAttribute('aria-label','业务标签');tags.value=(savedEvaluation?.tags||[]).join('，');const note=node('p','这是 Owner 对内容的业务评价，不改变原参与者评分或奖励。');note.className='hint';
    const save=button('保存业务评价',async()=>{if(ambiguous||ticket!==generation||!dialog.open)return;save.disabled=true;try{const saved=await call('evaluate',{platform:row.platform,content_id:row.content_id,revision,...selector,value:Number(score.value),tags:tags.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)});if(ticket!==generation||!dialog.open)return;revision=saved.results_revision;$('library_summary').textContent='保存后资料版本 '+revision+' · 内容质量评价已更新';$('library_error').textContent='评价已保存：'+saved.value+' 分'+(saved.tags.length?' · '+saved.tags.join('，'):'');}finally{save.disabled=ambiguous;}});score.disabled=tags.disabled=save.disabled=ambiguous;$('library_records').append(note,score,tags,save);
    const versions=value.versions||value.content_versions||[];for(const v of versions){const record=v.record||v.data||v;const card=node('article');card.className='record';card.append(node('h3','正文版本 '+(v.version??v.version_id??v.revision??'')),node('p',record.body||record.text||''));card.lastChild.className='body';card.append(node('small','采集入口：'+entryText(record)));$('library_records').append(card);}
    const comments=value.comments||[];$('library_records').append(node('h3','已保存评论 · '+comments.length));for(const c of comments.slice(0,100)){const card=node('article');card.className='record';card.append(node('strong',c.parent_comment_id&&c.parent_comment_id!=='0'?'回复':'评论'),node('p',c.text||c.body||'未取得评论文字'));card.lastChild.className='body';card.append(node('small','采集入口：'+entryText(c)));$('library_records').append(card);}if(comments.length>100)$('library_records').append(node('p','此处展示前100条；导出保留完整已保存评论。'));
    const unassigned=value.unassigned_comments||[];if(unassigned.length){$('library_records').append(node('h3','归属类型未确认的评论 · '+unassigned.length),node('p','以下评论只关联原平台数字标识，未归入当前正文。'));for(const c of unassigned.slice(0,100)){$('library_records').append(node('p',c.text||c.body||'未取得评论文字'));}if(unassigned.length>100)$('library_records').append(node('p','此处展示前100条；其余保留在资料库。'));}const unknownMedia=value.unassigned_media||[];if(unknownMedia.length){$('library_records').append(node('h3','归属类型未确认的媒体 · '+unknownMedia.length));for(const m of unknownMedia.slice(0,100))$('library_records').append(node('p',String(m.path||m.media_id||'未报告文件名').split('/').pop()));}
    for(const item of (value.media||[]).filter(m=>m.platform==='weibo'&&m.status==='reference_only'&&(m.media_kind==='image'||(/^https?:\/\/(?:[a-z0-9-]+\.)*sinaimg\.cn\//).test(m.url||''))&&typeof m.run_id==='string')){
      const register=button('核验已采原图',()=>guarded(async()=>{
        if(ticket!==generation||!dialog.open)return;register.disabled=true;
        try{
          const response=await fetch('/api/media-processing',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-CSRF':token},body:JSON.stringify({action:'image_attach_native',payload:{run_id:item.run_id,media_id:item.media_id}})});
          if(!response.ok)throw Error('原图尚未完整保存或来源核验未通过，请查看运行诊断。');
          const result=await response.json();if(ticket!==generation||!dialog.open)return;
          revision=result.results?.import_revision||result.results?.results_revision||revision;
          await detail(row);
        }finally{register.disabled=false;}
      }));$('library_records').append(register);
    }
    const attachments=(value.media||[]).filter(item=>item.status==='local_bytes_verified'&&typeof item.path==='string'&&item.path.startsWith('attachments/'));
    if(attachments.length){
      $('library_records').append(node('h3','已保存图片 · '+attachments.length));
      for(const item of attachments){
        const get=button('下载已保存图片',()=>guarded(async()=>{
          if(ticket!==generation||!dialog.open)return;
          get.disabled=true;
          try{
            const response=await fetch('/api/media',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-CSRF':token},body:JSON.stringify({run_id:item.run_id,path:item.path})});
            if(!response.ok)throw Error((await response.json()).error||'图片读取失败');
            const blob=await response.blob();
            if(ticket!==generation||!dialog.open)return;
            const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=item.path.split('/').pop();a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
          }finally{get.disabled=false;}
        }));
        const cloudNote=node('small','原图已核验并保存在本机；尚未查询云端状态。');
        const cloudButtons=[];
        const cloudErrors={cloud_configuration_required:'尚未配置项目云连接。',image_capture_not_received:'正文尚未取得云端回执，请先完成数据回传。',image_capture_ambiguous:'存在多个来源回执，尚未确定图片归属。',image_upload_outcome_unknown:'上传结果待核对，请稍后查询状态；不会重复上传。',image_cloud_not_saved:'图片尚未保存到云端。'};
        const cloudAction=(label,action,file=false)=>{
          const b=button(label,()=>guarded(async()=>{
            if(ticket!==generation||!dialog.open)return;
            cloudButtons.forEach(x=>x.disabled=true);
            try{
              const payload={run_id:item.run_id,path:item.path};if(file)payload.asset_sha256=item.sha256;
              const response=await fetch('/api/media-processing',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-CSRF':token},body:JSON.stringify({action,payload})});
              if(!response.ok){const problem=(await response.json()).error;throw Error(cloudErrors[problem]||'云端图片操作未完成，请查看运行诊断。');}
              if(file){
                if(response.headers.get('X-Content-SHA256')!==item.sha256)throw Error('云端图片校验未通过。');
                const blob=await response.blob();if(ticket!==generation||!dialog.open)return;
                const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=item.path.split('/').pop();a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
                cloudNote.textContent='已从私有云回取并核验原图。';
              }else{
                const result=await response.json();if(ticket!==generation||!dialog.open)return;
                cloudNote.textContent=result.state==='received'?'私有云已保存，云端回执已核对。':'图片尚未保存到私有云。';
              }
            }finally{cloudButtons.forEach(x=>x.disabled=false);}
          }));cloudButtons.push(b);return b;
        };
        $('library_records').append(get,cloudNote,cloudAction('查看云状态','image_cloud_status'),cloudAction('保存至私有云','image_cloud_save'),cloudAction('下载云端图片','image_cloud_file',true));
      }
    }
    const info=node('details');info.append(node('summary','来源、版本标识与原始字段'),node('pre',JSON.stringify(value,null,2)));$('library_records').append(info);$('library_previous').disabled=true;$('library_next').disabled=true;
  }
  $('library_search').onclick=()=>load(true);$('library_previous').onclick=()=>{offset=Math.max(0,offset-50);load();};$('library_next').onclick=()=>{offset+=50;load();};
  $('library_export').onclick=()=>guarded(async()=>{const response=await fetch('/api/results',{method:'POST',headers:{'Content-Type':'application/json','X-Crowd-CSRF':token},body:JSON.stringify({action:'export',payload:{format:$('library_format').value,filters,revision}})});if(!response.ok)throw Error((await response.json()).error||'导出失败');const manifest=response.headers.get('X-Crowd-Export-Manifest');if(manifest){const bytes=Uint8Array.from(atob(manifest.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));const value=JSON.parse(new TextDecoder().decode(bytes));$('library_summary').textContent+=' · 导出 '+value.row_count+' 条（附来源与缺失字段）';const previous=$('library_manifest');if(previous)previous.remove();const b=button('下载导出说明',()=>download('crowd-export-manifest.json',value));b.id='library_manifest';$('library_summary').after(b);}const url=URL.createObjectURL(await response.blob()),a=node('a');a.href=url;a.download='crowd-results-'+revision+'.'+$('library_format').value;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  return {ingest:run_id=>call('ingest',{run_id}),open};
})();
