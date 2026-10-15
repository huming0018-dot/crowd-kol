# 分布式采集系统｜固定交接入口

更新：2026-10-16 03:10 CST，Asia/Shanghai。维护：Codex /root。本文件维护当前状态；重要历史留在日志。**交接是每轮工作的伴随机制，主线继续推进。**

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

### 2026-10-16当前增量（E47优先，以下为历史时点）

- **E47代码/采用/发布**：受控8990 Signer与工作台旧页只读会话恢复9文件已独审并采用pro-managed-signer-b5c9289fe9b65a7d/PID66029，原63675停；03:04非作者实际核9冻结/427其他源码/fullset、127保护/6当时身份+19源导出、五库schema/raw等actualbackup、idle/pending0、原Bili暂停1/12/ACK0与两原浏览器/桥保持。XHS原collector新增私有0600安装描述仅原python/source_root路径，无凭据。源码aadbb265fcb35cb8329cc23b85bf27feee2e053b已push0/远端同，parent33ef2fe；fresh Edge34全部26模块保持，没有本批SQL/Edge变更。默认MC、WB媒体范围、身份/评分/云回执/OTA保持。
- **E47新真实有限交付**：唯一新task95bf7c2a/childb749bedc/cloud0e5e0421/local191453b6，仍原XHS/同18字段+Pro、57/20/120/media=false。自动领取完成，原SDK40观测=1正文39评论；本地completed0、共享28/57、中央completed/spent28/reserved0。非作者freshSQL逐条核40UUID/hash/权威envelope/回执，99中央来源步骤与本地typed精确（28开始28响应1正文21页收到21页保存）；R78三格式各100全行/41本次语义逐字段和版本/bodyhash保真。运行自动Signer66430 started0→stopped13/failed=false，PID退出、8990无监听，原意图保留；40新proof同digest已消耗且每条总尝试1/无重队列错误。不是手工预启Signer，也不把旧SQLite投影冒新请求。
- **E47耗时与边界**：新来源17.8343秒、来源终态至最后云回执52.4099秒；旧ddf为17.8329秒及94.6743秒，本轮观测交付段缩短44.64%。只有一次真实对照，40vs41条/API28vs30且网络未控，不能宣称纯因果、P95或稳定提速保证。新39评论vs旧40，共同34稳定字段全同；两次均10根但只8根相同，缺2根及其4回复/新2根及其3回复解释全部ID差异，排序/删除原因未知不猜。仍limit_reached、媒体false/1reference不是字节云回取，中央checkpoint_committed false不证明游标commit，不是全量等价或全产品验收。
- **E47遗留/下一步**：代码支持XHS/DY8990运行内受控生命周期，但安装描述本轮只登记XHS，且仅XHS真实通过；DY安装登记/whole/真实、Bili8989管理和在途Node孙进程父死清理仍未验。工作台只对白名单只读查询允许nonce刷新一次，写操作绝不重发；root已首次实际刷新后健康/1741ACK/pending0，第二次正式重启后的浏览器自动恢复尚未实机验，不把离线guard复现当原403根因。WB原绑定/登录主体未知，真实新图/云回取未验；Bili原窗口待本人、原任务暂停剩11，不能再开MC登录或猜client。continuation旧pin须适配66029并独审。OTA71真实采用/两设备全端/48h仍缺，watchdog暂停。

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
| .crowd-launch/runtime-revisions/pro-managed-signer-b5c9289fe9b65a7d/ | E47实际独核通过的工作台源码快照；默认MC，显式Pro按已审平台/模式门禁，不外推媒体/推荐；工作树HEAD不等于运行版本 |
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
| crawler-extension | d7707cb82d26e0594ef8220299a5e8c3a37cf8cd | 71登录状态诊断源码；包签名发布/缓存已证，实际采用未证 |
| crowd-kol | aadbb265fcb35cb8329cc23b85bf27feee2e053b已发布；parent为文档33ef2fe | E47正式66029/Edge34已实际独核通过。已另有新XHS41来源/105步骤/41ACK有限验收，未涵盖全量及媒体字节；其他脏文件不并入 |
| crowd-pages | 0a3bc4f04d0b2ffafd4c8619096ba6f3e28ea900 | 签名OTA71；固定ZIP提交deaab37b7eca21056ee2007e9d7aaeef90e15960；实际终端采用未证 |

