> 历史盘点基线：下文E63/12:07时点事实。2026-10-16 13:00增量见末节；最新运行事实看固定HANDOFF，不将旧“未接入”当当前状态。

> 当前状态入口：本文能力状态是盘点时点快照；自动ACK接线/运行采用的后续变化见[HANDOFF E70](../HANDOFF.md)，不要由旧表“未接”推定当前代码仍缺失。资产用途及历史证据仍保留。

# 现有资产实证盘点（规划输入，不是产品验收）

2026-10-16，Asia/Shanghai；盘点者 `/root/central_steps`。只读源码、版本与既有验收报告；未运行产品/测试、未查询平台或云、未读取凭据、未改正式项目或业务数据。

**结论：已有两组应融合的成熟资产。**采集工作台已有来源引擎、身份、预算、原始保存、中央回执、步骤、媒体、导出与参与者横切；CTFS toolbox 已有 M0–M7 最小确定性链。应连接两者，而非再建采集器、任务系统、评分器和发布后台。已购 Pro 三个 Agent 可作为后续分析/创作适配器，不能充当确定性评分或事实审计。

## 证据口径及根路径

- **源码已读**：本轮实际读取入口/有关核心源码；不等于执行通过。
- **报告实读**：读取既有独立实际报告并核文件摘要；本轮不冒称亲跑该业务。
- **存在**：仅确认文件/目录存在；不作功能承诺。
- **未知**：未取得实际部署/运行/完整数据证据，不根据聊天补齐。

| 简称 | 准确根路径与本轮核验 |
|---|---|
| WORK | `/Users/hubowen/Desktop/桌面 - 胡博文的MacBook Pro/pushpull`；已读根 AGENTS、crowd-kol/AGENTS、固定 HANDOFF |
| KOL | WORK 下 `crowd-kol`；实际 HEAD `18d14b35a7354d945beb01fd5bb7ab7e03b50863` |
| MULTI | KOL 下 `server/crowd/v4/multiplatform`；当前来源/身份/媒体/结果工作台源码 |
| EXT | WORK 下 `crawler-extension`；HEAD `d7707cb82d26e0594ef8220299a5e8c3a37cf8cd`；`v4/manifest.json` 是4.2.71，根manifest仍1.0.0，不能混称 |
| PAGES | WORK 下 `crowd-pages`；HEAD `0a3bc4f04d0b2ffafd4c8619096ba6f3e28ea900`，签名分发面，与源码仓分开 |
| CTFS | `/Users/hubowen/Desktop/桌面 - 胡博文的MacBook Pro/china-travel-food`；HEAD `cec5c45ba5c03660bd253fe3da4d9e26cc3acddb`；根/toolbox未找到AGENTS，本轮读其HANDOFF和模块/版本入口 |
| TOOL | CTFS 下 `ctfs-toolbox`；源码`pyproject.toml`=0.5.1，版本表明确0.5.1为候选、0.5.0保持原生产；本轮85个0.5.1 source_files逐SHA全部一致；对0.5.0表84项中80同、4变，故不能称当前源码就是0.5.0运行包 |
| MC | `/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler`；HEAD `098cae5a00023ad55f00ca9665d22d0f260e2ab2`；旧基线报告记有本地修改，HEAD不等于实际文件版本 |
| PRO | `/Users/hubowen/Desktop/爬虫/references/mediacrawler-pro-2026-10-14`；8仓本轮HEAD逐项等SOURCE-MANIFEST；私有许可参考，仅本地使用/薄适配，不复制私码发布 |
| RUN16 | `/Users/hubowen/Desktop/爬虫/outputs/runtime-2026-10-16`；本轮实际来源及独审证据 |
| PRD | 本目录`REFERENCE-v2.2-TEXT.txt`：311行全文已读；是2026-10-11评审稿，不把选型/开源热度当已实现或当前外部事实 |

## 12:07前历史可验证运行锚点

