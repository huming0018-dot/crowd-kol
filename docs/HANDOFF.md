# 分布式采集系统｜固定交接入口

更新：2026-10-16 11:30 CST，Asia/Shanghai。维护：Codex /root。本文件维护当前状态；重要历史留在日志。**交接是每轮工作的伴随机制，主线继续推进。**

## 1. 接力规则

1. 先读本文件、[证据索引](handoff/EVIDENCE.md)、[变更日志](handoff/CHANGELOG.md)，再读工作区 AGENTS.md 和涉及的模块。
2. 核对环境、分支、未提交改动和证据日期。聊天摘要、作者自述、测试目录存在、进程在线，都不能替代实际验收。
3. 无法访问或核验时明确说明缺口，标“未知/未验证”，继续可独立完成的工作，不声称已同步。
4. 每轮结束都更新日期、本轮结论和下一步；主要改动后，用[接力模板](handoff/ENTRY_TEMPLATE.md)更新本文件相关状态和证据，向日志追加记录；不复制整段对话。
5. 用户新指令优先。读过交接包不等于获得新采集、部署、付费或外发权限。

## 2. 目标、范围与阶段

目标：中心数据库动态分配任务到用户终端；本地复用本人登录、静默采集、耐久回传；中心逐条确认、监控步骤、定位异常。Owner 不应手工分配账号或 HTTP 请求。

必须保留：Kimi/现有参与者流程、身份、评分、暂停继续、outbox、回执、OTA；吸收 MC/已购 Pro 的平台、评论回复、媒体、推荐、账号、断点与分析能力。PC/Mac/VM/手机均在长期目标中；手机控制与手机本机执行分别验收。有效会话尽量长期复用，不能承诺 Cookie 永不过期。

当前阶段：本地13项映射修复已正式运行65679/wb-progress-45b8e4f7-a1346798，实际采用独审23750a+idle803731+固定Python9ead通过；12实际源码变更18d14b35已推送。中央仍Edge40。原WB续采af947/epoch4已实际新增1评论ACK，现31；真实4.28MB原图Owner核验、私有云保存/回取及R88三导出已由非作者32a77277独审。仍failed74/partial，原累计10of12剩2；不再请求已确认缺口或重复下载。原任务登录重登恢复、其他Pro完整平台/连续OTA/跨端/48h未全验。

2026-10-14新轮授权：并行实现中央槽释放、Owner恢复入口、Pro成熟能力桥；独审后正式采用并做原范围真实云回执、登录恢复与连续OTA验收。上轮只读交接限制已结束。保留原身份、原任务和每台两条预算；不自动扩额度、外发Pro私码、重置凭据、arm试验或恢复看门狗。

## 3. 当前状态

### 本轮产品校准｜先完成v2.2整产品计划，旧候选已收束

- 用户最新主线：先定义完整交付产品/机制/功能、盘点资产、双路线外部复用研究、明确ponytail+caveman工作法及技术栈、按结果倒推。原E63完整入口保存在[截至E63快照](handoff/archive/HANDOFF-through-E63-20261016.md)。固定执行基线为[统一产品与交付计划](product/PRODUCT-PLAN.md)，并读[架构](product/ARCHITECTURE.md)、[资产](product/ASSETS.md)、[研究](product/RESEARCH.md)和[非作者审查](product/PLAN-REVIEW.md)。当前事实仍看本HANDOFF，不把计划当部署。
- 本轮实际：完整读用户v2.2原件（SHAaee488f2），三个代理分资产/架构/独审；主控完成22能力U01–U22、8融合包F0–F7及工期/验收。两轮规划审查关闭本地游标vs云ACK、051vs065候选混用、四评分域及已有公式、Vox/第三域前置和重复审批等问题。仅文档/研究，没有新增采集、候选采用、云部署或恢复watchdog。
- 资产事实：现toolbox已有M0–M7，不重建框架；版本表标050生产但实际wheel/服务待fresh，051 PG查询候选源码85项一致；另谱系065 M4生命周期NOT_PASS，不能按semver覆盖。美食/软件发布双包存在，历史工程消费摘要不等完整生产双消费者。v2.1原件在已查范围未找到，明确未读。
- 工程收束：Owner无有效工作续采提示候选a44ea未独审/采用；DY strict与async受控审已收束982fb，media cap仍未独审、Owner新run会话caller未接线，最终共享reader组合未全审；不再写成“正在采用”。既有owned fixture已清理，不新增来源填洞。
- 下一项按既有授权F0→F1：核当前toolbox实际wheel/接口，以已ACK真实材料建capture→RAW薄适配，复用现clean/scorer/audit/consumer交付完整纵切，不重抓；F2知识生命周期、F3 Pro/会话、F4参与端/OTA按槽位并行独审。完整产品包括M0–M7及Kimi参与端，不继续只围单平台调试。原任务/预算/unknown/登录本人要求、云回执/贡献奖励/OTA继续保留。


