# 可执行实现索引｜保留现成内核与真实权限边界

日期：2026-10-16。只读核本地API/源码/采用与审查原件，未修改正式文件，未运行代码/平台/云/模型。完整SHA与绝对路径原件位于`/Users/hubowen/Desktop/爬虫/outputs/product-plan-refresh-20261016/`下的LOCAL-IMPLEMENTATION-PINS.json、PRO-PYTHON-REFERENCE-PINS.json、CANDIDATE-REVIEW-PINS.json。JSON原件仅本地；近期源文件完整SHA附在本文第6节，可供外部接力核同版本。短号只用于阅读，执行前用完整值。

## 0. 当前基线与状态词

正式repo：/Users/hubowen/Desktop/桌面 - 胡博文的MacBook Pro/pushpull/crowd-kol（简称 REPO）。本次只读HEAD=bc8227aee6a695553dfa274f82e5df2df778251d；是仓库当前提交，不等运行版。

正式实现 F=REPO/server/crowd/v4/multiplatform。固定HANDOFF本机12:52记当前87942/domain-79e4de53-0fad9455；实际采用原件 RUN/e66-domain-consumer/formal-adoption/runtime-adoption/ADOPTED.json，源发布回执指source_commit=f7e475053c4e639ee0f6c4bb1f68993fb12a7d83/push0。该PID本轮未fresh探活；中央Edge40沿本地既有证据，未调用云重核。

RUN=/Users/hubowen/Desktop/爬虫/outputs/runtime-2026-10-16。以下“正式”指已有采用原件；“候选/设计”不能作为当前已启用功能。不将051/065按版本号整体升级。

## 1. 近期可复用实现与同输入验收

