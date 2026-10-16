# 分布式采集系统｜固定交接入口

更新：2026-10-16 08:58 CST，Asia/Shanghai。维护：Codex /root。本文件维护当前状态；重要历史留在日志。**交接是每轮工作的伴随机制，主线继续推进。**

## 1. 接力规则

1. 先读本文件、[证据索引](handoff/EVIDENCE.md)、[变更日志](handoff/CHANGELOG.md)，再读工作区 AGENTS.md 和涉及的模块。
2. 核对环境、分支、未提交改动和证据日期。聊天摘要、作者自述、测试目录存在、进程在线，都不能替代实际验收。
3. 无法访问或核验时明确说明缺口，标“未知/未验证”，继续可独立完成的工作，不声称已同步。
4. 每轮结束都更新日期、本轮结论和下一步；主要改动后，用[接力模板](handoff/ENTRY_TEMPLATE.md)更新本文件相关状态和证据，向日志追加记录；不复制整段对话。
5. 用户新指令优先。读过交接包不等于获得新采集、部署、付费或外发权限。

## 2. 目标、范围与阶段

目标：中心数据库动态分配任务到用户终端；本地复用本人登录、静默采集、耐久回传；中心逐条确认、监控步骤、定位异常。Owner 不应手工分配账号或 HTTP 请求。

必须保留：Kimi/现有参与者流程、身份、评分、暂停继续、outbox、回执、OTA；吸收 MC/已购 Pro 的平台、评论回复、媒体、推荐、账号、断点与分析能力。PC/Mac/VM/手机均在长期目标中；手机控制与手机本机执行分别验收。有效会话尽量长期复用，不能承诺 Cookie 永不过期。

当前阶段：中央Edge37/36码、当前17文件续采及单Owner确认修复均已正式采用并独立现场核验；本机38406/owner-preview-fb5636ff3bb3，源码2143c7c远端同。真实原微博预览、第二步授权、自动领取和中央15步骤已跑；新尝试已知failed74/wb_reply_page_shape_invalid，耗2次、父累计5/12剩7，原29回执保留且无新增。正修实际SDK响应层合同、最新失败与原seed分离的链式恢复及终态细因上云；不重发旧grant、不扩额度。贴吧V3受控独审通过，当前窄合/账号准入及真实云链未验。OTA/全端/48h未全验，看门狗暂停。详见E58。

2026-10-14新轮授权：并行实现中央槽释放、Owner恢复入口、Pro成熟能力桥；独审后正式采用并做原范围真实云回执、登录恢复与连续OTA验收。上轮只读交接限制已结束。保留原身份、原任务和每台两条预算；不自动扩额度、外发Pro私码、重置凭据、arm试验或恢复看门狗。

## 3. 当前状态

### E58｜36码中央诊断正式上线；当前客户端续采合并与贴吧独审继续

- **云代码/部署/独审**：复用已审36码有限枚举，15码严格子集保留；SQL仅替枚举和当前9dcc基线守门，JS仅换数组，其余鉴权、事件幂等、任务和权限不变。102项真实PGlite检查及重复迁移guard拒绝通过，非作者e407放行；root执行SQL成功并发布Edge37 ACTIVE27，非作者98bc独立fresh逐字核仅steps变化/其他26模块不变、SQL正文与真实ledger20261016002450一致，source d180/image77ce与ACL保持。两源文件按实际ledger命名，源码56639c17f7e66bb494ce306dd0f214a4e26f9bc1 push0/远端同。不是新来源、真实运行错误投递或续采业务验收；本轮云变更没有发来源请求。
- **云部署时保护边界（后续真实微博尝试另见下项）**：独立Owner三status实际读回：Bili paused1/12/ACK0，WB failed3/12/ACK29，ZH stopped12/12/ACK0。当前本机仍27263，默认MC/idle/outbox0；云37不会自行升级本机caller。XHS上轮原账号单次官方自检已证，不重复扫码或self，没有匹配cloudwait，不凭旧pending启动。Bili原Chrome连接/同主体核验仍缺，未擅自重连或重发未知任务。
- **客户端/单Owner正式采用**：FREEZE36 1c885的17差异合并经非作者8bcc独跑72含Cloud38、微博四组实际SDK/MC受控链、Bili Bridge/CDP、XHS17、Owner20、Fleet10后放行。root采用36106，非作者6e165核17精确+435其他/fullset、五库schema/raw等本次实际备份、170保护/6身份/24产物/9WB/3ZH；源码ed7bdddb push0/远端同。源码回执曾记录审查中间SHA e4cc，最终锁定6e165链接另存SOURCE-PUBLISH-FINAL-REVIEW-LINK.json，旧回执保留。真实UI首preview后自动轮询丢闭包确认；单Owner V3经13新+原20/4/4及3额外反例08a15独审，拒desired-only停止和同revision旧DOM授权，允许合法晚预览保Map。root再采用38406/owner-preview-fb5636ff3bb3，非作者b425实际HTTP owner摘要、其余451/全set、五库/保护项在来源动作前保持；源码2143c7c2e3c42a7294809789ad319422c6cfd03b已push0/远端同。
- **真实微博续采（已知失败，未通过业务验收）**：root在原工作台只点一次有效确认：先预览原29回执/剩9，自动轮询及显式Owner刷新后确认仍保留，再点当前确认按钮一次。中央唯一grant15bb与原task e2d613f2…/child c012…/worker关联、epoch2，终端自动创建9b1e6e85-5e4f-4536-b74b-750f778346c1/cloud6cb18c98…；同输入仅预算12→剩9，不新增正文额度。实际终态74/wb_reply_page_shape_invalid，新API2/9，父累计5/12剩7、reserved0。非作者28cb核原29 items及receipt逐字typed等旧回读、9旧资产SHA同；复用4条typed等旧norm、pending0，新capture0/新ACK0/新媒体0，仅1媒体引用，成功三导出未过。中央15steps中4条source步骤逐字段等本地SQLite（两次开始/HTTP200）；终态目前仍run_failure_unclassified/exit74，细因仅本地。HTTP200不证正文或真实响应形状；原响应body未留，不把SDK剥data的代码风险认定为本次已证根因。没有重试/重放旧grant。
- **贴吧受控链及当前窄合**：V2四组实证阻断保留；V3 88d96765修业务码/取消与73语义/重启summary检查点与选定前缀/scope假exhausted和计数，经非作者e489受控整链与反例独跑通过。current-36106窄合4d2c候选保WBseed/WBI/媒体，仅作者受控测试通过，非作者窄审及正式采用尚待。原21条publicraw投影业务字段及三导出可核，原图URL没有固化证据；真实PC sync UID/业务码、原账号ref/Pro绑定/Bridge对应仍缺，不能扩SUPPORTED或称新来源/云通过。
- **证据事故/恢复边界**：准备采用器时误复用旧continuation-runtime-adoption目录，6份历史文件被覆盖；旧RUNTIME-FREEZE已精确恢复dfc03655，另4份BEFORE哈希索引及旧PREPARATION原字节未恢复，不能继续作为可现场复核原件。新草稿已移continuation-current-runtime-adoption并保碰撞清单，root只读扫描原聊天输出未找回4索引。未改原账号/浏览器凭据/业务库/任务数据；这不使缺失历史证据恢复有效。后续采用必须用当前现场新索引和五库备份独立核，不能借旧通过替代。
- **下一步**：微博SDK child响应层/单次传输的单adapter候选pro-wb-child-wire/FREEZE.json 91ae23已改，作者20组whole及真实SDK剥层合同受控通过，尚未独审或采用；先完成该候选独审，不再用方便的data.data夹具；同一实际SDK证明共享预算/步骤/取消与73不被retry吞。链式恢复须分离最新9b1已知失败与不变原6ad seed/旧29ACK，新的latest epoch2授权只用剩7，不能复用epoch1 grant或把reason改写embedded。补wb_reply_page_shape_invalid细因中央有限码；候选均独审后才正式采用/云部署及再次真实尝试。并行贴吧当前窄合/真实主体前置，不扩预算/绕登录；Bili原连接与同主体、其他Pro平台/参与端连续OTA/全端/48h仍缺，目标active、watchdog暂停。

### E57历史｜原XHS官方后台自检真实通过，MC交错提示收口；其他Pro完整链继续

- **实际交付**：复用已购Pro query_self/原账号Bridge和已有owned_signer，仅新增独立last_self_check与operation意图/worker/result；保持原SID/gen/ref/pending/verified_at/authorized及state。正式账号页按钮“仅检查原账号登录（不采集）”，CLI同动作及有限失败日志齐全。不是新采集run，不调用observe(authenticated)发来源授权。没有复制vendor或凭据入发布源码。
- **独审与真实结果**：主组件6db4+时间UI82c6由非作者2045400d复核原SDK业务17/动作6/caller2/Bili14/worker10（含继承）/UI11及端点与owned生命周期负例；这些计数有重叠，不累加宣称唯一总数。root唯一实机按钮产生operation8abfba0c-cb57-4842-811f-064e8b4cd045，Bridge1/sign1/official1均200且authenticated_same_account；intent→result2.285688秒，仅这一次自检，不是整个采集速度或P95/CPU/RAM收益。非作者f9fca实际核核心8逐类型同、五库schema/raw等本次备份，worker23399/ownedSigner23406已退出、8990无listener，source0、原任务/额度/回执保持。
- **界面问题及修复**：最新明确登出/换主体不再被旧authenticated盖过；旧负向检查不盖更晚verified_at。实机checking时旧MC暂停字段误显示“继续核验”；首单UI020又被独审发现“旧self死后新MC活锁被误隐藏”反例，未采用。最终83da两文件在原active锁取得后仅将遗留checking诊断标历史未知，保operation原件，配显式checkOnlyActive UI，活self锁先拒不写，真正MC暂停/继续仍保留。真实caller5/账号43/Bili14/DOM7+旧11复核结果另见最终UI独审；缺测试子进程依赖的首败保留，补的browser_session与正式同SHA，不是改产品凑通过。
- **采用/发布分层**：初5文件23049/215c96运行冻结，正式前14a7、真实后f9fca独核通过；尾项2文件当前27263/xhs-check-ui-a0f565cb-98559c68，实际现场以xhs-selfcheck-ui-adoption的ADOPTED与independent/ACTUAL-RUNTIME-FINAL.json为准。源码0c7449855d75ae30ad4370f3ea6a4acfd27871ef已push0/远端同；此处文档发布另看HANDOFF-E57-PUBLISH-RECEIPT.json。本机27263六源发布未含续采/诊断caller；云端另有本轮三SQL+Edge36成功回执，独立fresh回读d387820c已核Edge36的27文件与三SQLbody/实际ledger/RLS/ACL及原任务不变；不能拿旧本机采用报告的07:19快照替代该新证据。
- **其他平台与未完成项**：贴吧core ebf按原SDK/真实SQLite/成熟图片链/三导出受控重放6进程通过，原3根17回复/2图，预算8/12，limit_reached不冒exhausted；root新增“业务码缺失/冲突被认证”两负例为CHANGES_REQUESTED，V2已接续修但完整入口尚未独审/采用。原URL、完整元数据、真实checkpoint/journal、账号同主体、owned媒体与中央云链分别验；不能以21行或旧图片当新来源/新云ACK。DY/KS亦未完成Pro正式同输入验收。
- **新授权/云范围**：本人明确答复“允许步骤诊断及原续采迁移”，原件central-authorized-deployment/HUMAN-AUTHORIZATION.json已核；不再是等待批准。已读DEPLOYMENT-RECEIPT.json：source/image/steps三迁移均success、crowd-machine Edge36 ACTIVE；source RPC readback MD5 d18030f62b42827f28f8b02c7c81e4c3、ACL仅postgres/service_role、RLS=true、新表0行。独立fresh回读POST-DEPLOY-FINAL.json d387820c通过：Edge36/27文件、三SQL实际body/ledger、RLS/ACL与新表0行；原三个task_status保持，无source。7云源码b20611c85177dd6e4e21bebde07fb318f4c1af6b已push0/远端同，不含私有index或vendor。随后96996e95仅将正式SQL名对齐实际ledger：20261016001508/001523/001534；字节不变、0云调用，旧计划名原件保留outputs，不重复执行迁移。15码旧诊断与后续独立36码是不同版本，不把36码候选说成已上云；sourceCalls0/businessAcceptance=false/原任务变更0。
- **下一步**：完成贴吧V2正式整链候选与非作者审，逐项保正文、根回复分页、媒体和三导出，不缩功能或扩原预算。XHS旧pending并非当前cloud wait，禁止重启548或凭self通过新建任务冒恢复；Bili待原Chrome连接及同主体，原3cda剩11/总12不变。中央已获本人明确授权，三SQL+Edge36已部署有回执，独立fresh回读已通过，本机当前基线caller窄合仍待，业务未验；WB29/剩9、ZH stopped12/12/ACK0、参与端/连续OTA/全端/48h未全验，看门狗仍暂停。

