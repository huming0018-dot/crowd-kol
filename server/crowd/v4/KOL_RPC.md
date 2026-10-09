# KOL 发布接入 RPC v1

`public.crowd_v4_kol(p_action text,p_payload jsonb default '{}')`，仅 authenticated 且现有 approved/consent participant。owner 只取 auth.uid()。普通失败 `{error:code}`，guard限制 `{allowed:false,reason,wait_ms}`，身份无效SQL42501。

| action | payload | result |
|---|---|---|
| list | `{}` | `{targets:[],tasks:[],contents:[],capabilities:{platforms:['xiaohongshu','bilibili'],max_items:10,max_comments:20,include_replies:true,reply_expansion_platforms:['xiaohongshu']}}` |
| upsert | `{url,label?,group?,interval_minutes?,target_id?}` | `{target}`；interval 0禁周期或60..10080分钟 |
| start | `{target_id,mode:'manual'|'history'|'periodic',max_items?:2,comment_limit?:0,comment_depth?:1,window_days?:30,interval_minutes?:60}` | `{task}`；max_items1..10；history是有界历史一批，不代表全部历史 |
| claim | `{}` | `{task:null|{id,target_ref,platform,target_kind,target_id,url,max_items,known_ids,lease_token,credential_epoch,comment_limit,comment_depth,window_days,refresh_ids,include_replies:comment_depth===2}}` |
| guard | `{task,lease,action:'search'|'detail'|'scroll'|'comment',content_id?}` | `{allowed,reason,wait_ms,admission_id?}`；每次真实源站动作先准入，每次失败重试再guard |
| submit | `{request,task,lease,admission_id,record}` | `{gate:'received',request,task,content_id,received_at,version,source_kind:'rendered_public_dom',reward_eligible:false,inserted:boolean}` |
| finish | `{task,lease,reason:'completed'|'partial'|'auth_required'|'risk_paused'|'cancelled'|'error'}` | `{task}` |
| stop/resume/delete_target | `{target_id}` | `{target}`；停止新任务/派发，保留既有内容和合法待交付结果；delete_target软删跟踪目标 |
| delete_content | `{platform,content_id}` | `{deleted:true}`；明确删除该owner内容/版本/指标/评论，但保留无正文幂等回执摘要，旧request不能重新恢复内容 |
| export | `{target_id?,limit?:100}` | `{contents:[],tasks:[],coverage:'observed_only'}`；最多500条 |
| session_changed | `{platform,principal_ref:64hex,verification:'rendered_account_navigation'}`；兼容旧`{}`失效动作 | `{credential_epoch,principal_bindings,identity_changed}`；主体改变取消当前源站任务，旧已采准入仍只回传不重抓 |

Target shape: `{id UUID,platform,target_kind:'creator'|'content',target_id,url,label,group,status:'active'|'paused'|'deleted',interval_minutes,next_due_at,...}`。
Task shape是独立UUID任务，不是旧众包bigint任务。task在list可含`state,reason,received,attempts,created_at,finished_at`；claim的known_ids最多500，供增量重叠扫描，不能推断全源站完整。

`record`沿用v4 `{schema_version:4,standard,extra,evidence}`。标准字段：platform,note_id,url,title,captured_at,published_at,author_display,like_count,collect_count,comment_count,view_count，可选share_count/danmaku_count。未知指标必须null，不伪造0。`extra.author={id,url}`，creator任务必需且精确匹配目标。`extra.author_opinion_quotes=[]`；可选media_present和comments，以及原DOM适配器字段：field_observations、metric_labels、published_label、hashtags、content_type、comment_status、replies_status；evidence.selector可选。指标observations必须与standard值一致，保留exact/approximate/not_visible/unparsed/not_requested状态，未知null不能伪装0。`evidence={text,original_length,truncated,parser_version,source:'rendered_public_dom'}`。

XHS内容24hex，主页`https://www.xiaohongshu.com/user/profile/<24hex>`，笔记`https://www.xiaohongshu.com/explore/<24hex>`。Bili作者数字ID，主页`https://space.bilibili.com/<id>`，视频BV+10位字母数字，`https://www.bilibili.com/video/<BV...>`。upsert允许这些URL附常见query/fragment但服务器只存规范无query URL；短链解析不在DB执行。

comments shape沿用`{items:[{key:'comment-1',parent_key:null,text,original_length,truncated}],coverage:'visible_loaded_only',complete:false,captured_count,truncated}`，≤20且不超过task.comment_limit。comment_depth=2允许真实parent_key指向本页已出现的根评论；一律不接评论者author_display（必须null），可保留受限comment_id、is_reply、like_count/label和published_label。XHS适配器可展开可见二级，Bili仍受当前DOM可见性限制，不能保证展开所有二级。媒体下载、完整历史遍历未实现。

共享guard通过私有legacy bridge task接现有crowd_v4_guard：外部一直closed，仅同一事务内临时leased供guard判定后恢复closed，旧客户端不会claim它。两平台KOL预算reservation key均为kol:platform:content命名空间摘要，仅共享预算，实际content ID保持BV。无写入crowd_v4.proofs/rewards路径，不把机器API伪装DOM。

周期任务由登录插件claim时按server next_due_at补一批，不是无设备在线仍能采的云端调度。周期任务保留用户已保存的max_items/comment_limit/comment_depth/window_days。一次task默认2最多10个detail尝试，所有失败计入；旧guard更严日限/冷却/间隔继续有效。首交必须持有本task/detail准入，24小时内可迟到；原request重放优先于租约状态，数据与回执同事务。暂停/删除目标不删除内容；内容删除单独明确动作，不允许旧幂等重放复活已删内容。


## 作者、历史与授权派生证据