| 功能/状态 | 固定源码或冻结 | 具体文件/函数 | 输入 → 输出 | 必须保留 | 最小同输入验收 |
|---|---|---|---|---|---|
| Pro成熟原链，正式本机保留 | F/pro_executor.py SHA45b8e4f759ab3f1436828b614198f66c17b12ce7c39db0dee30bfb9ae9f30f12 | execute、install_transport_limits、checkpoint、observations/import_records；原SDK入口见§2 | 原manifest/request/同主体绑定+原SDK → acquisition SQLite/checkpoint/规范化/步骤/媒体 | 默认MC、显式Pro不静默fallback；共享预算/73/取消；parent/softcap/partial；不拷私码 | 原WB同请求/同公开断点离线原SDK重放，旧ACK行origin不变，新fresh逐receipt；真实WB现31/10of12剩2不得再抓 |
| API预算与末端账本，正式 | shared_request_budget.py SHA879131bb38f173ed93d758ce6dda8fe4a9603fd4ee82dfe49c352101b00743c7；Pro45b8 | RunRequestBudget.debit/snapshot；Pro sync_request_budget/finally | 同run/request绑定账本 → 全Pro+media实际used或明确unverified | predebit、不reset/refund；媒体后末计数；缺失/坏账不伪0、不finish未知 | 原SDK→MC媒体→worker/finish数字同ledger；初始化后缺账本→None/unverified；原73/cancel对象保持 |
| 已ACK31素材，正式F1A保留 | F/material_bridge.py SHA452f19cf087f21b4884421c464fe587229ab4a0bc88817f3725db129d26b9b79；helper b127ed65… | snapshot_bundle、run/read_publication；workbench_material_call.command；dashboard.material_delivery | 固定capture snapshot+原canonical receipt+05185pins/六包 → 原Consumer HTML/JSON/JSONL/CSV | 原capture UUID/hash/receipt/parent/origin/partial，四评分域分开；read不build/重抓 | /materials四格式同31typed，坏snapshot/packpin/FIFO拒；原WB31逐回执保持，不当餐厅推荐 |
| 真实六店领域消费，正式F1B0.3.3 | dashboard79e4de53d9dd664c6e6ef1bdf592bab036e65f65d6a03cd618df24d07c088030；publication_reader0fad9455d1b9b4803de29bfa72db57955511ff9cc8797363f188e0beb14c0d5b | Application.material_delivery(domain=True)；publication_reader现read；Consumer.current/render | 原64,902B bundle/3canonical/25quote + cuisines0.3.3 →6发现候选 | 原/materials继续；固定as_of/原RAW；editorial≠食客；未知保留；读取SQLite RO | /data-product及report.json/items.jsonl/items.csv同6；原raw6f3af…，report cec2019d…；原iab三下载原字节/现采用独审919e83e6 |
| 6店明确地址/营业unknown，独审候选 | RUN/f1b-cuisines-unknowns/FREEZE f72749236a013f2cfcee651d40c622e6686182f6be4ea87eacbfe835ebcf067f；非作者3ca8b74a… | cuisines0.3.4 pack.yaml/fields.yaml，仅version+两optional/labels；其余4文件同 | same RAW →6店新增12unknown；原分/源/引文不变 | 不把非空optional当验证器、不改权重、不自动本人批准 | compare_readonly：旧0.3.3独立root原样、新0.3.4新root；原7语义字段同/12unknown可见；无生产指针切换 |
| F2原记录保真，独审工程候选 | fidelity freeze ea96f1cad7e3623debca04386641382243d5ac78022032f847e57a5c7d4c752b；runner e689a6e2… | extract_dialogue_records/seed/software、chunk_coverage、build_candidate | 原文本 → 精确UTF8 span/完整记录、派生分离/真实覆盖 | 不截4000/不删user_idea；空白缺口pending；不全量跑原main | 脱敏UTF8/重复段/长段；原214跨度exact/18,239字符保；仅计数hash，不外发原corpus |
| F2事件与首pin，独审工程候选 | events freeze60e704714fdfa9a061fe7432641cd1170303d6a2bdefc5a2dc7a3875d4692d4c；runner831faf71… | read_event_records/build_event_candidate/sdk_loop；原KnowledgeStore getters/pin | 实际feedback/gap持久化+close/reopen →真实event ID/hash绑定cand1；首COMMITTED→pin→默认查询 | 不预制ID/零hash；scope/rejected/hash拒；工程role不冒本人 | 3脱敏域首pin1；2域新包/回滚pin3；4真实事件回读；旧4保真回归；未证完整main/CLI/真实Consumer切pin |
| Owner知识待审preview，独审候选未接正式 | preview freeze0522d29dbae7efc2ca1cee521c8774d21392c828727894b2a40908312b8d3fdb；非作者82f7ed63… | knowledge_review.preview/act；原SDK get_proposal/get_payload/get_receipt/get_evidence | 原prop034/固定hash/六pack → 差异、12unknown、证据/权限前置 | private/proposed、0review/grant/release/pin；原DB0写；CSRF≠admin | preview真实6diff与DB前后hash同；approve/reject IO前authority_unmapped；wrongscope/hash/FIFO拒；详见§4 |
| 新ACK自动材料，离线提取器/设计，未启用 | auto freeze1588257a0724564c137c68a83fd06b02aeee45d21bf47f09687a8a3374f16db2 | ack_snapshot.extract_rows/read_scope_rows；CloudWorker finish/callback+Jobs见§3 | 单scope已ACK原envelope/receipt →通用材料snapshot；非ACK计排除/partial | 无新来源队列、未知账/finish不明不调度、旧转写不变、历史origin不换latest | 5离线组+实际31投影：29+1+1、provenance0；下一需真实Worker受控finish→callback→Jobs/Consumer/重启幂等整链，当前尚无 |

四评分域：材料/来源准入；餐厅领域品质/口味；Owner采集质量评价；参与者贡献奖励。上述素材/六店准入通过均不转换成后3域分数。

## 2. Pro原Python调用链：优先原成熟模块，薄适配补证据

本地已购参考 SDK=/Users/hubowen/Desktop/爬虫/references/mediacrawler-pro-2026-10-14/MediaCrawlerPro-Python。仅记录路径、函数与SHA元数据，不复制/发布源码。7原文件完整hash见 PRO-PYTHON-REFERENCE-PINS.json。

