# 分布式采集系统｜固定交接入口

更新：2026-10-15 15:02 CST，Asia/Shanghai。维护：Codex /root。本文件维护当前状态；重要历史留在日志。**交接是每轮工作的伴随机制，主线继续推进。**

## 1. 接力规则

1. 先读本文件、[证据索引](handoff/EVIDENCE.md)、[变更日志](handoff/CHANGELOG.md)，再读工作区 AGENTS.md 和涉及的模块。
2. 核对环境、分支、未提交改动和证据日期。聊天摘要、作者自述、测试目录存在、进程在线，都不能替代实际验收。
3. 无法访问或核验时明确说明缺口，标“未知/未验证”，继续可独立完成的工作，不声称已同步。
4. 每轮结束都更新日期、本轮结论和下一步；主要改动后，用[接力模板](handoff/ENTRY_TEMPLATE.md)更新本文件相关状态和证据，向日志追加记录；不复制整段对话。
5. 用户新指令优先。读过交接包不等于获得新采集、部署、付费或外发权限。

## 2. 目标、范围与阶段

目标：中心数据库动态分配任务到用户终端；本地复用本人登录、静默采集、耐久回传；中心逐条确认、监控步骤、定位异常。Owner 不应手工分配账号或 HTTP 请求。

必须保留：Kimi/现有参与者流程、身份、评分、暂停继续、outbox、回执、OTA；吸收 MC/已购 Pro 的平台、评论回复、媒体、推荐、账号、断点与分析能力。PC/Mac/VM/手机均在长期目标中；手机控制与手机本机执行分别验收。有效会话尽量长期复用，不能承诺 Cookie 永不过期。

当前阶段：Pro本机真实有界批次、固定观测的真实云交付、连续OTA已接入正式运行并独审通过；仍不是全部平台/全端完整产品终验或48小时实验阶段。详细状态见第3节。

2026-10-14新轮授权：并行实现中央槽释放、Owner恢复入口、Pro成熟能力桥；独审后正式采用并做原范围真实云回执、登录恢复与连续OTA验收。上轮只读交接限制已结束。保留原身份、原任务和每台两条预算；不自动扩额度、外发Pro私码、重置凭据、arm试验或恢复看门狗。

## 3. 当前状态

### 2026-10-15当前增量（优先于下列10-14历史时点）

- 按14:22开始的15分钟批次并行推进，三作者分工、非作者交叉独审。正式功能源码5f40ef3、03a38fe及发布b6be7cd均已推送。正式工作台5文件已采用，PID31520；独立核386其他源码、121历史文件、4库与实际备份逐行等同。旧1526ACK保持，新的source0验收使当前1529ACK、pending0。数据repr摘要的跨Python差异已用同解释器和原始行比较解释，不隐藏差异。
- 中央机器步骤SQL及Edge24正式部署，12文件相对actual23仅core/unified_monitor两改+machine_steps新增，其他9精确保留。机器沿原worker/claim/run/epoch；不削弱参与者表FK。SQLite耐久队列、未知ACK原事件重放、永久坏组保留隔离、独立上传线程、Owner最近200/历史分页已独审。Pro每个持久保存页有hash绑定事件；MC原引擎逐页仍缺，不称全平台逐请求监控完成。
- 新验收task `b619f7f5-8a2c-49a8-b752-674b9dc1441a` completed，1正文+根评论1+回复1、3唯一ACK、source spent/reserved0；6中央步骤与本地持久队列/Owner真实HTTP逐项一致，全文字段/parent/media引用/origin/metrics/冻结rev71/原envelope与finish均独审通过。此为已保存数据交付，不是新来源、媒体字节或登录恢复现场验收。
- 登录共享层已修：checking/logout/check_failed撤销旧核验，原生pong异常耐久check_failed；原session/pending_run/account_ref/outbox保留。36测试及root独立真实store13负例通过。完整真实登出重登与原云任务继续尚未验；Pro专属原生账号状态接线仍在补，不把MC隔离结果外推。
- 原生helper通用binary `8198638abe0013ff3540e3d1a41f682a8fc206d793bd61e4d97cc666f3272a91`已在原本机沿既有锁/备份/reconnect采用。实际Chrome native schema1/applied70；原配置/state与身份/进度保护通过。updater_enabled原储存两侧均缺失，不能从摘要相等推为显式开启。
- OTA70 source03a38fe，签名seq2026101570；固定ZIP2992d9f，ZIP SHA `ac2f529ea19f45917e23e942b725ad045efb5fcc42754f897e9ea00636e42531`、release SHA `9e5b46b1ace6a612c2897ef95113b82a9884593daae1beb190f64b1bf0ccc284`，通道及一键helper已发布b6be7cd。原本机69→70、identity/queue/history/进度/原received2/outbox0与真实云started/waiting/completed已独审。另一原节点14:57实查仍69，远端helper未验。首个只读native错误漏取安全错误码、升级后两个原Chrome进程消失原因未知；已核句柄不存在后只重开同一原XHS profile，不重发apply。
- 新错误码固定分类及生产三函数已部署，实际定义/ACL/原source/receipt保持独审通过。历史失败fresh全表为12条unexpected_error，旧四条只是旧快照，均保留；没有自然ota_*新错误现场，不能倒填根因或称自然故障码往返已过。
- CookieBridge曾因原进程退出与Chrome开发者模式关闭失联；本机服务已用同一已审封装恢复。原Bili client正常复连但Bili/DY Cookie当前无，其他单Cookie不代表登录有效。用户已新增明确授权原XHS profile加载同组件并仅同步127:8274；安装正常目录选择器已打开，原生控制只能定位另一份日常Chrome，等待用户在原选择器选目录。没有改日常Chrome或搬运Cookie作旁路。
- XHS/DY轻量Signer原SDK候选已修NODE_OPTIONS预载、Python DNS/UDP等拦截缺口并独审准入validate-only；不是平台接受签名或实际采集通过。XHS/DY分页/Pro账号适配继续并行。默认MC保持；48h和看门狗不启动。详见E28及本轮日志。


