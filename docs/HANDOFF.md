# 分布式采集系统｜固定交接入口

更新：2026-10-15 23:36 CST，Asia/Shanghai。维护：Codex /root。本文件维护当前状态；重要历史留在日志。**交接是每轮工作的伴随机制，主线继续推进。**

## 1. 接力规则

1. 先读本文件、[证据索引](handoff/EVIDENCE.md)、[变更日志](handoff/CHANGELOG.md)，再读工作区 AGENTS.md 和涉及的模块。
2. 核对环境、分支、未提交改动和证据日期。聊天摘要、作者自述、测试目录存在、进程在线，都不能替代实际验收。
3. 无法访问或核验时明确说明缺口，标“未知/未验证”，继续可独立完成的工作，不声称已同步。
4. 每轮结束都更新日期、本轮结论和下一步；主要改动后，用[接力模板](handoff/ENTRY_TEMPLATE.md)更新本文件相关状态和证据，向日志追加记录；不复制整段对话。
5. 用户新指令优先。读过交接包不等于获得新采集、部署、付费或外发权限。

## 2. 目标、范围与阶段

目标：中心数据库动态分配任务到用户终端；本地复用本人登录、静默采集、耐久回传；中心逐条确认、监控步骤、定位异常。Owner 不应手工分配账号或 HTTP 请求。

必须保留：Kimi/现有参与者流程、身份、评分、暂停继续、outbox、回执、OTA；吸收 MC/已购 Pro 的平台、评论回复、媒体、推荐、账号、断点与分析能力。PC/Mac/VM/手机均在长期目标中；手机控制与手机本机执行分别验收。有效会话尽量长期复用，不能承诺 Cookie 永不过期。

当前阶段：Pro本机真实有界批次、固定观测的真实云交付、本机连续OTA已接入正式运行并独审通过；仍不是全部平台/全端完整产品终验或48小时实验阶段。详细状态见第3节。

2026-10-14新轮授权：并行实现中央槽释放、Owner恢复入口、Pro成熟能力桥；独审后正式采用并做原范围真实云回执、登录恢复与连续OTA验收。上轮只读交接限制已结束。保留原身份、原任务和每台两条预算；不自动扩额度、外发Pro私码、重置凭据、arm试验或恢复看门狗。

## 3. 当前状态

### 2026-10-15当前增量（优先于下列10-14历史时点）

- **最新现态优先（23:36，E38）**：本人完成原CookieBridge恢复后，原client d2617c14-779a-4984-823a-3d81c99723d3连接恢复。只结束本轮自有Chrome17009，原目录重开23266，扩展在Secure Preferences登记仍在且Bridge重新连接；未换profile、手工删锁或编辑凭据。退出使用SIGTERM，不是已验证的应用正常退出。新单次官方self为HTTP200/code0、同原账号摘要；1Bridge/1签名/1平台请求，原身份/绑定/548文件保持。该次凭据source=cache，不是实时同步证据；不写Owner账号状态或重启548。Signer23420已正常停止/sign1/failed=false，原浏览器和Bridge保留。驱动及实际结果分别由非作者独核通过，见E38。
- **引擎与未完成项（E38）**：正式仍为xhs-bridge-launch-2a1a0b3429f8d84e/PID21129、SQL150035/Edge29；最近Bili18ACK/25来源步骤/R75三导出属于Native MC，非Pro媒体接管。单任务source_executor路由5文件候选初9路线/117回归/33数据库合同通过，但独审发现安装描述文件读取存在检查与读取间替换风险，正在修复；未正式采用。完整Pro媒体仍明确拒绝，成熟媒体隔离/共享总预算/平台图片云合同和真实同输入媒体未完成，不能删媒体或画质选项凑通过。OTA71最后已验仅缓存/applied70；watchdog PAUSED/48h未启。

- **23:20历史执行引擎核准（E37补充；XHS现态见E38）**：正式snapshot的pro_executor.selection只读全局CROWD_EXECUTOR；media=true或任何非空platform_options都会在启动前回退MC，mc_runner显式请求白名单没有source_executor。故本轮Bili真实正文/评论/音频/导出/ACK及部分页监控是Native MC证据，不能写Pro同功能已接入或已验收。默认MC保持；单任务严格路由与成熟媒体链正在下一轮候选中实现，待独审/正式采用/同输入实际引擎取证后另记E38。XHS已通过异步工具请求仅恢复此前授权的原目录组件登记，不要求扫码；原Chrome17009正常保留，登记恢复仍未完成。

