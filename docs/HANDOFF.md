# 分布式采集系统｜固定交接入口

更新：2026-10-16 09:54 CST，Asia/Shanghai。维护：Codex /root。本文件维护当前状态；重要历史留在日志。**交接是每轮工作的伴随机制，主线继续推进。**

## 1. 接力规则

1. 先读本文件、[证据索引](handoff/EVIDENCE.md)、[变更日志](handoff/CHANGELOG.md)，再读工作区 AGENTS.md 和涉及的模块。
2. 核对环境、分支、未提交改动和证据日期。聊天摘要、作者自述、测试目录存在、进程在线，都不能替代实际验收。
3. 无法访问或核验时明确说明缺口，标“未知/未验证”，继续可独立完成的工作，不声称已同步。
4. 每轮结束都更新日期、本轮结论和下一步；主要改动后，用[接力模板](handoff/ENTRY_TEMPLATE.md)更新本文件相关状态和证据，向日志追加记录；不复制整段对话。
5. 用户新指令优先。读过交接包不等于获得新采集、部署、付费或外发权限。

## 2. 目标、范围与阶段

目标：中心数据库动态分配任务到用户终端；本地复用本人登录、静默采集、耐久回传；中心逐条确认、监控步骤、定位异常。Owner 不应手工分配账号或 HTTP 请求。

必须保留：Kimi/现有参与者流程、身份、评分、暂停继续、outbox、回执、OTA；吸收 MC/已购 Pro 的平台、评论回复、媒体、推荐、账号、断点与分析能力。PC/Mac/VM/手机均在长期目标中；手机控制与手机本机执行分别验收。有效会话尽量长期复用，不能承诺 Cookie 永不过期。

当前阶段：两文件partial-gap已正式运行53987并独立现场核验，源码7a586fa已推送；中央仍Edge39。原WB30回执/已7of12剩5保持，本轮新来源0/新增ACK0。可复用多origin断点和DY/KS接入在独立候选推进，尚未最终审/上线。其他Pro/登录/OTA/跨端/48h未全验。详见E61。

2026-10-14新轮授权：并行实现中央槽释放、Owner恢复入口、Pro成熟能力桥；独审后正式采用并做原范围真实云回执、登录恢复与连续OTA验收。上轮只读交接限制已结束。保留原身份、原任务和每台两条预算；不自动扩额度、外发Pro私码、重置凭据、arm试验或恢复看门狗。

## 3. 当前状态

### E61｜回复差距修复已正式运行；可复用断点及DY/KS仍在接入

- **代码/隔离测试**：仅adapter/executor两文件，合法终页少于声明时耐久记录missing_unknown并继续独立根/媒体，最终仍74/partial，根游标/完整标记不推进。非作者abeda独跑原Pro SDK→ownedMC媒体→三导出8行、8读回篡改、8旧wire及4额外保存错/预算73/取消/父错硬停反例；合成5of7不是真实性能或新增采集。
- **正式采用/独审/发布**：root采用53987/wb-partial-1f87d525-e30a2366，旧50165停；非作者51d235实际核2exact+454其他/fullset、HTTP Fleet41719/Ownerfb563、五库backup schema/raw相等、189保护/fresh6账号24产物28WB3ZH保持、idle/outbox0。两源7a586fa1821e8c5fa92fdffdcc1c690f16340ba1 push0/远端同。云仍已核Edge39/steps68，没有新云部署、来源、grant、回执或媒体。
- **原真实任务**：沿E60实际独审70868，WB现30条回执（旧29+新1），a061 failed74/wb_reply_terminal_incomplete，累计7/12剩5；本轮采用不改变该真实失败。三HTTP导出R86各32行仅1新、准确错误码与6source上云为上轮实证。当前新鲜现场核原30/额度保持；Bili暂停1/12、ZH stopped12/12保持。a061已有fresh1，旧零fresh单层续采不可再用。
- **可复用断点进行中**：central在wb-public-progress中复用原seed/journal/Pro断点及source_continuations；只读真实原件重建3段ACK[29,0,1]共30、已7/剩5，22原件SHA不变，0来源/云/凭据请求。多origin实际SDK整链与通用SQL/JS尚未通过最终冻结/独审，不把重建当完整恢复。已确认的行保各自origin；终页差距保missing_unknown，不重复请求同缺口，只补未访问根与媒体。未知/pending/未ACK/冲突/主体改变仍拒；不新增表/固定epoch特判/扩总12。
- **DY/KS进行中**：native正复用Pro成熟入口和现有AccountSessions/固定Bridge client会话绑定，官方UID与session身份分开。原DY对照88实体/89导出行，仅54,237B JPEG，不能称完整MP4；原KS5实体/7导出行含22,868B JPG和1,899,154B MP4。临时三格式投影及session_only→本人确认→manually_confirmed状态机为受控证据；新平台Pro真实来源/云回执、当前账号会话可用性未验，不改权限或伪装官方self。
- **双路线/下一步**：Scrapy官方异常说明支持区分item/request与关闭整个采集器的失败作用域；本项目只借鉴机制，不引入框架或丢已获数据。独立推演以a061全局throw阻断后两根/媒体为实证，修局部覆盖差距但不假完整。先完成已ACK断点整链/独审及当前基线窄合，再以新中央grant使用原剩5；用户恢复授权已存在，不需重新询问，但不能绕当前未完成的执行门禁。其他Pro/登录恢复/连续OTA/跨端/48h仍未全验，目标active，看门狗暂停。

