# 分布式采集系统｜固定交接入口

更新：2026-10-16 14:47 CST，Asia/Shanghai。维护：Codex /root。本文件维护当前状态；重要历史留在日志。**交接是每轮工作的伴随机制，主线继续推进。**

## 1. 接力规则

1. 先读本文件、[证据索引](handoff/EVIDENCE.md)、[变更日志](handoff/CHANGELOG.md)，再读工作区 AGENTS.md 和涉及的模块。
2. 核对环境、分支、未提交改动和证据日期。聊天摘要、作者自述、测试目录存在、进程在线，都不能替代实际验收。
3. 无法访问或核验时明确说明缺口，标“未知/未验证”，继续可独立完成的工作，不声称已同步。
4. 每轮结束都更新日期、本轮结论和下一步；主要改动后，用[接力模板](handoff/ENTRY_TEMPLATE.md)更新本文件相关状态和证据，向日志追加记录；不复制整段对话。
5. 用户新指令优先。读过交接包不等于获得新采集、部署、付费或外发权限。

## 2. 目标、范围与阶段

目标：中心数据库动态分配任务到用户终端；本地复用本人登录、静默采集、耐久回传；中心逐条确认、监控步骤、定位异常。Owner 不应手工分配账号或 HTTP 请求。

必须保留：Kimi/现有参与者流程、身份、评分、暂停继续、outbox、回执、OTA；吸收 MC/已购 Pro 的平台、评论回复、媒体、推荐、账号、断点与分析能力。PC/Mac/VM/手机均在长期目标中；手机控制与手机本机执行分别验收。有效会话尽量长期复用，不能承诺 Cookie 永不过期。

当前阶段：正式本机工作台PID14880/owner-publication-b0881396-8edd79f7。Owner知识审核与独立发布/版本入口已正式采用，真实提案未批准，release/pin/rollback预检均正确禁用；知识四写表仍0。现场独审8aaa2582核4exact+465其他/fullset2新增、五库及31ACK素材/六店四格式保持，三原材料/领域/自动指针不变，knowledge-runtime为唯一授权配置变化；2过期预览nonce按TTL单列。源码5293ea5已push/ls-remote同。自动ACK处理仍待采用后合法新ACK实际发布；Pro Tieba原SDK回复/身份门/字段恢复有限独审通过，但原UID/媒体URL缺失、路由/云ACK未验，未正式替换。DY薄合并候选已冻结19e4610e（5改5新），作者报告保search/creator/零评论detail原路径，非作者central_steps正在复核；默认off，尚未正式采用或开放新能力。原本机节点14:31实核原Chrome在但参与扩展未登记/安装70/缓存71，不能改日常同ID的3.5.2扩展。原两节点恢复/连续OTA、全平台、双域/远端消费/跨端/48h未全验，原T0 13:06:48沿用。

2026-10-14新轮授权：并行实现中央槽释放、Owner恢复入口、Pro成熟能力桥；独审后正式采用并做原范围真实云回执、登录恢复与连续OTA验收。上轮只读交接限制已结束。保留原身份、原任务和每台两条预算；不自动扩额度、外发Pro私码、重置凭据、arm试验或恢复看门狗。

## 3. 当前状态

### E73｜知识发布入口已正式采用、现场独审与源码发布；完整闭环未验

