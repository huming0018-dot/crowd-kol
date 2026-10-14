# 交接证据索引

更新：2026-10-14。只索引实际存在且本轮读取/核对的材料。状态以各证据的观察日期为准；已有报告用于定位，原始响应、差异和测试输出用于复核。下列 WORKSPACE 指本仓上级目录，AUDIT 指 `WORKSPACE/outputs/collector-adversarial-audit-2026-10-14`，EXEC 指 `WORKSPACE/outputs/unified-distributed-product-2026-10-14/execution`。完整SHA与未提交清单见本地 `2026-10-14-local-inventory.json`，未随Markdown发布。各旧条目为对应时点的历史观察；当前状态以HANDOFF第3节与E27为准。下列JSON、运行产物和PRIVATE文件均只在本地，在线读者无法访问原件时必须标未核验。

| ID | 材料、版本与用途 | 实际检查与证据边界 |
|---|---|---|
| E01 | EXEC/SESSION65-FREEZE.json、CHANNEL65-INDEPENDENT-VERIFY.json、participant-65/FREEZE.json；AUDIT/rea-shipped65-evidence.json、shipped65/manifest.json | 正式65源912b080；实际包解开检查（REA），非仅看版本声明。内包143663B/SHA256 0ee83b8deb48748bf9bfab95cd552026d877be5b2dae039af2326ef2fbf13df8；外包372007B/f18a477ea1f49304c6f65c045c601761c79299363b6b812488156b195e50ad30。10-14本轮重算本地包摘要。不能代表每台终端已应用 |
| E02 | EXEC/ACCESS65-DEPLOY-READY/{CLOUD-REVIEWER-V12-READBACK.json,CLOUD-REVIEWER-PUBLIC-MANIFEST.json}；crowd-pages/v4/releases/；公开元数据入口见主文档 | 10:58 CST非作者生产三文件精确SHA回读与固定公网包核验，crowd-access v12。后续接力须复查线上是否仍同版本；本轮交接不重发包 |
| E03 | EXEC/SECOND65-ADOPTION-INDEPENDENT.json、LOCAL65-IDENTITY-INDEPENDENT.json、LOCAL65-NATIVE-INDEPENDENT.json、LOCAL65-PARKING-INDEPENDENT-VERIFY.json；REVIEW-LOCAL65-PHYSICAL.md；local-physical-acceptance/REVIEW64-BODY-AND-RECEIPTS.md | 实机/云响应和独审原件：两实体65、4正文精确ACK、原身份保持、本机自然停车。远端助手完整ACK不可直接访问；全评论、媒体及完整重登恢复不在这4正文验收里 |
| E04 | 本地 `2026-10-14-cloud-readback.json`（未在线共享）；EXEC/FINISH65-INDEPENDENT-RESULT.json、FINISH65-INDEPENDENT-PRODUCTION.json、FINISH66-PRODUCTION-AFTER.json；server/crowd/v4/supabase/migrations/20261014031206_crowd_v4_received_task_finish.sql | 11:34:42 CST实际SELECT：task19/20仍leased、2/2、过期；proof31–34 MD5固定。已部署finish函数MD5 98517d09b9759c5d316d7981b9a3b64f。作者17/独立18用例与定义差异/ACL回读为历史本轮执行证据；交接整理没有调用finish |
| E05 | AUDIT/recovery-checkpoint/{FREEZE.json,CHANGE.patch,TESTS.json,INDEPENDENT-FINDINGS.md}；reliability-adversarial-results.json、reliability-validation.json | 冻结未发布恢复候选，作者7组PASS不替代非作者FAIL。二次OTA与无deadline探针已独立复现；原正式包空档130秒后丢评论阶段（触发阈值为120秒）另有published65-sleep-enrichment.json。未构建新正式包、未改变线上 |
| E06 | AUDIT/dispatch-data-observability-review.md、reliability-login-review.md；evidence/{outbox-poison-probe.py,outbox-poison-result.json,cloud-aggregate.json,live-*.sql} | 真实CloudOutbox+临时SQLite+确定性替身：4坏1好三轮，好记录0次尝试；不是生产压测。40 Node+82 Python定向回归通过，另2项旧回归漂移失败；不称全仓绿。中央11:18聚合有236参与者事件；机器steps未接。SQL只读原件仅本地保留，不外发 |
| E07 | 本地 `2026-10-14-local-inventory.json`（未在线共享）、三仓git status/HEAD；automation-3配置的status只读字段 | 10-14实际Darwin；三仓SHA、dirty和本地upstream divergence。未fetch/比较远端当前HEAD。看门狗PAUSED，未恢复。snapshot在文档整理中生成，后来文档自身改动须再看git diff |
| E08 | AUDIT/product-ui-observations.md；EXEC/owner-wait-runtime/{ADOPTED.json,AFTER-LOCK-RELEASE.json}、EXEC/REVIEW-OWNER-WAIT-RUNTIME.md | 采用前NODE-WAIT-UI-HTTP-READBACK为NOT_ADOPTED负例，不作成功证据。后续采用/解锁原件与11:25–11:27主代理CUA只读UI：七平台多选、评论媒体、字幕优先、登录核验、任务历史/需处理界面；未创建任务。lsof确认45937监听PID91977。界面/端口不证明调度健康或平台登录现在仍有效 |
| E09 | /Users/hubowen/Desktop/爬虫/references/mediacrawler-pro-2026-10-14/SOURCE-MANIFEST.json；AUDIT/pro-{core-capability,login-media,bonus-capability}-review.md及各handoff manifest | gh只读确认组织会员active；实际克隆8私仓，SHA固定且工作树干净。各报告逐文件记源码/文档/测试定义与未读范围。未运行Pro/模型、未迁移登录、未测试性能、未实现接入。教程视频未能读取，不称已看 |
| E10 | WORKSPACE/AGENTS.md、.agents/skills/{ponytail,caveman}/SKILL.md、outputs/mediacrawler-execution/OPTIMIZATION_RULES.md；outputs/unified-crawler-product-2026-10-10/{PRD.md,技术规范.md,实施与验收计划.md}；AUDIT/mature-platform-benchmark.md | 项目约束与历史需求；不作为当前完工证据。成熟产品24官方来源已联网查，提供队列/会话/监控/资源机制；未采购或实跑外部服务。用户10-14消息明确保真比较、固定交接伴随每轮工作 |
| E11 | AUDIT/会诊与完整升级路线.md、pro-feature-independent-review.md、pro-feature-independent-evidence.json、pro-login-media-independent-review.md | 非作者复核核心/附赠7项遗漏或边界及综合3处表述，作者修正后复读；登录/媒体关键静态合同亦独审通过。通过范围为静态盘点与路线，Pro运行/性能/接入未验 |
| E12 | AUDIT/pro-equivalence-contract.md、fixtures/pro-equivalence-cases.json、pro-equivalence-independent-review.md、pro-equivalence-independent-checks.json；evidence/bili-existing-asset-{located,independent-check}.json | 合同c573ece7、案例330bd0bc、独审e54344e4：12历史真实案例、16缺样、8平台矩阵；全部auto_acquire=false、比较not_run。98引用中92匹配，6引用因D1在2源码文件上产生候选漂移，旧摘要可由Git81ab4ae核对；不随候选改金标准。B站既存41,743,492B MP4独立核对SHA90553cbf，无重新下载。正文、评论分页、媒体、导出通过后才比较性能 |
| E13 | AUDIT/handoff-independent-review.md、handoff-independent-checks.json、handoff-final-delta-check.json；本目录2026-10-14-doc-validation.json、2026-10-14-root-recheck.json | 本地机制独审PASS；初轮36工件SHA/bytes与27链接通过、指定14当前文件凭据扫描0。主代理再次实际复现outbox堵塞，未改生产。最后增量独审57工件/27链接/14当前文件模式扫描通过；root另查15文件/35链接通过。检查范围与时间分别记录，旧12:01 inventory归档。后续主要状态更新继续登记，不把旧SHA冒作新文件 |
| E14 | AUDIT/outbox-fix/{SOURCE-SHA.json,CHANGE.patch,TESTS.json,AUTHOR-REGRESSION.log,AFTER-POISON-PROBE.json}；d1-independent-review/{REVIEW.md,REVIEW-EVIDENCE.json,adversarial.py,RESULT.json} | 基线81ab4ae；cloud_sync候选f431dead。作者92相关回归通过（10新+82原）；临时SQLite/替身及本机loopback，无来源或生产调用。原4坏1好fixture三轮10次替身调用，好记录1次capture/1ACK，4坏仍pending且可显式原ID恢复；独审10负例+78关联通过；其中6项首次loopback环境拒绝，获工具批准后单独重跑通过，无断言跳过。三文件SHA精确匹配f431dead/5d2adb9f/c168cf09。中央槽释放与Owner恢复UI未实现，不称D1全部关闭或已部署 |