| 能力 | 当前可核状态 | 未完成 |
|---|---|---|
| 参与者/评分/安装与OTA | 有正式实现及历史远端71升级证据 | 本机连续升级/两节点原生恢复和48h未全验 |
| 中央任务/步骤/回执 | Edge39正式，WB新1回执/6来源步骤及有限错误真实投递 | 所有平台同输入及两设备完整链未验 |
| Pro平台采集 | XHS/Bili/WB有各自有限真实证据；贴吧窄合已采用 | 各平台完整评论/媒体/导出保真逐项仍见风险表 |
| 当前WB恢复 | 30回执/已7of12剩5保持，partial-gap已采用 | 多origin断点、其余回复/新媒体真实回执未验 |

历史执行阶段已移至[截至E60的完整快照](handoff/archive/HANDOFF-through-E60-20261016.md)，重要决定和变更仍在CHANGELOG/EVIDENCE。以下当前入口不再重复逐轮全文。

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
| .crowd-launch/runtime-revisions/wb-partial-1f87d525-e30a2366/ | E61当前53987；继承16源并正式采用2文件partial-gap、Ownerfb563/XHS/Bili/CDP/流式媒体SHA保持。中央Edge39/68码已独核。真实WB新1评论已ACK，现30/父7of12剩5、reply_terminal_incomplete/74；新媒体与完整回复未过。默认MC，显式Pro原守门保持；snapshot不等于Git HEAD |
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
| crowd-kol | 7a586fa1821e8c5fa92fdffdcc1c690f16340ba1已push0/远端同；E60客户端0a0fcde/云chain9a9d354保留 | 当前53987/wb-partial-1f87d525-e30a2366/云39；原WB30回执/已7of12剩5，未完成项见E61 |
| crowd-pages | 0a3bc4f04d0b2ffafd4c8619096ba6f3e28ea900 | 签名OTA71；固定ZIP提交deaab37b7eca21056ee2007e9d7aaeef90e15960；远端71登记/摘要/完成事件已证，本机71采用及远端native文件链未验 |

crowd-kol所列发布回执本轮已读；其余仓沿先前已核版本，不能当本次新鲜HEAD。运行源码以第3节E61及e61-partial-runtime-adoption批准冻结/现场独审为准，并保留continuation-current-runtime-adoption的17文件继承链，不能以HEAD替代；不要reset/clean或覆盖其他改动。


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
| Pro接入 | E44新XHS41来源/105中央步骤/R77导出/41ACK有限实证，最终独立现场有限范围通过；旧94→新40的有效阈值变化已有证据，完整数据集保真仍未通过；媒体false不含字节云链。Bili最新原生诊断为已知失败/Bridge0/nav0；旧Bridge101仅历史，原3cda暂停1/12，Pro音轨云和全量仍未验。E40 Bili单正文音轨组合已采用及现场独审。原XHS本人self已通过，e7真实正文/94评论、三导出/95云ACK独审，软阈值/86状态已采用；临时Signer已停。图片新显式代理通路已取得同字节、工作台读取/导出/浏览器下载通过；E34原单图图片云合同/回取通过，自动来源媒体仍缺。微博正文与静态原图/云v2已在E46采用，已有原29正文/评论和本轮已知失败真实链，完整Pro评论回复/新图云回取仍未验，其他平台Pro合同未补齐；E36 B站同输入有界批次正文/17评论/音频/导出/18ACK通过，但缺旧1回复/根保存事件/全视频仍未证 | 图片云合同/自动来源触发，同输入其他平台完整字段、分页回复、媒体、导出与逐条回执；不以工具测试替代真实成功 |
| 审查容量 | 历史有模型容量错误；本轮已完成媒体/五库/导出/OTA独审，WB正式接线及采用独审已通过，原单图图片云实际合同/回取与正式Owner入口独审通过，无新外部服务凭据接入 | 后续仍须非作者实际审查，不能把未出结论算通过或自行改模型 |
| 全端及质量 | Windows/VM/mobile、全评论媒体字幕、ASR质量和48h未全验 | 分OS/平台/维度的真实证据，不以Mac样本外推 |