### E56历史｜原任务卡片联动正式运行；真实账号核验与云诊断仍待门禁

- **代码/首败/独审**：仅owner-ui.js、accounts-ui.js。V1同VM独审发现晚回包覆盖全局页、已移除卡片仍打开账号页、无executor空匹配自动recover三项实证；原件保留。V2 08498修入口序号/账号页generation、每次刷新唯一匹配；原公开task/child无source_executor/request，只有权威cloud_pro与原task/child/platform唯一匹配才开原会话。未知Bili0匹配阻断；明确MC保原guard，其他平台及全局登录保留，不能声称公开旧MC都可识别。非作者6b64ae独跑同VM20、原账号与Owner4矩阵，三原反例重放通过。
- **正式采用/现场/发布**：root唯一采用两JS到19052/owner-cards-b4e6bfa9-4f11bd6a，旧15194停；非作者0c9117核2精确+443其他/fullset、五库schema/raw等本次实际备份、170保护与当前6身份+24产物+9WB+3ZH保持；idle/alive/stale=false/pending0，原默认MC/暂停意图不变。源码160c351c6f0953d019bc6f9a974b74e5a68cfbdf已push0/远端同，父dabd0886。中央诊断四文件未纳入，Edge35/RPC沿07:19原件；现场报告明确未发新Edge查询，不能称云状态本轮fresh。
- **真实界面/业务边界**：root在原IAB3/tab1刷新→全部任务→原3cda卡片，实际打开唯一原Bili账号对话框，含“选择原账号已登录浏览器”“复用原账号后台核验”。只点击入口；无bind/recover/official_self/source，DOM原预算1/12/ACK0；root之后六账号摘要仍等采用前，见ACCOUNT-AFTER-UI.json。界面联动验收通过不等于登录恢复、正文/评论分页、新音轨、三导出或新云ACK。
- **XHS本轮恢复证据与实际缺口**：本人确认加载后，root仅一次原d261本机Bridge刷新，source=extension/has_cookies=true；07:28:47快照缓存age1.7秒是当时观察，非持续fresh。非作者f226核原登记/账号元数据保持，原71456/profile保持，participant未登记，旧self仍过期。正式pro_login_recovery.launch只支持Bili；XHS open_login/recover仍走MC浏览器核验且新proof可触发desired_running等待任务自动resume，因此当前没有可安全直接调用的纯Pro XHS官方check-only入口。903d原gen1/ref存在，pending/authorized为191453b6…而非548；没有发新self、启动浏览器或改状态，不重启旧548。
- **下一步/阻塞**：原Bili最后07:18已核CDP expired/未绑定，本轮未重连或再查询、未verify；由本人确认原Chrome连接，再在本轮原task卡片选择原平台页面、绑定原SID/gen/ref/pending，单独官方同主体核验后按剩11验正文、根回复分页、新音轨、三导出与权威ACK；未知意图不重发，不扩总12。为XHS补产品级纯Pro check-only隔离语义，复用已购SDK现有query_self，不另造采集器、不要求本人再次加载或扫码；需实现/独审，不能拿Bridge刷新当登录成功。中央steps-only精确替换及续采升级授权待答，未执行；WB29/剩9、ZH stopped12/12/0ACK、participant/连续OTA/全端/48h与watchdog暂停保持。

### E55历史｜Owner原任务浏览器入口与媒体内存修复已正式；中央诊断被拒未部署

- **产品缺口/修复与独审**：原云Pro等待任务隐藏选择入口，普通选择又新建SID/gen0丢失原pending/ref关联；仅bind不切provider仍走被禁用native。实际临时状态机复现后，root四文件V2 a173修为原task/child沿既有Worker完整守门绑定原SID/gen/ref/pending、撤旧proof、显式existing_cdp，之后另点后台核验，不自动来源或继续。非作者05c64实际100隔离检查通过；首审current generation=True误等1已修strict int，首败保留。没有删除旧身份或迁移到新会话。
- **媒体资源优化**：单mc_runner.py d44c将已下载媒体SHA整文件读入改file_digest/低版本256KiB分块。root非作者2f4a重放Python3.11/3.9各5测试、3个真实旧MC样本/4媒体SHA及临时三导出字节一致。64MiB温缓存控制实验仅证明哈希片段减少内存，不外推整体采集耗时/P95或其他机器；没有重采或重新下载。
- **采用/现场/发布/真实UI**：root唯一采用五文件到15194/owner-browser-perf-7ce70892-6b888cc3，旧10723停，运行冻结4738ebf0。07:13:04非作者30608ca3核5精确+440其他/fullset、五库schema/raw等实际备份、170保护与当前6身份+24产物（19导出+5Bili）+9WB+3ZH保持；默认MC/Edge35全26与三个RPC保持、无续采表。源码65844dfea2a1a37407a0f93da854c3a096721340已push0/远端同，父1f14。root在原工作台IAB3/tab1刷新并打开账号页，原Bili浏览器选择入口可见；只看连接元数据，先pending随后07:18expired/0targets/未导入/未绑定，无bind/recover/restart/source，六账号摘要仍同。UI存在不是平台登录验收。
- **中央诊断离线通过但未执行**：独立V2 fdeea仅原steps队列/单Edge/现有stepsRPC有限终态error_code/exit_code，不含续采表/sourceRPC或claim/finish改动，修漏CDP主码后native非作者f38c通过8+38 Python/102真PGlite/10UI/59恶意检查。root尝试单stepsRPC精确迁移被自动审批再次拒绝，理由是正式事件校验的持久替换仍缺明确授权；executed=false，无间接执行。已向本人发新精确授权请求待答。07:19实际回读Edge35全26、三RPC MD5/ACL保持、无续采表，不能称中央新诊断已生效，也不把后台账号失败伪作新source事件。
- **当时尚缺（2026-10-16 07:20；卡片入口已由E56修复）**：当时只修全局账号页原会话选择/绑定入口；正式owner-ui.js:136–140任务卡片“核验原账号以恢复此任务”仍直接recover_cloud_login，不主动打开账号页选择器，不能称所有Owner入口完成。下一步把任务卡片联动到原账号选择，避免默认native未关联时重复失败。本轮没有新真实self/source/ACK。原Bili paused1/12/reserved0/ACK0，旧400UNKNOWN及已知诊断失败保持。等待本人确认CDP连接后，由root核原平台页/绑定同原任务并新官方同主体证明，再按原剩11有界验正文、评论分页、新媒体、三导出、云ACK；不重发未知调用或扩预算。云DDL批准pending、WB29/剩9、ZH stopped12/12/0ACK、XHS Bridge在线但participant未登记/旧self过期、OTA71/全端/48h未过、watchdog暂停保持。

### E54历史｜安全复用组合已正式采用并发布；真实连接与采集仍未验收

- **代码/测试**：existing_cdp组件9ed7068（同session绑定端口/target/fingerprint与generation/ref/pending、私FD、借用原上下文）经root非作者2b3c通过；8边界、3私FD清理及6组原SDK账户池/官方同主体恢复受控用例。Bili native_persistent双入口IO前禁用保留，WB/ZH调用同一成熟私FD函数。Bridge本地WBI候选1a4d经central非作者35a38通过，28单元与9个原SDK/真MC媒体子进程场景覆盖音轨、预算、错主体、proof与取消，原Bridge未配置显式能力时仍沿旧Signer路径。两者已窄合为组合7a39，root非作者8d4318复核全部冻结/源码差异、33单元与5UI通过；作者最终33单元/19原SDK场景，central非作者另重放关键11整链与legacy/UI并核完整来源差异，通过报告见E54M。受控原SDK/媒体/导出不等于真实账号验收。
- **本地报错诊断已接入**：账户请求日志dac07经非作者66d审查，真实Handler7与额外恶意4通过；仅原五类账号操作、固定错误码/UTC/关联ID，拒绝把payload、Cookie、URL或异常正文写入日志。日志失败仍原400，Host/Origin/CSRF不变。旧响应清洗可能回显纯字母数字未知异常的既有边界保留，新日志将其统一invalid_request；不能以此补造旧400根因。
- **本轮只读实际状态**：06:35:34元数据确认原XHS71456/原profile仍在、Bridge d261 connected=true、扩展登记仍在；Cookie缓存fresh=false/age4899.2秒、旧官方self超180秒，未新核验。原profile中的participant仍未登记，不能把本人此前“好了”（Bridge重载）扩成participant恢复或71已采用。
- **正式采用/现场/源码发布**：root唯一采用十运行文件到10723/bili-safe-6af67806-c1c8eee2，旧5663正常停，运行冻结e9058a37；06:48:26 central非作者现场99f988核十精确/435其他/fullset，五库schema/raw等实际备份，170保护与当前6身份＋24产物（19导出＋5Bili）＋9WB＋3ZH保持。idle/alive/stale=false/pending0、默认MC、Edge35全26模块/三个RPC保持且无续采表。十文件源码efc4eb75f927f2857c26b409741b4d53a899f52f已push0/远端同，父c9e4e06；不是实际登录或新来源验收。E53源码7b3f6212与交接c9e4e06此前push0/远端同有回执。Bili paused/spent1of12/reserved0/ACK0与旧UNKNOWN/已知诊断失败保持；06:36:24原browser_candidates重读为expired/0target/credentials_imported=false/未绑定；未重连，本人连接确认及原账号CDP绑定待完成，不能拿候选受控sameUID替代真实proof。云DDL明确批准pending、ZH stopped12/12/0ACK、WB29ACK/剩9、watchdog暂停、48h未启动保持。
- **测试隔离经验**：CDP作者首SDK fixture仅patch httpx导出而未强制底层，可能尝试公共nav（仅合成Cookie，是否发出未取证），失败原件保留；最终六组强制MockTransport，父子进程物理拒绝全部INET/DNS、0尝试，由非作者独跑通过。不能声称整轮从未有网络尝试，也无原凭据被读的证据。