- 原子采用回执：RUN16/`e63-progress-runtime-adoption/runtime-adoption/ADOPTED.json`，revision `wb-progress-45b8e4f7-a1346798`，newPID **65679**。本轮实际只读监听核到唯一`127.0.0.1:45937` PID65679；未重新重启或核全库。中央 **Edge40** 依已读固定handoff/已有部署证据，**本轮没有fresh云查询**。
- 最新真实WB报告：RUN16/`actual-wb-progress/independent/FINAL.json`，SHA **32a772772d47b1a9f9609d6e5d3cd2f64fce865b545dcf13f1a7b7e93a87f6e3**，有限实证PASS；累计31条云回执（旧30+新评论1），本段3次/总10of12剩2，finished failed74/`wb_reply_terminal_incomplete`。4,284,573B JPEG原字节/像素→Owner attachment→私有云v3保存/回取已核；R88三导出各33行。**不代表全部回复/平台全量完整。**
- 时序复核：首次读取固定HANDOFF为E62/10:38、正文写53987；随后root已更新本机正式`docs/HANDOFF.md`为**未发布E63/11:09、65679/31ACK**，本轮已重读确认。`git show 5a6b4aa:docs/HANDOFF.md`核到最后发布版本的E62/10:38；本轮未重新联网查询远端。应区分本机已修改与已发布，不能把旧“剩5/未采用”作为现状。本报告不另立运行控制入口。

## M0–M7：资产、复用与真实缺口

拥有者列指维护边界/权威源，不假定某个历史bot当前在线。CTFS历史角色dev/collector/QA/PM见PM_START_HERE，但其中2026-10-01账号/配额/数量已经旧，不能作现场状态。

