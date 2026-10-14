# 交接变更日志

当前状态只维护在[固定入口](../HANDOFF.md)，本文件保留重要变化与决定。日期默认Asia/Shanghai。

## 2026-10-14｜建立固定交接入口，主线继续

- 接力者：Codex /root；独审待完成后追加结果。
- 目标：后续GPT/Codex/bot无需用户重复前情，能核对事实接续；不是工作移交或暂停主线。
- 实际改动：以crowd-kol/docs/HANDOFF.md为唯一当前状态；新增证据索引、模板、版本/云只读快照和日志；两个工作区根目录设置指针，AGENTS约定先读/每轮更新。旧入口标历史并保留原文。
- 本轮实际查阅：当前对话、AGENTS/技能/优化规则、统一PRD/技术规范/计划、既存验收与生产回读、三仓源码/版本/未提交差异、正式65解包、8个Pro固定SHA参考仓及三份逐文件报告、四类成熟产品官方文档与当前工作台UI。
- 本地代码版本：crawler-extension912b080、crowd-kol81ab4ae、crowd-pages e171476；均codex/v4.0.6-handoff。恢复候选与其他原有dirty全部保留。handoff尚未提交/推送。
- 验证：Darwin；本地HEAD/upstream与SHA实查；Supabase只读SELECT于11:34:42确认task19/20仍leased、各2/2和4proof MD5；不是启动/续采/finish。
- 关键更正：第二设备已报告65，旧11:05进度页“仍63”已过期；两机正文ACK不等于任务finish/完整登录恢复/48h验收；Pro8私仓现已可读，不再沿用旧无权限结论。
- 部署/线上变更：无新采集、部署、推送、外发、Cookie导入、Pro执行或试验arm；每小时开发看门狗保持PAUSED。
- 主线：综合独审、Pro同输入保真合同、持续运行阻断优先；保留参与者流程/评分/云回执/OTA。上线和业务维度未验项继续保留。
- 证据：E01–E10；2026-10-14-cloud-readback.json；2026-10-14-local-inventory.json。
- 历史保存：旧docs/HANDOFF.md在Git81ab4ae版本/blob cc09e64b93a11979b18355c3d0db45b383d52e14；旧执行PROGRESS另存原字节到archive，不从历史补写当前事实。

- 旧执行状态原件归档SHA256：9851008f188694ca3be73243a6c10cdcb56483e5c7255ade92ef2efec0375c15；原路径现为指针，历史字节未删改。

## 2026-10-14 12:06 CST｜交接独审通过，主线本地修复与Pro保真对照继续

- 接力者：root；交接非作者审查owner_monitor_impl；Pro核心/附赠及综合路线非作者审查unified_cloud_impl。
- 实际改动：修复AGENTS/优化规则的旧PROGRESS口径；纠正130秒隔离样本、快照日期与采用前失败探针引用；补入真正生产独立回读和采用原件。三个源码仓均有接力AGENTS；每轮结束都更新，不仅重大改动才记。
- 验证：handoff独审PASS，36工件摘要/字节、27链接、指定14文件凭据模式检查均通过；主代理实际重跑outbox临时SQLite复现，24替身调用、好记录尝试0。只读/隔离，非生产测试。
- 主线产物：会诊与完整升级路线；Pro报告独审修正7项，综合路线3项；保真合同12历史案例+16缺样已写，独审中；不会按缺样清单自动采集。
- 本地代码推进：unified_tasks开始CloudOutbox公平回传、隔离错误/可恢复及退避的最小改动；待作者测试与非作者复核，未改运行版本。跨平台释放受中央单running合同约束，不能以丢坏行/伪finish换吞吐。
- 版本与部署：三仓HEAD保持；本轮只有文档/证据和进行中的本地修复，未提交、推送、部署或启动新采集。运行仍按既存4c0快照、参与包65证据核对。
- 证据：E11–E13。未验证：Pro真实等价、资源、平台当前可用性、任务自然finish、完整重登/连续OTA、48h及非Mac终端。

## 2026-10-14 12:23 CST｜Pro保真基线独审完成，D1限定本地修复通过