1. F/pro_executor.execute先核selected root/probe，设置同run VOX_ACQUISITION_ID/SQLite路径、base_config与aggregate config同评论阈值、共享预算/NativeSteps/账号hook。然后导入原main模块，argv_for原CLI映射，通过run_upstream_bounded在owned Signer范围内执行原Python main，**没有用新采集器替换整个SDK**。
2. SDK/main.py main→CrawlerFactory.create_crawler；WB media_platform/weibo/core.py async_initialize/start→既有Search/Detail/Creator/HotSearch handlers、NoteProcessor/CommentProcessor。模式准入以当前中央/本地scope为准，不因模块存在扩支持。
3. WB正文：handlers/detail_handler.DetailHandler与processors/note_processor.NoteProcessor.get_note_detail_async_task/batch_get_specified_notes；评论：CommentProcessor.batch_get_note_comments/get_note_all_comments/get_comments_all_sub_comments。
4. 原repo/platform_save_data/weibo/weibo_store_impl.py store_content/store_comment落平台SQLite；repo/checkpoint/checkpoint_store.py原CheckpointRepoManager.save/update/add_note/update_note落checkpoint。自有pro_weibo_adapter包住当前回复wire/父子/分页耐久事实，seed/public progress保多origin/原receipt，不直接改私仓循环凑完成。
5. F/pro_executor.checkpoint/observations/import_records重读checkpoint+原观测；WB合法terminal gap保持failed74/missing_unknown，不把声明差距伪成全局complete。中央source_step与原SDKcheckpoint是两个证据屏障，不能互相代替。
6. 已有代码支持的mode、实际已购模块存在、受控whole、正式采用、新真实source ACK各是不同等级。当前WB实际有限partial31ACK/图云/导出，不等其余平台真验，更不等全回复穷尽。

最小工程后续：先原SDK+fake最低transport whole/真实SQLite/checkpoint/共享预算，不新增Pro私仓fork或跨目录复制。未来真实来源只由root按原输入/同主体/原总预算执行；本轮索引没有新授权调用。

## 3. 新ACK→现后处理→Jobs→Consumer：最窄可执行增量

实际F/cloud_sync.py SHA6a48e0e1c0a3a6e812f4a5de49f41c53802a17fe1f79d128b0e12627917635f5：

- CloudWorker._tick的delivering先flush/pending=0，finishing标准finish并核task/child/epoch/worker/finish_hash/run。只completed+transcript_only会入postprocessing_runs。
- _locked_tick取该既有耐久list，enqueue成功才移除，失败保留并显式postprocessing_error；tick旧后处理。_save保存该list。
- dashboard._light_postprocessing还再次筛transcript_only，其他run直接return。**不能只放开CloudWorker条件，否则普通素材被移出但没处理。**

正确ACK映射：record.origin.run_id是本地源run；envelope.run_id是云run；原wire RECORD_FIELDS没有provenance。单task/child可含多个原local/cloudrun/epoch，保各行origin。旧表captures列是id/run_id/envelope/digest/state/receipt/error。

下一实现盒（尚未实现）：
1. 原postprocessing_runs继续唯一待处理list，配同项的finished scope metadata保存local/task/child/cloudrun/epoch/platform/outcome/ledger used/finish_hash；不新增来源队列。未知/账本不明/finish未验保原拒绝。
2. 薄composite callback保旧transcript准入/幂等，新增材料路径用ack_snapshot，只选acknowledged+原received receipt+typed ID/hash精确。failed/stopped材料保partial；completed也不推全量。媒体/作者独立行不伪文本，明确deferred。
3. 素材bundle写project内inputs/confirmed-bundle.json，manifest使用现snapshot-file与expected_sha。现connector_snapshot.SnapshotFileConnector.fetch用project内openat/NOFOLLOW/bytes上界/hash，读取本地ACK副本，**不是平台重抓**。
4. 直接现051 toolbox.cli run→Jobs.run。STAGES原crawl/clean/score/audit/deliver；crawl只指上述snapshot-file，保内部receipt、job fingerprint/lock/attempts/精确refs/unknown保留，不手改stage来“跳过crawl”。固定CLI合同：python -m toolbox.cli run MANIFEST --job-id ID --as-of ASOF --dir PACK_ROOT。
5. 使用既有后台执行槽/固定子进程，enqueue只建耐久job，不能在源Worker tick里同步跑整批阻塞租约。原AnalysisJobs.start硬接Codex，不可直接当确定性handler触发模型；需最窄固定provider/子进程分支，不能复制新队列框架。
6. job完成Consumer独立审计后切新材料发布指针，旧独立root不变；没有新ACK不生成同scope重复job。自动队列项/材料job/源run/云ACK/餐厅结果五个状态分别显示。