代码行、复现与状态分级见E06–E14。作者的“已解决”必须由差异、测试原件和独立证据支持。

- E54历史：10723/十文件/Edge35实际独核99f988与源码efc4eb75远端回读已完成；真实CDP绑定和官方同主体仍缺，原请求expired。原Bili pause1/12/ACK0不变，账号模式安全保护不放松。

- E55历史：15194/五文件增量/65844dfe已实际独核发布；原工作台Owner选择入口可见但没有执行绑定/核验。07:18连接expired/0targets/未绑定。独立steps-only持久变更仍被审批拒绝、未执行，明确授权待答；不把UI或离线102检查当中央诊断上线。

## 8. 接力可做与推进顺序

先读E61及e61-partial-runtime-adoption现场51d235，再读原真实a061独审70868和多origin候选。partial-gap已正式采用，不重复部署；当前WB仍是有1fresh的已知失败，不能套旧零fresh链。

1. 完成wb-public-progress真实ACK重建→多origin复用→Pro SDK→媒体/导出→通用中央grant的整链和非作者审。原总12/已7/剩5、旧30/各origin保持，未知/pending/noACK/冲突拒；不用固定epoch特判，不自行重新派任务或扩额度。
2. DY/KS优先复用成熟Pro及既有session绑定，不要求上游没有的官方自身UID接口，不伪造官方主体或越权读新profile；实际来源/云未验前不称接入完成。
3. 贴吧原主体/URL、Bili原授权连接及同主体仍缺；ZH原任务stopped12不重启。参与端OTA/跨端/48h继续保未验。
4. 本轮以前逐阶段记录在历史快照与日志。固定入口维护当前状态，FINAL一次完整锁定，附证另文件；每轮结束仍更新日期、结论和下一步。


参与端连续OTA、其他Pro平台正文/评论分页/媒体/三导出、跨端和48h未全验，看门狗仍暂停；不得自行arm试验或扩大参与者预算。

## 9. 维护与共享

唯一当前入口为本文件；WORKSPACE/HANDOFF.md和爬虫/HANDOFF.md只作指针。[证据](handoff/EVIDENCE.md)、[日志](handoff/CHANGELOG.md)、[接力模板](handoff/ENTRY_TEMPLATE.md)及仓库AGENTS.md共同维护。

[在线固定入口](https://github.com/huming0018-dot/crowd-kol/blob/codex/v4.0.6-handoff/docs/HANDOFF.md)随已授权分支更新。本轮四文档发布以RUN16/HANDOFF-E61-PUBLISH-RECEIPT.json的commit/push/remote为准，源码提交与文档提交分开；缺回执不认定已发布。[截至E60完整历史](handoff/archive/HANDOFF-through-E60-20261016.md)保留旧入口全文和原SHA，重要决定及发布记录继续在CHANGELOG/EVIDENCE中。

接力者先读本入口、证据、日志并核日期/所涉源码与原件，再按第8节推进；主要改动按模板回写，每轮结束更新日期、结论、下一步。读不到原件时明确标未知/未核验，不把Markdown中的记录当自己查询线上所得。

JSON、PRIVATE、运行数据和原始日志默认仅本地，不随交接文档外发。按最小范围提供脱敏证据；不添加.env、Cookie、密码、令牌、私钥、邀请或登录资料，不打包全部outputs/私仓源码。旧4.2.0/4.2.5等只作历史，旧入口Git81ab4ae/blobcc09e64b保留。
