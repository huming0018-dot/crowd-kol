# 分布式采集系统｜固定交接入口

更新：2026-10-15 16:26 CST，Asia/Shanghai。维护：Codex /root。本文件维护当前状态；重要历史留在日志。**交接是每轮工作的伴随机制，主线继续推进。**

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

- **16:26现态优先**：自有修复8文件提交23f7ae48648b43893935dd91729448168f849873；正式工作台已采用pro-platforms-bbbda8cfbc3c878d/PID52074，原42837正常退出。8运行文件冻结，原5锁/5库实际备份及原行、配置和历史任务在采用守护内保持；非作者live独核通过：385其他源码逐字节相同、123历史配置/任务及5库逐原行等于实际备份。默认MC保持，没有全局启用Pro。云端实际1624ACK/pending0，原两参与任务与额度不变。
- 原XHS本人登录后官方200/code0/self摘要通过；先前f4de 77/check_failed/观察0保留，未抹成成功。临时Signer整串Cookie猜账号锁由独审修正，身份仍固定Bridge client和官方self摘要；新有界e7e01fbb-5e8e-47b3-b473-5d24fc77f1cc已真实completed，1正文+94评论（44根/50回复），46 guarded HTTP尝试含loopback，34.609秒意图至终态；不是平台专属总请求或端到端/P95。43持久页/checkpoint独核、可访问页链exhausted不代表平台全量。旧548失败73不重启；当前原会话已恢复并绑定e7，不能用新任务替代旧任务恢复验收。
- 真正发现并修复：max_comments20只写聚合config，XHS/DY从base_config读取导致本次94条超阈值。原94及全部失败保持；2行初始化补接、原SDK实际processor/SQLite/checkpoint独审正反例通过。语义为整页含回复软阈值（20可保存24再停），不是硬20；修复后尚无新真实来源cap验收。未知核验失败新86与明确登出77分开、Owner中文提示、知乎/贴吧字幕module hook不依赖factory一并独审并采用；全MC测试仍有4继承fixture失败，不能称全套绿色。
- e7正式导入冻结rev72，JSON/JSONL/CSV三格式97项=95新正文评论+1新媒体引用+1旧媒体项；双哈希保真比较已重算来源/语义/正文合同，旧10实体无缺失或字段变化，85是新观察而非全新发布。真实新媒体字节0、URL引用与旧MC不同，媒体完整性仍未通过。正在复用既有安全下载器处理已保存引用，不重采正文评论，不把图片伪成云视频。
- 云任务2dcf771d-c73e-4e22-b4f0-0b689ba8c2aa沿唯一创建意图实际completed，95唯一received回取逐字段typed等同冻结rev72；source spent/reserved0，未再采来源。95份原始envelope/hash/UUID/receipt与outbox逐条非作者独核通过，finish/source0、52条交付阶段中央步骤seq7–58连续至completed；不是新来源执行。临时Signer47739已正常停止，22native签名/0外部nav/failed=false；浏览器和CookieBridge保留。其他平台、完整原任务重登、远端连续OTA和48h仍未全验。

- XHS现存图片下载独审22测试+7原下载器负例通过后，root唯一执行实际失败；INTENT保留、资产目录空、无下载回执，原3文件SHA保持。旧driver丢失败阶段/次数，根因和实际GET次数未知；后续受限环境DNS gaierror；主机实际resolved1/non_public1，当前应被安全下载器拒绝，两者都不证明旧因。没有自动重试、没有上传图片。安全诊断journal已补固定错误码/阶段/计数，23测试+7下载负例+2失败journal负例独审，工具仅本地就绪、未重执行旧意图；已定位现有云合同仅MP4，不可伪装图片。平台只读优先矩阵优先B站同输入媒体/微博新adapter/知乎；B站旧f2c与75da输入不同不得拼证据，Pro知乎creator实际仅answers、articles/videos客户端存在不等已覆盖。见E31补充。

