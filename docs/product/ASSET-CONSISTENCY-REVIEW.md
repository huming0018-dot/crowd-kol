# 资产一致性独审

2026-10-16，Asia/Shanghai。审查者 `/root/central_steps`；被审作者：PRODUCT-PLAN主控、ARCHITECTURE/RESEARCH作者。本审查**不为自己实现的ASSETS签独审PASS**；用其已读取来源进一步核对三份规划。只读文稿、正式源码及既有报告，未运行/发布/新增来源。

结论：**CHANGES_REQUESTED_BEFORE_IMPLEMENTATION（4处窄修）**。融合方向与现有资产一致：Pro成熟引擎优先、中央来源派单与toolbox阶段DAG分工、保原参与奖励/身份/OTA、先已ACK→RAW→clean/score/audit/consumer，不增加一套通用框架。未发现把31ACK/原图/R88写成完整回复通过；第二消费者工程摘要也保留未验。以下文字会影响接线顺序或版本选择，应先修。

## 必须修正

| 优先级/位置 | 实际依据与风险 | 最小修正建议 |
|---|---|---|
| **P1 PRODUCT-PLAN:56：写成“本地outbox→中央ACK→提交检查点”的统一保存顺序** | 现Pro的本地分页/checkpoint推进发生在SDK保存后；normalized/import/outbox/中央ACK是后续交付链。真实af947仍local failed74/partial且原根checkpoint不推进；不能据此泛化成上游永远等待中央ACK才提交。把目标写成统一顺序，实施者会被迫重写成熟Pro控制流，和“不重写引擎”矛盾 | 改为两条独立屏障：“SDK本地保存并回读后才推进相应本地游标；中央交付在outbox耐久和逐条ACK后才确认交付。两者独立记录，不把本地commit冒成云ACK；已知partial按原游标合同保留。”若未来确要云ACK前置游标，作为另一个显式协议改造及迁移门禁，不当现有事实 |
| **P1 PRODUCT-PLAN:101/116/118；ARCHITECTURE:108/150/211：0.5.1与0.6.5兼容接线门不够明确** | TOOL/`runtime-version-map-0.5.1-candidate.json`85source逐SHA一致，是现0.5.1 PG只读候选；M4/`m4-lifecycle-fix01-review/M4-LIFECYCLE-FIX01-INDEPENDENT.md`的0.6.5是另一路部分源码包/已装wheel3e1259…，runner实际失败且NOT_PASS。版本数字不能证明0.6.5包含051 PG改动、可整包覆盖或有共同已审父版本 | F0明确三行：“版本表所标0.5.0生产待fresh核；0.5.1消费候选；0.6.5 M4隔离候选NOT_PASS”。新增一句：禁止按semver直接升级/整覆盖，先逐文件/接口比对M4差异、051 PG只读差异与实际运行wheel，窄合后共同回归RAW/ODS/DW/APP、两域consumer及M4生命周期。F1不必等待把NOT_PASS065整包装上 |
| **P2 ARCHITECTURE:98–102、PRODUCT-PLAN:81：评分四域只说“不混”但实际对应不足，且把已有贝叶斯写成第五步“才引入”** | TOOL/scorer.py是sources/refs/coverage/recency的证据/准入分；CTFS/`cloud/vendor/pipeline/scoring_engine.py`已有真实diner口味过滤/180日衰减/先验8收缩，证据不足NULL；MULTI/results_store.py人工quality评价明确reward_eligible=false；v4 ratings与参与奖励亦分账。RESEARCH R08已正确主张复用旧公式，与架构新增语气不一致 | 明列四域：①toolbox证据/准入；②餐厅/领域品质；③Owner采集结果quality；④参与者贡献/支付奖励。把“才引入贝叶斯/衰减”改为“先核旧口味公式/DB触发器与金样，作为领域rubric复用；仅污染模型训练/新增置信方法待标注评估”。主观human rating作为证据输入另留，不自动转口味或奖励 |
| **P2 ARCHITECTURE:68；PRODUCT-PLAN:166及版本表：本机/发布与当前实际证据归属应固定** | E63当前是本机已更新11:09；本地`git show5a6b4aa:docs/HANDOFF.md`仍E62/10:38。E63新真实32a77277是WB的1新评论/原图私有云与三导出，XHS是此前独立run证据，不能合称“E63证明WB/XHS媒体”。TOOL0.5.0“生产”来自版本表，本轮未fresh实机验当前服务 | 统一注明“本机未发布E63，最后已发布交接5a6b4aa为E62；源码18d14b35已发与文档发布分列”。M0改“E63证明WB有限新评论/原图/ACK；XHS有限证据另按原run引用”。技术表“生产0.5.0”改“版本表标记的0.5.0生产基线（实际服务/wheel待核）” |