## 当前只读云快照怎样复核

用已授权数据库连接对明确的任务、proof、函数定义做SELECT；不要执行claim、control、finish或任何有副作用的RPC充当查询。11:34快照只包含任务摘要、proof MD5与函数MD5，**没有重新读全部48小时实验字段**。不从“本轮没启动”推出后台试验状态永远不变。

## 状态判据

- **计划**：PRD/方案定义，未看到实现差异。
- **代码**：实际源码、版本/差异已定位；测试存在不等于已执行。
- **测试**：写明样本、版本、隔离/实机、命令、退出码、输出路径及失败。
- **部署**：写明实际目标、服务/包版本、远端回读；本地commit或ZIP不是部署。
- **线上运行**：新鲜的终端/数据库观测；worker在线不是业务成功。
- **业务验收**：同输入字段/分页/媒体/导出完整性及精确回执，必要时云回取；未满足维度仍未通过。

路径指向缺失、文件SHA已变化、证据与运行版本不同时，先标记“待重新核验”。不要用报告作者的完成声明填补证据。

## 本轮正式采用与授权接续（2026-10-14）
新增根目录 RUN=WORKSPACE/outputs/distributed-runtime-2026-10-14。下列均为原件路径，PRIVATE不对外共享。

| ID | 证据 | 状态边界 |
|---|---|---|
| E15 | RUN/ota-recovery/independent/REVIEW.md、CHANNEL66-INDEPENDENT-VERIFY.json、CHANNEL67-INDEPENDENT-VERIFY.json、OTA66-67-PRESERVATION.json、CLOUD66-READBACK.json | 源码独审/签名URL复核/本机连续实际应用；远端67与完整登录恢复未验 |
| E16 | RUN/slot-release/SOURCE-SHA.json、INDEPENDENT-REVIEW.md、INDEPENDENT-REVIEW-EVIDENCE.json；迁移20261014062752/Edge v21 | 原ID/manifest/finish合同独审；已部署回读；真实坏组未触发 |
| E17 | RUN/owner-recovery/SOURCE-SHA.json、independent/REVIEW.md | 36Python/4JS/6权限负例和1280/390隔离浏览器；当前真实groups0 |
| E18 | RUN/RUNTIME-FREEZE.json、adoption/ADOPTED.json、adoption-independent/REVIEW.md/RESULT.json | 真实运行8文件及380旧文件、四DB原行保持；117配置前置hash未落盘，独立不能逐项复算 |
| E19 | RUN/REAL-SAVED-*.json、real-saved-independent/READBACK.json及三种EXPORT.PRIVATE文件 | 真实原保存1正文8评论云结果/任务完成；0来源请求；UNIFIED-INDEPENDENT.json实际68项PASS_WITH_LIMITS；原ID/正文评论/parent/ACK/finish与三导出一致，仅保存数据范围 |
| E20 | RUN/pro-bridge/FREEZE.json、independent/REVIEW.md | opt-in桥离线独审，通过不等于Pro真实来源或性能验收 |
| E21 | RUN/COOKIEBRIDGE-INSTALL.json、COOKIEBRIDGE-PERSISTENCE.json、cookiebridge-runtime/SOURCE-SHA.json/ACTUAL-ID-VALIDATE-ONLY.json | 临时装入ID返回；正常重启未保留。封装独审independent/REVIEW.md及LIVE-BOUNDARY.json：17隔离测试+实际ping边界通过；仅127:8274启动，真实cookie未读取 |