- **实际改动与版本**：四份自有源（2改2新）复用原Host/Owner认证及065 SDK、V2 publication，不新增服务/队列。4源组件冻结4067189a/非作者ea3d2157；源码5293ea5e2d9feff3163982b67b17f281fbbfc95d已push/ls-remote同。计划1.2七文档已发布849188de，不以文档通过替代产品验收。
- **准备/发现/复核**：e73-owner-publication-adoption冻结0fa25dff；非作者0ccb43fa核原8采用函数AST/全文仅两常量、4映射和原3安装+追加3恢复反例通过。准备审的“旧rollback target须null”是审查假设错误，原白名单存在而COMMITTED缺失，已保初记录说明，不改产品造通过。仅复用已审E71机制，不复制全run/profile。
- **正式采用**：root唯一执行4源精确复制/旧2备份→批准冻结→预检96原source终态与5锁→adopter --apply：旧6620停、新14880；随后独立installer --apply，0600备份旧knowledge-runtime并原子切为f56ce8601fa5638e0618a44ffa437e9cd92fb764570f5257671c4d36770a5a76。新2配置仅指原binding/service/DB；仅单DB只读备份证据，不迁移、不种旧release、不调用grant/review/release/pin。材料/领域/auto三指针保持。
- **实际现场独审**：independent-runtime/FINAL.json 8aaa25828ea20a00d81717af942df1517bac66c19fb33f6260d40be6683ced32。14880唯一/旧6620停；4exact+465其他/fullset2新增；五库两次actualbackup/schema/raw同；原身份/预算及31ACK和六店四格式保持。230旧保护清单=227exact耐久+1授权知识入口配置变化+2已过期300秒preview nonce，后两项不是耐久数据；初FileNotFound保留，绝不写230全同。知识原DB22967c45088bb938c692443514e2c60c54136d039be8e21c689efbdf2daa685a与全表/rows同，四写表0，调度自然idle/pending0/scheduler alive。
- **真实页面/认证**：独审通过原CloudClient只读Owner认证执行publication_preview一次、原preview一次：原prop034/ad30、12unknown、人类UID None；acceptedfalse，candidate/current/rollback均None，三个发布动作false。root IAB真实预览另一次，首张ACTUAL-UI.jpg只展示审核区域、早先ACTUAL-UI.txt为无变更diff，不作为完整页面证据；后补ACTUAL-UI-FULL.txt与ACTUAL-PUBLICATION-SECTION.jpg实际可见发布区，独立API预检也证无原COMMITTED不可回滚；页面显示5分钟有效、发布/知识版本独立，未点任何审核/发布动作。原051 Consumer与云APP指针均未切；这不是本人批准后的完整发布消费验收。
- **Pro并行结果**：Tieba原freeze4ebcc+身份overlayefb63f，非作者b27e4b62独跑错ID拒绝与正常1body/3根17reply/2原JPEG/23三导出、11of12；缺reply而上游CP仍完成的反例由完成门拒媒体，不能称上游CP已修。field-recovery-v1冻62388ad7/非作者f4678b1c恢复21条日期/吧信息/计数，原gold未改、旧存档经model可保原语义；原UID不可逆、page/CDN URL仍合成，媒体source关联有原manifest但不冒原HTTP。仍未路由/新源/云ACK，不能正式替换。下一DY薄合并冻19e4610e：针对当前正式5改5新，不覆盖Owner/cloud；作者报告原105回归+WB多origin/新gate及热搜9of12通过，Pro环境缺requests首败保留并改用现MC环境，不装依赖。非作者central_steps正在复核，默认flag off且未采用，不以此候选称功能已交付。保正式search/creator/零评论detail，不能旧候选整包覆盖。
- **原节点具体缺口**：e73-local-node/LOCAL-FRESH.json于14:31只读核原903d资料Chrome71456在、扩展未登记、安装4.2.70/缓存71；日常Chrome69991是另一同ID产品，未触碰。CUA只能绑定日常窗口，Dock入口超时无可控原窗口，未清资料/重建身份或强更。e72设备云读回14:21另一71节点心跳正常/test_completed但loginunknown，70心跳昨日；均不代新采集、重登或连续OTA验收。
- **下一步**：优先合法未访问输入/原预算的新ACK自动处理真实门；Pro DY薄合并同输入/旧功能回归后独审采用并补真实ACK；Owner真实决定后显式release/pin，再接同数据Consumer与云发布；两原节点扩展登记/登录恢复/连续OTA保持未验。真实审核不代本人点；不重放旧ACK/重抓WB终页，不扩预算、arm48h或恢复暂停watchdog。完整U01–U22目标active。

### 计划1.2｜完整产品、资产权威与结果倒排校准（本轮仅文档）