### E53历史｜Bili原生资料复用真实失败，已正式止损；成熟Bridge/CDP路径待核验

- **已实现/历史采用与发现**：V4原生Bili/同次nav公开WBI参数/原MC音轨受控整链经472d冻结、5095非作者审查，14文件曾采用1426并发布92353178；原SDK受控HTTP5/nav1/loopback0及三导出通过不是原持久登录可用证明。原生真实诊断随后未取得可用凭据，触发本轮止损；不能继续沿旧14文件离线通过宣称native可采。
- **当前正式运行与发布**：三生产`pro_native_credentials.py`、`pro_login_recovery.py`、`accounts-ui.js`已采用`native-profile-guard-5d33f0c10dc9461d`/PID5663，旧1426正常停。Bili凭据读取的read/collect两入口在profile IO或启动浏览器前拒绝未核实的凭据模式；安全诊断保留固定native原因，账号页不再显示未使用的Bridge、不把空凭据判为登出。组件非作者86a3、UI独审d67a通过；现场481989ec核三精确及其余源码/fullset、五库当前schema/raw等本次备份、166保护及6身份＋19导出＋9WB资产＋3ZH元数据保持。Bili account更新为本次诊断状态、binding改为native是此前已知操作变化，不声称一直等旧77f/8b05。代码7b3f6212d85ec7bfe28f7345a6c5026101fe7f1d已push0/远端同，父92353178。Edge35/RPC不变、默认MC，无中央V3部署。
- **真实恢复结果及未知边界**：原V2唯一POST400的intent/UNKNOWN仍保留，具体错误及旧marker影响未知。有限核销后的新一次diagnostic已root显式apply并启动，但终态check_failed；实际Bridge0/官方nav0，原账号未取得新认证证明，原source仍paused/spent1of12/reserved0/ACK0，不能写“已恢复”。原诊断误归Bridge失败的缺陷由本次安全native诊断修复。当前CookieDB计数元数据独立只读确为0、mtime1792102016.584；未读Cookie值。此前19条尚无可复核固化before原件，不能断言“19→0”已证或归因删除/本人登出。已安装Playwright bundled中的mock/basic启动参数确实存在，只能作为机制疑点和时间关联，删除因果未建立；已停止再次开启原profile试参数。
- **成熟替代路径与当前连接**：Bridge→同次官方nav公开WBI参数→成熟原MC媒体的替代候选，仅受控HTTP6及三导出通过，尚未正式采用、无新来源或ACK。只读查到正常Chrome69991/127.0.0.1:9222；root一次现成browser_candidates仅得pending、0targets、credentials_imported=false，未绑定25cc、未做官方同主体。已请本人确认原Chrome连接，不能称已登录或按profile名字判同一账号。原Bridge967 disconnected，仅旧Bili缓存标记；原XHS71456/d261 connected亦不能证明Bili同主体。不动日常Chrome3.5.2。
- **仍未通过**：云续采/诊断升级明确授权仍pending、未执行；WB29ACK/3of12/剩9保留，ZH0894实际12/12/0ACK且已Owner停止。Bili真实正文/根回复分页/新媒体/三导出/逐条权威ACK与连续OTA仍待分别验，本机participant71、全端/两设备及48h未通过，watchdog暂停。

### E52历史｜403防循环修复已正式接入；中央升级等待明确授权

- **真实失败与止损**：修复首败后新task08940d4f发生四个local e246/68d/6d1/1a5，各官方self200、Signer200、文章403，被旧guard当77/login_required，并被失败前旧self自动恢复。实际共12/12、0正文/0ACK。root已Owner停止，原件显示parent stopped、child waiting、spent12/reserved0/ACK0；不再发知乎任务、不扩预算、不把官方self成功当内容可访问。原0a0dc9/034b仍是已正常failed释放的0spent/0reserved/0ACK，失败原件与唯一attempt保留。
- **已修改/测试/正式运行**：仅本机4生产+1回归测试已采用access-recovery-c863975c5447bb63/PID95308，旧90039正常停。知乎内容403改failed87/pro_content_access_denied，保留已认证状态；官方self401仍77。通用自动恢复必须有失败之后的新核验，原authorized_run与旧verified_at不能自证恢复；历史等待项只读原失败run时间守门。38原调度回归、原SDK403→87及失败空导入、self401→77、26额外caller负例独审通过。未带中央诊断/continuation/新SQL或Edge变更，不冒称云端已能显示新诊断。
- **采用后独立现场与发布**：05:24:37非作者实际核5精确+436其他/fullset、五库schema/raw等实际备份、166保护及6身份+19导出+9WB原件+3知乎元数据保持；idle/alive/stale=false/pending0，Bili paused与ZH stopped等待列表保持、Edge35全部26模块/三个RPC保持、无续采表。源码e71b10c2a3e22cbbe29c42d6a3bfc939583cb444已push0/远端同，parent99b49bd。实际修复生效不是新来源业务通过；没有再次采集或新增ACK。
- **中央候选与审批阻塞**：WB续采combinedV3 a83e + 必需f83b文案覆盖已获非作者9293离线通过（21运行文件/Owner grant/剩额/原SDK复用/新媒体/诊断87与SQL合同）。首次apply_migration被自动审批拒绝：创建持久表并整体替换核心任务RPC的高影响范围尚缺明确授权；已向本人提问，仍待回复。实际SELECT确认source_continuations不存在，source/image/steps三RPC MD5均保持原值；未换方式执行，未部署此候选，也未真实WB续采/新媒体云回取。原WB29ACK/3of12/剩9保留。完整V3未来须基于95308重新窄合并，不能再按旧90039整文件覆盖。
- **Bridge/设备边界**：05:14:12原Chrome71456/原profile与client连接保持；root一次固定本机刷新后source=extension，非作者元数据fresh=true/age17.5秒。未向平台self或来源请求，未输出或保存凭据；原self已过180秒，不能用新缓存推断当前登录。participant仍缺登记，本机71未验，远端71仅既有证据。原Bili仍暂停1/12，watchdog暂停、48h未启。

- **其他平台在研**：`RUN16/pro-native-bili-provider/`正在补原持久登录复用与同次官方nav公开WBI参数的成熟纯函数接入；计划避免默认8989依赖和重复核验，不复制Pro受限实现。候选尚未完成独审或正式采用，原Bili暂停与1/12保持。

### E51历史｜知乎文章正式接入，真实首试启动故障已定位并释放

- **已正式采用和发布**：知乎原Pro文章/回答、评论分页/回复、原持久登录→私有FD、同ref自检、Signer及来源投影九文件经V3/登录组件/文章增量互为非作者审，通过14整链、7原SDK登录链、136单测、15 WB/计数回归；文章另13原SDK场景/2scope/回答回归/原JS随机loopback签名通过。86806九文件采用后非作者实际核9+429/fullset、五库schema/raw备份、129保护/6身份+19导出+9WB原件保持；Edge35仅合同0b586变化，其他25模块同34、无SQL。源码122659d1de45ed735f9f3b7ab92adb915e1b0328已push/远端同。MC默认、WB已选3/持久计数、参与者/评分/outbox/OTA保持。
- **同输入纠偏与真实失败**：实际331a是zhuanlan文章，最初回答候选不能替代；root补文章成熟client/extractor/store入口后独审，中央V2修3host目标与前置校验不一致，19正12负/旧MC hash与行为保持，原16字段只加Pro、media=false/1正文/3评论阈值/12API/180秒、不添interval。原69c三0600路径/平台元数据已安装，无Cookie值。唯一新task0a0dc9bb/local034b4531自动领取，但启动86/pro_signer_wrapper_changed：文章wrapper改了而manager仍pin旧SHA。真实0API/0来源事件/0ACK，Signer/凭据助手/self均未启动；不是平台登出证明，不能叫新知乎来源成功。
- **原失败已正常结束，修复正式采用中**：缺DB的启动失败另卡importing，中央仍reserved12。精确failed86/0耐久budget/0事件/无DB/无任何Signer凭据与续采意图的空导入修复经非作者11正负例/真实原件只读验证，其他import错误仍拒绝。维护V1独审发现会碰原Bili登录heartbeat，V2仅实例跳过其他等待项且保列表、限制原lease heartbeat/failed0finish；经真实state临时库完整_tick独审后root sole实际执行，原task现failed/spent0/reserved0/ACK0，原034b失败原件保留、worker idle。未手改state/SQL、未重采。先遇锁忙在intent前退出，确认未执行后才再次取锁。Signer pin修复另通过真正owned8990原JS/SDK生命周期5签与正常stop；四文件已采用90039/pro-zhihu-launchfix-f98fa02701cb2d78，旧86806停，采用后非作者实际核4冻结/436其他/fullset、五库schema/raw等本次备份、130保护及6身份+19导出+9WB原件+3ZH元数据保持，调度idle/pending0/defaultMC、Edge35/26模块保持；源码0dfbc04eef2050a48ef670cc50fa61f54a3df8ed已push0/远端同，父122659d。
- **继续工作与缺口**：WB续采SDK组件V2经root非作者六原SDK进程/旧5精确复用、新3候选、未知写/取消/fresh同ID/projector只读/三导出通过；不把旧来源冒新HTTP。完整Owner grant/新lease剩9/新媒体下载与旧bodyACK/仅fresh云交付受控V1已冻结，V2正窄合知乎及启动修复，尚未部署/真实续采；WB旧29ACK/failed3of12不变。知乎新来源/真实评论分页/真实云ACK仍需修复后的有界实测，不以离线或启动当验收。本机participant目录仍待本人、71未证；远端71既有证据保持。Bili原暂停、watchdog暂停、48h未启。

### E50历史｜评论选择与持久计数已正式采用，原任务续采尚未贯通