E21补证（15:31）：RUN/COOKIEBRIDGE-CLIENT.json、COOKIEBRIDGE-RESTART-PASS.json、COOKIEBRIDGE-BILI-SYNC.json：正式加载正常重启保留、客户端精确绑定、仅本机Cookie同步存在；未验证native登录或来源。旧PERSISTENCE.json是前次失败时点，不再代表当前安装状态。


<a id="dr-pro-plan"></a>
### DR-PRO-PLAN｜CookieBridge限定独审与B站静态准备

- `outputs/distributed-runtime-2026-10-14/cookiebridge-runtime/independent-formal/REVIEW.md`、`RESULT.json`：4包装/18上游源SHA一致，10作者+7独立检查PASS；真实Cookie读取/网络/监听均0。明确本机无Origin进程无token可访问边界。
- `outputs/distributed-runtime-2026-10-14/pro-bridge/live-plan/SOURCE-SHA.json`、`STATIC-PLAN.json`、`AUTHOR-TESTS.log`：固定BVID/原session/client、1正文/20批后评论阈值/回复保留/媒体不重下载；显式预算8+1+已用1。脚本05bc1aa9，7替身测试PASS；START-INTENT不存在，未启动。
- `outputs/distributed-runtime-2026-10-14/pro-bridge/live-plan/README.md`：SignSrv必要性源码行、正常入口/未知不重发、原云回执接入边界。独立启动脚本最后复核待收，不代表Pro真实分页或ACK完成。