- 交付定义：Owner、参与端、中央、Pro能力包、M0–M7、消费应用、运维与复用七类对象；U01–U22/F0–F7保持。总入口docs/product/DELIVERY-BRIEF.md，唯一范围PRODUCT-PLAN.md 1.2；实际状态仍只在本HANDOFF。
- 实际动作：回读用户v2.2原件文本、当前交接/正式规则、资产/架构/研究/计划；再次联网核Pro、Scrapy、yt-dlp、Prefect、datacontract、Crawl4AI官方资料。未把新版上游声明当本地固定版已接。
- 非作者central_steps初审三问题已修：D1/D2/D3退出范围；F6既有包交付仅依F1，新版重算才依F2；知识审核/release/pin与消费/云指针分开、无旧COMMITTED不能虚构回滚。修旧DY“未通过原SDK”与知识“全部未实现”过期表述，保历史时点。复核见product/PLAN-1.2-REVIEW.md。
- 验证：22需求/8工作包存在，三文档相对链接按正式位置全部可达；这只是文档放行，不是运行/线上/业务通过。本轮无新采集、部署、人工知识决定或看门狗恢复；既有候选/真实状态不由规划自动升级。
- 下一步：沿原T0优先闭合新ACK自动交付、真实知识发布消费、原两设备恢复/连续OTA三条链；Pro与字幕按同输入矩阵补齐。继续非作者独审，不重启规划、不删困难功能、不用更多候选代正式结果。未知项仍是全部平台保真、第二原节点恢复、连续OTA、远端动态消费、全端/双域/48h完整验收。

### E71｜Owner真实知识预览已正式；自动ACK与旧结果保持（14:10）

- **产品代码**：E69六源复用原065 SDK，新增同一工作台“知识更新”、固定Owner权限映射和显式审核意图；原自动ACK、参与者/评分/回执/OTA路径保持。源码55431f5d71bdb09e677ac112dac99344a032a7da；自动ACK前一提交f4885cec5dbd31823ebd0fbb9b339af7fc172d49已push/ls-remote同。
- **发现/修复/组件独审**：HTTP-INITIAL的fixture跳过初始化缺关闭依赖，修测试替身后HTTP1PASS；原code未为造通过而改。六源冻结7b4f65/native a5ae553c核真实Handler/CLI五测、三错误边界、UI14检查、真实SDK clone中唯一grant+decision和unknown不重试；真实原知识无写。不是生产审核证据。
- **采用**：E71 prepare冻7035ea49；非作者68fe0b40核8函数AST与原采用器同、单DB RO backup/三旧指针保持、7独立用例/10次SDK执行（含重复继承，不冒10unique）；原解释器18MB超16MB误限已分64MiB校验，首败保留。批准冻5ee29415。预检五锁/96原source终态/无活动租约；唯一root分开执行adopter与installer。实际旧180停止、新6620；配置706e9077、17新资产、source知识DB不改，0自动决定。
- **现场独审**：7c1324f9879f6ad8b10b3df3f497409a93cce7e0d75f3ccec1dbaf0d2b54942b，实际6+461/fullset4新增、221保护/fresh6+51+33+3、五库actualbackup/schema/raw前后同。原31素材4格式/逐ACK canonical、六店4格式/原报告hash及6pack同；material/domain/auto三指针SHA保持。调度自然claiming、无lease/localrun、pending0/scheduler_alive，不写假idle。
- **真实Owner/页面**：root原CloudClient task_list只读认证通过；独审真实/api/knowledge preview恰1次、root原IAB另一次，原prop034/hashad30e269、address6+current_status6/humanUIDNone/central_owner_service。实际UI显示文件diff和明确采用/退回/不采用，截图/AX存e71-runtime-continuation；未点采用。knowledge单DB与原全部表/rows相同，四写表仍0。私token不进证据/交接。
- **Pro并行结果**：f3-pro-discovery-v2冻af36a324/native8cf81111：原Pro main/handler/SQLite热搜1榜项1关系、正文+3根1reply+JPEG/6导出/9of12、预算8止73、homefeed87/封面/89导出有限同输入均受控通过。仍缺原视频/UID、排行关系消费投影/Owner云能力矩阵，未采用；不能旧候选整文件覆盖当前。其他平台薄适配继续，不新增来源。
- **发布链后补（14:16）**：V1独审实证未知结果被新intent绕过，临时pin history2→3，未采用；V2冻dfd34b7c/root非作者127122bb实际14测与原反例通过，history2→2，重启/换操作均拒。仅后端工程候选；Host/UI接线由central继续，真实旧COMMITTED基线/Consumer联动仍缺。14:16只读核正式四写表仍0，见KNOWLEDGE-FINAL-COUNTS。
- **下一步与边界**：P0-A合法未访问输入/原预算的新ACK→自动结果实际验收；P0-B原SDK显式accepted→release/pin/rollback→Consumer新旧对比/反馈继续（原065四表0，不能伪种旧committed）；P0-C原两节点恢复和连续OTA；随后其余平台/字幕全文质量、动态交付/双域和48h。当前发布链WIP由central接续，native停止编辑该目录；下一平台由knowledge独立候选。看门狗暂停、无新采集/中央变更/真实知识审核。