- **正式运行**：已从79044更新为pro-wb-bounded-progress-9cfb601d24eec2fb/PID82744。四文件包含MC兼容评论选择和当前持久计数，组件非作者5d2a/83a9、组合编排独审通过13测试及原SDK整链。采用器实际核五库已有行、原任务/配置不变；采用后非作者现场独核4冻结/433其他/fullset、五库schema/raw等备份、129保护及6身份+19来源导出+9WB资产保持；实际原WB显示1正文28评论、仍failed74，来源报告0/0保留。默认MC/idle/alive/pending0、原Bili暂停1/12与Edge34/26模块保持。源码3ebed6b0b8f2c618f987a89c228ecafbd957b6ec已push0/远端同，父d086。先前回复分页两文件ecf8/c62b已在79044正式运行并经实际独审，d086344922f07014b45206ace5061f3611f735ad已发布，父1f66b69。
- **功能和边界**：原MC在callback前选根，旧Pro先存20根才限；现按同输入max3选前3根及其回复，保留raw20/selected3证据，未处理游标不跨，部分页不冒完整。fixture少请求不是实际平台稳定加速证明。计数读已保存观测，显示原WB1正文28评论并保留来源报告0/0及failed；不改历史文件、正文版本、29ACK或预算。原e2d/6ad仍failed、used3/12/剩9，无新来源或新媒体云回取。
- **原任务续采在实现**：中央failed无通用恢复，简单requeue会maxitems0；Owner CAS grant/同worker新lease/可信公开seed/finish账户context/新媒体绑定旧bodyACK仍未整链部署。seed初版发现跨数据库commit与来源journal间崩溃窗口，V2 fac910补耐久pending并经root非作者8测试/重开/遗漏行负例及旧29只读断言通过（b430），原5条精确复用不增版本；组件通过不是SDK/Owner整链通过，未决明确unknown；不能把旧29当新来源或再次投递。grant16隔离测试不等于续采可用，不新建任务/重置预算。
- **知乎及设备待办**：知乎whole94452独审查出账号切换竞态和声明回复数量可篡改两项P1，修复V3 aefd已由原peer独立复核14整链+121测试及两个原P1反例通过（0f797），未正式接入。原持久知乎凭据候选de993也经root非作者15测试+7原SDK受控整链通过（e8f479），正在窄合当前82744及中央route合同；原69c真实官方self仍未验，不能用合成Bridge作已登录证据。participant目录选择尚无新确认，本机71未证；远端71既有证据保持。watchdog暂停、48h未启。

### E49历史｜微博原登录正式接入与真实部分交付

- **代码/正式运行/发布**：WB原持久资料→原MC凭据转换器→私有FD→原Pro账号池两份自有码，经V2非作者冻7bea/报告bbdf独审采用pro-native-wb-ee8c83c2060ba13c/PID75108，旧66029停止。非作者现场6819实际核2冻结/435其他/fullset、128保护/6原身份+19资产、五库schema/raw等actualbackup、idle/pending0、原Bili暂停1/12与Edge34全部保持。两0600新配置仅已有SDK路径及WB/native_persistent绑定，无Cookie。源码c49446d69b09ce155c9b39b70549d1e2b017d21d已push0/远端同，parent e05775a。V1超时无界等待及修复期失败保留；V2恶意持FD后代、抗TERM、父死清理、250ms正常慢退、10provider+5原SDK整链独审通过；真实原浏览器取凭据已在本次来源中使用，不外推所有OS。
- **新真实来源明确部分失败**：唯一task e2d613f2/child c012ccf4/local 6ad03e92，原WB e7c5会话/原89da同16字段，仅显式Pro；media=true/1条正文配置/3评论软阈值/12API/180秒、不新增interval均保真。自动领取后官方self通过，建立首次当前UID基线，历史同主体未知。实际1正文28评论=29原SDK观测/归一化/29权威UUID/hash/envelope/ACK精确；37中央来源步骤与本地sequence一致（3开始3响应1正文21页收到9页保存）。中央和本地failed74/wb_embedded_replies_incomplete，used3/12/reserved0，未提交父checkpoint、不伪完成。新媒体未下载、无WB新图云回取；不能拿29ACK当完整分页/媒体验收。
- **导出/页面实测**：正式R79三导出各31全行，本次29语义版本、typed字段/bodyhash/新run观测一致；非作者已逐31全行和29新来源语义独立复核通过。实际跨75108重启，原IAB未reload，监控恢复1741ACK/pending0，原未提交library_tag标记保留；已清测试标记。banner正常出现，但一次非白名单旧请求提示仍在，不能说全部操作自动恢复。UI-ACTUAL-RECOVERY.json/截图留原件。
- **下一步与不变项**：优先补WB真实暴露的独立子回复分页，再按原任务剩9总预算续验，不能新建/盲重试或改media=false凑通过。已购Pro及原MC WB都仅嵌入回复，新增自有分页适配0ecc候选已离线独审f450通过，仍未采用/未验真实schema，不冒成熟完整能力。知乎首组件740845候选已原SDK持久化/导出受控通过，整入口身份/签名/预算/投影仍在实现，正式SUPPORTED未扩。原participant目录32502仍待本人选择，本机71未证；远端71、原19/20两条回执和XHS40ACK/99步骤保持。watchdog暂停、48h未启。

### E48历史｜03:32 OTA现态与原profile恢复边界

- **远端71已有新证据**：03:17 fresh云查询原6a88节点71/正式release cfe4、注册03:16:48、健康71/current/queued0；昨22:39有OTA started/waiting/completed，后续自然started/skipped无新OTAerror。事件本身无版本摘要，结论联合节点登记/摘要/健康，不外推远端native文件/回滚链直验。
- **本机阻断定位**：原3cde仍70，最新云登记昨17:38、最后事件16:51。helper8198638a、loaded70/applied、计划任务正常、签名71ZIP dceb完整缓存；原XHS903d profile无participant licije…登记、无临时load参数，原Local Extension Settings七文件855031B保留（只SHA不读值）。原23266初在，随后Kimi无窗及宿主ps不存在；root随后观察原Chrome均已退出，原因未知，不归因代码、OTA或用户行为，不能冒给旧PID窗口。日常原33775已退出，root最新定位日常69991；其同ID指向另一产品3.5.2，禁止覆盖。完整installed70逐32文件/31releasehash/正式公钥签名与缓存71权限未扩展已独核。仅诊断，未恢复/发OTA。
- **原profile已正常重开，参与者仍未恢复**：root已正常启动同903d原资料Chrome71456，窗口32478/目录选择面板32502；无临时load参数，AX确认原CookieBridge1.1.0已启用。参与者登记仍缺，面板尚未选目录；工具pending_editor_write守门阻止后续输入，已请本人仅选择原已审CrowdParticipantExtension目录。此为开窗/Bridge状态，不是参与身份恢复或本机71采用。随后才可核原storage/身份并走既有bootstrap/签名缓存→apply→selfreload→ACK，不关闭其他Chrome。现原task19/20 complete2/2、proof31–34 received、原用户approved/consent保持；当前本机outbox值未知，恢复后安全状态核。OS anyChrome守门确使离线poll只缓存，在线扩展可走现成apply，不为此先重写全局锁。WB原账号provider V2仍待独审、未采用；它不同于E46已采用的WB图片云v2，后者仍由当前66029继承。provider实际结果待root回执，不预写。

### E47历史增量（03:10时点）

- **E47代码/采用/发布**：受控8990 Signer与工作台旧页只读会话恢复9文件已独审并采用pro-managed-signer-b5c9289fe9b65a7d/PID66029，原63675停；03:04非作者实际核9冻结/427其他源码/fullset、127保护/6当时身份+19源导出、五库schema/raw等actualbackup、idle/pending0、原Bili暂停1/12/ACK0与两原浏览器/桥保持。XHS原collector新增私有0600安装描述仅原python/source_root路径，无凭据。源码aadbb265fcb35cb8329cc23b85bf27feee2e053b已push0/远端同，parent33ef2fe；fresh Edge34全部26模块保持，没有本批SQL/Edge变更。默认MC、WB媒体范围、身份/评分/云回执/OTA保持。
- **E47新真实有限交付**：唯一新task95bf7c2a/childb749bedc/cloud0e5e0421/local191453b6，仍原XHS/同18字段+Pro、57/20/120/media=false。自动领取完成，原SDK40观测=1正文39评论；本地completed0、共享28/57、中央completed/spent28/reserved0。非作者freshSQL逐条核40UUID/hash/权威envelope/回执，99中央来源步骤与本地typed精确（28开始28响应1正文21页收到21页保存）；R78三格式各100全行/41本次语义逐字段和版本/bodyhash保真。运行自动Signer66430 started0→stopped13/failed=false，PID退出、8990无监听，原意图保留；40新proof同digest已消耗且每条总尝试1/无重队列错误。不是手工预启Signer，也不把旧SQLite投影冒新请求。
- **E47耗时与边界**：新来源17.8343秒、来源终态至最后云回执52.4099秒；旧ddf为17.8329秒及94.6743秒，本轮观测交付段缩短44.64%。只有一次真实对照，40vs41条/API28vs30且网络未控，不能宣称纯因果、P95或稳定提速保证。新39评论vs旧40，共同34稳定字段全同；两次均10根但只8根相同，缺2根及其4回复/新2根及其3回复解释全部ID差异，排序/删除原因未知不猜。仍limit_reached、媒体false/1reference不是字节云回取，中央checkpoint_committed false不证明游标commit，不是全量等价或全产品验收。
- **E47遗留/下一步**：代码支持XHS/DY8990运行内受控生命周期，但安装描述本轮只登记XHS，且仅XHS真实通过；DY安装登记/whole/真实、Bili8989管理和在途Node孙进程父死清理仍未验。工作台只对白名单只读查询允许nonce刷新一次，写操作绝不重发；root已首次实际刷新后健康/1741ACK/pending0，第二次正式重启后的浏览器自动恢复尚未实机验，不把离线guard复现当原403根因。WB原绑定/登录主体未知，真实新图/云回取未验；Bili原窗口待本人、原任务暂停剩11，不能再开MC登录或猜client。continuation旧pin须适配66029并独审。本机OTA71采用、远端原生文件链、两设备全端/48h仍缺；远端节点71登记/摘要/完成事件已有E48新证据，watchdog暂停。

### E46历史增量（02:52时点，已发布33ef2fe）

- **E46实际采用**：WB本地原图链、附件注册/Owner入口、25MiB图片云v2与精确显式路由已组合采用wb-media-v2-0bc0ea5d3195e2a3/PID63675，原61292停。02:51:01 CST非作者实际10冻结/420其他源码/fullset、127保护/6身份19源导出、五库全部schema/raw等actualbackup、无新表，idle健康/pending0、原Bili暂停1/12/ACK0与两原浏览器/桥连接保持。默认MC及参与流程/评分/outbox首投优化/原云回执/OTA保持。
- **E46中央**：实际SQL迁移20261015184558/crowd_weibo_image_v2，只有旧MD5守卫及精确replace图片RPC，无表/trigger/ACL重建。fresh RPC41204/body等已审候选/MD5 134e0f96284a346550eb94e0eb2191fc；原音视频34817/md53d039…、图片guard/RLS/service-only/私有50MiB五MIME保持。先Edge33仅3image变化、23原32模块逐字保持；后Edge34仅contract开精确WB媒体路由，fresh26模块4对应formal冻结、22其他逐字原32/JWTfalse保持。
- **E46范围/验证**：显式Pro仅WB/detail/单内容/media=true/无wordcloud/空options图片链；混合/视频实际到成熟child明确拒绝，不删媒体伪成功。复用原MC下载器、共享预算及原Pro正文/分页；本地附件复核同run观测、图片字节与像素，再走原私有存储prepare/commit/get。非作者原SDK整链、实际4.28MB JPEG fixture解码、Python→Node/Deno→PGlite、旧XHS34/音视频208及Python29/13路由负例通过。缺summary曾AttributeError断HTTP已固定ValueError，首败保留。完整浏览器UI未实机验；没有新微博来源、新下载、真实云回执或回取，不能把fixture图当新图。正式同输入业务验收尚缺。自有15文件源码f12bae0cefafb6c18b560b709c23d2ffd336bed0已push0/远端同，parent34576d66，见wb-media-adoption/SOURCE-PUBLISH-RECEIPT.json。

