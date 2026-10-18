# 统一产品计划刷新｜独立审查

日期：2026-10-16。审查者：Codex `/root/knowledge_reuse_probe`。范围：只读规划、原v2.2与实际资产/证据对照；未实现、部署、启动采集、运行旧cron或访问平台/云。本审查没有联网重新验证研究页面内容，不把已有文档的“已查官方”冒成本次联网结果。

## 结论

**整产品定义与三方分工可保留，现计划不能原样作为下一轮可执行排期。** 主要问题是当前事实停在E63/F1未采用阶段，已发生的F1A/F1B正式结果没有并入执行基线；自动新ACK处理、真实Owner知识授权与消费者数据适配仍没有足够具体的接线合同。先修下面前三项执行阻断，再按后四项细化；不重写PRD或M0–M7框架。

优点应保留：U01–U22没有因“先做切片”删总需求；四评分域分离；Pro平台核心优先、原MC媒体和参与者链保留；本地保存/云ACK分屏障；051/065隔离；D1/D2/D3及48h计时分开；ponytail/caveman正确定位为方法而非技术平台。v2.2中的Pydantic draft07、GLTR=广告、永久URL、强行新编排框架等前提已得到合理校正。

## 实际核验材料与边界

- 固定`crowd-kol/docs/HANDOFF.md`，实际更新时间12:52，主结果卡记当前87942/domain-79e4de53-0fad9455、F1A31素材及F1B六店正式入口；这是读现交接及已有现场证据，不是本审查新HTTP/云查询。
- `docs/product/PRODUCT-PLAN.md`、`ARCHITECTURE.md`、`ASSETS.md`、`RESEARCH.md`、`EXECUTION-CONTRACT.md`及原v2.2提取/manifest。正式仓本次只读HEAD为`bc8227aee6a695553dfa274f82e5df2df778251d`。
- 用户原HTML实际54,110B/SHA `aee488f21b14637a805f38ba4686b31bc5ce4be459acac950f8b2603863a6c5b`，与manifest相同；提取文本SHA `2d8dc4db8ada8ad2cf091b4518b319221555155fce8daaad72712cf763d57912`，312 splitlines，与manifest相同。部分旧正文写311行属于计数口径，未发现因此漏掉M0–M7。v2.1原件仍未取得，不假装完整核过主PRD。
- 前序本审查者已亲核的`f1b-real-six/independent-knowledge/FINAL.json`、`f1b-cuisines-unknowns/independent-knowledge/FINAL.json`、`f2-owner-knowledge-preview/independent-knowledge/FINAL.json`及M7复用定位，用来核当前具体缺口；不将候选审查升为正式采用。
- 定位现`cloud_sync.py`后处理入口、现toolbox Consumer/bindings及CTFS Next app；不读取凭据。

## 七项具体问题

### 1. P1｜现状与下一步互相打架，接力会重复已完成工作

**依据**：PRODUCT-PLAN §4 U09/U17与§9仍说桥未验、当前18d14b35/65679、下一步F0→F1；ASSETS“当前可验证运行锚点”仍65679；ARCHITECTURE §7仍称media cap未独审/组合未全审；EXECUTION-CONTRACT顶部只补F1A/E65，§7仍V2桥BLOCKED、最高优先级仍F1A。固定HANDOFF已是E66，F1A/F1B正式、V3已通过，DY组件组合有限审也已完成。

**影响**：新接力者会重修已关闭反例、重做RAW桥或把候选0.3.4当正式包。计划声明“HANDOFF权威”有帮助，但不足以抵消多个“当前/下一项”的冲突。

**最小修订**：保旧事实为“11:xx历史快照”；计划所有当前状态从同一张具名状态表引用，补F1A/F1B正式与F2待审、自动新ACK未通。删掉现态段落中的旧未来时，不改原历史报告。退出证据：从任一入口读出的正式revision、候选包、当前唯一动作一致。

### 2. P1｜F2“审核→发布”没有可信Owner身份/授权路径，顺序现在不可执行

**依据**：ARCHITECTURE M4、EXECUTION-CONTRACT F2要求人工ReviewDecision、release、pin，但没有具体actor映射资产。现真实prop034是private/model owner；065禁止model grant，自造owner也不能grant或读该私有提案。已审preview只有authority_unmapped拒绝，不是缺一个“批准”按钮。

**影响**：按原工期直接做F2闭环，会卡住或诱发把AuthContext字符串改admin/engineering_test冒充本人。

**最小修订**：F2拆成现已完成的保真/事件工程slice、真实待审提案、可信Owner身份绑定、exact grant/reviewer决定、release与Consumer切pin五步。绑定步骤指明复用哪条现登录身份及scope；未核前标待设计，禁止模型/浏览器提交role放权。新旧051 root独立、知识pin与Consumer指针分别验。退出证据包含实际actor来源/授权/grant/decision，而不是CLI 0。

### 3. P1｜新ACK到处理缺少明确触发合同，手工样本通过不能保证持续产品

**依据**：计划讲“中央ACK→M5阶段”，但当前`cloud_sync.py:1220–1222`只在outcome completed时排postprocessing，原callback也不是自动通用RAW处理。现真实WB31ACK仍failed/partial；F1手工固定快照已经可用，不能替代后续任务自动进入数据产品。