- `profile {request,task,lease,admission_id,profile}`：使用该creator task的search准入；profile精确字段author_id/url/nickname/public_handle/metrics/captured_at/source/parser_version；metrics只followers/notes/likes_collected，每项value/label/status。返回`{gate:'received',request,task,kind:'profile',received_at,source_kind:'rendered_public_dom',reward_eligible:false}`。稳定UUID丢ACK重放，24h有效准入支持停止后迟到交付，不增加内容received或奖励。list.profiles只返每target最新一条，历史在私有profiles表保留。
- `detail {platform,content_id}`：仅当前owner，返回content、最多100个versions、100个metric_snapshots、200个comments原始采样、200个comment_entities、200个comment_versions、100个evidence。版本摘要只含内容身份/作者/title/body/published_at/content_type/hashtags；采集时间、parser版本、指标/label及评论变化不冒充正文版本。
- `attach_evidence {platform,content_id,authorization_ref,kind,evidence}`：kind=ocr/transcript/demographics。另存派生证据，不覆盖DOM原文。source_kind必须authorized_local_file、asset_sha256为64hex、observed_at有效时间；可带truncated:boolean和coverage:local_file_bounded。
- OCR允许raw_text≤24000、blocks≤200；每block严格为text≤2000、confidence0..1、bbox四个0..1数、semantic_type=unclassified、review_status=unreviewed。transcript只接非空获授权文本，不伪称做了语音识别。
- demographics只接population/dimension/coverage_period字符串、sample_size非负整数≤2147483647、aggregate_values 1..100个非负数；禁止raw_text/blocks或个人明细行。其授权只标`verification=user_declared_not_independently_verified`，不声称独立核实授权或画像真实性。
- evidence按owner/platform/content_id/kind/asset_sha256唯一；同载荷重放返回同evidence_id，异载荷`evidence_reused`，不覆盖已有记录。delete_content级联删除正文版本、指标、评论和派生证据，原幂等元数据receipt保留。

`finish reason=risk_paused` 需risk_type=captcha/rate_limit，缺省保守rate_limit；同事务调用旧guard记录真实冷却，重开任务不清除。无内容ACK的completed自动降为partial/no_received_content；creator可见有界批次一律partial/observed_only，不把采满配额当全源站覆盖。

`claim.refresh_ids`仅给服务器24h未更新的最多1条，仍占max_items与源站guard预算；客户端不得无界刷新全部known_ids。暂停/删除目标与删除内容分开。旧众包有效lease存在时claim返回legacy_task_active，不抢占旧采集器或丢其outbox。

## 当前检查与上线边界

`CROWD_TEST_TOOLS=/private/tmp/crowd-fix-tools node crowd-kol/server/crowd/v4/tests/kol-db.mjs`加载全部正式迁移，运行双owner权限、双平台实际Chromium DOM输出、真实kol.js状态机→SQL回执、丢ACK重放等针对性检查。测试数据库身份/时间仍是隔离fixture；不是生产真实两条来源验收。真实登录、页面变化、付费授权和完整历史覆盖不能由这些测试替代。


## 评论实体与采样分开

原 comments 表继续逐request保存原始可见样本（包含受限record元信息），不删除重复观察。真实comment_id存在时，以owner/platform/content_id/comment_id唯一维护comment_entities；正文/截断范围变化增加同实体comment_versions，单纯点赞变化不新增正文版本。相同真实ID在同一页重复或自相矛盾拒绝，不能制造多个实体。

没有真实ID的评论保持sample-only，不以comment-1或正文hash伪造稳定ID。父/根ID只从当前样本的parent_key→实际comment_id映射。parent_observed表示实际父ID可见；父样本没ID或明确is_reply但父级不见时标orphan；未报告回复属性且无法确认关系标unknown，字段null。明确根评论标root。后次关系不可见时保留当前unknown/orphan及历史观察，不假装仍已观测到旧关系。

detail.comments仍是观察记录，界面应将comment_entities作为实体列表，并单列没有record.comment_id的样本，避免把多次观察当多个评论。detail.comment_versions保留真实ID正文版本，评论点赞/标签及发布时间不可见时为null。delete_content级联删除实体、版本和全部样本。

## 平台账号主体绑定

settings按平台保存principal_ref、verification和服务器verification_at。摘要由客户端从全局导航“我/我的主页”等公开DOM取得当前账号ID后，以SHA256(owner + 换行 + platform + 换行 + id)计算；文章作者链接不算当前账号。服务器记录的是经系统身份鉴别后的客户端DOM观测声明，不是平台签发的身份令牌，也不是独立认证证明。不读Cookie或私有JS状态。

新任务复制对应平台principal_ref/principal_verification/principal_verification_at；claim返回全部字段。未绑定任务ref=null、verification=unverified，可做公开页面普通采集但不得宣称账号已核验。绑定任务每次源站guard前必须由插件重新观察全局导航并比对摘要：无法确定就identity_verification_required，变化就platform_identity_changed，要求本人登录/确认。服务端guard同时检查任务epoch及已登记绑定；服务端不能替插件证明当前浏览器DOM。

同平台相同主体再次报告只更新时间，不增加epoch或取消任务；新主体/首次绑定增加全局credential_epoch并取消旧queued/running任务，保守隔离旧执行游标。其他平台绑定保留，但旧任务仍因全局epoch作废。预算、冷却、既有内容和合法待回执不清零。兼容空payload只清全部绑定并轮换epoch，绝不标核验成功。list同时返回当前principal_bindings与credential_epoch。

已删除目标显式upsert可恢复active，清旧周期interval/next_due，需再次start才启动；暂停目标编辑保持paused。授权派生evidence可选processor，仅apple_speech_ondevice/manual_import/apple_vision，记录声明的处理器，不替代本机执行证据。