### 10-14历史基线（现态以本节上述增量为准）

- 中央delivery_pending释放来源槽、原manifest/epoch交付恢复、Owner原ID恢复入口已独审并部署（E16/E17），Edge23保留原合同；尚无自然坏组完整恢复现场证据。参与者XHS pilot与机器多平台仍是两执行链，机器中央全部步骤、任意任务任意节点尚未全通。本轮不替换原身份/评分/参与者流程，原两设备各2条预算保持。
- 正式功能提交：crowd-kol `30139a2`（绑定/拒绝收尾提交8c3444a及HTTP窄扩容）、crawler-extension `c5ff909`、crowd-pages `76474d2999e752e0b385b544e5a60f33e65a2033`，均已推送原授权分支；后续交接文档提交另见git log。
- 正式工作台：`saved-http-fa00c58899c78085` / PID92704；Edge `crowd-machine` v23，保存引用200、可选固定revision及完整行摘要已接入，原10文件含index/auth保持。四库、121原任务配置及389其他源码字节通过独审，1290既存ACK保留。明确未派发/未暂存的本地永久拒绝耐久failed/API0，复用原run收尾；未知网络/已有outbox不套此路径。HTTP仅任务preview/create放宽128KiB，其他操作保持原32KiB。
- Pro同输入新试验 `f2cb4ede-696d-45c2-9f42-38fcaa21c2b0`：completed/exit0，1正文20根86回复，40runner请求+1Signer，启动意图到终态43.003秒；18分页saved，父批与vox检查点已提交。覆盖为limit_reached/upstream_batch_limit，非全评论耗尽；17子页事件时commit=false保留。旧2fe仍failed/api_request_limit，不回填成功。Pro默认未全局启用。
- 原2fe129正文评论正式导入rev70；新f2c107正文评论导入rev71。三格式已独核。138快照=133本run(129正文评论+4派生媒体引用)+5旧项；144快照=114新run(107正文评论+7媒体引用)+30其他run项。更正此前“9旧项”推断；媒体引用不等于视频字节或转写质量。
- 两项旧交付：129任务 `83f47fbf-3bd2-41db-bf94-66aa23a0aaaa`、107任务 `4f00dd4a-b2f0-40ae-a03e-f36d2592c3fa`，ACK/finish通过而origin/metrics保真未过；原任务、字段和ACK经fresh SQL/完整包核保持，失败证据保留。纠正版source0、不重采：129→`025fa7d1-b5d2-451e-91e7-cd53787e8160`，107→`5141604d-411b-4284-bfd7-e682ee718f4c`。两者completed，236份观测的正文/评论/父子/media/origin/metrics交付字段与原规范记录和冻结导出完全一致，原ACK/envelope/finish哈希独审通过。236是两快照ACK总数，去重为131实体（同一视频正文1、评论130），不是236条独立新内容。工作台1526ACK、pending/quarantine/deferred0；旧2fe来源失败不因云交付完成变成功，新f2c仍是有界批次。
- 计数校准：f2c的40是guarded HTTP尝试，包含本机CookieBridge/Signer调用；另有Signer外部nav1，合计41受控尝试。浏览器资源请求及原生浏览器请求不由runner计数，平台专属请求总数未独立测。此前“40次平台来源请求”表述撤回，见COUNTER-SCOPE-CORRECTION.json。
- OTA69已签名发布；本机真实68→69通过非作者独审，原身份/队列/历史/进度/登录恢复摘要8字段保持。两原节点独立SQL均69、release摘要`b212cdbe63d85a9d0066aed6d54066f6b95f07951da60a7b38d38a5f6d47492e`，原task19/20仍2/2。另一台原生连续链不能由中央版本替代。
- 历史OTA四条failed/unexpected_error保留；当前native poll自然恢复current，但具体网络或IO根因未知。现有native吞stderr/非零通码需要补安全诊断分类。完整登出重登、机器中央全部逐步、全平台/OS、48h仍未全验；看门狗PAUSED。
- CookieBridge本机ping通过；原profile持久加载证据已完成。Signer两旧试验及f2c均正常停止，预算不复用；原浏览器/CookieBridge保留。审查曾whole-run clone跟随profile后失败，3临时目录root核已清除，部分复制清单未知；后续只允许固定数据白名单，规则已写AGENTS。