## 已一致、无需扩改

- PRODUCT U05/U06/U22、ARCHITECTURE§7和RESEARCH独立推演：31历史ACK/最新1、10of12剩2、knownpartial74与媒体字节成功分开；没有把缺口改完整或剩余2自动可重试。
- 0.5.1候选/85source一致只是源码证据；6food+2software、工程PG/4HTTP/SCOPED_PASS是已读历史摘要，不是本轮fresh运行。PRODUCT§10与RESEARCH§3明确待查原件，未用fixture升级为生产双消费者通过。
- M4最新0.6.5确NOT_PASS；本轮追加读取真实独审原文确认runner缺toolbox.schema/源文件、内容导入/版本/第三域/反馈等不成立。不能用之前0.6.3局部修复PASS关闭完整生命周期。
- v2.1原件未取得，三份计划均将其作为待核，不假装已读。v2.2全文读取及原文manifest存在。
- 研究中的Pydantic/Prefect/Storage为外部材料校准，不称现依赖已安装；本审查没有重做联网来源事实核验，不为RESEARCH全部外部论断额外签事实PASS。
- 保留现CTFS consumer/清洗/本体包、中央租约与outbox、原MC媒体/Pro平台流程、原EXT/PAGES升级链，不把Vox/Remix/PicTactic整套后台重部署。这与资产地图一致。

## 审查范围与下一步

实读三文稿全内容、ASSETS引用的版本表/关键源码，并追加读取M4主HANDOFF与065独审原文。未审ASSETS自有结论为独立通过；未核云/生产PG/模型质量/每平台真实模式/当前PWA。此结论仅是资产映射一致性，不是完整PRD/安全/工期审核。

作者只需改上述4处并锁三文稿SHA；复读差异即可，不需为文稿重跑来源/云或旧SDK。完成后才恢复F0→F1既有素材纵切。

## 改后复核：PASS_WITH_LIMITS_ASSET_CONSISTENCY

本次仅复读作者文稿变化，不运行代码/云/来源；上述首轮发现保留为历史。四项均已关闭：

1. PRODUCT-PLAN:56明确两条独立屏障，本地耐久/游标与中央outbox/ACK分离，不要求成熟SDK逐页等云。
2. PRODUCT-PLAN:101/112与ARCHITECTURE:165明确版本表050待核、051PG候选、另谱系065NOT_PASS，禁按semver整覆，F0逐差异窄合和共同回归；F1不依赖安装NOT_PASS包。
3. PRODUCT-PLAN:112、ARCHITECTURE:102/104列四评分域，先复用旧口味公式/DB触发器，Vox与新分类器不作为首个确定性纵切前置。
4. PRODUCT-PLAN:168区分本机未发布E63/最后发布5a6b4aa E62、源码发布与文档发布；ARCHITECTURE:68仅把E63新业务归WB，XHS沿历史run另引。

另复核ARCHITECTURE:201/202/208：Vox、第三领域从关键路径移开；P0–P4映射到主计划F0–F7，F4从F0后并行，不等P4。与主计划F1直接利用既有数据、F6先两现有无关领域一致。RESEARCH原字节不变，R08旧公式复用及第二消费者原件待核边界仍成立。

**当前结论只允许把这组三文稿作为资产一致的规划输入**，不等于产品全范围/工期/外部事实全面独审，更不自审ASSETS为独立PASS；不构成正式部署或新来源动作。仍需F0核实际wheel/服务、双域运行原件及M4候选兼容性。精确本轮文稿SHA见ASSET-CONSISTENCY-RECHECK.json。