### E70历史规划校准｜实际状态已由E71更新（13:47）

- **用户结果和计划**：新增[交付总览与主线控制表](product/DELIVERY-BRIEF.md)，作为唯一PRODUCT-PLAN1.1的阅读入口；明确Owner/参与者/消费者、七类产品交付、三资产职责、M0–M7接线、技术栈、双路线研究、P0/P1/P2结果门。原U01–U22/F0–F7保留，不以六店纵切替代全产品。完整研究/架构/资产沿用原三文档。
- **实际材料**：本轮完整读取v2.2并核SHAaee488f21b14637a805f38ba4686b31bc5ce4be459acac950f8b2603863a6c5b、固定交接/正式规则/两技能、计划与资产/研究、实际E68现场独审与E69失败日志、Pro模式探针；重开Pro/Scrapy/yt-dlp官方页。v2.1原件、跨端/生产双消费者等未知不补事实。本次校准不新增平台请求、部署、依赖或真人知识决定。
- **补记实际采用（不能丢）**：13:38 E68 auto-material-adoption非作者实际FINAL47403f70确认PID180、旧87942停止，六源精确/457其他/fullset、五库实际backup/raw、220保护资产/fresh92、原31ACK及六店四格式保持。自动配置600/11keys已安装，旧两指针保持。V3独审d80cb3b2修pending误报、owned进程收尾和离线import多余context；没有采用后新ACK/真实自动发布，仍欠业务链验收。E68为该执行证据目录名，下面同编号团队研究是其他历史记录，不互为证据。
- **Owner知识未完成**：binding/service V3实际SDK隔离测试与组件独审通过；E69 Host候选调用器独审通过，但HTTP-INITIAL.log报fixture缺health_events的收尾ERROR，不能将其中断言推为整体通过。候选未正式采用；真实Owner决定/release/pin/新版消费均未验。
- **Pro融合未完成**：f3-pro-discovery固定候选参数2测通过、whole在0来源请求时报signer入口不可用，NOT_PASS，未采用。热搜模式需同时映射预算、checkpoint/summary、discovery gate/导出；不是改字符串即通。旧DY媒体第13次超12与匿名UID不可比保持阻断。证据PROBE c394404f/FREEZE cacefa73。
- **唯一下一步**：先补P0-A采用后真实新ACK自动处理证据；并行收束P0-B Host实际测试/正式入口及原知识发布回滚、P0-C两原节点恢复/连续OTA。随后原成熟Pro能力矩阵、字幕/同音频质量、远端消费/动态反馈/双域，再组合冻结与48h。原任务身份/预算/评分/ACK/OTA保持，看门狗仍暂停。不得把旧31条重放冒作新采集验收。


### E67｜总计划1.1校准（文档，运行未变）