| 模块 | 可用资产（相对上表根）/拥有者 | 已读/实际证据边界 | 取舍与最小融合点 | 重复和缺口 |
|---|---|---|---|---|
| **M0 存储** | TOOL `toolbox/storage.py`,`postgres.py`,`schema.py`,`storage_factory.py`,`schemas/`；KOL `results_store.py`,`cloud_sync.py`及v4迁移/私有媒体bucket。维护：toolbox数据内核、中央服务端分别保持权威 | TOOL RAW原字节hash、版本化ODS/DW/APP parent_ref源码已读；版本表/051说明记录6食物候选+2软件项目、工程PG回读，未独立取得本轮现场PG。WB逐ACK/真实图云/R88报告实读 | **直接用**toolbox分层存储/契约；**薄适配**中央capture/本地observation→toolbox RAW（保真bytes/来源ID/缺口/engine/原receipt）；中央Outbox仍是交付权威，不能移成第二奖励库 | 现机器实体版本不是完整CTFS RAW/ODS/DW分层；toolbox工程PG≠生产Supabase/RLS。多origin/public source progress已存在，不重做另一套血缘/续采账本 |
| **M1 采集** | PRO Python/Golang/SignSrv/CookieBridge/Downloader；MC原七平台；MULTI `pro_executor.py`,`mc_runner.py`,`pro_*adapter.py`,`shared_request_budget.py`,`account_sessions.py`,`pro_source_steps.py`；EXT DOM参与端 | Python平台/保存/检查点与本地适配源码已读；XHS有限真实与WB31/图字节链证据存在，WB本轮报告实读。Tieba/DY受控验证≠真实主体/完整新源，Bili登录/部分模式仍有限。TOOL本身只`snapshot-file`与`http-public`连接器 | **直接用**Pro成熟平台HTTP/提取/保存流程和原MC成熟媒体；现工作台仅做任务/身份/预算/归一/中央协议薄适配；给TOOL加“已交付capture快照输入”连接器，先避免二次采集 | PRD要多源权威召回/抽样F1–F6并非社交七平台同义；CTFS旧`cloud/vendor/pipeline`有michelin/map等但本轮只定位。不要同时维护Pro/MC/自写三套同平台parser；例外需同输入证据 |
| **M2 清洗** | TOOL `cleaner.py`,`validators.py`,`stages.py`,`pack_schema.py`；CTFS `cloud/vendor/pipeline/stage1_validate.py`,`entity_align.py`,`raw_place.schema.json`；MULTI normalization/results_store | TOOL严格JSON/原byteshash、配置指针、引文/身份版本源码已读。旧entity_align源码已读：品牌/行政区及人工歧义桶，仍有绝对路径/美食硬编码。旧删除器封锁说明已读，非事务merge不能恢复使用 | **直接用**TOOL清洗内核；**薄适配**社交帖子/评论/媒体标准实体schema及来源指针。实体对齐作为领域插件人工裁决入口；原normalized留原样作RAW，不倒写历史 | 当前采集typed归一不等于现实店铺实体清洗/事实核验；PRD地理编码/字段保鲜/事实轴完整程度未验。旧`merge_duplicates`是**淘汰写入路径候选/只读审查参考**，不能用它自动合库 |
| **M3 评分** | TOOL `scorer.py`+`packs/*/rubric.yaml`；CTFS `cloud/vendor/pipeline/scoring_engine.py`,DB005/012/016及softad006/007；MULTI `results_store.py`人工evaluation；v4 ratings/reward分别另列 | TOOL仅确定性sources/refs/coverage/recency与准入；cuisines0.3.3明确“发现线索/private_lead”，不是吃过/口味。旧评分源码明确真实diner/非广告可信UGC、180日衰减/先验8/证据不足NULL，未执行或核线上分数。本地Owner evaluation标quality/reward_eligible=false | **直接用**toolbox配置评分与原美食rubric/公式作为可审核领域组件；先新鲜证据→实体，再评分。人工质量评价作为输入而非事实或自动奖励。**不再造泛评分服务** | 通用证据分、餐厅口味分、人工采集质量分、参与者奖励是4个域。软广模型训练/校准、两独立食客声音、跨域一致性未完成证明；Pro Vox标签不能直接替代经验证评分 |
| **M4 本体** | TOOL `ontology.py`,`pack_schema.py`,`packs/cuisines/0.3.2,0.3.3`,`packs/software-releases/0.3.2,0.3.3`六文件包；CTFS `research/category/`,`research/_taxonomy/`、旧pipeline业务词根 | 已读纯YAML/JSON包校验、install/verify/rollback及rubric/expectations；两个领域包实际存在，版本映射报告两项目消费；不据此声称房源/livehouse已验证 | **直接用**现OntologyManager/版本包，不重建包注册器；把既有美食分类/源计划/回归集映射入包。升级知识需版本/人工审后采用，保留证据引用 | PRD外“知识摄入→待审区→改包→影响回归→发布”的完整闭环未在现六文件包证明；自动吸收研究/用户反馈不是已实现能力。现项目业务词仍散在legacy代码，不能先宣称零领域内核 |
| **M5 编排** | TOOL `jobs.py`,`cli.py`,`stages.py`串行DAG/锁/pause-resume；KOL `owner_tasks.py`,`cloud_sync.py`CloudWorker/中央lease；CTFS `cloud_router/watchdog`历史脚本。维护：工具箱阶段编排vs中央终端分配 | TOOL STAGES=crawl/clean/score/audit/deliver与版本绑定已读；中央任务ACK/总预算10of12/已知partial真实报告已读。历史cron/线上容器是否运行本轮未知，看门狗按当前handoff暂停 | **直接用**中央负责设备/任务/来源预算；toolbox负责已获数据的阶段DAG。以一个job/task引用关联两者，不再上第二个来源队列。先串行CLI，**仅有实际并行运维需求再评估**PRD的Prefect | 别把暂停源任务的恢复当工具箱DAG重算；未知外部调用不能自动重发。cron/Prefect/现watchdog三套并行会重复工作；48h未arm/未验，不能预宣长期自愈 |
| **M6 审计** | TOOL `auditor.py`独立从RAW重算、schemas；KOL v4隔离PGlite/NativeSteps/步骤回执；RUN16独立报告；CTFS `release_audit.py`等历史门 | 已读RAW→ODS/DW精确重算及tool/pack/time绑定。WB业务独审不是bot进度口述。本轮没有重新跑这些测试；规则版本/生产权限与实际数据质量分开 | **直接用**现审计内核+各域gate；采集验收补完整parent、coverage、bytes、receipt，CTFS发布再补事实/实体/评分gate。**不另建一套“通过即上线”的泛审计系统** | PRD A–H/覆盖全格与软广可靠性未因工程测试多自动实现。固定handoff漂移要修；历史缺失索引不能重造。离线绿、部署、真实业务三层报告必须分开 |
| **M7 交付** | TOOL `consumer.py`不可变JSON/HTML+loopbackserve；CTFS `app/pages/`Next.js，crowd/admin/API与店铺/chef界面；MULTI dashboard/results/Owner/Fleet/account/media；PAGES安装分发 | TOOL 0.5.0消费只SQLite；051候选PG只读工程说明/85sourceSHA一致。CTFS app页面/package源码定位，但本轮未HTTP验活；工作台45937实际监听。WB R88三格式33行/真图回取报告实读 | **直接用**Results/三导出/附件页；**薄适配**toolbox审计通过DW→同业务PWA/API。采集Owner与消费者美食页面不同角色，不让用户维护三个后台。报告和分析从现有capture选择，不重新抓 | 本地工作台≠远程多端产品；M7消费者同域发布版本/可追溯事实/筛选体验仍需验。CTFS旧PWA不能直接读取未清洗机器raw替代DW；飞书三表/多主题复用仅定位/计划，未本轮验收 |