- **接力者 / 独审**：root统筹；unified_tasks实现D1；owner_monitor_impl独审D1；formal54_merge制定Pro合同并复核登录/媒体；unified_cloud_impl复核合同/核心附赠。
- **目标与实际改动**：固定handoff持续记录每轮；主线继续。已固定Pro八平台/附赠能力保真合同，28案例中12历史、16缺样，全部禁止自动采集、候选/Pro比较not_run。修复CloudOutbox永久错误饿死后续好行，增加耐久重试/隔离及显式原ID再送，保原7列、原字节、ACK和finish门禁。
- **文件 / 版本**：代码仅cloud_sync.py、test_cloud_sync.py、test_cloud_outbox_retry.py；基线crowd-kol81ab4ae未变，三个候选SHA分别f431dead86954b303bd84cf478adc8c31a1608912fb13548ecded17c9e2a9cf3、5d2adb9f57c957346ad565cc8f41219f6d9770e47bfe9b1b00891b07adbda5d7、c168cf09ba554f919c5f510999c55bbec313dd5503adce2549bc051fac176ea4。其他既存dirty保留。交接、证据、索引与本日志同步更新。
- **验证**：作者92相关测试（10新+82原）通过；同旧fixture三轮10次替身调用，good捕获1次/精确ACK1，4坏仍pending/quarantined4，原id/envelope/digest不变。独审另亲跑10组负例和78关联回归；6项初始loopback绑定受沙箱拒绝，经工具批准只重跑这6项通过，没有跳过失败断言。
- **独审发现与闭环**：第二发送前租约拒绝错误消耗重试、旧请求迟到错误污染新ACK两项P1草稿缺陷，作者修复后独立8次guard负例/真实线程竞态复核通过；90秒hold不承诺网络exactly-once。原源码/测试SHA与冻结清单精确一致。
- **实际查到的新资产**：B站BV1ocaW6rETo原run MP4仍在项目，41,743,492B、SHA90553cbfe22ac0feb2fe49cf0370be1489c81c2fafd7402ec92713a6f602d2a2；root定位后两代理独立核对，无新下载。旧Downloads副本仍缺；解析原响应/平台完整时长尚缺，不能据此声称Pro等价。
- **部署 / 线上生效**：未提交、推送、运行时采用或部署；未读写真实outbox，未新采集、云写、模型调用、导入Cookie或启动48h实验。开发看门狗仍PAUSED。本地修复不改变正式参与包65和既存工作台运行快照。
- **业务验收 / 未验**：这次是合成/临时SQLite及loopback合同测试，不是真实云回执或长期并发验收；Pro输出比较、完整重登/连续OTA、原任务自然finish、ASR语义质量、其余平台维度和非Mac终端仍未全部通过。
- **下一步**：补D1中央running槽/交付待处理合同和Owner鉴权恢复入口，受控采用；R1–R4修复并行；随后Pro Python协议桥接现mc_runner/ResultsStore/outbox。所有替换先同输入验证正文、评论分页/回复、媒体与导出，速度不能放行功能缺失。
- **证据 / 更新**：E11–E14；AUDIT/pro-equivalence-independent-review.md、pro-login-media-independent-review.md、outbox-fix/、d1-independent-review/；统一审查索引outputs/mediacrawler-execution/reviews/2026-10-14-handoff-pro-d1.md；当前状态更新于../HANDOFF.md，完整摘要见本地inventory。

- **最终交接增量复核**：owner_monitor_impl核57工件摘要、27链接、14文件凭据模式、旧inventory归档及三候选SHA，PASS；原件AUDIT/handoff-final-delta-check.json，SHA4d0131261ebcafc4a481c85ce4a058f3bf3629b617d0976d027286aa99692c1b。root另核15当前文件/35链接、57摘要无漂移，结果2026-10-14-doc-validation.json；不同范围不混算。未重跑已过代码测试或查询生产。

## 2026-10-14 15:15 CST｜正式采用、真实回传与连续OTA；Pro接入仍有门禁
- root统筹；unified_tasks中央/封装，owner_monitor_impl Owner，formal54_merge Pro桥；代码交叉非作者独审。源码21文件提交7ff5b44；扩展96c8d2f；Pages d081643。
- 正式部署迁移20261014062752、crowd-machine v21；运行时采用delivery-pro-cf7408cca2616868。原四DB行/1017ACK及旧源码兼容独审通过；配置117项前置hash未保存，明确证据限制。
- 保存数据任务41c92098-8316-421c-b825-949cc6564e26自动领取并完成1正文8评论云回传，ACK合计1026；不新采、不扩大参与者预算。逐字段云/导出独审待续。
- 本机65→66→67连续实际加载，原身份/队列/history/2条进度保持；task19已complete，task20/第二台67未验。66最初安装URL不符原native规则，保留invalid_url历史，改正确路径并重新独审后应用；未放松原native校验。
- 用户批准原CookieBridge1.1.0仅同步127.0.0.1:8274。临时CDP装入返回ID，但正常重启不保留；这推翻“持久安装完成”。正式UI目录选择受原生工具选错Chrome实例阻挡，未操作日常Chrome。封装10作者测试根复跑通过，非作者审查受模型容量限制，服务尚未启动/未读cookie。
- 下一步按HANDOFF第8节；Pro默认未激活，完整重登/分页/远端OTA/48h仍未验。无看门狗恢复、无试验arm、无凭据写入交接。