最小同输入验收：受控原finish response→耐久callback上下文→同31ACK及partial→本地Jobs Stage→四格式；重启/重复enqueue不重复RAW/version/job；pending/receipt错/多scope/ledgerNone/unknown finish不处理；原transcript调用矩阵/Owner暂停/来源预算与回执全保持。此验收尚未执行，现仅提取器候选/投影可复核。

## 4. 中央Owner认证→065知识审核：真实权限路径与缺口

原知识API位于固定065隔离环境site-packages/toolbox/knowledge.py；不要在051数据进程混import065。实际proposal=prop:f1b-proposal-cuisines-034，scope=engineering/ctfs/cuisines-gap-review、model/private/proposed，target/stored base_hash=ad30e269708d3b26d52f11f472716f6513ed95c8b311c90393d394a5846116d4。

现可执行：knowledge_review.py --action preview。protected0600后台配置固定路径/actor/scope/hash，只以原bot同actor getters读临时快照，不改源库；不能将其算本人审核。approve/reject均authority_unmapped、0写。

现SDK真实权限：
- grant_review(proposal_id,base_hash,grantee_actor)：model不能授；私有提案仅其owner actor或admin能授；禁止self-grant，精确proposal+base_hash绑定。
- get_proposal/get_receipt/get_payload/get_evidence：private受actor/已授reviewer范围限制；新造本机Owner actor不能自动读该model私有提案。
- review(proposal_id,'approved'|'rejected'|'request_changes',reason,evidence_refs)：reviewer/admin；private需exact grant（可信admin例外）。approved必须候选locator/version/hash证据。
- release(pack_id,version,target_hash,packs_root,candidate_dir=...)：只能已accepted/证据匹配，再不可变COMMITTED；pin另显式。
- get_package/query_concepts/list_pin_history：用于COMMITTED版本/pin读回；知识pin不是051消费者指针。

未实现的可信身份桥：当前dashboard app.token是CSRF；CloudClient role='owner'是中央项目角色。二者都没有已核映射把当前本人授成知识scope admin/reviewer。不存在可直接使用的映射即继续待审，**不得造AuthContext(admin)、改model私有owner、伪grant或把工程approved当本人**。

最小真实绑定前置：复用现中央Owner登录/项目授权能否提供稳定本人actor ID及可信项目角色；后台将该明确授权绑定到知识scope/角色（先核受保护绑定配置与现授权是否足够；不足则记录具体缺口，不推定已授权）。该model提案需可信知识admin授exact grant给另一个已映射reviewer；随后dashboard持Owner会话+Origin/CSRF，浏览器只交decision/preview token，不交路径/actor/role。后台重核原状态/hash/授权并耐久单次decision，未知不重发；approve/reject调用原SDK。release与生产消费者切root/pin分别验收。

同输入验收：真实本人映射前approve/reject始终拒；映射后exact prop034/6hash/真实grant决策一次，坏actor/scope/hash/late包/重复未知拒；rejected不发布；approved只有原COMMITTED/hash回读后才能另行切051独立root，新旧同RAW/12unknown/旧报告回滚保持。**目前均仅preview候选，未实现或通过该真实审批链。**

## 5. 近期顺序与退出条件

1. 现F1A31+F1B6原Consumer正式可读保持；不为了计划刷新重启/采集。
2. 优先自动ACK候选的Worker→callback→现Jobs完整离线闭环与非作者，先解决动态入链；不重新开发评分或另排来源。
3. 并行真实Owner知识映射/审核入口，缺权限如实待审；0.3.4可工程重算，不自动正式采用。
4. 之后知识审核的版本驱动同RAW Consumer切换/旧版回读，再复用旧PWA展示领域标签/地图/真实反馈；食客与餐厅品质证据不足继续unknown。
5. 每项提交/测试/独审/采用/真实用户读取分别记证据，不用代码目录存在、状态completed或聊天摘要替代交付。

本轮没有执行上述动作，只输出研究索引与SHA元数据；正式handoff/代码/云/业务数据均未修改。


## 6. 可移植的完整版本元数据

仅路径/函数/SHA元数据，无私仓代码或凭据。源文件可访问时先核SHA；读不到私库的接力者标未验证，不从此表重建源码。