## 参与者横切：保留，而不是让Pro替代

| 资产/入口 | 实际来源及状态 | 复用方式/不混淆 |
|---|---|---|
| 报名、同意、邀请、原身份 | EXT `v4/src/join.js`,`identity.js`,`participant-session.js`,`participant-background.js`；CTFS app/crowd及v4 access；源码/目录已核，当前全部参与者真实链未本轮验 | **直接用**既有参与身份/人工同意。平台登录身份与参与者Auth不同；不能拿Pro Cookie替代报名 |
| DOM采集与安全暂停 | EXT `agent/pool/work-tabs/session-health/node-monitor`；v4README已读，原公开DOM和人工设备证据路径保留 | **保留**仅需人类设备/DOM来源场景；机器API结果明确不同engine/evidence，不能伪DOM/领取真人奖励 |
| 回执/奖励账本 | KOL v4 source受理、receipts/rewards协议；机器source受理reward_eligible=false。具体每个参与者奖励当前余额未查 | **直接用**服务端奖励/幂等UUID，不重算或迁移成M3实体分；机器结果不会凭点赞数发真人奖励 |
| 参与者主观评分 | `supabase/migrations/20261008170819_crowd_v4_ratings.sql`已读：optional human rating锚received proof，与note rewards分离；CTFS旧数据还有UGC口味评分 | **薄适配**作为独立evidence类型，须保作者/任务/来源/是否真实体验。单次任务评分不自动当独立食客证据 |
| 机器Owner人工质量评价 | MULTI `results_store.py`versions/observations/evaluations；源码写明quality/reward_eligible=false | **直接用**批次/内容version评价，服务采集反馈与改进；不能混入商家口味或支付奖励 |
| 安装/签名OTA/回滚 | EXT `v4/build.py`,`updater/`；PAGES `v4/releases/`、已签名71渠道；当前源码71；固定handoff有远端71历史登记/本机未全验限制 | **直接用**现签名渠道/原ID/回滚；不再造新的安装器。源码71/服务器登记71≠本机完整连续OTA通过。保留stop/outbox/storage |

## 已购8仓：只保留一份平台能力与一个用户入口