下一步：优先补native安全诊断分类、机器中央完整步骤与原任务登录恢复；继续其他Pro平台同输入正文/评论分页/媒体字节/导出验证，保持默认MC直至替换各维度通过。旧无snapshot/digest引用保留历史兼容，不能声称具备分布式观测绑定；新交付必须固定results_revision与record_sha256。不得重建未知任务、重复扫码或把批次上限称全部评论耗尽。证据及发现见E25–E27与本轮日志。

## 4. 项目地图

工作区根：`/Users/hubowen/Desktop/桌面 - 胡博文的MacBook Pro/pushpull`（下称WORKSPACE）。当前聊天cwd `/Users/hubowen/Desktop/爬虫` 是参考目录，不是正式源码仓。

| 位置（无绝对前缀时相对WORKSPACE） | 职责与实际边界 |
|---|---|
| crawler-extension/v4/src/ | 扩展：participant-background/session、agent、work-tabs、identity/api、pool、node-monitor、updater |
| crawler-extension/v4/build.py、updater/ | profile构建、Mac Swift助手、签名更新；构建器生成版本化worker |
| crowd-kol/server/crowd/v4/ | 中央SQL、迁移、Edge、机器工作台、后处理和测试 |
| .../multiplatform/dashboard.py、owner-ui.js | Owner创建/结果/登录/监控；workbench_cli是同一工作台客户端 |
| .../cloud_sync.py、mc_runner.py | 机器任务桥、SQLite outbox、外部MC执行与归一化 |
| .../account_sessions.py、browser_session.py | 持久会话、既有浏览器接入、账号核验；Windows差异尚未解决 |
| .../results_store.py、media_cloud.py、../postprocess/ | 实体版本/观测、媒体私有云、字幕/OCR/本地ASR；OCR不是全文听写 |
| .../supabase/functions/{crowd-access,crowd-gateway,crowd-machine}/ | 安装/参与入口、参与RPC、机器/统一任务及监控 |
| Supabase项目bdwrhshgdeghgyzwpxnl | 中央数据库；crowd-machine-media为已有私有媒体bucket；项目ID不是凭据 |
| crowd-pages/v4/releases/ | 安装包和OTA发布面，不是canonical源码 |
| http://127.0.0.1:45937/ | 本机工作台，其他设备不能直接访问loopback |
| https://app-lyart-eta-22.vercel.app/api/crowd/manifest | 正式安装元数据入口；最近已存生产回读见E02 |
| .crowd-launch/unified-workbench/ | 工作台配置、SQLite、作业运行资产；不复制其内容进交接包 |
| .crowd-launch/runtime-revisions/machine-steps-ed2cbd370253e241/ | 最近已采用工作台源码快照；工作树HEAD不是运行版本 |
| .crowd-launch/seven-platform-live/ | 原采集目录、会话和运行数据；不清理或复制登录资料作VM模板 |
| /Users/hubowen/Desktop/爬虫/references/mediacrawler-pro-2026-10-14/ | 8仓私有参考副本；SOURCE-MANIFEST.json固定SHA；未纳入发布仓或安装包 |
| outputs/collector-adversarial-audit-2026-10-14/ | 当前会诊、独立复现、正式65解包、未发布恢复检查点及Pro盘点 |
| outputs/unified-distributed-product-2026-10-14/execution/ | 两设备验收、回读、安装/OTA证据；PRIVATE文件不复制进交接包 |
| outputs/unified-crawler-product-2026-10-10/ | 统一PRD/技术规范/计划；需求范围可参考，10-10状态已陈旧 |