- **23:15正式功能增量（E37；运行版保持，XHS现态见E38）**：MC选中部分保存阶段page_partially_saved已独审并正式接入SQL20261015150035/crowd-machine Edge29 ACTIVE，本轮先采用mc-partial-page-90696313f6233689/PID19437（旧10368停），随后wrapper正式采用为当前xhs-bridge-launch-2a1a0b3429f8d84e/PID21129（旧19437停）。新阶段明确“本页已保存选中部分”，保留page_saved全页语义和checkpoint_committed=false。源码6文件f97309a8673c8c05f4f9b9a88ae99e33f55e8730已发布，随后wrapper两文件2cfa68059a6938f20843c53a063fbf0efec7775a发布；非作者实际ls-remote与本地HEAD同2cfa且parent为f973，其他脏文件未并入。实际独审4runtime/399其余源码/完整fileset、124保护资产、五库schema/raw行等实际备份，cloud自然idle/alive/pending0（采用后时点）。
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
| .../results_store.py、media_cloud.py、../postprocess/ | 实体版本/观测、媒体私有云、字幕/OCR/本地ASR；OCR不是全文听写 |
| .../supabase/functions/{crowd-access,crowd-gateway,crowd-machine}/ | 安装/参与入口、参与RPC、机器/统一任务及监控 |
| Supabase项目bdwrhshgdeghgyzwpxnl | 中央数据库；crowd-machine-media为已有私有媒体bucket；项目ID不是凭据 |
| crowd-pages/v4/releases/ | 安装包和OTA发布面，不是canonical源码 |
| http://127.0.0.1:45937/ | 本机工作台，其他设备不能直接访问loopback |
| https://app-lyart-eta-22.vercel.app/api/crowd/manifest | 正式安装元数据入口；最近已存生产回读见E02 |
| .crowd-launch/unified-workbench/ | 工作台配置、SQLite、作业运行资产；不复制其内容进交接包 |
| .crowd-launch/runtime-revisions/xhs-bridge-launch-2a1a0b3429f8d84e/ | 截至E37当前已采用工作台源码快照；包含原MC监控/图片能力，工作树HEAD不是运行版本 |
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
| crawler-extension | d7707cb82d26e0594ef8220299a5e8c3a37cf8cd | 71登录状态诊断源码；包签名发布/缓存已证，实际采用未证 |
| crowd-kol | XHS启动wrapper2cfa680；部分页监控f97309a；Bili诊断6f8dbcb | 正式runtime见E37；非作者ls-remote同2cfa，Bridge登记仍缺失，其他未提交资产保持 |
| crowd-pages | 0a3bc4f04d0b2ffafd4c8619096ba6f3e28ea900 | 签名OTA71；固定ZIP提交deaab37b7eca21056ee2007e9d7aaeef90e15960；实际终端采用未证 |

以上HEAD本轮实际读取。运行源码以第3节当前增量及E37采用冻结为准，不能以HEAD替代；不要reset/clean或覆盖其他改动。


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
| R1–R4 | 本机68→69→70已过；71已签名发布并native缓存，但实际仍70/71采用未证。原task19/20各complete2/2；完整登录恢复/真实评论休眠分页及远端原生连续链仍未全验 | 保持原任务、同账号，以原ID继续/准确partial/ACK证明，不新建任务制造成功 |
| D1 | 槽释放、原ID交付恢复、Owner入口已上线；当前无真实坏组可验 | 实际defer→原ID ACK→finish链；不人为破坏用户数据充当验收 |
| D2–D3 | 机器中央phase/Pro保存页/ACK已部署并source0实证；MC逐页机制已在E35采用，E36 Bili24来源事件根页保存缺失保留；E37新批次25步骤含选中部分保存已证，游标commit仍未证；通用参与者派单及supervisor child PID/预算标记时间仍不完整 | 任意任务两节点不重复领取、完整中央来源至ACK时间线 |
| D4–D7 | 用户中台恢复、克隆身份围栏、跨任务去重和并发仍未全验 | 同UID不清outbox恢复、双节点epoch竞态、失败隔离与受控并发 |
| Pro接入 | 原XHS本人self已通过，e7真实正文/94评论、三导出/95云ACK独审，软阈值/86状态已采用；临时Signer已停。图片新显式代理通路已取得同字节、工作台读取/导出/浏览器下载通过；E34原单图图片云合同/回取通过，自动来源媒体仍缺。微博模块已正式安装但未真实采集，其他平台Pro合同未补齐；E36 B站同输入有界批次正文/17评论/音频/导出/18ACK通过，但缺旧1回复/根保存事件/全视频仍未证 | 图片云合同/自动来源触发，同输入其他平台完整字段、分页回复、媒体、导出与逐条回执；不以工具测试替代真实成功 |
| 审查容量 | 历史有模型容量错误；本轮已完成媒体/五库/导出/OTA独审，WB正式接线及采用独审已通过，原单图图片云实际合同/回取与正式Owner入口独审通过，无新外部服务凭据接入 | 后续仍须非作者实际审查，不能把未出结论算通过或自行改模型 |
| 全端及质量 | Windows/VM/mobile、全评论媒体字幕、ASR质量和48h未全验 | 分OS/平台/维度的真实证据，不以Mac样本外推 |