| 根/相对文件 | SHA256 |
|---|---|
| `F/pro_executor.py` | `45b8e4f759ab3f1436828b614198f66c17b12ce7c39db0dee30bfb9ae9f30f12` |
| `F/mc_runner.py` | `25de79e451c478b20905c22d07b1f895244d749f32c8e2d3374678113a583ba8` |
| `F/pro_weibo_adapter.py` | `e30a23665e01c549927faffb6de6e09c10106f491deeea366ecbf4789b7457a2` |
| `F/pro_weibo_seed.py` | `0feaf804f156e7dab4d798a9fe22af4ed3627acbc1bafb8272f59be84f7eb3e2` |
| `F/shared_request_budget.py` | `879131bb38f173ed93d758ce6dda8fe4a9603fd4ee82dfe49c352101b00743c7` |
| `F/pro_source_steps.py` | `a260e7e54ea7d6272e8787aaf39157a7da3d22d7b9318a8cdacc20b260244533` |
| `F/cloud_sync.py` | `6a48e0e1c0a3a6e812f4a5de49f41c53802a17fe1f79d128b0e12627917635f5` |
| `F/dashboard.py` | `79e4de53d9dd664c6e6ef1bdf592bab036e65f65d6a03cd618df24d07c088030` |
| `F/publication_reader.py` | `0fad9455d1b9b4803de29bfa72db57955511ff9cc8797363f188e0beb14c0d5b` |
| `F/material_bridge.py` | `452f19cf087f21b4884421c464fe587229ab4a0bc88817f3725db129d26b9b79` |
| `F/workbench_material_call.py` | `b127ed650a469e040b1d9b46ae50aca5ef872e6f65bb6b14c6f57ea76d1b6c01` |
| `F/results-ui.js` | `ea9b2a8858ba0fe0066c8be9abb58aac57b9ce44551bebf0d85904c7abcfcf0a` |
| `SDK/main.py` | `c2b32c6b474b4ec6fcdc3e58bdf71016a754f2d259be2c00308411a34f4574ab` |
| `SDK/media_platform/weibo/core.py` | `547d92716a446253083f095728775077efd2544748a9bc5665a67ec7ca289e72` |
| `SDK/media_platform/weibo/handlers/detail_handler.py` | `d831bf5b92b4a08b38916157bec55678213e98acdd8bd79796a40dff98c5e490` |
| `SDK/media_platform/weibo/processors/note_processor.py` | `bf1a53a276ef742aedcf8bb443bd00ace860fb2036288c4adace2ce26a294b01` |
| `SDK/media_platform/weibo/processors/comment_processor.py` | `4f5e4ec2ed6181bfec6dbfa5df1fb391677fa8b70731d13abd3a66d0f2c80e57` |
| `SDK/repo/platform_save_data/weibo/weibo_store_impl.py` | `eea6e282d756431a75edaca033d30c739b2fa42a40da5fe32a58eafef30a8ab9` |
| `SDK/repo/checkpoint/checkpoint_store.py` | `99f3c40c01939c6efda5f836a7735ec7c37f9f469ab60445cb2b869ff7cfbb1d` |

## E71新增正式入口（2026-10-16，运行事实看HANDOFF）

| 正式文件 / 实际接口 | 用途 / 已验边界 |
|---|---|
| server/crowd/v4/multiplatform/dashboard.py Application.knowledge_request、POST /api/knowledge | 原Host/Origin/CSRF后调用固定服务；真实预览已核，未代本人决定 |
| knowledge_review_call.py call | 固定0600配置与原CloudClient配置路径；隔离065进程/stdin请求/25秒超时；没有浏览器role/path |
| owner_knowledge_binding.py OwnerKnowledgeBinding.authenticate/validate_decision/decide | 原中央Owner认证到固定scope；原SDK精确grant/review与耐久intent，不发release/pin |
| owner_knowledge_service.py OwnerKnowledgeService.preview/decide/status | 同数据diff/私有preview token/明确决定/只读原intent查账；真实四审核发布表仍0 |
| knowledge-ui.js knowledgeView.show | 实际工作台“知识更新”入口，展示真实提案差异和12unknown；不自动采用 |

六源精确SHA由RUN16/e71-owner-knowledge-adoption/independent-runtime/FINAL.json（7c1324f9）固定；源码提交55431f5d71bdb09e677ac112dac99344a032a7da/远端同。不要把发布链未采用候选加入正式入口；原051 Consumer与065知识pin仍是两个不同指针。