- 后续独审补证：unified_tasks亲读现Owner API与SQLite，68项PASS_WITH_LIMITS；UNIFIED-INDEPENDENT.json固定九条原ID/哈希/云ACK/finish/JSON、JSONL、CSV一致。来源请求0，仍不是Pro新采或完整评论分页。

- 后续CookieBridge独审：新非作者cookiebridge_review完成10作者+7独立检查，无源码阻断。根启动127.0.0.1:8274，真实ping本机/精确扩展200、网站Origin403，LIVE-BOUNDARY.json；未查Cookie端点。用户已收到正式原浏览器目录选择的人工完成说明，等待安装完成，不重复要求扫码。

## 2026-10-14 15:31 CST｜用户正式加载后的真实复核
- 用户明确回复已加载；root只读原profile扩展页见CookieBridge1.1.0启用。正常关闭/重启原自有B站浏览器，扩展和client ID均保持，COOKIEBRIDGE-RESTART-PASS.json推翻前轮安装未保留的当前状态（旧失败保留）。
- 原worker client与127:8274注册精确相同；仅本机查询Bili cookies并只保存存在/绑定bool，COOKIEBRIDGE-BILI-SYNC.json。值不输出/不落盘。原session新增0600 pro-binding.json仅存client与本机URL，不含凭据。
- 原生pong仍未做。发现Pro SignSrv独立nav/重试不在runner计数，准备原Bili服务受限入口，runner9+signer外部1总10；未启动SignSrv或新采任务。两个代理并行准备并随后交叉审查。


## 2026-10-14 15:35 CST｜CookieBridge限定独审与Pro同输入启动准备
- 接力者/作者：formal54_merge；CookieBridge作者unified_tasks，由formal54_merge非作者审；启动脚本另由cookiebridge_review审。
- 实际改动：新增本地一次性启动计划/请求/替身测试/说明；未修改正式runner三源、默认MC、私仓或真实账号。CookieBridge wrapper 4源SHA/18上游SHA和原Bili扩展登记只读核对。
- 验证：CookieBridge 10+7检查通过；启动脚本静态检查+7替身测试通过，修复非零退出/缺run_id误成功；无真实来源/服务启动/Cookie读取。
- 范围：原session25cc6e3b-5882-439f-a1b6-979500ad9854，BV1ocaW6rETo，显式预算root已核账号1+runner8+signer1，不覆盖原扩展背景流量。media=false复用已有字节，不删除评论回复。
- 部署/业务：脚本未采用，Pro新正文/分页/导出/云ACK尚未验；root已做的原账号nav另见BILI-ACCOUNT-CHECK.json，不重复请求。
- 下一步：signer独审完成后root选云worker或本地CLI一条启动路径，未知不得重发。最终脚本非作者报告待收。证据见EVIDENCE DR-PRO-PLAN。

- 15:28后的原账号补证：BILI-ACCOUNT-CHECK.json记录一次官方B站nav HTTP200/code0/isLogin=true，主体hash与历史原session一致，无Cookie/ID持久化。此1次计入显式试验预算，后续runner8+signer外部1；不将扩展后台登录检查流量声称纳入该限额。静态启动脚本已7作者+2独立组通过，尚未执行。

## 2026-10-14 16:12 CST｜Pro第一次真实来源：partial，不冒充完成
- CookieBridge正常重启与同原账号nav已验；原SignSrv受限封装独审通过并真实启动，外部nav1成功；未替换默认MC。
- 原run d6b2d434-18b8-4448-98d8-70c172d4873f取得1正文27评论，8attempts后300秒wall_timeout；checkpoint未提交。独审正文与87ae一致，新19根8回复无孤儿，旧6回复仅重合5，媒体仅引用；完整等价未通过。
- 调用正式results ingest保留原partial成功；响应保存因重复相对前缀失败，未重发导入，改用SQLite只读恢复实际30observations证据。三格式导出rev69共35快照项，独审确认28本次+7旧项，未把旧项计新采。
- 创建唯一source0 saved交付任务0cb0b49a，回传精确28版本；源任务保持failed/unverified。真实云ACK独审继续。
- 发现并正面更正旧E19 refs来自另一视频，旧9ACK不作此视频同输入证据。后续采集预算退出线程卡住的疑似根因正由作者离线真SDK复现，不在缺现场栈时写成事实。

