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

## 4.2.5 执行器检查点与显式设备交接

新增迁移 `20261009040306_crowd_v4_kol_recovery.sql` 保留原公开 RPC 名称、owner 身份、历史回执及无奖励隔离。原实现移为不可对 authenticated/anon 执行的私有 `crowd_kol.rpc_base`，公开入口增加执行器检查。旧任务 `execution_protocol=0` 沿用旧合同；带安装级稳定 UUID `executor_id` 的 claim 将新任务绑定为协议 1。已有动作尝试的旧协议运行任务不能无证据升级或由新执行器接管，返回 `legacy_executor_required`。

新任务返回 `executor_id,execution_protocol,checkpoint,max_discovery_scrolls,max_comment_pages`。同 owner 的另一执行器不能普通 claim 接管；返回 `old_executor_required`。旧包省略 executor_id 也不能操作协议 1 任务。executor_id 是安装标识，不是防恶意同 owner 伪造的新认证凭据；系统身份仍取服务端 auth.uid() 和 approved participant。任务绑定的是已登记的平台主体摘要，不能替代平台签名认证。

| 动作 | 参数 | 约束及返回 |
|---|---|---|
| claim | `{executor_id}` | 绑定/续租本执行器；released 必须明确 recover；过期租约需原设备先对账 release |
| guard | 原参数加 `{executor_id,request:uuid}` | 客户端外调前持久化稳定 request。同 request 只扣一次，重复响应 `allowed:false,replay:true,reason:source_outcome_unknown,admission_id,attempt_state`，绝不授权再次执行。异载荷 request_reused |
| action_settle | `{task,lease,executor_id,admission_id,outcome:'observed'|'failed'}` | 原执行器仅在源动作明确返回后报告。unknown 不能转为成功；detail 的 observed 不接受，必须真实 submit 回执或明确 failed。失败不退预算。相同结果幂等，冲突拒绝 |
| checkpoint | `{task,lease,executor_id,expected_revision,candidate_ids,processed_ids,scrolls,coverage}` | 返回 `{checkpoint}`。两 ID 数组分别最多100、平台合法原始 ID、不带导航 token；coverage 只 partial/observed_only。processed 必须存在本 task 的服务器 snapshot；既有 processed 不可倒退，未决 candidate 不得消失，除非已 ACK 或该详情已有明确失败。CAS冲突返回 checkpoint_conflict；原载荷丢ACK重放返回当前 checkpoint/replay:true |
| recovery_status | `{task}` | 仅 owner 返回原任务台账和未决动作，无正文/导航 token。source_coverage 永远 unverified；未 release 时 old_outbox_drain=unverified |
| release | `{task,lease,executor_id,checkpoint_revision,outbox_drained:true}` | 原设备先停止新动作、完成本地 outbox 原信封回传、明确 settlement、持久检查点。服务端拒绝未决准入、缺失 ACK 清单或版本冲突。成功 `{released:true,task:<id>,checkpoint,source_coverage:'unverified'}`，停止该执行器源动作，保留历史回执 |
| recover | `{task,executor_id}` | 必须已 release、当前任务未取消、目标 active、credential_epoch 未变、已绑定且相同 principal；返回完整 `{task,source_coverage:'unverified'}`。保留同 task/lease/attempts/checkpoint，换执行器并延长租约20分钟。已成功接管的同执行器重放可读回同任务，不再次续租 |
| finish | 原参数加 `{executor_id}` | 原执行器才可完成协议1任务；交接后旧执行器不能 finish/guard/checkpoint |

新设备不能凭本地 captured 游标跳过数据。客户端按服务器 ACK 的 processed 集合排除已收内容，保留未决候选 backlog，重新打开主页、重放有限滚动取得新的 DOM locator；这些定位访问也必须重新走 guard。搜索总上限协议1为3次（初次及最多2次恢复定位）、普通滚动总3次、显式 history 总最多30次；恢复不重置累计次数。评论每内容默认1页、显式最多5页、任务总次数还受 max_items × max_comment_pages 限制，总保存评论仍≤20。所有动作继续受旧 guard 更严日限、会话休息、验证码、全局暂停和最小30秒间隔约束。周期新任务保留上述用户设置。

不能自动恢复的状态有明确流程：未知源动作或原设备还有未交付 outbox 时，回原设备对账/交付；无法确认就保留 `source_outcome_unknown`，不能靠超时释放或退款。失去原设备且无法确认其队列时，本版不宣称安全自动接管。release 中的 outbox_drained 是原执行器声明，服务器进一步检查已签发动作及真实回执，但不能证明设备不存在未受控的本地数据。完整源站覆盖、原设备磁盘损坏恢复、跨账号/epoch恢复仍未实现。