## E22：首次原账号Pro真采与partial保留
- RUN/pro-bridge/live-plan/START-RESULT.json：唯一run d6b2d434-18b8-4448-98d8-70c172d4873f；原status failed/wall_timeout/exit-15，8attempts。
- RUN/signsrv-runtime/{SOURCE-SHA.json,independent/REVIEW.md,LIFECYCLE.jsonl}：原算法引用，13作者+7独立测试，真实signer外部nav1成功；加账号预检1，显式试验合计10次。
- RUN/pro-bridge/live-independent/{REVIEW.md,READBACK.json,EXPORT-VERIFY.json,CLOUD-PARTIAL-PREFLIGHT.json}：正文匹配87ae同视频；新19根8回复无孤儿，旧6回复只重合5，checkpoint未提交，不能声称评论等价。
- RUN/pro-bridge/live-plan/INGEST-RECOVERED.json、PRO-OBSERVATIONS.PRIVATE.json、EXPORT-SNAPSHOT.PRIVATE.*：原partial已进正式库，30观察=1正文27评论2媒体引用；rev69原导出35项包含7旧项，精确28 refs核验通过。
- RUN/pro-bridge/live-plan/CLOUD-PARTIAL-{REQUEST,PREVIEW,CREATED}.json：唯一task0cb0b49a-e884-4a6a-ab1e-bee390bddbd2，existing_saved/source0；待最终28ACK独审。原来源不改failed。
- 更正：E19实际refs正文117410296235621是另一条非遗视频；当时task targets填写BV1oca不匹配。9条所选旧记录回传证据仍有效，但目标匹配/同输入对照没有通过，不能引用为此视频基线。本次真实aid117355149531810，参照原87ae视频数据，不重写原历史证据。