crowd-kol所列发布回执本轮已读；其余仓沿先前已核版本，不能当本次新鲜HEAD。运行源码以第3节E47当前增量及pro-signer-adoption采用冻结为准，不能以HEAD替代；不要reset/clean或覆盖其他改动。


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
| D2–D3 | E44已采用Pro真实Python transport与durable readback同journal接线，E44新XHS41逐条ACK及105来源步骤已独立实证；既有机器phase/Pro保存页/ACK也已部署；MC逐页机制已在E35采用，E36 Bili24来源事件根页保存缺失保留；E37新批次25步骤含选中部分保存已证，游标commit仍未证；通用参与者派单及supervisor child PID/预算标记时间仍不完整 | 任意任务两节点不重复领取、完整中央来源至ACK时间线 |
| D4–D7 | 用户中台恢复、克隆身份围栏、跨任务去重和并发仍未全验 | 同UID不清outbox恢复、双节点epoch竞态、失败隔离与受控并发 |
| Pro接入 | E44新XHS41来源/105中央步骤/R77导出/41ACK有限实证，最终独立现场有限范围通过；旧94→新40的有效阈值变化已有证据，完整数据集保真仍未通过；媒体false不含字节云链。Bili后台核验最新仍Bridge101/self0、原3cda暂停1/12，Pro音轨云和全量仍未验。E40 Bili单正文音轨组合已采用及现场独审。原XHS本人self已通过，e7真实正文/94评论、三导出/95云ACK独审，软阈值/86状态已采用；临时Signer已停。图片新显式代理通路已取得同字节、工作台读取/导出/浏览器下载通过；E34原单图图片云合同/回取通过，自动来源媒体仍缺。微博正文与静态原图/云v2已在E46采用，但Pro真实采集/新图云回取未验，其他平台Pro合同未补齐；E36 B站同输入有界批次正文/17评论/音频/导出/18ACK通过，但缺旧1回复/根保存事件/全视频仍未证 | 图片云合同/自动来源触发，同输入其他平台完整字段、分页回复、媒体、导出与逐条回执；不以工具测试替代真实成功 |
| 审查容量 | 历史有模型容量错误；本轮已完成媒体/五库/导出/OTA独审，WB正式接线及采用独审已通过，原单图图片云实际合同/回取与正式Owner入口独审通过，无新外部服务凭据接入 | 后续仍须非作者实际审查，不能把未出结论算通过或自行改模型 |
| 全端及质量 | Windows/VM/mobile、全评论媒体字幕、ASR质量和48h未全验 | 分OS/平台/维度的真实证据，不以Mac样本外推 |


代码行、复现与状态分级见E06–E14。作者的“已解决”必须由差异、测试原件和独立证据支持。

## 8. 接力可做与推进顺序

安全起步：读取源码/文档、uname/pwd/git status/log、SHA比对、既存脱敏证据；用已授权连接器执行明确只读查询。测试先审其副作用。不要为了核验调用claim/start/finish/arm，或启动会自动执行任务的服务。

下一步：先读E47实际采用/新任务独审与aadbb265源码发布，核对66029/Edge34未漂移。真实新XHS自动Signer与40ACK/99步骤/R78有限验收已完成，交付耗时单样本下降不是稳定保证；不为扩大统计无条件重采。WB图片链与精确路由已采用，下一步先核原WB持久登录/绑定可用性再做最小同输入新来源，不重复扫码或借旧图冒成功；新字节/评论分页/导出/真实私有云回取逐项独审。默认MC及原Bili3cda暂停1/12剩11保持。先读新XHS69602e3b/ddf0753c最终非作者现场报告及COMMENT-CAP-ROOT-CAUSE/CENTRAL-CAP-INDEPENDENT：41ACK/105步骤/R77已有限通过，旧阈值未生效、本次双赋值后生效导致页范围变化已解释；不能倒填旧实际scalar，也不能以此替代94→40完整数据集等价。保留当前57/20/120/media=false配置与limit_reached/partial，不无条件重采；需要补缺时基于诊断确定最小有界下一步，不重启548或删选项。新正文/评论/导出/ACK已有限实证，媒体字节、云音轨、checkpoint及全量仍另验。Bili待本人在原43833/window32276完成登录，原窗不关；条件变化后后台官方同主体再Owner继续原task剩11。旧continuation V4 pin51342，必须适配当前66029冻结并独审后才可运行。账号页已接正确Pro恢复入口，不开MC窗口；MC关闭顺序真实Cookie持久性仍单列。Pro中央全链/媒体云/OTA71/两设备/全端/48h均按证据分级，watchdog暂停。