### 公开媒体定位与本机派生文本

record.extra 可含 `media_refs`（最多20项）和 `media_status:public_refs_available|no_eligible_public_ref`。每项严格 `{url,kind:image|audio|video,source:rendered_public_dom,status:discovered_not_downloaded}`；HTTPS、无用户信息/端口/query/fragment，域名仅 xhscdn.com/xhsimg.com/hdslb.com 及其子域。它们只是实际 DOM 提供的公开定位，不表示已下载、已授权或完整媒体；实际下载仍需用户授权及本机下载器独立安全验证。派生 evidence.processor 新增 `faster_whisper_local`，与原本机处理器一样只另存派生证据，不覆盖正文。

### 本轮检查

`tests/kol-recovery-db.mjs` 加载完整正式迁移链，验证 owner/执行器隔离、真实 SQL 回执检查点、幂等 guard、未知动作阻塞、过期租约显式交接、预算保留、媒体白名单及本机处理器标记。两套实际 `kol.js Agent` 连接 PGlite：两页发现，第一条提交后丢 ACK 原 UUID 重放，原设备 release，新设备恢复主页/滚动，只抓剩余第二条。断言累计 detail/search/scroll 为2/2/2，原信封重投不增加源详情访问。页面输入仍是隔离 DOM fixture，不能替代真实平台双设备验收。

### 固定观察窗口、48小时重叠与覆盖状态

任务创建时服务端固定scan_from/scan_until，claim原样返回。periodic任务overlap_hours=48；授权窗口必须至少48小时＋一个周期，即window_days×1440≥2880＋interval_minutes。不足时明确invalid_overlap_window并返回required_window_days（12小时周期至少3天），不先接受再必然停住。扫描范围保留至少48小时回看，并包含最后一次实际扫描若发生错误、风险/登录中断、租约过期或无内容回执时的未完成窗口；若其起点超出本次window_days授权，start返回incomplete_window_outside_authorization，自动周期在target.scan_block_reason记录同原因，不自行扩大范围。本人明确增加window_days后再start。正常有界结束partial/observed_only不等同故障窗口，但仍不证明源站完整覆盖。更早历史故障缺口保留旧任务台账供手动回填，不把它们无期限强加给所有后续周期，也不标记已补齐。

target.last_attempted_scan仅首次源guard获准时由数据库时间更新，不由客户端提交；last_complete_coverage当前始终null。检查点coverage和观察窗口不是完整覆盖水位。日期只有YYYY-MM-DD时，协议1按UTC当日末尾是否仍可能落入scan_from保守过滤；无法精确判定当天时刻，不冒充精确发布时间，也不凭首条旧帖停止列表。旧协议0的历史outbox保持此前日期校验口径。epoch变化不能将旧检查点作为新账号游标使用。

### 不可访问来源与图片评论

只在DOM明确不可访问提示时报告source_not_found/source_private/source_deleted；解析连续失败的客户端平台暂停用parser_paused。action_settle的failed可带固定failure_reason，finish的error可带同一枚举detail_reason，后端保留分类，不存任意错误正文或URL。它们是客户端可见提示分类，不宣称服务器获知平台真实删除/隐私状态。

评论新增content_type=text/image/mixed、is_placeholder、media_count（可见图数0..100）及reported_reply_count（未知null）。纯图评论必须text=''、original_length=0、truncated=false、content_type=image、is_placeholder=true、media_count>=1；“可见图片评论，无文字”只在界面呈现，不作为抓到的原文存入。文字/图文仍保留真实文字和原长度，不允许placeholder=true。实体保存类型/图数/回复数；图片不在此自动下载。正文版本摘要对纯文本保持旧口径，图片/图文增加媒体形态；回复数变化不制造正文版本。

正常零新增也有明确终态：creator `finish reason=observed_only` 仅在真实 search 准入已 settled observed、无 unknown/failed 源动作、至少一个检查点且已存内容回执均列入 processed 时接受，仍写 state=partial/reason=observed_only。已知内容全部跳过或列表确实为空不等于故障，下一周期不必扩大窗口；未导航的空任务不能冒称正常观察。客户端无失败的有界 creator 结束使用这一合同；源失败仍记录 error。actual Agent 全known→0新增→同窗口再次周期启动已在SQL纵切验证。