- 本轮按用户要求先定义完整交付、机制、资产用途、v2.2基础研究、融合步骤与结果倒排。唯一计划仍为[PRODUCT-PLAN](product/PRODUCT-PLAN.md)，版本1.1；第11节规定当前剩余顺序，第12节规定本机/中央/消费拓扑、Owner知识权限设计与能力冻结表。U01–U22/F0–F7保留，不把美食六店纵切当采集整产品。
- 已核用户v2.2原件SHAaee488f2、现主仓HEADbc8227a、E66独审与发布回执；读现CloudWorker/Owner认证边界和本地索引。重新查Pro/Scrapy/yt-dlp/Prefect官方页面，研究与独立推演分别记录。没有新平台/中央查询、采集、运行采用或部署；下方E66运行事实保持，本轮没有fresh探活。
- 非作者初审7问题；修正旧E63/F1未采用表述、ACK自动处理触发/幂等/partial、可信Owner权限路线、旧PWA ID与事实边界、远端认证APP快照路线、连续T0及完整源函数SHA索引。复核见[PLAN-REFRESH-REVIEW](product/PLAN-REFRESH-REVIEW.md)；仅计划放行，产品能力未因此完成。
- **唯一下一执行顺序**：P0-A新ACK→原postprocessing_runs→toolbox Jobs自动处理；P0-B真实Owner项目scope映射/审核；P0-C原参与者/登录恢复与连续OTA。随后按平台矩阵补完整Pro/媒体字幕、同音频质量、动态交付/反馈与双域，再组合验收/云APP发布/48h。首个P0实施动作记绝对T0并沿用，不每轮重置。watchdog仍暂停。
- 自动ACK提取器1588257a为本地离线候选，5组作者测试、未独审/接hook/启用；现31原origin分布29+1+1。Owner preview/0.3.4未正式采用。跨端/第二原节点/全部平台/生产wheel/现PWA与48h仍未全验。新计划不删除原预算、身份、队列、评分、ACK或OTA。


### 历史旁支研究｜外行可用的虚拟产品团队（非采集当前结果）

- 用户澄清希望从想法开始，由协调者调度产品引导、架构、前后端/数据库、测试、安全、发布和迭代角色，最终服务真实用户。分工与调度门见[研究记录](../../outputs/code-agent-tools-research-20261016.md)。
- 当前工具目录已有 Supabase/Postgres、Vercel 前后端/部署/验证、GitHub 与代码审查入口；工具可见不代表账号连接和权限已验证。建议先用 Codex 做单一协调者，按阶段委派，不堆互相聊天的机器人。
- 自动化测试、独立安全审查、真人试用和上线监控各自给不同证据；AI 不能独自证明公众喜欢或产品可商用。PostHog 需要产品埋点后才能分析真实行为，Sentry 用于上线错误跟踪。
- 本轮只更新研究和交接；没有安装、运行候选或触碰代码、数据库、权限、部署和用户数据。下一步收到具体产品想法后先产出简报/MVP范围，再让用户审阅架构和成本。

### 历史E66结果卡｜六店领域消费；当前状态看E70