- E22云回传复核（2026-10-14 16:15）：`outputs/distributed-runtime-2026-10-14/pro-bridge/live-independent/CLOUD-ACK-VERIFY.json`，原task0cb0b49a completed；1正文27评论/28ACK逐字段等于本run导出，原outbox envelope及finish hash复算一致。来源请求0；原来源failed/wall_timeout、coverage unverified不变。

### E23｜Pro异常清理修复正式采用（2026-10-14）
- 源码848bd315cb1140cd071eaff33e0a4b844fa48a86已推送原授权分支；2文件，私有Pro原仓未改。`outputs/distributed-runtime-2026-10-14/pro-bridge/budget-stop/independent/REVIEW.md`：19回归+2独立context+5实际SQLite合成生命周期通过；真实旧超时唯一原因未知。
- `outputs/distributed-runtime-2026-10-14/pro-cleanup-adoption/ADOPTED.json`：运行pro-cleanup-a1fc351a598c8e08/PID51742。非作者`pro-cleanup-adoption-independent/LIVE-RESULT.json`核4数据库逐表与实际backup一致、118原job/config SHA保留、387旧源码文件不变、1054ACK/pending0；运行端口唯一PID及command精确匹配。
- 采用脚本独审9组通过并修复3继承问题：PREFLIGHT持久hash、相同HTTP代码下核新PID、ps错误不当退出。回滚保数据，不覆盖新增行。真实平台完整性仍未通过；预算停车本机真实验收另记，不以离线耗时当采集提速。

- E23本机真实停车：`outputs/distributed-runtime-2026-10-14/pro-cleanup-adoption-independent/LOCAL-STOP-LIVE.json`，run a23d8844-43d1-4a32-b012-cda3eda4611c实际api1/api_request_limit/exit73，sup53620已ESRCH、run命令无残留，SQLite各表0。SignSrv与原失败任务/导出/28ACK共9SHA不变。意图到终态3.912秒仅整段，childPID/标记到退出用时未知。

### E24｜保存数据目标门禁与两原节点最新云状态
- `outputs/distributed-runtime-2026-10-14/existing-saved-target-gate/independent/REVIEW.md`及RESULT：7独立+79最终回归；旧refs拒、新28refs通过，固定版本而非标题推断。本地Owner四入口及worker-before-stage门禁；云直接客户端仍能绕Owner校验，未假称中央证明完成。
- 4文件提交55418cc已推送；运行`saved-target-85bd07038fef3096`/PID56343。`saved-target-adoption/ADOPTED.json`与`pro-cleanup-adoption-independent/SAVED-TARGET-LIVE.json`：3runtime SHA、386未改旧文件、4真实DB/119保护文件保留。两次锁忙在Stop前退出；有界2秒等待差异经3真实flock负例独审后采用成功。
- `saved-target-adoption/ACTUAL-PREVIEW.json`：原错视频请求HTTP400 existing_saved_target_unverified（因缺明确映射，不能称已证mismatch）；本次28refsHTTP200。只preview，未create/新采。初驱动预期mismatch断言失败后保存实际协议，不改产品掩盖测试。
- `ota-recovery/TWO-NODE-CURRENT-READBACK.json`为root实际Supabase只读响应：原task19、20均complete、target/received2，各proof_count2；关联原节点均4.2.67/enabled，login_state unknown。版本上报不替代另一台原生连续OTA/重登验收。
- `ota-recovery/TWO-NODE-STEP-READBACK.json`为两节点脱敏日志聚合：均有claim/detail/upload/receipt；comments只有started未有completed，OTA没有事件。原身份/登录/租约错误历史保留，不由当前complete抹掉；步骤证据还未完整。
- `pro-pagination-contract/PLAN.md`分官方联网/固定私仓证据与独立推演；分页外桥候选仍待非作者审查。`signsrv-runtime/STOPPED.json`记录导航预算耗尽后正常停止自有SignSrv，没有重启规避预算，CookieBridge及原浏览器保留。

