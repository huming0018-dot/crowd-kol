'use strict';
// Machine preflight declarations are not live platform-login or device acceptance proofs.
(() => {
  const panel=node('details'),heading=node('summary','机器能力 · 正在读取'),body=node('div');
  panel.append(heading,body);$('runs').after(panel);
  const platforms={xhs:'小红书',dy:'抖音',ks:'快手',bili:'B站',wb:'微博',zhihu:'知乎',tieba:'贴吧'};
  const statuses={assignable:'本地预检通过',needs_attention:'需要处理',not_reported:'尚未上报'};
  const reasons={expired:'能力上报已过期',capability_expired:'能力上报已过期',worker_expired:'节点授权已过期',worker_disabled:'节点已停用',not_reported:'尚未上报',not_configured:'尚未配置 Pro',dependency_unavailable:'Pro 依赖未就绪',identity_unverified:'原账号身份尚未核验',login_in_progress:'正在核验登录',unsupported_scope:'尚未接通此采集范围',source_changed:'Pro 安装版本待核对',preflight_failed:'本地预检未通过',ready:'本地预检通过'};
  const scopesText={xhs_detail_body_comments_v1:'小红书单篇正文与评论（不含媒体）'};
  const uuid=v=>typeof v==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
  const count=v=>Number.isSafeInteger(v)&&v>=0;
  const label=(v,max=80)=>typeof v==='string'?v.slice(0,max):'未知';
  const when=v=>{const d=new Date(v);return v!==null&&v!==undefined&&Number.isFinite(d.getTime())?d.toLocaleString():'尚无记录';};
  let cursor=null,busy=false;
  async function refresh(){
    if(busy||document.hidden)return;busy=true;
    try{
      const v=await api('/api/cloud',{action:'worker_capabilities',payload:{limit:100,...(cursor?{after_worker_id:cursor}:{})}});
      if(v.available!==true){heading.textContent='机器能力 · 尚未接通';body.replaceChildren(node('p','能力接口或权限尚未就绪，不能据此判断节点可分配。'));return;}
      if(v.schema!=='crowd-worker-capabilities-page-v1'||!Array.isArray(v.nodes)||v.nodes.length>100||!count(v.total)||!v.counts||!['assignable','needs_attention','not_reported'].every(k=>count(v.counts[k]))||v.next_cursor!==null&&!uuid(v.next_cursor))throw Error('invalid_projection');
      heading.textContent='机器能力 · 可分配 '+v.counts.assignable+' · 需处理 '+v.counts.needs_attention+' · 未上报 '+v.counts.not_reported;
      body.replaceChildren(node('p','共 '+v.total+' 个机器节点，本页 '+v.nodes.length+' 个 · 云端时间 '+when(v.server_time)),node('p','可分配表示已配对节点的本地预检声明仍有效；平台登录在实际执行前再次核验。手机控制、各系统安装及真实采集须分别验收。'));
      for(const row of v.nodes){
        if(!uuid(row.worker_id)||!Object.hasOwn(statuses,row.status))throw Error('invalid_projection');
        const section=node('section');section.append(node('h3',label(row.name||row.worker_id.slice(-8))+' · '+statuses[row.status]));
        const revision=typeof row.source_commit==='string'&&/^[a-f0-9]{40}$/.test(row.source_commit)?row.source_commit.slice(0,12):'未知';
        section.append(node('p',label(row.host_os)+' / '+label(row.host_arch)+' · '+(row.engine==='mediacrawler_pro'?'MediaCrawler Pro':'引擎待核对')+' · '+label(row.protocol)+' · SDK '+revision));
        section.append(node('p','平台：'+(Array.isArray(row.platforms)?row.platforms.map(p=>platforms[p]||'未知平台').join(' / '):'未知')));
        const scopes=Array.isArray(row.scopes)?row.scopes.filter(s=>typeof s==='string').slice(0,20):[];
        section.append(node('p','可执行范围：'+(scopes.length?scopes.map(s=>scopesText[s]||'未识别的采集范围').join(' / '):'尚无可分配的 Pro 范围')));
        if(row.reason)section.append(node('p',reasons[row.reason]||'具体原因待核对；请查看节点诊断。'));
        if(row.identity_basis==='cached_authenticated_self_id')section.append(node('p','身份依据：原账号缓存身份，核验于 '+when(row.identity_verified_at_ms)+'；不是刚完成平台登录核验。'));
        section.append(node('p','上报 '+when(row.reported_at)+' · 声明到期 '+when(row.expires_at)));
        body.append(section);
      }
      if(!v.nodes.length)body.append(node('p',cursor?'本页已无机器节点。':'尚无机器节点能力可查；不能按平台注册数判断 Pro 可用。'));
      if(cursor){const first=node('button','返回第一页');first.onclick=()=>{cursor=null;return refresh();};body.append(first);}
      if(v.next_cursor){const next=node('button','下一页');next.onclick=()=>{cursor=v.next_cursor;return refresh();};body.append(next);}
    }catch(_error){heading.textContent='机器能力 · 查询失败';body.replaceChildren(node('p','无法读取最新能力，不据此领取或重发任务。'));}
    finally{busy=false;}
  }
  refresh();setInterval(refresh,10000);
})();