- **正式版本/入口**：87942/domain-79e4de53-0fad9455；源码f7e475053c4e639ee0f6c4bb1f68993fb12a7d83，外部发布见E66回执。工作台45937→资料库→“查看领域发现/导出领域发现”，固定`/data-product`、`/data-product/report.json`、`/data-product/items.jsonl`、`/data-product/items.csv`。原`/materials`31ACK素材页/导出/config保留。
- **真实用户结果**：六店原64902B bundle/3完整canonical正文/25exact引文，经原05185pin+cuisines0.3.3 clean/score/audit/Consumer，原生候选报告。原iab实际页/三下载精确正式快照；报告hash cec2019d3f3c7724d2ff6712d31cbf44a1a4731ee1b255f94cd4fe4cbfb6b5a8。不是伪造餐厅推荐或新云ACK；raw是canonical bundle bytes，未保原HTTP bytes。
- **审查/采用**：六店27冻件35169c17/非作者e97863fa；原CLI无stdout读取→薄publication_reader复用Consumer.current/render/make_storage，只本机SQLite RO，不新服务/处理框架。四源冻9f3a8a/非作者46584a4d，Manifest重读漂移/pins同bytes/错误project/pack/report均实拒；11实际HTTP/兼容31通过。准备V2 2daf5124/aec4efe0，唯一installer计数18含WALSHM初败→16白名单修复，旧冻件保留。原采用器切87942/旧83631停。
- **现场证据**：非作者919e83e6实际4exact+456其他/fullset1新增，五库实际backup schema/raw两次等、220保护+fresh6/50/33/3同、idle/pending0/原wait同；领域6与原素材31各四GET精确，原31逐ACK canonical/digest/receipt保持。新领域配置600/pin固定，旧素材配置不变。BROWSER-FINAL另核原iab3下载和截图，不借测试当实机。
- **知识增量当前状态**：f1b-cuisines-unknowns新包0.3.4只version/fields两optional unknown和labels，原四配置/rubric/core同；同RAW重算新增12unknown、原7语义字段/25引文/评分同，旧root可读。f7274923/非作者3ca8b74a有限通过，真实gap→model提案prop:f1b-proposal-cuisines-034为private/proposed，reviewgrant/review/release/pin0；未采用正式。非空optional仍不核事实，不能当地址/营业验证器。
- **权限及待审入口缺口**：现Cloud Owner身份不等知识admin/reviewer。f2-owner-knowledge-preview候选0522d29d只读实际prop034/差异/证据，approve/reject在IO前authority_unmapped，已由非作者82f7ed63有限独审通过但未接正式；禁止造AuthContext(admin)或engineering_test冒本人授权。先复用真实登录/项目Owner授权完成映射，之后才开放动作。
- **主线下一结果**：新ACK接现CloudWorker postprocessing_callback/toolbox jobs自动形成处理/发布，不新来源队列、不重发未知；并行知识真实Owner映射/审核及同数据新版切pin/回滚、领域实体事实与现PWA动态分类/地图/体验反馈。当前HTML显示taxonomy内部标签，消费体验仍需复用旧前端补齐，不能把原生报告称完整PWA。
- **保留与未验**：0新来源/0新云ACK，原WB partial74/10of12剩2/任务身份预算保持；F1A正式31链与E65独审继续有效。F2保真/事件/pin工程slice已独审，完整main/CLI/Owner批准/Consumer联动未全验；双无关领域真实消费、七平台完整Pro/原两节点登录与连续OTA/Windows VM手机/48h未全验。主控PM/集成，central作者，knowledge/native非作者交叉；看门狗仍暂停。

### 12:07前规划阶段记录｜整产品基线继续有效

- 用户最新主线：先定义完整交付产品/机制/功能、盘点资产、双路线外部复用研究、明确ponytail+caveman工作法及技术栈、按结果倒推。原E63完整入口保存在[截至E63快照](handoff/archive/HANDOFF-through-E63-20261016.md)。固定执行基线为[统一产品与交付计划](product/PRODUCT-PLAN.md)，并读[架构](product/ARCHITECTURE.md)、[资产](product/ASSETS.md)、[研究](product/RESEARCH.md)和[非作者审查](product/PLAN-REVIEW.md)。当前事实仍看本HANDOFF，不把计划当部署。
- 本轮实际：完整读用户v2.2原件（SHAaee488f2），三个代理分资产/架构/独审；主控完成22能力U01–U22、8融合包F0–F7及工期/验收。两轮规划审查关闭本地游标vs云ACK、051vs065候选混用、四评分域及已有公式、Vox/第三域前置和重复审批等问题。仅文档/研究，没有新增采集、候选采用、云部署或恢复watchdog。
- 资产事实：现toolbox已有M0–M7，不重建框架；版本表标050生产但实际wheel/服务待fresh，051 PG查询候选源码85项一致；另谱系065 M4生命周期NOT_PASS，不能按semver覆盖。美食/软件发布双包存在，历史工程消费摘要不等完整生产双消费者。v2.1原件在已查范围未找到，明确未读。
- 工程收束：Owner无有效工作提示初稿a44ea仅历史；后续45ad候选独审并随本轮采用；DY strict与async受控审已收束982fb，media cap/async/strict与当前共享reader组合已有有限独审通过，但不等于DY真实准入；Owner新run会话caller为未采用候选；不再写成“正在采用”。既有owned fixture已清理，不新增来源填洞。
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
| .crowd-launch/runtime-revisions/wb-progress-45b8e4f7-a1346798/ | 历史E63的65679；13映射/12变更/1新模块，实际独审23750a+idle803731+固定Python9ead；云40/步骤68。原WB31ACK/累计10of12剩2，真实原图云v3/回取/R88三导出独审32a77277，完整回复仍partial74；默认MC/原身份/OTA及其他源码保持，snapshot不等于Git HEAD |
| .crowd-launch/runtime-revisions/owner-knowledge-412a2e2f-3d33539b/ | 当前E71不可变运行源码/PID6620；六源入口，原自动ACK worker仍固定旧immutable路径，不能按Git HEAD替代运行SHA |
| .crowd-launch/unified-workbench/knowledge/、data-products/knowledge-runtime.json | 原提案单库迁移/固定审核配置与私有intent；配置0600、非凭据公开库，原四审核发布表0；不得复制私token |
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
| crowd-kol | f7e475053c4e639ee0f6c4bb1f68993fb12a7d83本轮5源码/测试本机提交；发布看E66回执，原a036e19/6e6d39已发布 | 当前87942/domain-79e4de53-0fad9455/云40；六店领域候选+31素材双入口，原WB partial74/10of12剩2保持 |
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