### E63｜已正式采用；原任务新增回复、原图云保存回取与导出通过独审

- **代码/独审**：本地V2冻结a854f94f8d01afb667b55c7383f5c881e42156c5195ecf3f33a566e7cc173865，13映射（12实际变更/1新模块）保留原Pro SDK/多origin journal与MC媒体。非作者8ad851cf独跑原7组/38回归+新边界，原missing-ledger整链反例已修：初始化后缺失/损坏计数未知，不finish或重发；仅同次执行可证明未初始化且0请求时保0。正常/预算73/取消保持。旧fdda及其失败证据保留；旧ba074自引用空SHA未执行，新准备d135c9c排自身，另初次V2 baseline父引用读取错误已终止并保metadata，无正式影响。
- **正式采用/发布**：批准冻结a7a5f97b、非作者采用编排fe3b896f；root采用65679，旧53987停。实际非作者23750a核13exact+444其他/fullset/1新模块、五库与真实备份schema/raw相等、189资产及fresh6账号24产物28WB3ZH保持、HTTP Fleet41719/Ownerfb563。初瞬时claiming记录未当idle，附证803731实际idle/outbox0；固定Python再核9ead92d通过。12源码18d14b35a7354d945beb01fd5bb7ab7e03b50863 push0/远端同。默认MC/显式Pro范围及原浏览器保持，中央E62的Edge40/steps68/权限不变。
- **真实原任务/步骤**：Owner原卡预览→仅确认一次新grant d5d4083d-2ef6-42cb-92ce-ab37abc509f5；原task e2d613f2、child c012ccf4、worker均保持。local af947a96-1a41-4d51-a6ea-2312c84c9b42/cloud4c1d810d-df5e-401a-bc84-274ca29fa68a epoch4。旧30typed envelope/receipt保持，新回复5264011553672116（parent5264010781918759）1条已ACK，总31。6实体按各自origin复用；本轮实际3次（pro2/media1），原累计10/12剩2/reserved0。36云steps与本机完整相等，8来源事件匹配，最后paused/failed/74诊断已上云；账号authenticated同gen/ref。仍wb_reply_terminal_incomplete/74，根/完整checkpoint不推进，不将可访问部分当全量。
- **真实媒体/导出/云回取**：实际JPEG 4,284,573B/1080×8101/SHA5240cdbf5116f4fd73495d22bfad4f5050afee846ddd09340fec008e6c935598；通过原Owner“核验已采原图→保存至私有云→下载云端图片”。云v3 ready artifact067979d8，37字段/原正文epoch1→latestgrant epoch4/私有bucket对象精确。非作者自己GET与source、Owner附件、浏览器下载四份字节及像素相等。JSON/JSONL/CSV真实HTTP R88各33数据行，全部typed/entity version/body hash同；仅1新评论，其余历史/复用/媒体，JSONL另有manifest首行。实际增量最终独审32a772772d47b1a9f9609d6e5d3cd2f64fce865b545dcf13f1a7b7e93a87f6e3，报告一次锁定。核证早先raw-URL hash、JSONL首行、record_hash投影假设错误均留初失败并按成熟合同另名修正，没有改gold或产品造通过。
- **未完/下一步**：完整回复仍有平台终页缺口，不再重抓同页或重复同图消耗剩2。central正候选修Owner预览“原1份”混淆历史31及无未访问工作仍可继续的提示；未采用。DY原homefeed300/16字段已作受控原合同正文87评论/原封面对照，但视频第13次超原12、匿名作者不可重建，未放行完整替换；组件独审另发现bool计数与同步签名阻塞取消，窄overlay正在修，产品newrun会话授权caller尚未闭环。Bili本轮纯本机元数据：原Bridge967…离线且缓存约8h过期，d261在线无Bili；原account check_failed/gen1/verified_at0/provider native_persistent，不能据此声称平台已登出。Bili暂停1/12、ZH stopped12/12保持；原登录恢复/连续OTA/其他平台/跨端/48h未全验，完整目标active/watchdog暂停。