**影响**：若只接completed则漏掉已交付partial材料；若一概改所有failed入队则可能处理未ACK、重复或unknown材料。Jobs原crawl阶段不能用于重放已采来源。

**最小修订**：明确触发键为具名task/child/ACK集合摘要+处理版本；只从耐久已ACK记录构建快照，partial保原因；无新ACK幂等no-op。利用现CloudWorker callback/Jobs确定性阶段，不建第二来源队列；重启、迟到ACK、同输入重算与失败隔离各一项有限验收。退出证据是下一批新受理材料自动发布及重启不重复，而非再做同31条手工构建。

### 4. P2｜M7“复用旧PWA”缺少ID、分类及反馈合同，不能直接接六店

**依据**：ARCHITECTURE M7/ASSETS写可复用旧Next；实际旧restaurants数值ID、cuisines关联、favorites外键不能接六店字符串source_record_id。六店分类键在`draft.feature_keys`，不是`classification`；现包缺中文label/parent树。收藏只有二态；reviews/举报不是想吃/不感兴趣/吃过三态。六店无核验坐标。旧详情页165行非高德即食客的OR逻辑不能移植。

**影响**：直接整页复用会假ID、丢候选、混素材准入/口味分、凑地图点，或把localStorage收藏当M4反馈闭环。

**最小修订**：指定现`/data-product/report.json`为第一同源只读消费者输入；借旧页纯卡片/筛选样式，不搬旧写库逻辑。分类label/parent走具名纯配置，未映射待整理；无坐标显示待核。三态反馈绑定可信actor+project+report hash+record revision+幂等intent，复用KnowledgeStore反馈但不自动认定真实食客。详同级e66 `FRONTEND-REUSE-PROBE.md`。

### 5. P2｜最终云端/多设备消费部署拓扑仍未落到可执行路线

**依据**：计划选中央Supabase、终端SQLite、toolbox PG候选、Next消费者，同时实际两个正式数据结果仍是本机45937、source-pinned051与本地SQLite。文档正确承认“本机不等远程”，但没有明确未来由谁生成已审发布快照、怎样将APP快照给异机PWA、哪些身份能访问、哪些状态驻云，回滚时哪一指针是权威。

**影响**：容易出现远端Next调用用户127.0.0.1或把原SQLite/私有源码/全部运行目录打包上线；仅本机结果被误当可供两天多用户消费。

**最小修订**：增加一张“本机/终端/云端/消费者”部署表和一次可逆迁移路线。先选择发布后的静态report对象+受控查询，或已验PG只读视图其中一条；给身份/RLS、数据发布hash与原ACK引用、云端读取和回滚证据。不因旧app存在就重开云写入。本项是计划缺口，不要求本轮部署。

### 6. P2｜时间盒与能力冻结缺乏实际起点/队列，不能据此再承诺两天完整

**依据**：计划§7仍“从恢复开始”0–1/1–4/4–8小时，执行合同仍F1A最高；D1平台×模式×正文×回复×媒体×导出×ACK×登录恢复矩阵被列为首要，但没有链接具名已冻结矩阵。手机本机执行只列独验，没有运行选型。当前多个外部条件未就绪，F2审核、两原节点/OTA与跨端不是同一串行耗时。

**影响**：每次继续都可重启时钟；D1/D2/D3与各项U需求边界虽正确，实际仍无法判断剩余多少、下一槽做谁、哪天可交什么。

**最小修订**：固定本轮T0/计划版本，按当前证据直接填F/U执行表；每项标可自主、需设备/本人、依赖真实权限、未选型。D1矩阵生成后才定冻结范围；D2材料纵切可并行推进，不被D1外部条件全阻断，发布声称仍分别过门。跨端保总需求但先交运行方案/最小实机验收，不用网页控制代替。本项不要求缩总目标。

### 7. P2｜研究可作原则依据，尚不足以成为可移植功能的实现索引

**依据**：RESEARCH共15条主要为一手来源，明确“借机制/不装框架/需实测”，总体可靠性优于原v2.2星数表。但R01的组织首页、R04 main分支、R06 current、R07 stable等是动态入口，不能证明固定私仓SHA某函数/某平台已支持。Pro模式完整矩阵、许可覆盖、实际安装锁/本地调用锚点仍待核。未发现证据足以断言引用内容错误；本审查未联网复查页面。

**影响**：下一实现者还要重找原函数、再猜Python/Go差异，研究停留在选型层，不能直接外部复用交接。

**最小修订**：只对近期将采用的Pro平台/yt-dlp/现知识API增加精确本地SHA+文件/函数+输入输出+保留能力+最小同输入验证，并对外部动态文档存检索日期/摘录摘要/固定tag或commit链接。不是重新泛搜15个框架或全安装。R02等仅借机制者保持“无代码移植”即可。

## 放行与下一步

七项均为计划可执行性/当前状态修订，不判整个现系统无效，也不授权上线。前三项是下一轮执行计划的阻断：**唯一当前状态、真实Owner知识授权、已ACK自动处理合同**。其余可并行收敛，不应再抢先重建评分器或新前端框架。

最短刷新产物：现有主计划更新版本与当前执行表；一张三方/本机云端权威图；F1A/F1B完成与F2/自动处理/消费下一项；近期Pro原函数索引；明确验收对象/证据/回滚。保留原v2.2功能、四评分域、参与者身份/回传/OTA及完整同输入门，不把“更快”作为替换许可。
