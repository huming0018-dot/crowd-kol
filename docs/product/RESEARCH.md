# 外部成熟能力复用研究与独立推演

日期：2026-10-16，Asia/Shanghai。范围：v2.2 M0–M7、Kimi参与产品、MediaCrawler/已购Pro融合。本文是选型依据，不是新组件已安装、已兼容或生产验收证明。

## 一、研究方法和结果

先检索项目资产，再查官方文档/上游仓库，最后判断“直接使用、薄适配、只借机制、暂不采用”。不按星数排序，不为凑技术名词增加依赖。当前具体源码锚点及证明等级见[资产表](ASSETS.md)。外部页面检索日期均为2026-10-16；网页最新能力不能反推本地固定SHA已经支持。

| 编号/模块 | 联网一手依据、实际结论 | 本项目采用方式与可复用输出 | 兼容性/成本与最小验证 |
|---|---|---|---|
| R01 M1 | [Pro官方组织页](https://github.com/MediaCrawlerPro)：Python主干、账号/IP池、断点、独立签名、CookieBridge、推荐/热搜及三个Agent；模式因平台而异 | 平台请求/提取/分页/原检查点优先用已购固定版；适配中央身份、预算、来源、ACK。账号提醒及分布式参与产品由现有资产补齐 | 公开介绍不是本地运行证据；逐平台固定完整输入。依赖隔离；许可仅本地参考/运行，不公开复制私码。不得把购买等同不受限商业再分发 |
| R02 M1 | [Scrapy架构](https://docs.scrapy.org/en/latest/topics/architecture.html)：请求调度、下载、解析、Item Pipeline分工 | 借输入/来源处理/落库职责边界；不用Scrapy替换已有Pro或中央调度 | 若未来通用公开网页规模超现httpx能力，再比较真实吞吐、错误与维护成本。现在不新增Twisted/第二队列 |
| R03 M1 | [Crawl4AI deep crawl](https://docs.crawl4ai.com/core/deep-crawling/)：BFS/DFS/BestFirst、max_pages、恢复状态；官方提示robots检查默认并非自动开启 | 权威源召回可选适配器。先用现HTTP/标准XML解析robots和sitemap；需要页面渲染/markdown再评估现成库 | sitemap覆盖不等于网站业务全量；Common Crawl只是历史发现。链接预览页面本轮返回Internal Error，未核该接口，故不写“一接入就解决全量召回” |
| R04 M0/M2/M4 | [Pydantic官方schema说明](https://github.com/pydantic/pydantic/blob/main/docs/concepts/json_schema.md)、[JSON Schema标准](https://json-schema.org/draft/2020-12)：Pydantic v2默认2020-12 | 现toolbox已pin jsonschema4.23.0，继续其显式dialect。新契约明确2020-12；旧draft07保留对应验证器，通过显式转换迁移 | 不能只改`$schema`标签。逐契约检查required/additionalProperties/null/枚举/格式，跑旧客户端和包回放；无需为验证JSON把现工具箱整套重写为Pydantic |
| R05 M0/M4/M6 | [datacontract-cli官方仓](https://github.com/datacontract/datacontract-cli)：ODCS、lint/test/breaking/export/import；MIT | 作为CI可选开发工具，先用两个版本的真实脱敏契约试验；内部canonical JSON仍是业务协议，ODCS为映射而非另一个真相 | 文档的breaking命令不意味着任意JSON Schema语义都受覆盖。验新增可选/删字段/改类型/收窄枚举四反例；记录CLI锁定版及映射局限再采用，不在每节点安装全部数据库驱动 |
| R06 M4 | [Confluent兼容性文档](https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html)：backward/forward/full及transitive | 借兼容矩阵和包引用ledger；保留现OntologyManager，不部署Kafka或Schema Registry服务器 | 新包对历史数据、旧消费者、新消费者分别验；允许破坏性版本须显式major+迁移/回滚，semver本身不证明兼容 |
| R07 M2/M6 | [Pandera官方](https://pandera.readthedocs.io/en/stable/)：DataFrame schema及多后端校验 | 当前行级jsonschema和既有审计足够；批量统计瓶颈明确后再上polars/Pandera。Soda/GX为声明式规则的备选，不同时引入三套 | 先测同一真实批次端到端耗时/峰值RSS；逐行与批量输出、空值/时间/时区一致。没有收益不新增依赖；v2.2关于GX所有权的叙述本轮未核，不沿用 |
| R08 M3 | [Algolia贝叶斯平均](https://www.algolia.com/doc/guides/managing-results/must-do/custom-ranking/how-to/bayesian-average)：小样本排序校正 | 优先复用自有legacy评分已存在公式；rubric固定先验、时间衰减、独立来源规则。不是再下载一个同公式skill | 分清评分均值与置信区间；平均式本身不产出校准概率。无真实体验/独立声音证据则不自动给口味分。先验要版本化，不拿平台赞数当食客样本数 |
| R09 M3/M6 | [GLTR原论文](https://arxiv.org/abs/1906.04043)：辅助辨识生成文本的统计可视化研究 | 仅研究模板重复/可预测性的候选特征；不采用作“软广检测器”或真假事实判决 | 文本生成、广告、商家工业化是不同标签。缺带来源人工标注和分平台留出集时，输出unknown/待审；openskill竞赛相对评级也不直接对应餐厅质量 |
| R10 M5 | [Prefect3官方迁移](https://docs.prefect.io/v3/how-to-guides/migrate/upgrade-to-prefect-3)：2→3涉及Pydantic/异步/最终状态/调度迁移 | 当前中央租约负责来源派发，toolbox jobs负责确定性阶段，均复用。不按v2.2直接装旧Prefect2，也不先加Dagu/Airflow/Temporal | 若后续并行DAG/依赖运维有实测必要，再隔离PoC Prefect3并固定版。须测子阶段失败不能流程假成功、迁移不重复调度；不恢复已暂停看门狗 |
| R11 M0/M5 | [Supabase Queues官方](https://supabase.com/docs/guides/queues)：基于PGMQ、visibility window与持久消息 | 借租约可见期/归档机制核现任务协议；不立刻替换现RPC、outbox、receipt | 传输窗口内一次投递不等于业务effect全局exactly-once。须保幂等键、epoch、ACK对账；真实双节点抢领/超时接管测试再判。无需为了“成熟”破坏现服务端合同 |
| R12 M0/M7 | [Supabase私有Storage官方](https://supabase.com/docs/guides/storage/serving/downloads)：认证GET或限时signed URL | 稳定引用存bucket/object key/hash/尺寸；临时URL按权限生成并刷新。沿用当前私有bucket及已验回取合同 | URL过期后重新签发、无权用户拒绝、原字节回取一致；不能承诺URL永久有效，更不能为持久链接改成公共bucket |
| R13 M1/M7 | [yt-dlp官方](https://github.com/yt-dlp/yt-dlp)：`--skip-download`、字幕选项和提取器 | 继续现watch-video/yt-dlp，先尝试官方字幕→音轨→本地ASR；选择全文文本时跳过完整视频，选择原视频时仍必须交付视频 | 支持提取器不保证每账号/每视频有字幕。实际覆盖平台、时间轴、全文完整度分别验；下载字节和源调用都计账。OCR单列，不替全文听写 |
| R14 后处理 | [Apple MLX Whisper官方样例](https://github.com/ml-explore/mlx-examples/tree/main/whisper)：本地转写/时间戳与模型选择 | Apple Silicon复用现MLX后端；其他OS沿用已接后端再验证。长音轨分块、VAD、缓存、保留原稿与修订稿 | 同一冻结音频测冷/热耗时、RTF、CPU/GPU/RSS/下载字节、CER/专名召回/重复幻觉；官方样例非本机跑分。ASR仍是本地模型，不宣称纯规则能听懂语音 |
| R15 开发技能 | [Anthropic官方skills](https://github.com/anthropics/skills)：指令及资源渐进式披露 | 本项目已存在ponytail/caveman/watch-video；直接读取应用，复用相关脚本而非装同名随机包 | ponytail/caveman是开发工作法，不是产品语言、数据库或自动化引擎。未核界面注册就不声称插件hook已启用；不修改WorkBuddy原技能 |

暂不增加Redis代理池、Kafka、ClickHouse、向量库、Kubernetes或多套Web后台。它们不是被永久否决：只有现有资源/可靠性指标证明确有必要，才建立同输入PoC并记录选择。公共免费代理不作为参与者默认凭据通道。账号池只能选择有效授权会话，不能保证永不封禁或靠轮换绕过明确限制。

## 二、独立推演：从真实瓶颈倒推

| 假设/当前线索 | 推导方案 | 收益假设/最小实验 | 否决条件 |
|---|---|---|---|
| 已有Pro和MC，又有toolbox；重复造内核增加迁移风险 | 一个采集控制面、一个toolbox确定性处理链；单向capture→RAW薄适配 | 同一已交付批次离线进入clean/score/audit/deliver，0新增平台调用，源回执/原字段/缺口全部保留 | 转换丢字段/父评论/媒体语义、重抓或改写原receipt即拒 |
| 源预算有限，签名/浏览器启动/媒体重下占大头 | Pro原签名本地化候选、连接与有效会话复用、已下载媒体hash复用 | 对原完整输入比较总HTTP次数/端到端耗时/新数据/媒体；受控结果仅筛选，真实结果才放行 | 纯签候选阻塞取消、身份不明、视频被封面替代或预算遗漏即拒 |
| 回复终页缺失导致反复续采 | 以“未访问工作+已知缺口”决定可继续；完整性和可交付性分别展示 | 原WB只读预览应显示31历史/1最新、缺口原因未知、无新工作不继续；不再抓同终页证明UX | 缺口被改成complete、未知调用被自动重发即拒 |
| 下载超长视频再转写耗时/磁盘大 | 用户明确选“文字稿优先”时，字幕探测前置；无字幕仅音轨；内容寻址缓存 | 同视频0完整MP4可得全文/来源时间轴，失败可解释；原视频需求保持独立选项 | 文本无覆盖率/时间轴、OCR混为全文、默认偷偷降级媒体即拒 |
| 并发被当作无限加速 | 跨平台/跨内容分别设槽；同账号来源限速；总CPU/RSS/上传/ASR资源令牌 | 先受控1→2并发比较p95完成/错误率/峰值内存，真实原预算小试后再逐档扩大 | 错误率/429/登录失效增加、重复任务或质量下降则降回1 |
| 用户多次被要求扫码/输入内部ID | 先核原Bridge/CDP绑定与会话新鲜度，仅平台明确要求时提醒；重登只恢复原任务剩余部分 | 本人登录后原主体/任务/队列/ACK保留；UI显示检测中/已恢复/仍需处理，下一次任务不重复扫码 | 新profile代替原身份、缓存标志当已登录、后台无限核验均拒 |
| 静态分类包不等于持续知识系统 | M4增加待审知识与反馈→版本差异→回归影响→人工采用/撤回 | 现美食+软件发布两包各消费一项真实修正；未采用版本不影响已发布结果 | 自动把模型结论覆盖事实、引用丢失或错误回写RAW即拒 |

## 三、研究完成与待确认

已完成：原v2.2全文读取；官方一手材料复核；本地源码/冻结/报告资产对照；采用与舍弃机制；最小收益实验和反证条件。没有安装新依赖、读Cookie、采集或部署。

待核不靠用户代做：①v2.1主PRD准确版本；②toolbox0.5.0生产wheel及0.5.1候选工程PG原件；③实际第二消费者版本/真实业务采用；④每平台成熟Pro模式完整矩阵；⑤Pro许可是否覆盖预期产品分发；⑥外部工具精确安装版/依赖冲突只在选入PoC后锁定。许可不清影响发布方式，不妨碍本地能力盘点/独立设计。研究文档是可重复选型模板，后续每次优化继续保留“联网证据+独立推演+采用/否决+实测”四栏。


## 四、13:00补充复核：研究怎样减少实际融合工作

本轮重新打开官方Pro组织、Scrapy架构、yt-dlp仓库和Prefect3迁移文档。公开Pro矩阵明确微博推荐流不支持，支持平台/模式须按矩阵展示；贴吧/Reddit不能由该表缺行推定支持全部模式，核本地固定版实现。Pro原生能力直接接本地已购版，独立签名/Bridge的授权与可用性分别核，不再从头写解析/分页。以上引用仍使用R01/R02/R10/R13原始官方链接。

| 可外部复用的融合经验 | 官方证据方向 | 项目独立推演方向 | 落地与退出条件 |
|---|---|---|---|
| 来源完成与数据交付分开 | Scrapy Engine/Downloader/Spider/Item Pipeline职责分层；Pro断点与保存 | 平台finish并非材料已处理；目前普通文本和partial不会进现transcript-only回调，直接扩大条件会静默出队 | 复用postprocessing_runs+固定scope上下文，现Jobs处理已ACK快照；重启/重复/unknown反例不通过不启用 |
| 先字幕再媒体 | yt-dlp已有字幕选项与skip-download | 文本需求若先完整MP4浪费字节；原视频需求又不能偷偷降为音轨 | 保现watch-video/yt-dlp接口，字幕不存在才音轨/ASR；同输入全文覆盖和字节/耗时联合测 |
| 避免迁移调度器代替功能融合 | Prefect官方2→3存在运行语义迁移 | 中央派单/租约和toolbox确定性阶段已有，另装DAG引擎增加重复调度面 | 当前不引入Prefect/Redis；只有已有实现无法满足量化并发/恢复目标时隔离PoC |
| 知识升级不能变成模型自动改事实 | JSON Schema/Confluent兼容矩阵见R04/R06 | 包版本兼容与真人采用权限是两项问题；当前提案预览不具备批准权 | 原Store/审核/pin复用，先接真实项目Owner权限；新旧同输入回算/旧发布回读，绝不伪造admin |

联网文档证明上游设计和选项，不证明本机收益；独立推演提供待检验机制，也不是既成结果。本轮没有安装新依赖、启用自动Jobs或改线上状态。可复用研究流程：固定问题与输入→查官方实现→匹配已有资产→最窄适配→坏输入与同输入→非作者审→正式回读→保留否决理由。精确工具版本只在被选为运行依赖时锁定，不为调研装全套工具。


## 五、1.2复核：按v2.2吸收机制，不批量引入框架

2026-10-16再次实际打开官方Pro组织、Scrapy架构、yt-dlp、Prefect tasks、datacontract-cli与Crawl4AI深爬文档。公开文档只证明上游声明，不代表本机固定版本已具备或已接入。

| 方向 | 一手材料与可复用点 | 在本项目的决定与最小验证 |
|---|---|---|
| 成熟平台 | [Pro官方](https://github.com/MediaCrawlerPro)：断点、账号池、签名分离、推荐/热搜及各平台差异 | 复用已购固定版原入口；先同输入根/回复/媒体/导出，不按公开最新版替换固定本地版。公开许可限制仍须核预期分发方式，购买不自动等于可再分发 |
| 调度与处理分层 | [Scrapy架构](https://docs.scrapy.org/en/latest/topics/architecture.html)；[Prefect任务](https://docs.prefect.io/v3/concepts/tasks) | 借职责与状态机制，保现中央租约和toolbox Jobs；v2.2的Prefect2选型不是必须迁移。只有现编排达不到已测目标时才隔离试验 |
| 低成本文字稿 | [yt-dlp](https://github.com/yt-dlp/yt-dlp)：字幕、跳过视频下载、格式与音轨选项 | 字幕优先于MP4；同输入记录请求数/下载量/耗时/RSS/全文质量。无字幕是正常分支，不用OCR补作字幕 |
| 契约 | [datacontract-cli](https://github.com/datacontract/datacontract-cli)：ODCS、lint及schema/质量测试 | 先核现JSON Schema合同与版本，缺兼容检查才最窄引入；不照README安装all extras或重写原契约 |
| 权威来源发现 | [Crawl4AI深爬](https://docs.crawl4ai.com/core/deep-crawling/) | 先用标准HTTP/XML解析既有robots/sitemap，深爬只补缺口；发现URL不等覆盖完整或事实已核。以已知名单召回率/重复率/请求预算作最小实验 |

独立推演：当前重复候选与多指针最易增加集成耗时。应减少在制切片，以已知合法输入打通源ACK→处理→发布的最短完整路径；只有功能/质量保持且总耗时、字节或操作数实测改善才合入。反例包括：缺回复但上游completed、知识pin成功但Consumer未切、终端心跳在线但登录unknown。三者均不能报告整链完成。