以下本轮HEAD均与PRO/SOURCE-MANIFEST一致；README入口已读；三Agent旧源码审查见WORK/outputs/collector-adversarial-audit-2026-10-14/pro-bonus-capability-review.md（报告实读，不冒称本轮整仓审完）。

| 仓库（PRO下同名目录） | HEAD | 用途与取舍 | 实测边界/拥有者 |
|---|---|---|---|
| MediaCrawlerPro-Python | d32dd565277116ba4880c28ccd417a7c376cb62d | **直接用**平台client/processor/extractor/store/checkpoint；工作台薄适配central/cap/identity | 已有有限XHS/WB真实；每平台/模式/媒体完整性分别验。私仓上游维护原平台能力 |
| MediaCrawlerPro-Golang | d87b06de07c6b1ffd1b2bb2ee2ce9b54e80e5446 | **仅参考/备选**Python-compatible CLI/存储；不平行接两套引擎 | 本轮仅README/HEAD，没有新真实运行证明 |
| MediaCrawlerPro-SignSrv | 26c53d8f3221d95e0d4961b0593debd179d3cf10 | **直接用原签名、薄安全wrapper**，owned lifecycle/无隐式重复请求；不重写签名 | 已有XHS自动签名真实；某平台标支持≠都登记/真实通过 |
| MediaCrawlerPro-CookieBridge | fcddd00887014a1a57acdd847d337f655f31e46c | **直接用**固定原client与正常浏览器，现桥采集/状态边界薄适配 | 连接/缓存/官方self三件事不同；不能把XHS在线映成Bili登录 |
| MediaCrawlerPro-Downloader | 35d3ef517b21f797bc8e0fcc5eda624b74323a28 | **成熟下载协议参考/评估直接用**；当前已验媒体复用原MC downloader，不再新写第三套 | 该独立UI/后台未整体验收。接入前比较现音轨/图片实际链，避免重复下载 |
| MediaCrawlerPro-VoxAgent | eb794d173c3d69eb94d140c0e419154b7b0fce4f | **薄适配**“已保存评论→固定样本→增量标签→确定性统计→可溯报告”，补研究消费层 | 本轮没模型调用/没有证明研究质量；不是M3已校准评分或M6确定性事实门 |
| MediaCrawlerPro-ContentRemixAgent | a73bb0edcaba8cb97b5337cba855555c551913e9 | **薄适配可选分析**提炼/拆解/模板/风格与分段；消费已获内容/字幕，不重建账号与采集 | 四平台文档/源码能力，非七平台全模式保证；生成事实/提示词仍需审核 |
| PicTacticAgent | 89a8120765477839fa25d55dbde17fcf3d93a222 | **仅可选创作工具**封面/参考图/编辑，放M7产物工具而非采集主路径 | 未做本轮生成/安装/质量实测；生成图不能伪原始媒体/事实证据 |

## Kimi原版、54、当前扩展：防错误参照

- **原MC**：MC根HEAD已核；WORK/outputs/mediacrawler-execution/reviews/10-mc-original-baseline.json实读，2026-10-09原config/BiliClient/XHSCore/extractor/crawler_util已有本地修改。不能以干净HEAD替代原运行基线。
- **“Kimi原版”扩展对照**：WORK/outputs/mediacrawler-execution/kimi-navigation-comparison/README.md实读，Kimi可读源码3.4.14、原设备4.2.6、修复树4.2.7/旧权限4.2.8分别列。直接tabs.create隔离对照并非安装整套Kimi扩展端到端采集；只能作为历史回归样本，不能当能力上限或正式替换。
- **54至少有多个工件**：WORK/outputs/mediacrawler-execution/local-ota-4254/`crowd-v4.2.54-capability-only.zip`、`local-ota-4254-sdk-integration/crowd-v4.2.54-sdk-local-test.zip`本轮只读ZIPmanifest都4.2.54、本机测试。`reviews/249-crowd54-batch-independent-review.md`实读说明批量草案隔离PASS但生产新API/SDK整链另门。版本号相同不是同包/相同实际能力，不重新发布54覆盖71。
- **旧CTFS3.5.2**：CTFS/crowd_extension/manifest.json真实3.5.2，和EXT/v4的4.2.71是两条源码/安装链，不能根据同公钥/名称/更新URL猜当前Chrome加载哪份。仅兼容历史保留，迁移必须核安装身份/queue而非删除旧storage。