| 能力 | 已核当前状态 | 未完成 |
|---|---|---|
| 中央/步骤/回执 | Edge40正式；原WB31ACK、最新36steps/8来源真实匹配 | 其他平台及两节点完整链 |
| 原WB恢复/媒体 | 新1回复+真实图云v3/回取+R88三导出独审 | 完整回复缺口仍保；无工作不再续采的Owner提示待改 |
| Pro平台/会话 | WB有限整链实证；DY优先原handler/循环/纯签候选 | DY媒体/本人会话caller/其他平台同输入保真与重登恢复 |
| 参与者/评分/OTA | 现有正式实现及历史远端71证据保持 | 连续原生升级/两节点恢复/全端48h未全验 |

[截至E62完整快照](handoff/archive/HANDOFF-through-E62-20261016.md)逐字保留此前入口，原SHA 9d97dd145726f9fb12056865daaedf63603544dc1d994c71da2f5d20d2a030b0；更早E60快照及重要日志/决定继续保留。当前入口只维护现态，不逐轮复制全文。

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
| .../results_store.py、media_cloud.py、audio_cloud.py、../postprocess/ | 实体版本/观测、视频/图片/音轨私有云合同、字幕/OCR/本地ASR；音轨不是MP4，OCR不是全文听写 |
| .../shared_request_budget.py、pro_media_integration.py、pro_media_parent.py、bili_media_child.py | Pro正文/评论保留原协议，原MC仅媒体子进程；同run共享Python尝试预算，owned POSIX进程组资源收尾；Windows未验 |
| .../supabase/functions/{crowd-access,crowd-gateway,crowd-machine}/ | 安装/参与入口、参与RPC、机器/统一任务及监控 |
| Supabase项目bdwrhshgdeghgyzwpxnl | 中央数据库；crowd-machine-media为已有私有媒体bucket；项目ID不是凭据 |
| crowd-pages/v4/releases/ | 安装包和OTA发布面，不是canonical源码 |
| http://127.0.0.1:45937/ | 本机工作台，其他设备不能直接访问loopback |
| https://app-lyart-eta-22.vercel.app/api/crowd/manifest | 正式安装元数据入口；最近已存生产回读见E02 |
| .crowd-launch/unified-workbench/ | 工作台配置、SQLite、作业运行资产；不复制其内容进交接包 |
| .crowd-launch/runtime-revisions/wb-progress-45b8e4f7-a1346798/ | E63当前65679；13映射/12变更/1新模块，实际独审23750a+idle803731+固定Python9ead；云40/步骤68。原WB31ACK/累计10of12剩2，真实原图云v3/回取/R88三导出独审32a77277，完整回复仍partial74；默认MC/原身份/OTA及其他源码保持，snapshot不等于Git HEAD |
| .crowd-launch/seven-platform-live/ | 原采集目录、会话和运行数据；不清理或复制登录资料作VM模板 |
| /Users/hubowen/Desktop/爬虫/references/mediacrawler-pro-2026-10-14/ | 8仓私有参考副本；SOURCE-MANIFEST.json固定SHA；未纳入发布仓或安装包 |
| outputs/collector-adversarial-audit-2026-10-14/ | 当前会诊、独立复现、正式65解包、未发布恢复检查点及Pro盘点 |
| outputs/unified-distributed-product-2026-10-14/execution/ | 两设备验收、回读、安装/OTA证据；PRIVATE文件不复制进交接包 |
| outputs/unified-crawler-product-2026-10-10/ | 统一PRD/技术规范/计划；需求范围可参考，10-10状态已陈旧 |

实际数据流：Owner→统一派发→参与者XHS pilot或机器七平台执行→本地checkpoint/outbox→中央逐条ACK→结果/评价/监控。现有统一入口下仍有两条执行链；不能把机器数据当人工奖励证据。

## 5. 代码版本与未提交资产

以下为相应发布回执/证据时点的版本；本次整理未向远端发起新查询。三仓均分支 `codex/v4.0.6-handoff`：

| 仓库 | HEAD | 未提交边界 |
|---|---|---|
| crawler-extension | d7707cb82d26e0594ef8220299a5e8c3a37cf8cd | 71登录状态诊断源码；包签名发布/缓存已证，远端节点71登记/摘要/完成事件已证；本机最后已证70、当前参与端运行未核 |
| crowd-kol | 18d14b35a7354d945beb01fd5bb7ab7e03b50863源码push0/远端同；云69781d1/partial7a586fa/E60旧源保留 | 当前65679/wb-progress-45b8e4f7-a1346798/云40；原WB31ACK/10of12剩2；文档发布另回执 |
| crowd-pages | 0a3bc4f04d0b2ffafd4c8619096ba6f3e28ea900 | 签名OTA71；固定ZIP提交deaab37b7eca21056ee2007e9d7aaeef90e15960；远端71登记/摘要/完成事件已证，本机71采用及远端native文件链未验 |