实际数据流：Owner→统一派发→参与者XHS pilot或机器七平台执行→本地checkpoint/outbox→中央逐条ACK→结果/评价/监控。现有统一入口下仍有两条执行链；不能把机器数据当人工奖励证据。

## 5. 代码版本与未提交资产

本地实查时间见快照的checked_at，三仓均分支 `codex/v4.0.6-handoff`：

| 仓库 | HEAD | 未提交边界 |
|---|---|---|
| crawler-extension | 03a38fe | OTA70已发布；其他未提交资产保持 |
| crowd-kol | 功能提交5f40ef3 | 中央机器步骤/共享登录状态与安全OTA合同正式采用；其他未提交资产保持，文档提交另见git log |
| crowd-pages | b6be7cd | 签名OTA70；固定ZIP提交2992d9ffc5388453ead9af0d1641af9da908a4f9；helper工具已发布 |

以上HEAD本轮实际读取。运行源码以第3节当前增量及E28采用冻结为准，不能以HEAD替代；不要reset/clean或覆盖其他改动。


## 6. 关键决定

- **保真优化。** 用户10-14明确要求；统一PRD K01–K06/R01–R08/P01–P10。优先Pro成熟能力，但全部能力逐项保留、适配、验收；没有证据不能标已完成。
- **统一合同，不强行统一引擎。** D2/D3证明两执行链尚未融合。任务/身份/回执/监控可以统一，已有平台解析不必全部重写。
- **分开五种状态。** 参与身份、平台会话、页面代际、任务租约、业务回执；R1–R7表明它们不能互相替代。
- **原结果先对账。** 保留UUID/payload/outbox/回执；临时、永久、登录、未知结果分别处理。未知不盲重试，也不能永久无解困入口。依据AGENTS、OPTIMIZATION_RULES、D1/D6。
- **原两设备和原预算保留。** task19/20各两条，不重建身份/任务制造成功；评分、旧3.x资产、54私人版保留。实验与看门狗不自动启动。
- **双路线+非作者独审。** 官方联网证据与项目独立推演并行，衡量耗时、资源、人工操作和质量；每项实质修改独立review/debug。依据AGENTS/OPTIMIZATION_RULES。
- **Pro购买状态已变。** 当前可读8私仓，不再写“无源码权限”；但静态读码不等于已运行或已接入。各仓许可保留；学习参考继续，公开再分发须核对实际许可，私码不混进公开包。
- **不整套换Go或云浏览器。** Pro Go存在账号池/回复等非等价项；云浏览器不自动继承原本地登录。来源E09/E10。可选通道先证收益和完整性。
- **手机单独验收。** 桌面扩展和Mac助手不证明手机常驻执行；控制门户不能代替用户要求的本机采集后宣称完成。

## 7. 未解决问题