## 各角色已有入口与能跑通的路径

| 角色 | 既有入口 | 已有可用路径 / 未验的最后一段 |
|---|---|---|
| 项目Owner/运营 | 本机`http://127.0.0.1:45937/`，MULTI `dashboard.py`+owner/accounts/fleet/results/media各JS；EXT控制台的工作台链接 | 有新WB源→保存→云ACK→Owner图云→回取→R88三导出有限实证；不是全自动实体清洗/食物评分/面向消费者推荐，亦非任意设备远程访问 |
| 参与者 | EXT/v4 `src/participant-controller.html`、controller/onboarding、安装邀请页；PAGES签名安装渠道 | 原人工身份、知情同意、页面采集/暂停、奖励保留；当前节点连续OTA/跨第二正式重启/全跨端/48h不能以本轮WB代验 |
| 数据开发/QA/PM | CTFS `PM_START_HERE.md`,`ROLE_WORK_SPEC.md`,`cloud/task_helper.py`；TOOL CLI/SDK `Stages` | 角色文档存在但旧账号/配额数据失效；TOOL两个项目固定版本工程证据在版本说明，不是本轮fresh运行。不要运行旧sync/cron/apply说明 |
| 数据研究者 | 已保存Results导出、TOOL clean/score/audit/run/job；Pro Vox待消费适配 | 原素材/语义/版本已可取；“已保存评论一键研究并回写证据”整条未验，不应再抓同评论启动新的独立数据库 |
| 消费者 | CTFS `app/pages/index.tsx`,`chefs/`及地图/详情；TOOL serve的JSON/HTML | Next.js/PWA源码存在，TOOL受审数据消费接口存在；本轮未打开正式PWA、不核当前线上DW/评分，不能声称整产品可用 |
| 发布维护者 | EXT构建/签名OTA，KOL迁移/独审/采用器，PAGES分发；TOOL pack/wheel/version-map | 现发布链复用即可；不同时建立toolbox云server、Vox后台、采集后台3个用户需手工切换的主控制台 |

## 避免重复开发的明确取舍

1. **平台原生流程保Pro优先**。薄适配只补现有中央身份/耐久/预算/回执/规范化边界；解析/分页异常必须先对比Pro成熟行为，不默认自写更强。
2. **现capture/Results到TOOL的单向公开RAW适配先于新M0–M7框架**。保留上游原bytes、已知缺口、回执和多origin；不把归一后的JSON谎称原HTTP原文。
3. **M3/M4/M6直接消费已存在toolbox**。先为社交内容和目标领域补纯数据包/映射；不再写第二个rubric、pack manager或audit runner。原美食特定实体匹配/口味公式经小fixture保真再插件化，不整包搬旧cloud目录。
4. **编排分工而非合并所有任务状态机**。中央负责采集租约与确认；TOOL负责确定性阶段。只连接job/task/record引用，不让DAG自动重发未知平台调用。
5. **旧数据/评价/参与奖励/OTA是保留资产**。机器结果质量评价与真人口味、参与奖励分别存储和展示，不为统一模型而混算。
6. **淘汰候选仅指重复实现/危险写路径**，不是现在删除：旧非事务实体删除器、重复评论分页/下载器、同版本多54实验包、重复cron/新平台抽象框架。先确认当前调用/迁移/回归，再移除；本轮没有删除任何东西。

## 此盘点尚缺什么证据