crowd-kol所列发布回执本轮已读；其余仓沿先前已核版本，不能当本次新鲜HEAD。运行源码以第3节E63及e63-progress-runtime-adoption批准冻结/现场独审为准，并保留continuation-current-runtime-adoption的17文件继承链，不能以HEAD替代；不要reset/clean或覆盖其他改动。


## 6. 关键决定

- 2026-10-16 E53：先核实原持久浏览器的凭据保护/启动模式，再选择复用方式；测试浏览器的默认mock/basic参数及受控媒体整链不能证明现有真实登录可复用。优先已成熟且已授权的Bridge/CDP入口；不盲改启动参数反复试原profile，不凭Cookie元数据为0推定本人登出或已证删除。来源：MODE-RISK-EVIDENCE、INDEPENDENT-COOKIE-METADATA及5663止损采用。

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

- E53历史观察（当前连接请求已expired，见下方E54）：Bili原生读取模式未验证，已在任何profile IO/spawn前禁止；真实新诊断known failed且0官方nav。旧400具体原因、旧marker影响、CookieDB当前0与早前报告19的因果均未知。9222连接仍pending/0targets/未导入/未绑定；必须先核原授权浏览器连接和官方同主体，不能靠受控链、profile名称或缓存标志放行。

| ID/优先级 | 问题、证据与影响 | 解决所需证据 |
|---|---|---|
| R1–R4 | fresh2026-10-16 OTA只读核：远端原6a88已上报71+正式cfe4摘要，当前注册/健康及昨22:39完成事件支持实际客户端采用；远端native文件/原生连续回滚链未直验。本机3cde仍70、心跳自昨停止，helper8198正常/签名71已缓存；原903d现Chrome71456已正常重开、Bridge AX启用，但participant登记仍缺，目录面板32502待本人选择，原storage仍在；当前参与者outbox值未读未知。原19/20均complete2/2，原身份保持；先恢复原profile扩展，不动日常同ID3.5.2 | 本机原ID/用户/outbox/2回执保持、自然71apply/reload/原生ACK/后续current；两节点连续原生链分别取证 |
| D1 | 槽释放、原ID交付恢复、Owner入口已上线；当前无真实坏组可验 | 实际defer→原ID ACK→finish链；不人为破坏用户数据充当验收 |
| D2–D3 | E44已采用Pro真实Python transport与durable readback同journal接线，历史E44新XHS41逐条ACK/105步骤、最新E47另一新任务40ACK/99步骤分别独立实证；既有机器phase/Pro保存页/ACK也已部署；MC逐页机制已在E35采用，E36 Bili24来源事件根页保存缺失保留；E37新批次25步骤含选中部分保存已证，游标commit仍未证；通用参与者派单及supervisor child PID/预算标记时间仍不完整 | 任意任务两节点不重复领取、完整中央来源至ACK时间线 |
| D4–D7 | 用户中台恢复、克隆身份围栏、跨任务去重和并发仍未全验 | 同UID不清outbox恢复、双节点epoch竞态、失败隔离与受控并发 |
| Pro接入 | E44新XHS41来源/105中央步骤/R77导出/41ACK有限实证，最终独立现场有限范围通过；旧94→新40的有效阈值变化已有证据，完整数据集保真仍未通过；媒体false不含字节云链。Bili最新原生诊断为已知失败/Bridge0/nav0；旧Bridge101仅历史，原3cda暂停1/12，Pro音轨云和全量仍未验。E40 Bili单正文音轨组合已采用及现场独审。原XHS本人self已通过，e7真实正文/94评论、三导出/95云ACK独审，软阈值/86状态已采用；临时Signer已停。图片新显式代理通路已取得同字节、工作台读取/导出/浏览器下载通过；E34原单图图片云合同/回取通过，自动来源媒体仍缺。微博E63已31正文/评论ACK及原图云v3真实保存回取独审，完整评论回复缺口仍保，其他平台Pro合同未补齐；E36 B站同输入有界批次正文/17评论/音频/导出/18ACK通过，但缺旧1回复/根保存事件/全视频仍未证 | 图片云合同/自动来源触发，同输入其他平台完整字段、分页回复、媒体、导出与逐条回执；不以工具测试替代真实成功 |
| 审查容量 | 历史有模型容量错误；本轮已完成媒体/五库/导出/OTA独审，WB正式接线及采用独审已通过，原单图图片云实际合同/回取与正式Owner入口独审通过，无新外部服务凭据接入 | 后续仍须非作者实际审查，不能把未出结论算通过或自行改模型 |
| 全端及质量 | Windows/VM/mobile、全评论媒体字幕、ASR质量和48h未全验 | 分OS/平台/维度的真实证据，不以Mac样本外推 |