### E25｜真实连续OTA68→69与两原节点
- `ota-observability/followup-69/RELEASE69-INDEPENDENT-{PACKAGE,SIGNATURE,REMOTE,CHANNEL,LIVE}.json`：32ZIP条目、26JS语法、原权限身份保持；原公钥签名/远端固定ZIP/通道字节核对通过。本机native applied69/seq2026101469，8身份/队列/历史/登录恢复摘要保持。
- source c5ff909；ZIP固定678cfd9875abc255b552116363591ea3515f1402，ZIP SHA96c5aec072638c3e2117cd9d2254279f8b85c791fb4be251f0ff0e9dca290db3；签名通道76474d2。release SHA b212cdbe63d85a9d0066aed6d54066f6b95f07951da60a7b38d38a5f6d47492e。
- `RELEASE69-INDEPENDENT-TWO-NODE-CLOUD.json`：非作者直接SQL核两原节点69和准确release摘要，原task19/20仍2/2，各proof2。另一台原生连续链和完整平台重登不由版本外推。
- `OTA-HISTORICAL-EVENTS.json`及`CURRENT-UPDATER-STATUS.json`保留四条failed/unexpected_error历史及先前operation_failed；后来poll自然current/null。`reviews/20261014-ota69-historical-failure-diagnostic.md`指出native吞stderr/通码，具体网络或IO根因未知，不能假归为网络或锁。

### E26｜Pro正常批次、保存200引用与观测保真缺口（22:43阶段历史，最终状态见E27）
- `pro-pagination-contract/independent/PIN-CAP-FINAL.json`：47作者+4实际SDK路径独立测试，preimport cap/原extractor置顶回复修复，64e23d9正式推送/采用。`pro-cap-adoption-independent/LIVE.json`核四库/120保护/388旧文件。
- `pro-cap-live/INDEPENDENT-LIVE-FINAL.json`：f2cb4ede-696d-45c2-9f42-38fcaa21c2b0真实completed/exit0，1正文20根86回复、40runner+1Signer；18页saved、父批及vox committed/completed，覆盖limit_reached/upstream_batch_limit。17子页事件时commit=false不回填。`TIMING.json`为意图到终态43.003秒，单样本非P95。旧2fe六数据文件SHA保持；新Signer已正常停止。
- `pro-followup-live/INDEPENDENT-EXPORT70-CLOUD129.json`：138快照=133本run(129正文评论+4派生媒体)+5旧，更正root“9旧”错误。`pro-cap-live/INDEPENDENT-EXPORT71-CLOUD107.json`：144=114本run(107正文评论+7媒体引用)+30其他run。三格式字段/hash通过；未把引用称视频字节/转写。
- `existing-saved-ref-limit/independent/FINAL.json`：68Python/Node6及独立边界；200允许/201拒，live预算/目标/ACK/finish保持。b967322已推送；Edge22真实回读11文件仅contract改100→200，原index/auth保持。`saved200-adoption-independent/LIVE.json`：PID87462，四库/121保护/387其他旧源码保持。初次跨Python repr摘要误报，经同解释器及备份逐行独核通过，非数据改动。
- 唯一交付129任务83f47fbf-3bd2-41db-bf94-66aa23a0aaaa与107任务4f00dd4a-b2f0-40ae-a03e-f36d2592c3fa，各对应目录有REQUEST/PREVIEW/CREATE-INTENT/CREATED，source0。不重建未知结果。
- `pro-followup-live/INDEPENDENT-CLOUD129-FINAL.json`：129真实唯一ACK、原envelope/receipt/hash、finish重算、completed/source0通过；文本及父子语义保持。但28条origin/4条metrics与导出70不等，Gate为FAIL_OBSERVATION_FIDELITY_PASS_DELIVERY_PROTOCOL。saved_version的MIN版本revision取首次观测导致，当时正在补可选results_revision精确快照；旧任务/ACK不覆盖。后续旧107独审 `pro-cap-live/INDEPENDENT-CLOUD107-FINAL.json` 同样保真失败（origin105/metrics20）；两项纠正版最终解决与真实独审见E27。
- 审查曾whole-run copytree跟随profile路径失败，3临时目录root核已清除：`pro-followup-live/ROOT-COPY-CLEANUP-VERIFY.json`。部分曾复制清单未知，无外发/日志凭据；现白名单复制并拒profile，规则已写AGENTS。原RO DB会建0B WAL/32KB SHM元数据，主库hash不变，不假称文件集全不变。