- 中央机器步骤：SQL迁移20261015062743、错误码迁移20261015062750及crowd-machine Edge24已部署；原worker/claim/run/epoch绑定、耐久步骤/坏组隔离/Owner分页已独审。此前source0三条及6步骤通过，当前新增95条交付阶段52步骤通过；MC原引擎逐页/所有平台来源全过程仍缺，不能称全程监控完成。
- OTA与原参与者：源码03a38fe、通道/工具b6be7cd，签名70 seq2026101570；本机原helper已采用8198638a通用binary，真实68→69→70/原身份队列历史/任务19、20各2条保持及云OTA事件已独审。另一原节点最后14:57实查69，未fresh核70或原生连续链。旧12条unexpected_error保留，新自然ota_*故障尚未现场；升级后旧Chrome消失原因未知，没重发apply。固定ZIP2992d9f/包摘要见E28。
- 旧B站/云资产：2fe来源failed/api_request_limit保持；新f2c有界批次1正文20根86回复、40runner+1Signer受控尝试（不是平台总数）。两份纠正source0云交付236观察=131去重实体，正文/父子/origin/metrics/冻结版本/回执独审已通过，不能当236新内容或全评论耗尽。保留旧保真失败与未知状态，详E25–E30。
- 48h实验和看门狗仍未启动/PAUSED。默认MC保持，后续Pro平台须逐维度同输入证明；手机/Windows/VM、本轮真实评论软阈值、图片云链、长视频质量及远端OTA仍有缺口。重要历史时点与首次失败保存在E25–E31及CHANGELOG，不把旧阶段候选状态当当前事实。

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
| .crowd-launch/runtime-revisions/pro-platforms-bbbda8cfbc3c878d/ | 当前已采用工作台源码快照；工作树HEAD不是运行版本 |
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
| crowd-kol | 功能提交23f7ae4 | 86/字幕窄修/中文UI/评论软阈值已正式采用；Git远端23f7ae4实际核同SHA，live非作者独核通过，其他未提交资产保持 |
| crowd-pages | b6be7cd | 签名OTA70；固定ZIP提交2992d9ffc5388453ead9af0d1641af9da908a4f9；helper工具已发布 |

以上HEAD本轮实际读取。运行源码以第3节当前增量及E31采用冻结为准，不能以HEAD替代；不要reset/clean或覆盖其他改动。


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
| Pro接入 | 原XHS本人self已通过，e7真实正文/94评论、三导出/95云ACK独审，软阈值/86状态已采用；临时Signer已停。图片真实下载失败、无字节/云保存；其他平台Pro合同未补齐，B站旧两样本非同输入 | 当前图片安全诊断/字节/云合同，同输入其他平台完整字段、分页回复、媒体、导出与逐条回执；不以工具测试替代真实成功 |
| 审查容量 | 3名独审代理本轮多次返回模型容量错误 | 不改用未经要求的新模型、不把未出结论的检查算通过；接续已有审查工件 |
| 全端及质量 | Windows/VM/mobile、全评论媒体字幕、ASR质量和48h未全验 | 分OS/平台/维度的真实证据，不以Mac样本外推 |


代码行、复现与状态分级见E06–E14。作者的“已解决”必须由差异、测试原件和独立证据支持。

## 8. 接力可做与推进顺序

安全起步：读取源码/文档、uname/pwd/git status/log、SHA比对、既存脱敏证据；用已授权连接器执行明确只读查询。测试先审其副作用。不要为了核验调用claim/start/finish/arm，或启动会自动执行任务的服务。

下一步：先读E31的真实XHS来源、冻结rev72导出与95云交付、评论阈值修复及正式采用；非作者live/原始ACK独核已通过，接着修现存XHS媒体诊断与字节链路，随后按优先矩阵推进其他Pro平台同输入正文/分页/媒体/导出。不得重建e7/95云任务或重发OTA；原任务恢复与MC原引擎逐页仍要单独验。不得重建未知任务、重复扫码或把批次上限称全量完成。证据及发现见E25–E27与本轮日志。


## 9. 维护与共享

唯一当前状态为本文件。WORKSPACE/HANDOFF.md和爬虫/HANDOFF.md仅指针。[证据](handoff/EVIDENCE.md)、[日志](handoff/CHANGELOG.md)、[模板](handoff/ENTRY_TEMPLATE.md)组成精简交接包。

本轮发布范围仅这四份Markdown及仓库AGENTS.md；授权目标为GitHub `huming0018-dot/crowd-kol` 的 `codex/v4.0.6-handoff` 分支。[在线固定入口](https://github.com/huming0018-dot/crowd-kol/blob/codex/v4.0.6-handoff/docs/HANDOFF.md)。本次同步状态以变更日志实际推送记录为准；尚未创建另一个在线共享页面。源码功能提交与交接文档提交分别记录。证据索引中的JSON、PRIVATE文件、运行数据与原始日志均只在本地，未随五份Markdown发布；在线接力者若不能取得原件，须标未核验，不把相对本地路径当作在线证据。

给接力者的固定指令：先读取此入口、EVIDENCE.md和CHANGELOG.md，核对所涉源码与证据日期，再按第8节继续。每轮结束更新状态、证据和日志；无法核验就明确标未知。外部bot只收到Markdown时只能读取已记录状态；要核验原件还须按最小范围提供相应脱敏JSON/产物，不能声称已查询线上。

旧docs/HANDOFF.md保存在Git `81ab4ae:docs/HANDOFF.md`，blob `cc09e64b93a11979b18355c3d0db45b383d52e14`；旧4.2.0/4.2.5说明只作历史。

交接包不含凭据值；不要添加.env、Cookie、密码、token、私钥、PRIVATE邀请或原始登录资料。路径/版本/摘要可以记录；分享前最小披露复核。不要将全部outputs或私仓源码打包外发。