代码行、复现与状态分级见E06–E14。作者的“已解决”必须由差异、测试原件和独立证据支持。

- E54历史：10723/十文件/Edge35实际独核99f988与源码efc4eb75远端回读已完成；真实CDP绑定和官方同主体仍缺，原请求expired。原Bili pause1/12/ACK0不变，账号模式安全保护不放松。

- E55历史：15194/五文件增量/65844dfe已实际独核发布；原工作台Owner选择入口可见但没有执行绑定/核验。07:18连接expired/0targets/未绑定。独立steps-only持久变更仍被审批拒绝、未执行，明确授权待答；不把UI或离线102检查当中央诊断上线。

## 8. 接力可做与推进顺序

先读本轮[统一产品计划](product/PRODUCT-PLAN.md)和两份独审，按F0–F7工作包推进；原E63实际采用/真实WB证据继续保留。不要重新部署已采用13源，不为填满预算重跑原WB终页/同图，不恢复已暂停任务。

1. F0先核toolbox实际生产wheel/版本、051与065独立差异；选已ACK真实样本锁输入/字段映射，禁止整包升级NOT_PASS候选。
2. F1最小capture→RAW→现clean/scorer/audit/consumer纵切，先给消费者可用结果；F2知识生命周期/F3成熟Pro来源与会话/F4原参与者恢复和连续OTA按计划限槽并行，每项非作者独审。模型分析不是首个确定性链前置。
3. 原WB31ACK/累计10of12剩2、partial74保留；DY视频预算/本人会话、Bili原连接、贴吧原URL/主体、ZH stopped12、参与端两原设备/OTA/跨端/48h分别保未验。原两设备各两条，不重建身份制造通过。
4. 主计划的阶段与指标是目标，不是当前完成。每轮更新日期/结论/下一步，主要变更记录精确版本/验证/采用/真实结果/独审，不靠测试数宣布业务完成。

看门狗仍暂停，未自行arm实验。D1/D2门禁通过后的48h另从真实开始计算。

## 9. 维护与共享

唯一当前入口为本文件；WORKSPACE/HANDOFF.md和爬虫/HANDOFF.md只作指针。[证据](handoff/EVIDENCE.md)、[日志](handoff/CHANGELOG.md)、[接力模板](handoff/ENTRY_TEMPLATE.md)及仓库AGENTS.md共同维护。

[在线固定入口](https://github.com/huming0018-dot/crowd-kol/blob/codex/v4.0.6-handoff/docs/HANDOFF.md)随已授权分支更新。E63当前状态及本轮产品规划文档发布以爬虫/outputs/product-integration-plan-2026-10-16/PUBLISH-RECEIPT.json的commit/push/remote为准；无此回执不认发布。原计划中的HANDOFF-E63-PUBLISH-RECEIPT未生成，不补造旧回执；E62更正发布见HANDOFF-E62-CORRECTION-PUBLISH-RECEIPT.json，旧回执保留，源码提交与文档提交分开；缺回执不认定已发布。[截至E60完整历史](handoff/archive/HANDOFF-through-E60-20261016.md)保留旧入口全文和原SHA，重要决定及发布记录继续在CHANGELOG/EVIDENCE中。

接力者先读本入口、证据、日志并核日期/所涉源码与原件，再按第8节推进；主要改动按模板回写，每轮结束更新日期、结论、下一步。读不到原件时明确标未知/未核验，不把Markdown中的记录当自己查询线上所得。

JSON、PRIVATE、运行数据和原始日志默认仅本地，不随交接文档外发。按最小范围提供脱敏证据；不添加.env、Cookie、密码、令牌、私钥、邀请或登录资料，不打包全部outputs/私仓源码。旧4.2.0/4.2.5等只作历史，旧入口Git81ab4ae/blobcc09e64b保留。