- **E46当前接入与UI风险**：原WB e7c5会话目录保留，但02:40只读无state/pro-binding/pro-executor、原profile无Bridge登记或精确运行进程；两已连client的WB状态均null，原登录主体/凭据是否有效未知，不猜client或判登出，不复制Cookie。先复用原profile完成明确绑定/官方主体基线，再同输入小试。旧页POST403另有离线6条件守门复现：重启令nonce过期足以触发同错，刷新可恢复，但实际旧请求头未留，原次根因未知；前端目前无旧页刷新提示，待修，不自动重发POST或放宽Host/Origin。Signer未来候选仍未采用，不算当前能力。

### E45历史增量（02:42时点，已发布34576d66）

- **E45实际采用/发布**：首投优化正式采用outbox-first-e89dee4adc555537/PID61292，原55325停止；02:39:29 CST非作者实际核2冻结文件、427其他源码/fullset、127保护、6份当前身份/19来源与导出摘要、五库actualbackup保持。唯一数据库变化是outbox新增空capture_first_delivery，旧表SQL/raw全同、其他库无新表；历史捕获不回填proof。源码两文件281ac9181857541d9ce421c01480901b250ed23c已push0/远端同，parent805cc5a。Edge32/SQL和默认MC/参与流程/评分/云ACK/OTA不变。
- **E45功能/效果边界**：仅全新capture同一stage事务铸造proof，消费与耐久尝试预扣在网络前，首次1租约守门+1capture；未知/失联/历史/重置/缺proof仍原receipt-first，同UUID/hash/ACK守门保持。9新/38原/7独立负例和采用包8便携/4schema/3额外坏表检查通过。2ms模拟41行只证明client+guard调用164→82；本次没有新source或真实capture投递，线上实际提速未测，不能把部署通过当效果验收。
- **E45未解决**：E44新XHS41来源/105中央步骤/R77/41ACK有限验收保持，旧94→40有效软阈值变化已解释但完整等价未过；没有媒体字节云验收。Bili原3cda仍暂停1/12剩11、Bridge101/official0未更新；原窗口43833保留，root最新AX快照6E5EE804仍见登录QR，没有新官方self，不重复要求扫码。continuation旧pin51342必须适配当前61292再独审。此为E45时点：WB本地静态图1cde已非作者通过，WB云v2当时尚待独审采用；随后E46已修summary并采用精确路由，仍未新下载或云上传。watchdog暂停、48h/两设备/全端/连续OTA业务验收仍未全过。

### E44历史增量（02:27时点，已发布805cc5a）

- **已部署中央合同（E44）**：crowd-machine Edge32 ACTIVE经非作者实际回读26运行模块，对31仅contract.mjs一处增加WB；25其他模块/image/audio/decoder/WASM/许可pin、JWT false及custom-auth保持。实际媒体RPC OID34817/定义MD5 3d039b00cbf9cb4090a9dd92f1960409、service-only和最新迁移162327未变。formal contract已精确同步。只表示中央可接受微博Pro入口，不能当微博媒体、完整子回复或热搜已验收。
- **统一代码与采用（E44）**：Pro真实HTTPX/aiohttp步骤、耐久正文/页读回投影、账号页正确恢复入口与微博显式路由11文件已组合，WB只合原SUPPORTED白名单一literal。组合103测试、Pro Bridge8及账号DOM通过，组件与采用包非作者审查通过。root已唯一采用pro-source-observability-a42363d843e7ee56/PID55325，旧51342停；02:07:17 CST非作者实际核验11冻结文件、417其他源码/fullset、5库schema/raw行等actualbackup、126保护/6身份、idle健康/pending0、原任务/原窗口保持。源码11文件+Edge合同共12文件fe4766e88c9899b9c817e912c0ae25e8d3fd7a5d已push0/远端同SHA，parent46006dd8；采用与发布各有原件。默认MC、参与者身份/评分/outbox/回执/OTA和原Bili暂停任务保持，未启动新来源。
- **监控可证明与未知（E44）**：底层请求开始/真实响应状态/异常沿原预算送既有mc-source-steps.sqlite3；包含本机Bridge/Signer的Python调用，不等于Signer内部全部外网请求。Pro页/body projector同journal原sequence，fact登记与事件原子幂等；由校验过的operation SQLite和分页描述证明当前已保存正文、页描述、完整或选中部分行。逐ID/parent读回，空页与saved=true单独不造保存成功，checkpoint不伪推进；原e7e95行/f2c107行/旧failed2fe的最小临时副本回放、9测试及90并发/30transport/3facts exactly-once独审通过，原件SHA保持。**旧run读回是现在的观测，不是历史真实HTTP补录**；未附请求关联/HTTP的0为未知哨兵。磁盘/锁/监控失败只固定source_monitor_error，不重试来源；全IO失败仍unknown，不宣称无丢失全链监控已终验。
- **新真实XHS有限云交付（E44；非作者最终现场审查通过，有限范围）**：root仅创建新task69602e3b/child69edfc3b，原XHS持久登录自动领取localddf0753c/cloud850b58bb；同e7输入18字段保持，仅显式Pro，预算57/评论软配置20/120秒/media=false未改。原XHS安装描述先前缺失，已用O_EXCL/0600登记同已购SDK root/python并经非作者核，未复制凭据。原官方self成功后accountstate合法更新，采用前6hash守护只属于02:07采用时点，不能要求账号状态永远不变。实际本地completed/exit0、API30/57；中央completed/spent30/reserved0，41新来源=1非空正文+40评论，41逐条不可变回执与权威envelope typed精确对应。105中央source_step与本地sequence逐条一致：30request_started/30response_received/1content_saved/22page_received/22page_saved。R77三格式各99行，其中42本次语义版本（41source+1media reference）逐字段/body hash和新run观测一致。root执行已审inspector有限范围PASS；02:23:37 CST非作者fresh云查询、41原Pro观测/不可变capture/回执、163中央事件中105来源步骤及R77三格式99全行/42新语义复核通过。仅有限新来源云交付，不是全产品验收。
- **本次未证明的功能（E44）**：分页coverage=limit_reached/upstream_batch_limit，不是exhausted；与旧e7的94评论相比本次40评论，有效阈值差异已有冻结源码及原SDK受控回放证据：旧0aca仅设聚合config，processor从base_config按值导入；23f7ae4后在导入前双设20。本次软阈值实际生效，1根页limit_reached；旧5根页exhausted。同一合成44根/50回复链原SDK旧路径94、新路径40由另一非作者重跑复现，不能倒填历史实际scalar为0。共同39评论稳定字段全同，旧缺55来自未选后续根页/回复、新增1；不是API预算耗尽（30<57），不能推断平台删除或这些缺项当前仍可取得。有效阈值原因已解释，但旧94到新40全量保真仍未通过，不能仅凭回执放行替换。媒体原配置false，1media reference不是已下载字节或私有媒体云回执；中央source_step的checkpoint_committed固定false，不证明游标commit；这不否定本地原SDK已完成checkpoint的事实。新Signer56392已正常停止/sign14/failed=false，无浏览器启动；30为Python守护尝试计数，不能外推所有平台内部网络。旧548/原Bili3cda预算/77不重启、不覆盖；仍需原同输入完整性对照和媒体/云音轨后续验收。
- **账号与下一步（E44）**：02:07:50 CST正式Owner HTTP只读已证账号页返回原Pro+Bili cloud_pro/task3cda/child5063与实际Bridge101/official0诊断，未触发恢复或浏览器动作。账号页仅对原云Pro+Bili等待任务显示后台恢复，精确task/child走已有context门禁，不再误导启动MC窗口；其他平台/本地旧登录保留。最新Pro核验仍Bridge101/self0，原Bili43833/window32276待本人登录，不能关闭或把历史XHS回复当确认。原3cda仍暂停/spent1/12剩11；V4曾适配旧51342，**新55325下须先更新冻结/独审，不直接跑旧pin**。新XHS任务已有限完成正文/评论/中央步骤/导出/41ACK；最终独立现场有限交付已通过，94→40差异已定位旧阈值未生效而本次生效；完整数据集等价仍未通过，旧548不重启、Bili任务不改、不删media/options凑通过。后续真实结果按维度独审，音轨云回取/OTA71真实采用/两设备全端/48h仍未全验，watchdog暂停。

### 01:48历史增量（E43；当时51342为正式运行）

- **最新正式运行（E43）**：关闭顺序与Owner后台提示已组合正式采用mc-login-close-8ea076214923fd39/PID51342，旧48081停。01:46:58 CST非作者实际核4冻结文件、419其他源码与完整fileset、126保护资产、五库schema/raw行等实际备份，idle/alive/pending0/defaultMC保持；原3cda暂停/spent1/12/reserved0/ACK0与原等待上下文、6原身份绑定hash保持，原Chrome43833/同client连接及原XHS23266保持。没有新来源、self或云任务变更。四文件源码a1cb414b611bf87af2317472fa133a8641c1fe23已push/实际远端同SHA，parent4881；此前4881/1685已发布。Edge31/SQL162327未改。
- **修复范围与限度（E43）**：仅官方已核验Bili且非borrowed连接，在原Playwright manager退出前close context，10秒收尾上限；其他平台/未核验/borrowed路径不变，关闭失败保留真实官方证明并记固定诊断。8专项/43账号回归/原SDK whole login-worker与故障退出独审通过；尚无真实浏览器关闭后的Cookie持久性验收，不能认定这就是先前Cookie/登记丢失原因。Owner后台提示已正式采用：browser_started严格false说明复用已有登录后台核验，旧MC文案保留，不自动继续暂停任务。
- **仍待本人登录与实际采集（E43）**：最新官方Pro核验仍是E42的Bridge101/official0，不能当新成功；原Chrome43833/window32276登录QR等待本人回复，窗口不可关闭。新代码采用没有代替登录，也没有重发恢复请求。本人完成后先核同原client平台凭据及官方同主体，再Owner继续原3cda仅剩11。continuation V4已仅两literal适配新runtime/freeze，root非作者精确差异及10项测试通过；FREEZE-V4 cb9c275d、runtime pin501f10aa，main未执行，不是任务恢复或来源成功。正文/评论/新音轨/导出/云ACK与音轨云回取仍未通过。watchdog暂停、48h未启保持。

### 01:44历史增量（E42；48081及Owner文案未采用为当时时点）