## 9. 维护与共享

唯一当前状态为本文件。WORKSPACE/HANDOFF.md和爬虫/HANDOFF.md仅指针。[证据](handoff/EVIDENCE.md)、[日志](handoff/CHANGELOG.md)、[模板](handoff/ENTRY_TEMPLATE.md)组成精简交接包。

固定交接文件由本入口、证据、日志、模板及仓库AGENTS.md组成；此前WB自有源码3c164f6已推送并回读；本轮图片b39029f及来源监控c113aa6已推送授权分支；上一轮交接7a86a62已发布；E35三份交接已由本地RUN15/HANDOFF-1844-PUBLISH-RECEIPT.json记录提交4843031/推送/远端同SHA；E36三文档已由RUN15/HANDOFF-E36-PUBLISH-RECEIPT.json记录4666f84/push0/远端同SHA；E37/E38交接已发布cda2b30，回执RUN15/HANDOFF-E38-PUBLISH-RECEIPT.json；E39已发布b9bce91ef0ccf2c7678cb27468cfea7ce0b3e135并远端同SHA，回执RUN15/HANDOFF-E39-PUBLISH-RECEIPT.json；E40–E42当时仅为历史候选，未单独发布；随后E43合并E40–E43三文档已正式发布46006dd8c6203e0170f47edb6ea6d5e66404e386，push0/实际远端同SHA见RUN15/HANDOFF-E43-PUBLISH-RECEIPT.json。E44三文档已正式发布805cc5a0229a72191163447a8bbdd0402e89c128，push0/远端同SHA，见RUN15/HANDOFF-E44-PUBLISH-RECEIPT.json。E45已发布34576d66c995deab8460e02ddd5dc87999a2e288，push0/远端同SHA见RUN16/HANDOFF-E45-PUBLISH-RECEIPT.json。E46已发布33ef2fe0018c756b6d7647896dd0da0a29ddada2，push0/远端同见RUN16/HANDOFF-E46-PUBLISH-RECEIPT.json。E47发布以RUN16/HANDOFF-E47-PUBLISH-RECEIPT.json为准；缺失或无法读取时不认定已发布。该记录缺失或无法读取时，不能认定本轮文档已发布。授权目标为GitHub `huming0018-dot/crowd-kol` 的 `codex/v4.0.6-handoff` 分支。[在线固定入口](https://github.com/huming0018-dot/crowd-kol/blob/codex/v4.0.6-handoff/docs/HANDOFF.md)。本次同步状态以变更日志实际推送记录为准；尚未创建另一个在线共享页面。源码功能提交与交接文档提交分别记录。证据索引中的JSON、PRIVATE文件、运行数据与原始日志均只在本地，不随交接文档发布；在线接力者若不能取得原件，须标未核验，不把相对本地路径当作在线证据。

给接力者的固定指令：先读取此入口、EVIDENCE.md和CHANGELOG.md，核对所涉源码与证据日期，再按第8节继续。每轮结束更新状态、证据和日志；无法核验就明确标未知。外部bot只收到Markdown时只能读取已记录状态；要核验原件还须按最小范围提供相应脱敏JSON/产物，不能声称已查询线上。

旧docs/HANDOFF.md保存在Git `81ab4ae:docs/HANDOFF.md`，blob `cc09e64b93a11979b18355c3d0db45b383d52e14`；旧4.2.0/4.2.5说明只作历史。

交接包不含凭据值；不要添加.env、Cookie、密码、token、私钥、PRIVATE邀请或原始登录资料。路径/版本/摘要可以记录；分享前最小披露复核。不要将全部outputs或私仓源码打包外发。