## 2026-10-14 16:22 CST｜partial云交付完成，Pro异常清理修复独审发布
- root统筹；formal54_merge实现；cookiebridge_review独审；unified_tasks独审后续运行采用脚本。
- 0cb0b49a原saved交付completed：1正文27评论/28ACK，三导出所选28refs逐字段相等，原envelope/epoch及finish hash独立复算通过。源任务d6b2d434仍failed/wall_timeout，coverage unverified，非完整采集验收。
- 两文件Pro收尾修复提交并推送848bd315cb1140cd071eaff33e0a4b844fa48a86，私仓未改；预算SystemExit/取消时原task finally关闭SQLite，保留原异常及已提交数据，溢出加固定原因标记。19桥回归+2独立context+5真实SQLite合成生命周期独审通过；作者另验ResultsStore26项。实际旧超时唯一根因未确认。
- 正式运行采用和零平台请求的本机预算停车验证继续；此记录不代表已采用。证据outputs/distributed-runtime-2026-10-14/pro-bridge/{live-independent/CLOUD-ACK-VERIFY.json,budget-stop/independent/REVIEW.md}。

## 2026-10-14 22:43 CST｜Codex /root与独立代理
- 目标/实际：Pro配置与置顶修复64e23d9、保存引用200修复b967322正式推送/采用；Edge22仅替换原contract，正式runtime saved200/PID87462，原四库/保护资产独核保持。修改范围及证据E26。
- 新f2c真实43.003秒完成1正文106评论、40runner+1Signer；源和导出分别独审，通过的是有界批次，非全评论耗尽。正常停止本轮Signer，CookieBridge及原浏览器保留。
- OTA69源码c5ff909、固定ZIP678cfd9、通道76474d2已发布；本机68→69保留8身份队列摘要独核，两原节点实际SQL均69+正确release摘要；另一台原生连续链/登录恢复未验。历史四条operation_failed类诊断问题仍留存，根因未知。证据E25。
- 云129任务83f47fbf completed/source0/129ACK/finish哈希独核通过，但28条origin和4条metrics与rev70导出不等，保真Gate失败。独审定位saved_version读首次版本观测；正在补refs.results_revision，旧ACK不得覆盖。107任务4f00dd4a同项独审继续。
- 修正过程错误：ping检查器使用错误字段、首次cloud preview路由错误、导出未选9项被误称全旧、审查跨Python repr摘要误报；保留失败原件，不修改数据制造通过。审查whole-run clone跟随profile失败，3临时目录已独核清除；只允许必要数据白名单，AGENTS已更新。
- 下一步：观测快照修复独审/部署→以固定rev70/71重验纠正版零来源云交付→补中央步骤、native诊断、完整登录恢复。48h/watchdog未启动，不宣称全平台/全端完成。

## 2026-10-14 23:50 CST｜Codex /root，观测绑定真实验收完成
- 改动：8c3444a为12文件冻结观测与已知未派发拒绝收尾；30139a2为2文件HTTP窄扩容。Edge23仅替换contract，原鉴权/其他10文件不变；runtime先snapshot5文件完整helper依赖，再saved-http/PID92704，仅窄改dashboard。原四库/121保护/原ACK均实际备份对照独审保持。
- 审查：refs200_review，124综合Python及21Node绑定断言、跨库错观测拒绝、四实际本地错误耐久failed/API0收尾、未知/staged不套用；52真实HTTP相关测试确认129/200引用及超限、Origin/CSRF限制。根因和失败原件保留，不把mock当生产坏组现场。
- 真实验收：025fa7d1与5141604d两纠正版分别129/107ACK，completed/来源spent和reserved0；采集字段含origin/metrics/父子/media与原规范records及冻结导出逐项相同，原envelope/receipt/epoch/finish重算通过。旧83f47fbf/4f00dd4a原错误观测和ACK完整保留，不覆盖。最终1526ACK/0pending，工作台idle/scheduler alive。
- 数量与计数校准：236是两冻结快照的观测，不是236新实体；去重131（同视频正文1、评论130）。f2c40为含本机桥接的HTTP尝试，另Signer外部nav1，平台专属/浏览器请求未独立测；43.003秒只本次有界来源终态，非总云交付延迟或P95。
- 交接：HANDOFF/EVIDENCE更新为唯一当前状态，E27给可复核工件；保持旧2fe失败、f2c批次完成，媒体仅引用不当作新字节/听写质量。下一步为native诊断分类、中央机器步骤、完整登录恢复及其他Pro平台同输入保真；默认MC保持，48h及watchdog未启动。

## 2026-10-15 00:04 CST｜固定在线入口发布准备
- Codex /root修改五份Markdown交接入口；refs200_review独立发现并修正旧ACK待办、Signer运行状态、历史E26和本地JSON被误作在线链接的问题。功能运行版本不变，未新增采集或部署。
- 本次仅发布docs/HANDOFF.md、docs/handoff/EVIDENCE.md、CHANGELOG.md、ENTRY_TEMPLATE.md与仓库AGENTS.md；所有JSON、PRIVATE产物、未提交ASR/迁移等保持本地。目标huming0018-dot/crowd-kol，codex/v4.0.6-handoff。实际推送与远端SHA核验随后记录；原件无法访问者仍须标未核验。