- **已修改/测试/采用/发布（E42，业务未验收）**：Bridge故障分类、Bili启动保护、严格原云等待任务恢复入口13项自有文件已独审并正式采用42916，源码1685f809d5fef76d62da17e91e617f976b17509a已push且远端同SHA。其后新增仅Pro+Bili的无浏览器官方核验，复用已购SDK固定client loader和原官方pong，原active锁/状态机/同主体generation与pending原子守门；真实父launch→stdin/FD→SDK子进程和取消/失败/竞态独审通过。现正式pro-login-bili-2d3f94bb24f176c7/PID48081，旧42916停；6冻结文件、415其他源码/fullset、126配置作业资产、五库schema/raw行等实际备份及idle/alive/pending0已非作者现场核验。源码6文件4881de95d6966fb85960f3ba146f85921851f768已push/远端同SHA。默认MC、参与者身份/评分/outbox/回执/OTA及Edge31/SQL162327保持；不是全部Pro能力或实际采集已验收。
- **真实恢复结果（E42）**：原任务3cda/child5063/cloud99b/local7f8仍暂停，requests_spent1/quota12/reserved0/ACK0（01:43:07 CST实际只读task_status，revision2/epoch1；文件名0147不作时间依据），首次来源执行前Bridge失败的原77及其首次HTTP/业务码未知保持。严格恢复API已原位绑定pending7f8。旧MC login-only曾实际官方HTTP200/code0、同主体并授权7f8、active锁释放；之后只读发现原profile的CookieBridge登记再次缺失，旧成功不等于当前桥可用。恢复原登记后，新Pro登录核验的唯一实际结果为Bridge HTTP200/business101、Bridge1/official-self0、check_failed/未授权；没有来源正文、评论、媒体或云ACK新增。不判平台登出，不重试未知或在条件不变时再核验，不把旧MC成功补成新Pro成功。
- **当前本人登录等待（E42）**：原Chrome43833/window32276保持打开，不可关闭。root实际AX后，本轮central再次只读AX独核，显示“登录”“登录后你可以”“扫描二维码登录”“登录二维码”；snapshot11E7686C-5937-48F5-9C22-DC4BCB687E87，树截断，不保存二维码图片。本人已被请求在此原窗口登录，当前尚无新回复/官方Pro同主体成功证据。Bridge连接/组件登记不能替代Bili登录与Cookie可用；不读/复制Cookie，不重开其他profile，不再启动MC登录窗口。
- **根因边界与局部待采用（E42）**：MC-LOGIN-CLOSE-ORDER.json以精确嵌套顺序合成回放，证实Playwright manager先退出、外层再尝试close context的代码顺序缺陷；不是实际原浏览器回放，也不能证明它导致本次Cookie/扩展登记丢失。当前同25cc账号无browser_connection字段，旧MC代码走同持久目录/Chrome channel，不是已证CDP或storage_state旁路；时序原因仍未知。Owner后台核验提示修复7056dedf已独审，尚未采用；旧cleanup5c50与知乎旧断言冲突已暂停，不算通过。
- **明确下一步（E42）**：待本人原窗口登录且同原client确有平台凭据后，使用已采用Pro恢复API做一次有界Bridge1+official-nav1同主体核验，不启动/关闭Chrome或MC浏览器、不补时间戳。通过后仅Owner继续原3cda，中央既有resume_login/claim产生新run/epoch且只分配剩11，总使用不超过12；不再创建新同输入任务。continuation V3仅固定实际采用版本的代码候选已审，未执行main；正文/评论分页与父子、同run新音轨/轨道、三导出、中央逐条ACK分别验，再做已授权私有音轨云保存回取独审。Pro本地SQLite页不是中央source_step，OTA71实际采用/全端/两设备/48h仍未通过，watchdog暂停。

E41 00:55历史候选记录了原3cda首次断桥和38818正常菜单退出→39840重开、原登记/client连接保持；当时Bili凭据和官方self未验，代码尚待采用。E42已推进采用及新的实际核验，但不抹去其原77/首次响应未知与预算。E40 00:32的“任务尚未创建/driver待审”仅是历史快照，不是当前状态；这是E42当时的发布状态；随后E43已合并并发布46006dd8，当前E44发布仍须独立回执。

- **00:32历史正式运行（E40）**：Pro正文评论→原MC媒体→私有音轨云合同已整套非作者审查并正式采用。本机pro-audio-combined-ff26da2ed8bb5022/PID34905唯一、旧27475停；16冻结运行文件和398其他源码/完整fileset、五库schema/raw行等实际备份、125配置/作业资产保持，调度idle/alive/pending0。crowd-machine Edge31 ACTIVE，实际26模块对30仅contract/media_storage_contract/media_storage/image_storage四模块变化；image decoder/canonical/WASM、index及部分页监控保持。实际迁移20261015162327/crowd_pro_audio_v3，ledger原statement SHA df30462a2f3a09056879f1ccee7e18b3b5766e7efad7491156da62c6b4a251b6精确等审包；RPC34817定义MD5 3d039b00cbf9cb4090a9dd92f1960409、service-only执行，原媒体bucket私有50MiB，新增audio/mp4后共五MIME。以上均由独立只读现场证据核验，不是作者自述。
- **能力与发布边界（E40）**：默认MC、旧请求hash及既有参与者身份/评分/outbox/云回执/OTA保持。新显式Pro仅放行Bili/detail/单正文/media=true/quality严格16+long_audio严格true，其他媒体/选项继续明确拒绝，不删选项或静默回退。20自有源码加实际SQL迁移共21文件提交fa30b761cd38c2a0eff79518323a85171555eb98，push返回0且root实际ls-remote同SHA，回执RUN15/pro-audio-adoption/SOURCE-PUBLISH-RECEIPT.json已核。原XHS Chrome23266及同原client Bridge连接再次独立核验保持，未读Cookie值、未重发self。
- **已闭环的代码问题（E40）**：共享预算302隐藏请求漏扣及坏stage免扣已修，真实localhost四transport/八子进程并发及回归独审通过；原失败保留。媒体子进程组timeout/cancel真实清理，独立65MiB流触发64MiB音轨限制并清暂存、101MiB输出触发watchdog；100ms采样不是零超调磁盘配额。实际原Pro main/SQLite/checkpoint→父stdin→原MC child合成底层链通过，正文评论typed保持、三格式逐字段/hash导出通过。音频SQL最初把合法12k正文按旧整体10k限制误拒，已仅v3扩整体上限并实测90k正文/真实换行和超限拒绝；原v1/v2/图片兼容、权限与bucket锁守护通过。Python音频/UI独审42项、真实FFmpeg音轨/视频区分与DOM负例通过。受控测试不证明真实音视频质量或云音轨回执。
- **本地安装与准备（E40）**：root已在原Bili collector安装0600的pro-executor.json，仅含本机root/python路径、无凭据，不改原身份/全局执行引擎，安装回执已核。
- **仍未完成（E40）**：截至此快照，新Pro同输入真实任务尚未创建，真实音轨云保存/下载回验与Pro中央逐页source_step未验；不能以原MC的18ACK/25来源步骤替代。准备driver V1的pending-outbox漏查和inspector原地补媒体标签两项被非作者阻断，V2已冻结b4b4e40d并交central非作者终审，尚未通过或执行真实主程序；未知意图不重发。旧成熟Bili-only SignSrv源码/54项私有参考hash/现成venv已只读核验可复用，绑定端口8989（不是XHS/DY的8990），root随后已复用旧工具新生命周期启动PID36429/8989，当前记录nav0/failed=false，未采来源；外部nav至多1另计，不冒充共享Python12预算内部流量。原task19/20各2/2、旧548failed73预算、OTA71仅缓存未采用、watchdog PAUSED及48h未启保持。

- **23:52历史路由时点（E39；已由E40组合采用推进）**：单任务显式MC/Pro路由已非作者独审并正式接入：源码六文件800949f80aeaa07db6ad499fc33a25721c5a6f0b已推送/远端同SHA；crowd-machine Edge30 ACTIVE，实际26运行模块对29仅contract/core改，12公共许可元文件保留，无SQL迁移。本机task-executor-route-85e5f3863629e220/PID27475唯一，旧21129停；非作者4源码/401其他源码/完整fileset、五库schema/raw行等实际备份及125保护项保持，cloud idle/alive/pending0。默认MC和旧请求hash不变；显式Pro能力不足明确拒绝，不偷偷退回MC。9路线/9正式便携测试/117回归/33真实PGlite合同通过。
- **原登录与媒体边界（E39）**：非作者再次仅查元信息，原XHS Chrome23266、原client连接及Secure Preferences登记保持；不重发self/getCookies。完整Pro媒体/options仍拒绝，不能把路由上线称Pro媒体已接管。共享预算候选被真实本机302反例阻断：2个HTTP仅扣1；坏stage可免扣也已定位，修复中。Bili媒体隔离候选有受控HTTP的原SDK流程验证，未真实平台下载/云保存；不接未审预算、不拿旧文件或正文ACK充当新媒体验收。71最后已验仍缓存/applied70；原19/20各2/2、旧548failed73预算、watchdog暂停/48h未启保持。

- **23:36原登录恢复时点（E38；登录证据保持，运行版见E39）**：本人完成原CookieBridge恢复后，原client d2617c14-779a-4984-823a-3d81c99723d3连接恢复。只结束本轮自有Chrome17009，原目录重开23266，扩展在Secure Preferences登记仍在且Bridge重新连接；未换profile、手工删锁或编辑凭据。退出使用SIGTERM，不是已验证的应用正常退出。新单次官方self为HTTP200/code0、同原账号摘要；1Bridge/1签名/1平台请求，原身份/绑定/548文件保持。该次凭据source=cache，不是实时同步证据；不写Owner账号状态或重启548。Signer23420已正常停止/sign1/failed=false，原浏览器和Bridge保留。驱动及实际结果分别由非作者独核通过，见E38。
- **引擎与未完成项（E38）**：正式仍为xhs-bridge-launch-2a1a0b3429f8d84e/PID21129、SQL150035/Edge29；最近Bili18ACK/25来源步骤/R75三导出属于Native MC，非Pro媒体接管。单任务source_executor路由5文件候选初9路线/117回归/33数据库合同通过，但独审发现安装描述文件读取存在检查与读取间替换风险，正在修复；未正式采用。完整Pro媒体仍明确拒绝，成熟媒体隔离/共享总预算/平台图片云合同和真实同输入媒体未完成，不能删媒体或画质选项凑通过。OTA71最后已验仅缓存/applied70；watchdog PAUSED/48h未启。

- **23:20历史执行引擎核准（E37补充；XHS现态见E38）**：正式snapshot的pro_executor.selection只读全局CROWD_EXECUTOR；media=true或任何非空platform_options都会在启动前回退MC，mc_runner显式请求白名单没有source_executor。故本轮Bili真实正文/评论/音频/导出/ACK及部分页监控是Native MC证据，不能写Pro同功能已接入或已验收。默认MC保持；单任务严格路由与成熟媒体链正在下一轮候选中实现，待独审/正式采用/同输入实际引擎取证后另记E38。XHS已通过异步工具请求仅恢复此前授权的原目录组件登记，不要求扫码；原Chrome17009正常保留，登记恢复仍未完成。