- TOOL 051工程PG候选的原云运行日志、独审完整报告未在本机浅层目录找到；本轮只有源码逐SHA一致+版本说明/记录，不将文档摘要当fresh现场验收。
- CTFS线上生产DW/APP/评分/当前PWA、历史cron/容器真实版本没有fresh查。旧规模/账号/配额不引用为当前事实。
- 已购Agent真实模型输出质量、softad模型标注/泛化、完整跨域消费、全部平台/媒体同输入及手机端未证明。
- Owner无效续采UX已另有隔离3文件快照`owner-continuation-work-preview/SNAPSHOT-FREEZE.json a44ea020…`，4Python+15VM作者验证，没有独审/采用。本轮不把该修复写成正式能力；后续应避免已访问完还反复请求终页/重复媒体。
- 登录当前Bili不能根据Bridge离线/旧缓存断言一定登出；参与者71恢复、48h、看门狗仍分别待验。此盘点不触发登录、自检、源任务或OTA。

## 配套主PRD与第二消费者：补充核证

- **v2.1未找到可读取原件**：本轮在CTFS、本cwd以及Desktop、Documents六层内按CTFS/PRD/v2.1命名只读查找，仅定位到既有v2.2文本；不证明整台机器不存在v2.1。v2.2明确自称配套v2.1主PRD，其完整架构边界与Phase0–3主定义仍是材料缺口，不能从模块详设倒推成已核主PRD。
- **第二消费者分级**：源码级确有`packs/cuisines`与`packs/software-releases`两域纯包，051版本表85项source逐SHA一致。版本表validation及`M7-PG-READONLY-0.5.1.md`记载6食物候选+2官方软件发布、同SDK/CLI、工程PG3RAW/32versions/4HTTP以及独立SCOPED_PASS；这是“已读历史工程运行与独审摘要记录”，不是本轮亲跑或已核原始运行回执。未找到对应原日志/完整独审原件，也未核当前活跃第二项目服务。因此可确认双域实现存在，第二消费者工程验证有文档证据，独立可复核运行原件及生产双消费者验收尚缺。不能用两个包或测试fixture宣称PRD复用门已完全通过。


## 2026-10-16 13:00资产增量与接线用途

- **F1A已正式**：`MULTI/material_bridge.py`及`material-packs/social-observations/0.1.0/`、`workbench_material_call.py`，原31 ACK派生资料与三导出已接工作台；只新增ACK自动触发仍缺。保capture/receipt为权威，不再造另一份解析或奖励。
- **F1B已正式**：`MULTI/publication_reader.py`、固定`domain-runtime.json`配置、隔离publication，六店Consumer只读页面/导出已实核。复用051 pin而非整装065。现六店没有核实坐标/当期事实，仍是发现候选。
- **前端可复用边界**：`CTFS/app`的Next/React筛选/卡片/Leaflet可借布局，但旧数值restaurant ID不兼容Consumer字符串ID；非高德来源即食客的旧逻辑必须淘汰；无核实坐标不造地图点。依据RUN16/e66-domain-consumer/FRONTEND-REUSE-PROBE.md。
- **自动ACK候选**：`RUN16/auto-material-processing/ack_snapshot.py`和冻结16项。真实字段是record.origin.run_id，不能假设provenance；仅离线5组测试，未独审/启用。复用现postprocessing_runs与toolbox snapshot-file Jobs，别另建任务队列。
- **M4候选**：`RUN16/f1b-cuisines-unknowns`同输入0.3.4、`f2-owner-knowledge-preview`真实提案预览有限独审；未审核/发布/pin，需已有中央Owner身份到项目审核权限的真实映射。测试工程角色不是本人批准。
- **保护边界保持**：E66独审原件核五库schema/行、原31 ACK和220保护资产保持。Pro私码、本机资料配置、原媒体/语料/运行数据库不进入公开文档提交；仅发布自有文档和代码白名单。

正式证据、commit、原件路径以HANDOFF E65/E66为索引；本轮读原独审和发布回执，没有新中央/来源调用，不能称fresh云验收。