先读本轮[统一产品计划](product/PRODUCT-PLAN.md)和两份独审，按F0–F7工作包推进；当前F1A/F1B及原E63真实WB证据继续保留。不要重新部署已采用13源，不为填满预算重跑原WB终页/同图，不恢复已暂停任务。

1. F0/F1A已有固定051 source-pin和31已ACK正式发布证据；生产wheel仍未知，不以源码运行补写wheel安装。后续保旧发布与原ACK，禁止整包升级NOT_PASS候选。
2. F1A及六店F1B候选已正式可用，继续领域事实/PWA、自动新ACK处理与F2真实Owner审核/新版同数据重算；F3成熟Pro来源/会话、F4原参与者恢复/连续OTA限槽并行，每项非作者独审。模型分析不作确定性首链前置。
3. 原WB31ACK/累计10of12剩2、partial74保留；DY视频预算/本人会话、Bili原连接、贴吧原URL/主体、ZH stopped12、参与端两原设备/OTA/跨端/48h分别保未验。原两设备各两条，不重建身份制造通过。
4. 主计划的阶段与指标是目标，不是当前完成。每轮更新日期/结论/下一步，主要变更记录精确版本/验证/采用/真实结果/独审，不靠测试数宣布业务完成。

看门狗仍暂停，未自行arm实验。D1/D2门禁通过后的48h另从真实开始计算。

## 9. 维护与共享

唯一当前入口为本文件；WORKSPACE/HANDOFF.md和爬虫/HANDOFF.md只作指针。[证据](handoff/EVIDENCE.md)、[日志](handoff/CHANGELOG.md)、[接力模板](handoff/ENTRY_TEMPLATE.md)及仓库AGENTS.md共同维护。

[在线固定入口](https://github.com/huming0018-dot/crowd-kol/blob/codex/v4.0.6-handoff/docs/HANDOFF.md)随已授权分支更新。E63当前状态及本轮产品规划文档发布以爬虫/outputs/product-integration-plan-2026-10-16/PUBLISH-RECEIPT.json的commit/push/remote为准；无此回执不认发布。原计划中的HANDOFF-E63-PUBLISH-RECEIPT未生成，不补造旧回执；E62更正发布见HANDOFF-E62-CORRECTION-PUBLISH-RECEIPT.json，旧回执保留，源码提交与文档提交分开；缺回执不认定已发布。[截至E60完整历史](handoff/archive/HANDOFF-through-E60-20261016.md)保留旧入口全文和原SHA，重要决定及发布记录继续在CHANGELOG/EVIDENCE中。

接力者先读本入口、证据、日志并核日期/所涉源码与原件，再按第8节推进；主要改动按模板回写，每轮结束更新日期、结论、下一步。读不到原件时明确标未知/未核验，不把Markdown中的记录当自己查询线上所得。

JSON、PRIVATE、运行数据和原始日志默认仅本地，不随交接文档外发。按最小范围提供脱敏证据；不添加.env、Cookie、密码、令牌、私钥、邀请或登录资料，不打包全部outputs/私仓源码。旧4.2.0/4.2.5等只作历史，旧入口Git81ab4ae/blobcc09e64b保留。