### E27｜冻结观测、已知拒绝收尾与真实云保真最终验收
- `existing-saved-snapshot/independent/FINAL-COMBINED.json`：124综合Python/21Node、真实236行快照与摘要正例，跨库同counter/正文版本但不同观测拒绝。可选results_revision+record_sha256绑定完整冻结导出行，legacy未绑定保持旧行为但不具有此保护；缺版本/未来拒而不读latest。source提交8c3444a。
- `existing-saved-rejection/{BEFORE,CALLER-BEFORE,CALLER-AFTER}.json`及`ACTUAL-READER-FIXED.json`：原本确定本地拒绝两tick仍authorized/重复读者/续租，四实际本地错误码补入窄白名单；修后原run durable failed/API0/emptycapture，原finish/idle/reader1，未知网络/已有outbox保持。只是实际类与临时库隔离证据，尚无生产自然拒绝案例，不声称其现场验收通过。
- Edge23实际11文件仅contract变化，原index/auth/verify_jwt保持；`snapshot-adoption-independent/LIVE.json`核PID91623、完整5文件含2helper、四库/121保护、原1290ACK。HTTP129实际预览因32KiB拒后，30139a2窄补仅tasks preview/create支持128KiB；`existing-saved-http-limit/independent/FINAL.json`52相关真实HTTP测试，其他操作/路径仍32KiB/CSRF/Origin保留。
- `saved-http-adoption-independent/LIVE.json`：最终PID92704/runtime saved-http-fa00c58899c78085，只dashboard窄变，389其他源码/121保护/四库与actual backup保持。Edge无需重复部署。任一源码HEAD都不能替代此运行快照。
- `pro-followup-live/INDEPENDENT-CLOUD129-SNAPSHOT-FINAL.json`与`pro-cap-live/INDEPENDENT-CLOUD107-SNAPSHOT-FINAL.json`：两纠正版completed/source spent/reserved0；所有交付采集字段（含origin/metrics/父子/media）=冻结export70/71+原规范records，差异0；236真实ACK与原envelope/digest/epoch完整唯一、finish重算分别94efe0d7681402364281da23094845f37503e071c22b2fa160d20cbaeeba9def、f50c68728f5b1432a9edea6ac8c74f55ac9ff2f9efddfc7e85fc0afefb477d20，等独立SQL。导出展示/人工评价元数据不是采集字段，完整行digest另在stage前核过。
- `existing-saved-snapshot/independent/FINAL-REAL-CLOUD236.json`最终PASS_ACTUAL_BOUND236_CLOUD_DELIVERY_WITH_LIMITS；236是两冻结快照观测数，实体去重131=正文1+评论130，不能称236独立新内容。`LEGACY-CLOUD-FRESH-PRESERVATION.json`核旧失败保真任务原字段/ACK/finish保持；原2fe仍failed，新f2c bounded completed，不说全评论耗尽。
- `FINAL-WORKBENCH-STATUS.json`：idle、scheduler alive、stale=false、1526ACK、pending/quarantine/deferred0。`pro-cap-live/COUNTER-SCOPE-CORRECTION.json`校准40为含loopback的runner HTTP尝试+另1Signer外部nav，平台专属请求未独立测，浏览器请求未计。