- **23:15历史功能增量（E37；当前运行版见E39，XHS见E38）**：MC选中部分保存阶段page_partially_saved已独审并正式接入SQL20261015150035/crowd-machine Edge29 ACTIVE，本轮先采用mc-partial-page-90696313f6233689/PID19437（旧10368停），随后wrapper正式采用为当前xhs-bridge-launch-2a1a0b3429f8d84e/PID21129（旧19437停）。新阶段明确“本页已保存选中部分”，保留page_saved全页语义和checkpoint_committed=false。源码6文件f97309a8673c8c05f4f9b9a88ae99e33f55e8730已发布，随后wrapper两文件2cfa68059a6938f20843c53a063fbf0efec7775a发布；非作者实际ls-remote与本地HEAD同2cfa且parent为f973，其他脏文件未并入。实际独审4runtime/399其余源码/完整fileset、124保护资产、五库schema/raw行等实际备份，cloud自然idle/alive/pending0（采用后时点）。
- **新真实有界验证（E37）**：独立新task bd2f778e-1f16-4e5e-9b01-d1dd188500be / local c089751f-933a-4286-8f72-6b13626c4dec实际completed/API8（上限12），1正文17评论、18逐条权威ACK、25中央source步骤与SQLite同；root partial_saved3及reply全页10/3/1真实配对，全部收到的页有保存或部分保存记账。rev75三导出各20行typed一致，18新来源语义/正文hash保持；相对修复前95ed全部18稳定实体相同。音频40367529B/SHA5c05…同旧，不是全MP4或本次云媒体。仅有界选中部分监控/数据回归通过；root仍partial不是full、checkpoint=false、非全量。75da/95ed/c089的manifest预算均1/3/12，历史75da缺1reply原因仍未知，不能归因预算。旧95ed的strict=false/原inspection保留，不补写历史事件。

- **23:15历史XHS恢复尚未完成（E37；已由E38推进）**：防默认禁扩展wrapper V2 source2a1a0b34已独审并正式采用xhs-bridge-launch-2a1a0b3429f8d84e/PID21129、旧19437停；两runtime文件精确、402其他源码/完整fileset/125保护/五库actualbackup原行及调度idle/alive/pending0由非作者独核。针对两个endpoint字段18个非字符串反例补str门禁，旧V1初审漏项/失败原件保留；正式53测试通过。root正常启动同原nested profile的Chrome17009，无disable-extensions或新增load/debug标记；精确LevelDB clientId键与原Bridge client摘要相同，但原Bridge仍offline且Preferences/Secure Preferences缺扩展登记。旧“目录不一致”推测已撤回；禁止换profile/复制登录资料/把缓存cookie存在当已恢复。原19/20各complete2/2、旧548failed73预算、OTA71仅缓存未采用、watchdog PAUSED/48h未启保持。

- **22:46历史时点（E36；最新运行版见E37）**：参与端71登录状态诊断已独审、签名发布并公网回取；原公钥/固定ZIP/安装包逐文件核验通过，本机native仅已下载缓存71，实际status仍applied70，不能称71已安装或远端生效。B站原登录持窗修复4492已独审正式采用，随后安全诊断72ce正式采用为bili-login-diagnostics-72ce8a883f77366b/PID10368，原7018停；诊断两文件源码6f8dbcb2d9b85873f9ed0156b181bb14dcf1169f本地HEAD及origin跟踪同SHA，root已取得push返回0和ls-remote同SHA，本文未另发远端请求。旧原worker7216保留原窗口但self不可用、8次暂停为历史失败；安全诊断72ce8a88源码及实际采用均非作者通过，10368唯一监听/原五库及123资产保持。root正常结束旧暂停worker后，同原session新有界核验一次取得官方HTTP200/code0、resumed/login_verified=true，无需用户扫码、未修改proxy。旧失败根因仍未取证，不用新成功倒填。
- **本轮真实采集增量（E36）**：原账号恢复后新有界Bili云task c81bb819-5486-4848-ad36-e7a48837d454、local95edb761-c070-4666-a192-7eed4d238d76、cloud run50fe2d98-55f0-4dce-927d-5ee92c8c40e8实际completed：1正文17评论/API8、18条云ACK，24中央来源步骤与本地SQLite typed一致；rev74三导出20行（18新来源实体的语义/正文hash/原始评论和直接parent已逐项核验）。40367529B音频SHA5c05e023…与旧75da相同，不是完整MP4、没有本次云媒体上传。正文/回执/导出/音频维度通过，完整验收未过：同输入旧9实体共享8无稳定字段差异，但旧1回复缺失/新10观察，原因未取证；根页received1/saved0虽实存3根，逐页保存监控不完整，无游标commit证明。非作者纯函数重算原24事件，严格页配对false；旧INSPECTION的bounded_sample_acceptance=true仅被独立旁证更正，原件不覆盖。原task19/20各complete2/2保持，原48h/watchdog不启动。
- **XHS核验边界（E36）**：原Bridge client的stale_cache凭据单次self得到HTTP200/code-100，1Bridge/1Signer/1平台；原文件与548已耗尽任务保持。Signer正常停止/sign1/failed=false。只证明此缓存凭据未通过官方self，不能判本人当前浏览器未登录，未改身份或重发任务。root随后仅通过原API open_login打开同903d原session，worker13403/page_ready、waiting_login；未证明登录恢复。当前原浏览器带--disable-extensions且未加载Bridge；首次“新旧profile不一致”推测已由旧34252同nested目录记录反证撤回，不能擅换目录或清profile。正式修复在研。旧v1在Bridge1/平台0/签名0因本地枚举拒绝终止；重复执行被O_EXCL挡在请求前仅有工具转录定位，未另存原stderr，不冒作独立现场证据。

- **18:44历史时点（E35；当前运行版见E36）**：MC来源逐页监控已正式接入，SQL实际20261015104015、crowd-machine Edge28 ACTIVE，本机mc-source-steps-a93e3c362d9264ff/PID82126，旧图片版79817停。自有源码8项提交c113aa60b4d313ac1de9df51cca1b3ff41f833c2已推送授权分支。非作者实查唯一监听、五库schema/raw行等真实备份、123保护项及仅5源码变化；调度idle/alive/pending0，无新source任务。图片代码保持，MC采用后真实Owner status/file回归同98878B及像素。当前58条仍为旧交付步骤，新真实来源source_step回执尚缺；不能把接线采用当全平台来源验收。

- **18:37历史时点（E34）**：自有图片云源码36项提交b39029ff0743925613d3a7219cf21f993c14693b已推送授权分支并ls-remote同SHA。中央image迁移实际20261015100501、crowd-machine Edge27 ACTIVE（实际26运行文件逐byte核候选）和私有bucket图片MIME已生效。本机image-cloud-b048d69fd3acc6ea/PID79817正式采用，旧68433已停；非作者核6源码/完整文件集/395其他源码、123保护资产及原五库schema/raw行等实际备份。rev73、1624ACK/pending0、58步骤全ACK保持。
- **真实图片云业务验收已过，仅此单图**：原e7正文/capture ac97394f、同job3179a0d4、artifact6bfc6313，原98878B WEBP一次PUT后仅GET续接；最终ready/receipt manifest154b6db9…、回取SHA64dad9b…/1080×1440/单帧/像素780b47…与原MC相同。非作者实际2个只读SQL核来源、capture/envelope、任务/child/run/epoch、引用/claim/私有bucket绑定；正式Owner HTTP与原浏览器“查看云状态/下载云端图片”真实通过。未重采来源、未重传原95内容、未改原五库和源三文件。
- **两次真实失败保留**：最初image_prepare invalid_image_manifest（Storage操作0），定位原Python正文28短换行转义与网关canonical域不同；分别保留哈希域，102交叉/9负例及原件PGlite独审通过，Edge26采用。随后一次PUT后commit image_object_mismatch；本机真实Deno2.5.4重现解码成功但node:crypto拒Uint8ClampedArray（托管现场原错误分支未直接取到），显式Uint8Array偏移视图和缺ImageData兼容由非作者真实Deno/Node及偏移/并发复核后Edge27采用，原对象仅commit/GET成功。没有移除正文或像素校验、删除对象、改假fixture或覆盖旧失败。
- **逐页监控18:37历史候选，后由E35正式接入**：MC source v3离线完整SDK/JSONL/SQLite/队列/Edge/SQL独审通过；发现JSONL假设、畸形事件与跨phase诊断字段泄漏均修复。后续Edge包基于实际27、runtime基于已采用图片版、CLI迁移20261015103312准备中；此时尚未部署/采用或取得新真实来源步骤回执。原WB真实链、自动来源媒体、原任务重登恢复、其他Pro平台保真/全端/远端原生连续OTA/48h仍未完成。watchdog保持PAUSED。

- **17:26历史时点**：WB自有五文件提交3c164f6eadae3a45c950453c4b61ca6ea597c0cd，独审后正式采用pro-weibo-aa40fc9b67a0e98d/PID68433，原61381正常退出。五锁/五库实际备份守护通过；非作者已核6文件/完整fileset/123配置/五库原始行不变，rev73、1624ACK/pending0及58步骤全ACK。非作者最终HTTP已自然idle/alive/stale=false，391其他源码字节与完整文件集保持，实际采用终审PASS。默认MC/WB未启用，未启动WB来源或新云任务。原媒体d744/真图/历史导出证据保持，不把模块采用称WB业务验收。
- 原XHS本人登录后官方200/code0/self摘要通过；先前f4de 77/check_failed/观察0保留，未抹成成功。临时Signer整串Cookie猜账号锁由独审修正，身份仍固定Bridge client和官方self摘要；新有界e7e01fbb-5e8e-47b3-b473-5d24fc77f1cc已真实completed，1正文+94评论（44根/50回复），46 guarded HTTP尝试含loopback，34.609秒意图至终态；不是平台专属总请求或端到端/P95。43持久页/checkpoint独核、可访问页链exhausted不代表平台全量。旧548失败73不重启；当前原会话已恢复并绑定e7，不能用新任务替代旧任务恢复验收。
- 真正发现并修复：max_comments20只写聚合config，XHS/DY从base_config读取导致本次94条超阈值。原94及全部失败保持；2行初始化补接、原SDK实际processor/SQLite/checkpoint独审正反例通过。语义为整页含回复软阈值（20可保存24再停），不是硬20；修复后尚无新真实来源cap验收。未知核验失败新86与明确登出77分开、Owner中文提示、知乎/贴吧字幕module hook不依赖factory一并独审并采用；当时全MC测试有4继承fixture失败；本轮db58009已补真实SDK测试桩，正式36通过，原失败日志保持历史。
- e7正式导入冻结rev72，JSON/JSONL/CSV三格式97项=95新正文评论+1新媒体引用+1旧媒体项；双哈希保真比较已重算来源/语义/正文合同，旧10实体无缺失或字段变化，85是新观察而非全新发布。原规范文件保持引用不重写；E32新增旁挂媒体经显式既有代理下载，已证明与旧MC字节/像素等价并进入正式rev73/HTTP下载。URL引用变化保留，不靠删参数判等价；图片云链在E34完成原单图真实验收；自动来源触发未验。
- 云任务2dcf771d-c73e-4e22-b4f0-0b689ba8c2aa沿唯一创建意图实际completed，95唯一received回取逐字段typed等同冻结rev72；source spent/reserved0，未再采来源。95份原始envelope/hash/UUID/receipt与outbox逐条非作者独核通过，finish/source0、52条交付阶段中央步骤seq7–58连续至completed；不是新来源执行。临时Signer47739已正常停止，22native签名/0外部nav/failed=false；浏览器和CookieBridge保留。其他平台、完整原任务重登、远端连续OTA和48h仍未全验。

