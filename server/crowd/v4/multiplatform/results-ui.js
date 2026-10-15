'use strict';
const resultsView = (() => {
  const call=(action,payload={})=>api('/api/results',{action,payload});
  function entryText(record){const names={search:'关键词搜索',detail:'指定详情',creator:'作者内容',homefeed:'首页推荐页面采样',trending:'热门页面采样'};return Object.hasOwn(names,record.discovery_kind)?names[record.discovery_kind]:'未记录（unknown）';}
  const sourceNames={xiaohongshu:'小红书',douyin:'抖音',kuaishou:'快手',bilibili:'B站',weibo:'微博',tieba:'百度贴吧',zhihu:'知乎'},recordNames={content:'正文',comment:'评论',dynamic:'动态',author:'作者资料',media:'媒体'};
  const launch=button('资料库',()=>open());$('open_settings').before(launch);
  const dialog=node('dialog');dialog.id='library_dialog';dialog.style.width='min(920px,calc(100% - 28px))';dialog.setAttribute('aria-labelledby','library_title');
  dialog.innerHTML=`<div class="dialog-head"><h2 id="library_title">已保存资料</h2><button type="button" id="library_close">关闭</button></div><div class="dialog-body"><p class="hint">保存已采结果、比较正文版本、评价和导出；不重新访问平台。</p><p id="library_error" class="error" role="status"></p><div class="grid"><label>平台<select id="library_platform"><option value="">全部平台</option></select></label><label>业务标签<input id="library_tag" type="text" maxlength="80" placeholder="按已保存标签筛选"></label></div><details><summary>作者、发布时间与记录类型</summary><div class="grid"><label>作者标识<input id="library_author" type="text" maxlength="200" placeholder="原平台ID或明确标注的匿名ID"></label><label>记录类型<select id="library_kind"><option value="">全部记录</option><option value="content">正文</option><option value="comment">评论</option><option value="dynamic">动态</option><option value="author">作者资料</option><option value="media">媒体</option></select></label><label>发布时间从<input id="library_after" type="datetime-local"></label><label>发布时间至<input id="library_before" type="datetime-local"></label></div></details><div class="actions"><button id="library_search" class="primary">查询</button><select id="library_format" aria-label="导出格式"><option value="json">JSON</option><option value="jsonl">JSONL</option><option value="csv">CSV</option><option value="xlsx">Excel</option></select><button id="library_export">导出当前筛选结果</button></div><p id="library_summary" class="hint"></p><div id="library_records"></div><div class="actions"><button id="library_previous">上一页</button><button id="library_next">下一页</button></div></div>`;
  document.body.append(dialog);for(const [id,title]of Object.entries(platformNames))$('library_platform').append(new Option(title,id));
  let revision=null,offset=0,filters={},total=0,generation=0,loading=false;
  $('library_close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{generation++;loading=false;launch.focus();});
  function getFilters(){const result={};if($('library_platform').value)result.platform=$('library_platform').value;if($('library_tag').value.trim())result.tags=[$('library_tag').value.trim()];if($('library_author').value.trim())result.author_id=$('library_author').value.trim();if($('library_kind').value)result.kind=$('library_kind').value;for(const [id,key]of [['library_after','published_after'],['library_before','published_before']])if($(id).value)result[key]=new Date($(id).value).toISOString();return result;}
  async function load(reset=false){if(loading)return;loading=true;const ticket=++generation;$('library_error').textContent='';if(reset){revision=null;offset=0;filters=getFilters();}
    try{const value=await call('list',{filters,revision,limit:50,offset});if(ticket!==generation||!dialog.open)return;revision=value.results_revision??value.revision;const rows=value.records||value.items||value.results||[];total=value.total??value.total_count??rows.length;$('library_summary').textContent=`固定资料版本 ${revision??'未报告'} · ${total} 条 · 第 ${Math.floor(offset/50)+1} 页`;$('library_records').classList.remove('detail');$('library_records').replaceChildren();
      for(const item of rows){const row=item.record||item.data||item;const card=node('article');card.className='record';card.append(node('h3',(row.platform==='zhihu'?({answer:'回答 · ',article:'文章 · ',zvideo:'视频 · '}[row.content_type]||''):'')+(row.title||row.author?.nickname||'已保存记录')),node('p',row.body||row.text||'没有可展示文字'),node('small',(platformNames[row.platform]||sourceNames[row.platform]||row.platform||'')+' · '+(recordNames[row.kind]||row.kind||'')+' · '+(row.published_at_utc?dateText(row.published_at_utc):'未报告发布时间')));card.querySelector('p').className='body';card.append(node('small','采集入口：'+entryText(row)));if(['content','dynamic'].includes(row.kind))card.append(button('查看版本、评论与评价',()=>detail(row)));$('library_records').append(card);}
      if(!rows.length)$('library_records').append(node('p','暂无匹配资料。先在任务中读取结果，资料会保存到本机。'));$('library_previous').disabled=offset===0;$('library_next').disabled=offset+rows.length>=total;
    }catch(e){$('library_error').textContent=errorNames[e.message]||e.message;}finally{if(ticket===generation)loading=false;}}
  async function open(){dialog.showModal();$('library_platform').focus();await load(true);}
  async function detail(row){const ticket=++generation,selector=row.entity_ref?{entity_ref:row.entity_ref}:{};const value=await call('detail',{platform:row.platform,content_id:row.content_id,revision,...selector});if(ticket!==generation||!dialog.open)return;$('library_records').classList.add('detail');$('library_records').replaceChildren();const back=button('返回列表',()=>load());$('library_records').append(back,node('h3',row.title||'内容详情'));
    const ambiguous=value.content_identity_status==='ambiguous_types'||value.contents?.length!==1;if(ambiguous)$('library_records').append(node('p','同一标识包含多种正文，暂不能评价。请返回列表选择具体回答或文章。'));const score=node('select');score.setAttribute('aria-label','内容质量评分');for(let i=0;i<=5;i++)score.append(new Option(i+' 分',i));const savedEvaluation=(value.contents?.[0]?.owner_evaluations||[]).filter(e=>e.evaluator_ref==='local-owner').at(-1);score.value=String(savedEvaluation?.value??3);const tags=node('input');tags.type='text';tags.placeholder='业务标签，逗号分隔';tags.maxLength=400;tags.setAttribute('aria-label','业务标签');tags.value=(savedEvaluation?.tags||[]).join('，');const note=node('p','这是 Owner 对内容的业务评价，不改变原参与者评分或奖励。');note.className='hint';
    const save=button('保存业务评价',async()=>{if(ambiguous||ticket!==generation||!dialog.open)return;save.disabled=true;try{const saved=await call('evaluate',{platform:row.platform,content_id:row.content_id,revision,...selector,value:Number(score.value),tags:tags.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)});if(ticket!==generation||!dialog.open)return;revision=saved.results_revision;$('library_summary').textContent='保存后资料版本 '+revision+' · 内容质量评价已更新';$('library_error').textContent='评价已保存：'+saved.value+' 分'+(saved.tags.length?' · '+saved.tags.join('，'):'');}finally{save.disabled=ambiguous;}});score.disabled=tags.disabled=save.disabled=ambiguous;$('library_records').append(note,score,tags,save);
    const versions=value.versions||value.content_versions||[];for(const v of versions){const record=v.record||v.data||v;const card=node('article');card.className='record';card.append(node('h3','正文版本 '+(v.version??v.version_id??v.revision??'')),node('p',record.body||record.text||''));card.lastChild.className='body';card.append(node('small','采集入口：'+entryText(record)));$('library_records').append(card);}
    const comments=value.comments||[];$('library_records').append(node('h3','已保存评论 · '+comments.length));for(const c of comments.slice(0,100)){const card=node('article');card.className='record';card.append(node('strong',c.parent_comment_id&&c.parent_comment_id!=='0'?'回复':'评论'),node('p',c.text||c.body||'未取得评论文字'));card.lastChild.className='body';card.append(node('small','采集入口：'+entryText(c)));$('library_records').append(card);}if(comments.length>100)$('library_records').append(node('p','此处展示前100条；导出保留完整已保存评论。'));
    const unassigned=value.unassigned_comments||[];if(unassigned.length){$('library_records').append(node('h3','归属类型未确认的评论 · '+unassigned.length),node('p','以下评论只关联原平台数字标识，未归入当前正文。'));for(const c of unassigned.slice(0,100)){$('library_records').append(node('p',c.text||c.body||'未取得评论文字'));}if(unassigned.length>100)$('library_records').append(node('p','此处展示前100条；其余保留在资料库。'));}const unknownMedia=value.unassigned_media||[];if(unknownMedia.length){$('library_records').append(node('h3','归属类型未确认的媒体 · '+unknownMedia.length));for(const m of unknownMedia.slice(0,100))$('library_records').append(node('p',String(m.path||m.media_id||'未报告文件名').split('/').pop()));}
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