代码行、复现与状态分级见E06–E14。作者的“已解决”必须由差异、测试原件和独立证据支持。

## 8. 接力可做与推进顺序

安全起步：读取源码/文档、uname/pwd/git status/log、SHA比对、既存脱敏证据；用已授权连接器执行明确只读查询。测试先审其副作用。不要为了核验调用claim/start/finish/arm，或启动会自动执行任务的服务。

下一步：先读E38原XHS登记恢复、重开连接和官方同主体self，再读E37部分页监控正式采用与新25步骤/18ACK/R75证据。优先完成单任务Pro路由独审、成熟媒体隔离和共享总预算，再按同一输入验证正文、评论分页/回复、媒体、三导出与云ACK。原XHS无需重复安装或扫码；官方self成功不等于旧548恢复或Owner状态更新。保留旧Bili24事件缺口原件和历史缺1回复原因未知，不重发未知任务或清预算。OTA71终端实际采用、两设备连续升级、全端和48h分别验；watchdog保持暂停。


## 9. 维护与共享

唯一当前状态为本文件。WORKSPACE/HANDOFF.md和爬虫/HANDOFF.md仅指针。[证据](handoff/EVIDENCE.md)、[日志](handoff/CHANGELOG.md)、[模板](handoff/ENTRY_TEMPLATE.md)组成精简交接包。

固定交接文件由本入口、证据、日志、模板及仓库AGENTS.md组成；此前WB自有源码3c164f6已推送并回读；本轮图片b39029f及来源监控c113aa6已推送授权分支；上一轮交接7a86a62已发布；E35三份交接已由本地RUN15/HANDOFF-1844-PUBLISH-RECEIPT.json记录提交4843031/推送/远端同SHA；E36三文档已由RUN15/HANDOFF-E36-PUBLISH-RECEIPT.json记录4666f84/push0/远端同SHA；E37/E38合并三文档本次发布以本地RUN15/HANDOFF-E38-PUBLISH-RECEIPT.json为准；该文件缺失时仍为候选。该记录缺失或无法读取时，不能认定本轮文档已发布。授权目标为GitHub `huming0018-dot/crowd-kol` 的 `codex/v4.0.6-handoff` 分支。[在线固定入口](https://github.com/huming0018-dot/crowd-kol/blob/codex/v4.0.6-handoff/docs/HANDOFF.md)。本次同步状态以变更日志实际推送记录为准；尚未创建另一个在线共享页面。源码功能提交与交接文档提交分别记录。证据索引中的JSON、PRIVATE文件、运行数据与原始日志均只在本地，不随交接文档发布；在线接力者若不能取得原件，须标未核验，不把相对本地路径当作在线证据。

给接力者的固定指令：先读取此入口、EVIDENCE.md和CHANGELOG.md，核对所涉源码与证据日期，再按第8节继续。每轮结束更新状态、证据和日志；无法核验就明确标未知。外部bot只收到Markdown时只能读取已记录状态；要核验原件还须按最小范围提供相应脱敏JSON/产物，不能声称已查询线上。

旧docs/HANDOFF.md保存在Git `81ab4ae:docs/HANDOFF.md`，blob `cc09e64b93a11979b18355c3d0db45b383d52e14`；旧4.2.0/4.2.5说明只作历史。

交接包不含凭据值；不要添加.env、Cookie、密码、token、私钥、PRIVATE邀请或原始登录资料。路径/版本/摘要可以记录；分享前最小披露复核。不要将全部outputs或私仓源码打包外发。