| ID/优先级 | 问题、证据与影响 | 解决所需证据 |
|---|---|---|
| R1–R4 | 本机68→69→70已过，本机70/另一原节点仍69各有准确release摘要；完整登录恢复/真实评论休眠分页及远端原生连续链未全验 | 保持原任务、同账号，以原ID继续/准确partial/ACK证明，不新建任务制造成功 |
| D1 | 槽释放、原ID交付恢复、Owner入口已上线；当前无真实坏组可验 | 实际defer→原ID ACK→finish链；不人为破坏用户数据充当验收 |
| D2–D3 | 机器中央phase/Pro保存页/ACK已部署并source0实证；MC原生逐页、通用参与者派单及supervisor child PID/预算标记时间仍不完整 | 任意任务两节点不重复领取、完整中央来源至ACK时间线 |
| D4–D7 | 用户中台恢复、克隆身份围栏、跨任务去重和并发仍未全验 | 同UID不清outbox恢复、双节点epoch竞态、失败隔离与受控并发 |
| Pro接入 | CookieBridge正式加载已跨重启通过；原Bili SignSrv三试验均已正常停止且预算不复用；CookieBridge本轮恢复、原XHS同组件安装已获新增授权但尚待目录选择；XHS/DY新Signer仅validate准入 | 正常重启仍有原扩展；只连127.0.0.1:8274；明确client/native pong；同输入正文、分页回复、媒体、导出 |
| 审查容量 | 3名独审代理本轮多次返回模型容量错误 | 不改用未经要求的新模型、不把未出结论的检查算通过；接续已有审查工件 |
| 全端及质量 | Windows/VM/mobile、全评论媒体字幕、ASR质量和48h未全验 | 分OS/平台/维度的真实证据，不以Mac样本外推 |


代码行、复现与状态分级见E06–E14。作者的“已解决”必须由差异、测试原件和独立证据支持。

## 8. 接力可做与推进顺序

安全起步：读取源码/文档、uname/pwd/git status/log、SHA比对、既存脱敏证据；用已授权连接器执行明确只读查询。测试先审其副作用。不要为了核验调用claim/start/finish/arm，或启动会自动执行任务的服务。

下一步：先读E28本轮正式采用与真实source0步骤、OTA70独审，不重复创建这些任务或重发OTA；继续原XHS CookieBridge安装后的本人会话核验、Pro分页/登录恢复及其他平台同输入媒体字节/导出/真实云验收，补MC原引擎逐页。不得重建未知任务、重复扫码或把批次上限称全量完成。证据及发现见E25–E27与本轮日志。


## 9. 维护与共享

唯一当前状态为本文件。WORKSPACE/HANDOFF.md和爬虫/HANDOFF.md仅指针。[证据](handoff/EVIDENCE.md)、[日志](handoff/CHANGELOG.md)、[模板](handoff/ENTRY_TEMPLATE.md)组成精简交接包。

本轮发布范围仅这四份Markdown及仓库AGENTS.md；授权目标为GitHub `huming0018-dot/crowd-kol` 的 `codex/v4.0.6-handoff` 分支。[在线固定入口](https://github.com/huming0018-dot/crowd-kol/blob/codex/v4.0.6-handoff/docs/HANDOFF.md)。本次同步状态以变更日志实际推送记录为准；尚未创建另一个在线共享页面。源码功能提交与交接文档提交分别记录。证据索引中的JSON、PRIVATE文件、运行数据与原始日志均只在本地，未随五份Markdown发布；在线接力者若不能取得原件，须标未核验，不把相对本地路径当作在线证据。

给接力者的固定指令：先读取此入口、EVIDENCE.md和CHANGELOG.md，核对所涉源码与证据日期，再按第8节继续。每轮结束更新状态、证据和日志；无法核验就明确标未知。外部bot只收到Markdown时只能读取已记录状态；要核验原件还须按最小范围提供相应脱敏JSON/产物，不能声称已查询线上。

旧docs/HANDOFF.md保存在Git `81ab4ae:docs/HANDOFF.md`，blob `cc09e64b93a11979b18355c3d0db45b383d52e14`；旧4.2.0/4.2.5说明只作历史。

交接包不含凭据值；不要添加.env、Cookie、密码、token、私钥、PRIVATE邀请或原始登录资料。路径/版本/摘要可以记录；分享前最小披露复核。不要将全部outputs或私仓源码打包外发。