- XHS媒体已经补到正式本机工作台：旧直连尝试unknown意图保留不重试；确认主机原配loopback HTTPS代理后，独审的新显式CONNECT/TLS实验1CONNECT+1GET取得98878B WEBP，SHA64dad9b…与原MC逐字节相同、1080×1440/单帧/RGBA摘要相同。保留源URL与HTTPS传输hash差异，不去参数造等价。已审附件模块/详情下载入口正式采用，实际HTTP/api/media和真实浏览器按钮下载均同字节；rev73三格式实际HTTP导出独审。该历史时点仅本地保存；E34已补同图私有云保存回取，来源自动下载仍未接通；原norm/status/manifest三SHA保持。
- 附件独审发现11类sidecar篡改误放行、暂存未注册可播放、坏JSON掉连接和blob等待后旧下载，均已修并以正式13单测/独立负例/Node时序复核；首次错误原件保留。该历史时点缺图片云合同，E34已补正式合同及原单图回取；未改名MP4。MC测试桩补真实SDK接口（原32业务测试AST不变），正式36测试通过，单文件db58009已提交；原4继承失败不再是当前正式测试结论，旧日志保留。
- 微博Pro v3已独审并正式安装：executor f237331c/module aa40fc9b，原SDK7 whole execute、59unit、旧XHS/DY6回归及严格负例通过；加能力展示后61unit/3环境门禁通过。原嵌套漏6仍完成与schema_version=True误放行反例保留，现缺额partial74/父游标保持、严格类型核验。上游真实cap四平台与本地required三平台/可选WB分域，默认MC，WB须显式引擎和flag。原WB profile仍在，但无运行进程/Bridge扩展元信息/pro-binding，登录有效性未验证，不判登出或重复扫码。已定位6旧MC样本；89da详情可作下一同输入基线，WB根parent=self不能套XHS空parent投影。实际WB来源、完整子回复、热搜/推荐、媒体字节与云尚未完成。

- 中央机器步骤：SQL迁移20261015062743、错误码迁移20261015062750及crowd-machine Edge24已部署；原worker/claim/run/epoch绑定、耐久步骤/坏组隔离/Owner分页已独审。此前source0三条及6步骤通过，当前新增95条交付阶段52步骤通过；E35已接MC原引擎逐页机制；实际新来源中央步骤与所有平台来源全过程仍缺，不能称全程监控完成。
- OTA与原参与者：源码03a38fe、通道/工具b6be7cd，签名70 seq2026101570；本机原helper已采用8198638a通用binary，真实68→69→70/原身份队列历史/任务19、20各2条保持及云OTA事件已独审。16:30后fresh SQL两原节点均70且release摘要9e5b46…一致；task19 ready、task20 unknown为节点上报而非官方平台self。两者各有started/waiting/completed及后续skipped，事件自身未带version/digest；远端helper二进制/采用链仍未验，旧69快照保留。旧12条unexpected_error保留，新自然ota_*故障尚未现场；升级后旧Chrome消失原因未知，没重发apply。固定ZIP2992d9f/包摘要见E28。
- 旧B站/云资产：2fe来源failed/api_request_limit保持；新f2c有界批次1正文20根86回复、40runner+1Signer受控尝试（不是平台总数）。两份纠正source0云交付236观察=131去重实体，正文/父子/origin/metrics/冻结版本/回执独审已通过，不能当236新内容或全评论耗尽。保留旧保真失败与未知状态，详E25–E30。
- 48h实验和看门狗仍未启动/PAUSED。默认MC保持，后续Pro平台须逐维度同输入证明；手机/Windows/VM、本轮真实评论软阈值、来源自动触发/其他格式真实图片云链、长视频质量及远端OTA原生链仍有缺口。重要历史时点与首次失败保存在E25–E31及CHANGELOG，不把旧阶段候选状态当当前事实。

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
| .crowd-launch/runtime-revisions/owner-preview-fb5636ff3bb3/ | E58当前38406，继承已审17文件续采/36码客户端及Owner轮询确认修复；XHS/Bili/CDP/流式媒体SHA保持。中央Edge37已部署独核。真实WB新尝试失败74，父5/12剩7/旧29，不能用部署或旧回执称业务通过。默认MC，显式Pro原守门保持；snapshot不等于Git HEAD |
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
| crowd-kol | 2143c7c2e3c42a7294809789ad319422c6cfd03b已push0/远端同；父ed7bdddb为17文件；云36码56639c17 | 当前38406/owner-preview-fb5636ff3bb3，云37；原微博已知失败shape/剩7/新ACK0，其他未提交资产不并入 |
| crowd-pages | 0a3bc4f04d0b2ffafd4c8619096ba6f3e28ea900 | 签名OTA71；固定ZIP提交deaab37b7eca21056ee2007e9d7aaeef90e15960；远端71登记/摘要/完成事件已证，本机71采用及远端native文件链未验 |

crowd-kol所列发布回执本轮已读；其余仓沿先前已核版本，不能当本次新鲜HEAD。运行源码以第3节E58及continuation-card-preview-runtime运行冻结为准，并保留continuation-current-runtime-adoption的17文件继承链，不能以HEAD替代；不要reset/clean或覆盖其他改动。


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

先读E58、actual-wb-continuation/INDEPENDENT-FINAL（28cb）、当前38406单Owner实际独审b425，再读17文件独审8bcc/现场6e165及最终源码链接。云端以Edge37/36码实际独审98bc为据，不沿旧Edge35/36快照当当前证明。真实原WB已领取、两请求后已知失败，不再是“尚未开始”。

1. 修SDK hotFlowChild原response合同并保单次HTTP与共享预算/步骤；不凭HTTP200推断实际payload形状，不复制vendor。修最新失败与原seed分离的链式续采后，只对latest epoch2/已知失败/原scope/剩7做新CAS授权，禁止重放原grant或reset总12/旧29。
2. 未知、pending store、取消半写或身份改变仍阻断；代码/离线/部署/真实来源/新增云ACK分别验，画面文字不冒全文转写。中央目前实际细因仍通用码，需要补有限wb_reply_page_shape_invalid映射，不能声称已上云。
3. 贴吧V3受控独审已过但账号ref/Pro绑定/原Bridge与URL保真仍缺；current窄合保持WB/WBI/媒体，只读先核原资产与最小真实主体路径，不借Bili/XHS新profile安装权限、不重连expired CDP。Bili原3cda暂停、已用1/总12；知乎原任务stopped12/12，不擅自重启。
4. 旧历史4BEFORE和旧PREPARATION原字节丢失，不能假装可复核；新的采用已用现场索引和五库备份独审，事故与缺口保留。完成后按模板更新唯一入口、证据和日志；completed代理用followup_task唤醒，不以协调消息代替执行。

参与端连续OTA、其他Pro平台正文/评论分页/媒体/三导出、跨端和48h未全验，看门狗仍暂停；不得自行arm试验或扩大参与者预算。

## 9. 维护与共享

唯一当前状态为本文件。WORKSPACE/HANDOFF.md和爬虫/HANDOFF.md仅指针。[证据](handoff/EVIDENCE.md)、[日志](handoff/CHANGELOG.md)、[模板](handoff/ENTRY_TEMPLATE.md)组成精简交接包。

固定交接文件由本入口、证据、日志、模板及仓库AGENTS.md组成；此前WB自有源码3c164f6已推送并回读；本轮图片b39029f及来源监控c113aa6已推送授权分支；上一轮交接7a86a62已发布；E35三份交接已由本地RUN15/HANDOFF-1844-PUBLISH-RECEIPT.json记录提交4843031/推送/远端同SHA；E36三文档已由RUN15/HANDOFF-E36-PUBLISH-RECEIPT.json记录4666f84/push0/远端同SHA；E37/E38交接已发布cda2b30，回执RUN15/HANDOFF-E38-PUBLISH-RECEIPT.json；E39已发布b9bce91ef0ccf2c7678cb27468cfea7ce0b3e135并远端同SHA，回执RUN15/HANDOFF-E39-PUBLISH-RECEIPT.json；E40–E42当时仅为历史候选，未单独发布；随后E43合并E40–E43三文档已正式发布46006dd8c6203e0170f47edb6ea6d5e66404e386，push0/实际远端同SHA见RUN15/HANDOFF-E43-PUBLISH-RECEIPT.json。E44三文档已正式发布805cc5a0229a72191163447a8bbdd0402e89c128，push0/远端同SHA，见RUN15/HANDOFF-E44-PUBLISH-RECEIPT.json。E45已发布34576d66c995deab8460e02ddd5dc87999a2e288，push0/远端同SHA见RUN16/HANDOFF-E45-PUBLISH-RECEIPT.json。E46已发布33ef2fe0018c756b6d7647896dd0da0a29ddada2，push0/远端同见RUN16/HANDOFF-E46-PUBLISH-RECEIPT.json。E47发布以RUN16/HANDOFF-E47-PUBLISH-RECEIPT.json为准；缺失或无法读取时不认定已发布。该记录缺失或无法读取时，不能认定本轮文档已发布。授权目标为GitHub `huming0018-dot/crowd-kol` 的 `codex/v4.0.6-handoff` 分支。[在线固定入口](https://github.com/huming0018-dot/crowd-kol/blob/codex/v4.0.6-handoff/docs/HANDOFF.md)。本次同步状态以变更日志实际推送记录为准；尚未创建另一个在线共享页面。源码功能提交与交接文档提交分别记录。证据索引中的JSON、PRIVATE文件、运行数据与原始日志均只在本地，不随交接文档发布；在线接力者若不能取得原件，须标未核验，不把相对本地路径当作在线证据。

给接力者的固定指令：先读取此入口、EVIDENCE.md和CHANGELOG.md，核对所涉源码与证据日期，再按第8节继续。每轮结束更新状态、证据和日志；无法核验就明确标未知。外部bot只收到Markdown时只能读取已记录状态；要核验原件还须按最小范围提供相应脱敏JSON/产物，不能声称已查询线上。

旧docs/HANDOFF.md保存在Git `81ab4ae:docs/HANDOFF.md`，blob `cc09e64b93a11979b18355c3d0db45b383d52e14`；旧4.2.0/4.2.5说明只作历史。

交接包不含凭据值；不要添加.env、Cookie、密码、token、私钥、PRIVATE邀请或原始登录资料。路径/版本/摘要可以记录；分享前最小披露复核。不要将全部outputs或私仓源码打包外发。

E52交接发布以RUN16/HANDOFF-E52-PUBLISH-RECEIPT.json为准；缺失或无法读取时不认定已发布。源码e71b10c与本次三MD发布分开记录。

E53交接发布以RUN16/HANDOFF-E53-PUBLISH-RECEIPT.json为准；缺失或无法读取时不认定已发布。源码7b3f6212与本次三MD发布分开记录。

E54三文档已按上述真实状态冻结待非作者文档复核；本三文档尚不认定已发布，正式发布应另存RUN16/HANDOFF-E54-PUBLISH-RECEIPT.json，缺失或不可读不认定已发布。

E55文档发布以RUN16/HANDOFF-E55-PUBLISH-RECEIPT.json为准，源码和文档发布分别核对。

E56文档51a15dde已发布，实际回执HANDOFF-E56-PUBLISH-RECEIPT.json；E57文档发布另看HANDOFF-E57-PUBLISH-RECEIPT.json，不能拿源码发布替代。
