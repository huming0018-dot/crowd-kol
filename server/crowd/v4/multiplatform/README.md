# 本机多平台采集工作台

这是 Crowd 自有本地桥和工作台。它调用用户另外安装的 MediaCrawler，不包含、复制或修改 MediaCrawler 源码，不接 Crowd 真人奖励、旧采集任务或生产数据库。

当前核对的外部项目：`/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler`，HEAD `098cae5a00023ad55f00ca9665d22d0f260e2ab2`，本地有 5 个修改文件。不是可无条件再发行的普通宽松许可依赖：其 LICENSE 为 **NON-COMMERCIAL LEARNING LICENSE 1.1**，商业使用须版权所有者书面许可。桥不会自动取得该许可；选择 `licensed_use` 和填写授权依据只是用户声明，未独立核验。

## Owner 使用顺序

1. 双击“打开工作台.command”，点击“＋ 新建任务”。选择关键词、指定内容或指定博主，勾选多个平台。
2. 输入共享关键词，或粘贴链接/导入 `platform,target` CSV，设置所有平台的总数量与接口总额，再预览分配。系统按平台自动分配；目标缺失、媒体不支持或预算不足的子项显示原因，不暗增额度。首次登录由本人在独立浏览器完成；系统尝试选择本平台空闲历史会话，已有会话不等于登录有效。
3. “指定博主”可开启持续跟踪，设置间隔、观察窗口与整个计划接口总额。总额跨周期保留；手动停止、上一轮未知或失败不自动复活。当前为最新作品观察，不保证平台日期筛选完整覆盖。工作台关闭期间不调度，重新打开后恢复核对原任务。
4. 首页看每个平台的实际状态，停止或继续未完成范围；结束后点“查看结果”阅读正文、评论，下载已保存媒体或本地派生词云。零条结果不会算采集成功。父任务的子进程只在父卡中显示，避免重复任务卡。
5. “资料库”查询平台、作者、时间、业务标签与记录类型；保存正文版本和指标观察、查看关联评论、评价，导出 JSON / JSONL / CSV / Excel 与来源清单。业务评价与原参与者奖励分开。后台导入也会保存资料；写库失败显示未完成导入，只重试既有结果，不重新访问源站。

此页管理本机机器采集作业。原众包身份、outbox、真人评分、生产回执和OTA使用原链路；本轮没有接通机器结果的生产接收器，也未把两条生产DOM ACK冒充这套统一流程的验收。

## 复用原采集目录与 Linux worker

已有各平台采集目录可用重复的 `--collector-root /绝对路径` 登记，配置保存在工作台 root 内，重启继续使用。会话和 run 必须唯一归属；重名冲突拒绝执行，不猜选。登记、list/status 不复制或读取浏览器凭据，不启动来源请求。`import` 会更新旧 run 的派生 normalized 缓存，因此它不是原目录纯只读操作。

本轮 workspace 交付启动器 `outputs/unified-crawler-implementation-2026-10-11/启动统一工作台.command` 复用已启动的45937服务和已登记目录；通用“打开工作台.command”仍采用原默认 root。具体 root 与历史数据导入证据见本轮交付 README。

Linux 常驻 worker 的启动、隔离与验证命令见 [docker/README.md](docker/README.md)。桥、外部 MC、Linux依赖环境与 runtime 分离；实际通过替身任务完成/停止/导入及删除容器后重建恢复。本轮没有提供七平台已登录 Linux 环境、安装 MC 全部依赖或开放远端服务，不能把容器生命周期通过称为七平台生产部署完成。

## 同一 HTTP / CLI / Skill 入口

`dashboard.py` 是任务服务；`workbench_cli.py` 是其标准库客户端，不另起调度。浏览器和CLI看到相同任务、预算与结果版本。CLI需要工作台已运行，地址仅接受带端口的本机HTTP，禁止重定向/代理。请求 JSON 由 stdin 输入；创建重试沿用同一 idempotency_key，响应未知先 status/list，不重复创建。

```sh
printf '{}' | python3 workbench_cli.py --url http://127.0.0.1:45937 tasks list
printf '{}' | python3 workbench_cli.py --url http://127.0.0.1:45937 watchlists list
printf '{}' | python3 workbench_cli.py --url http://127.0.0.1:45937 results list
printf '{"format":"xlsx"}' | python3 workbench_cli.py results export --output /tmp/crowd-results.xlsx
```

支持 tasks、watchlists、results、collector、media-processing、analysis（lookup/status/cancel）。导出要求新路径，文件与manifest均0600、核对SHA；不覆盖旧文件，碰撞/写入失败清理本次创建的半件。Excel需要工作台Python有openpyxl，Mac启动器优先使用本机已有bundled Python。

项目技能在 `skills/unified-crawler/SKILL.md`；直接读该文件执行即可。本轮已通过frontmatter校验和同HTTP CLI实际调用；未声称全局安装或界面热注册。

## 已下载媒体的本地处理

任务结果的“媒体 / 词云”中，原媒体可以下载或点“本地 OCR / 转写”。选择本次已采内容建立明确关联，后台验证文件属于本次导入清单，不根据文件名猜归属。词云为本地派生产物，单独标记，不冒充原图。

`media_jobs.py` 复用现有 postprocess：macOS Vision OCR、已有字幕导入、显式本机ASR。处理输入做SHA快照，原文件保留；状态与产物0600，单并发、可取消、同输入和处理器版本缓存。重启后未知任务需要核对，不偷偷重复处理。转写文本保留原媒体SHA、时间信息和待人工校对标记。

ASR需设置 `CROWD_LOCAL_ASR_MODEL`、`CROWD_LOCAL_ASR_PYTHON` 指向已有模型和对应Python，不自动下载模型。本次上限沿现有实现：60秒/25MiB音频，180秒处理时限；长视频自动切段未实现。本轮实际处理的是本地VTT，不是语音质量或真实图片OCR验收。

## 正文与评论分析

在“查看结果”的单篇内容下点“分析正文与评论”。先读取本地已保存分析或展示本次材料范围；仅在明确点击“发送所选文字并分析”后，将该版本的文字交给本机已登录 Codex CLI 对应的模型服务。不会重新采集、传浏览器凭据或改真人评分。

产物包括文本结构、带段落引用的原文声称与可借鉴方法、逐条评论标签、程序计算的统计、样本范围和缺口。正文或视频简介不冒充转录，标题素材只能做标题分析。报告始终标为尚未人工核验的模型分析，评论情绪对象不能当餐厅满意度或全部粉丝画像。

本机需要已有 Codex CLI；桥不安装模型服务、读取认证文件或采购服务。CLI 使用既有身份，忽略用户扩展配置，关闭 shell、插件、MCP Apps、浏览器、图片及其他工具入口，使用 read-only sandbox、临时会话和严格 JSON schema。后台再次验证评论身份、文本摘要、段号和标签分母，拒绝工具事件和错误结构。模型不可用时给出登录、额度、网络、环境或接口失败状态，已有采集结果不受影响。

每次处理一篇内容及最多200行评论、合计50000字，超限明确拒绝而非静默截断。缺失、敏感或截断评论单列排除；空文字保留未标。已有材料的重复身份冲突先处理，不混算。任务只并行一个，超时180秒可取消；同输入摘要、提示版本与CLI版本命中已完成产物，不重复请求。它尚不是跨模型全局计费幂等服务；CLI默认模型后台变化没有独立版本记录。UI中断后结果不明确时不自动重试。

分析文件保存在工作台root下的 `analysis/<job_id>/`，输入/状态/结果以0600保存。原始模型输出与临时事件在发布完成/失败状态前清理；错误诊断只在内存分类，不输出原消息或认证信息。命令行测试也需要显式 `--allow-model-transfer`，默认不会外发材料。

本次验证记录见 workspace 的 `outputs/analysis-integration-2026-10-10/` 和独立审查 `outputs/mediacrawler-execution/reviews/33-analysis-product-review.md`。隔离fake provider测试和浏览器入口确认不替代真实模型成功。

## 可运行能力与边界

| 平台值 | 搜索 / 指定内容 / 创作者内容 | 一级评论 | 回复开关 | 媒体下载 | 已知限制 |
|---|---|---|---|---|---|
| xhs | 上游真实入口已接 | 已接 | 已接 | 已接 | 带 `xsec_token` 的 HTTPS 正常定位链接可本地使用；无可用定位符的详情可能失败 |
| dy | 上游真实入口已接 | 已接 | 已接 | 已接 | 登录、风控及分页终点未实机全量验收 |
| ks | 上游真实入口已接 | 已接 | 已接 | 已接 | 当前 store 不保存 parent ID，导入标记 missing_upstream，不伪造完整树 |
| bili | 上游真实入口已接 | 已接 | 已接 | 已接 | 支持creator视频/动态/两者，动态单独ID与类型；关系链未实现，上游描述可能已截断至500字 |
| wb | 上游真实入口已接 | 已接 | 已接 | 已接 | 当前上游回复实现主要使用响应内附带回复，不能称完整回复分页 |
| tieba | 上游真实入口已接 | 已接 | 已接 | **不支持** | 上游有 browser HTML/fetch/goto，非纯 API；媒体请求明确拒绝 |
| zhihu | 上游真实入口已接 | 已接 | 已接 | **不支持** | 当前 creator 主要为 answers；桥补 CLI 未绑定 creator URL 列表的内存配置；详情需完整 answer/article/zvideo URL |

“已接”指可调用真实外部入口和参数，不表示 7 平台已经登录并采集验收。真实上游 21 组 CLI 参数解析/类绑定测试不访问平台；21 组生命周期测试使用自有替身，不冒充平台结果。

来源标记 `source_kind=mediacrawler_api` 是外部机器执行通道；每条结果额外标记 `upstream_transport=platform_dependent_api_or_browser_html`，不声称所有上游内容均来自 API，更不标记真人 DOM。始终 `reward_eligible=false`。当前导入内容、动态、评论及已落盘媒体/派生产物清单，并投影可取得作者身份；上游匿名作者明确标记，不能逆推真实身份。不声称取得粉丝画像。

## 启动与接口

工作台由同目录 `dashboard.py` 提供，仅绑定本机 loopback。双击 `打开工作台.command`。配置自备 MediaCrawler 路径，选择用途，再在可见浏览器由本人完成正常登录或验证码。首次登录不能无头；复用工作台自己的隔离 session 后可以勾选后台运行。后台再次发现扫码登录提示会停止并返回 login_required，切回可见模式由本人登录。默认 Playwright 浏览器未安装时，Mac 会使用已安装的系统 Google Chrome，但仍使用本桥的隔离资料，不连接用户现有窗口。

标准库 CLI（桥本体 Python 3.9+；外部执行器使用其自己的 `.venv/bin/python`）：

```sh
python3 mc_runner.py --root /absolute/local/runtime --mc-root /absolute/MediaCrawler capabilities
python3 mc_runner.py --root /absolute/local/runtime --mc-root /absolute/MediaCrawler start < request.json
```

所有动作读一个 JSON stdin，返回一行 `{ "ok": true, "result": ... }`；固定错误为 `{ "ok": false, "error": "code" }`。不返回原始异常、Cookie 或平台 URL。

`start` 请求示例：

```json
{
  "platform": "bili",
  "mode": "creator",
  "targets": ["https://space.bilibili.com/123"],
  "purpose": "noncommercial_research",
  "max_items": 20,
  "max_comments": 20,
  "comments": true,
  "replies": true,
  "media": false,
  "headless": false,
  "max_api_requests": 20,
  "timeout_seconds": 600
}
```

可选 `session_id` 为先前返回的 UUID；不传就新建隔离资料。`headless:true` 要求显式提供已存在的同平台 session，但“存在”不证明已登录或登录仍有效。`purpose:licensed_use` 还要求非空 `authorization_ref`，不自动验证授权。

`targets` 最多 10 个：search 是关键词；detail/creator 是平台 ID 或该平台 HTTPS URL。短链仅接受实际已绑定的上游支持形态，其余明确拒绝；B站详情要求BV，av不会猜转换。禁止外站、URL userinfo、端口、fragment 与登录凭据参数。XHS `xsec_token` 是此桥特准的本地导航定位符，仅在 0600 manifest 和子进程内存使用；不进入 OS argv、状态、标准化导出和日志。不会导入或替换原 MC 的登录凭据。

`status` / `stop` / `import` 输入 `{ "run_id": "UUID" }`；`list` 与 `capabilities` 输入 `{}`。

- start 返回 run_id、session_id、starting。
- status 返回平台、模式、阶段、api_attempts、固定 reason 与更新时间。running/waiting_login/collecting/comments/media 是上游固定日志关键词分类的提示，不是来源成功证据。
- stop 写停止意图。监管进程及子进程都检查停止；不根据持久 PID 重新找任意进程杀掉。
- import 只允许已结束或监管丢失且 session 锁已释放。返回 records、media、summary、来源、文件 SHA 与 normalized_path。
- list 返回最近最多 100 个 runs。

可选 `start_page`（1–10000）、`interval_seconds`（0–300；未给时保留上游默认）。`wordcloud:true`需启用评论，调用外部已有词云器；资源缺失只标派生失败，正文照常保存。B站 `platform_options.creator_sections` 可设 `videos/dynamics` 或两者，纯动态不支持评论/媒体开关；日期搜索参数与画质支持已按实际上游配置接入。实际日期覆盖和视频质量尚待真实样本验收。

## 限额、停止与状态真实性

`max_items` 只是上游配置，**不是通用的源站硬数量上限**。部分 search 在上游把小于 20 的值提升到 20，因此本桥拒绝 search 的 max_items < 20。某些 creator 会分页取更多，不能把导出截断假称源站限量。

独立硬边界为：默认 20 次 Python `httpx/requests` 发送调用（1–500 可显式设置）、并发配置 1、默认 600 秒总运行时限（30–1800）。计数在外调前增加，失败也计入。此计数**不包含浏览器静态资源、浏览器内部 fetch/goto、服务端重定向的所有实际网络包**，并非旧众包 guard 或完整平台请求预算。浏览器路径仍受总时限约束；不自动共享或重置旧众包配额。

媒体默认关闭；开启后：单文件操作系统上限 25 MiB，Python HTTPX 单响应 25 MiB/累计解码响应 100 MiB；输出目录 100 MiB 巡检停止（500ms 周期，可有短暂超量）。HTTPX 响应计数可能保守重复计算，不等于唯一媒体大小。浏览器 profile 和缓存不计入输出目录总额；单文件上限仍随子进程继承。不提供无限媒体下载或完整媒体覆盖承诺。`.part` 不进入可下载媒体清单。

结束 `completed` 只表示外部进程 exit 0，**不代表有内容、不代表源站完整覆盖**。上游可内部吞掉某些错误，因此必须结合导入数量/rejected_records 判断。任何结束结果 coverage 都为 unverified。失败/停止可导入已落盘部分，不清空队列，不自动重跑。

监管进程心跳超过 8 秒缺失则状态 interrupted_unknown；子进程独立监视本次监管 PID 的父子关系，监管死亡时停止自己的新进程组。不会根据老 PID 接管别的进程。未知来源动作不会自动重试。停止过程中已经发出的网络请求无法撤回。

## 隔离与文件

```
runtime/
  sessions/<session UUID>/browser_data/   # 仅本桥自己的登录资料
  runs/<run UUID>/manifest.json          # 0600，本机含原始输入定位符
  runs/<run UUID>/status.json
  runs/<run UUID>/phase.json             # 固定阶段/计数，不含原日志
  runs/<run UUID>/output/                # 上游原始输出，可能含定位符，仅本机
  runs/<run UUID>/normalized.json        # 白名单投影，可经本机UI导出
```

每 session 持有文件锁，防止两个运行同时使用同一隔离 profile；不同 session 不导入彼此凭据。每 run 输出独立。只通过 symlink 引用外部只读 JS/GraphQL 资源；Python 禁止生成外部 bytecode；缓存放入自己的 run。原始上游 stdout/stderr 不保存，阶段分类不会回显内容。

normalized 不是通用 DLP：只投影显式字段、不带原 URL/用户个人资料/Cookie/token；正文发现敏感参数赋值会标记 withheld_sensitive 并置 null。正常正文不凭空改成新事实。正文超过 24000 字会明确 text_truncated；时间/计数保留 reported 语义，缺字段 null。父评论缺失标记 missing_upstream，不补假 ID。上游已做的默认零值/摘要截断无法从保存结果逆推出原始完整性。

## 验证命令

```sh
PYTHONPYCACHEPREFIX=/private/tmp/crowd-mc-pycache python3 test_mc_runner.py
python3 -m unittest test_mc_runner test_dashboard test_analysis test_owner_tasks test_results_store test_watchlists test_unified_dashboard test_workbench_cli test_collector_roots
```

测试覆盖实际上游 21 组 CLI、7 真实 Crawler 类绑定（不访问来源），自有替身 21 组进程/输出、停止、同 session 互斥与复用、发送前限额、响应字节限额、平台/秘密参数边界、媒体清单。独立审查另复现监管丢失并复核子进程停止。发布时以 reviews 下的最终 SHA 与审查报告为准。

待确认：适用授权凭据；各平台本人登录；真实 source 回执与评论树/媒体清单验收；平台变化导致的上游错误；跨机器执行及服务器统一台账均未接入本桥。

## 参与者Pro回执进入现有素材处理

此入口连接已购Pro参与者的数据与现有工具柜，不修改平台请求、解析、评论或媒体核心。当前实现及运行证据看固定`docs/HANDOFF.md`，不能从本节推断所有平台或两设备已经验收。

数据流为：中央`participant_pro_receipts` Owner只读动作 → 原`postprocessing_runs/postprocessing_contexts`耐久列表 → `AutomaticMaterials`原单子进程 → 原固定工具柜的`Jobs`与`Stages.clean/score/audit` → `Consumer`按任务发布。没有第二套队列或评分器。输入适配只支持实际已接通的小红书Pro正文协议；其他模式保留需求，不能冒已接通。

- `pro_ack_snapshot.py`核原整数任务ID、真实subject/installation/dispatch、request/proof、canonical原文、hash及来源；不伪造machine UUID、child、租约或finish_verified。`received/verified`原样保留，不转成人工奖励；`rejected`明确拒绝，通用人审撤回同步尚未实现。
- `participant_material_feed.py`将完整已确认分组以0600不可变文件落在`data-products/participant-pro-ack-inputs/<sha>.json`，之后队列与游标同次原子保存。中央now()不是提交顺序，游标只用于一轮遍历；尾页清空游标，下轮完整复扫。相同ACK集合直接复用原ready状态，不重采来源或重复运行Jobs。
- `material_auto_worker.py`驱动现`material_bridge.py`；Pro需要原11键配置加`pro_snapshot_sha256`，并在生成和读取时核代码、pack、toolbox及输入pins。升级采用器须同时更新配置路径与SHA，不能仅修改Git HEAD。
- Pro发布保存在自己的ready状态`publication_pointer`中，**不替换**原`material-runtime.json`或`domain-runtime.json`。`/materials/participants`为正常资料库中的入口；每任务可查看HTML、JSON、JSONL、CSV。`participant_material_delivery.py`只读现Consumer输出，不触发采集或构建。
- 完成任务不代表来源覆盖全量。素材分只衡量可追溯性，不是内容质量、餐厅口味、知识批准或参与奖励。历史已确认回执回填不冒新增来源；snapshot-file的crawl阶段不冒外部HTTP访问。

现中央与本地均有限额且拒绝超限，不截组冒成功：每页最多8组、单组最多2000条/8MiB；本入口当前逐组读取，Owner Pro响应专用上限8MiB加包络、100万JSON节点，其他CloudClient动作维持原限额。全量复扫成本随组数增长；需要扩大规模时，再以实际数据实现可证明的提交版本/增量协议。

有私有真实fixture时运行`test_participant_material_*.py`，设置`CROWD_PRO_ACK_FIXTURE`和`CROWD_TEST_MATERIAL_AUTO_CONFIG`；缺fixture时集成用例会明确skip，不能称真实验收。SQL/Edge回归入口是`tests/participant-pro-owner-feed-{db,api}.mjs`，DB测试需已有`CROWD_TEST_TOOLS`中的PGlite。不得提交fixture、浏览器资料、Pro私码或凭据。

已知边界：同context已ready后不会因换pack/config自动重算；需要明确的重新处理/采用流程。重启恢复、上线后新ACK、异机Pro素材消费及通用人审撤回应单独验收；旧六店匿名分享授权不能推定为新Pro素材的匿名分享授权。

## 分享参与者已处理素材

资料库中的“分享参与者素材”只列出已就绪的任务批次。Owner 选择批次后，显式生成链接：先把同一 Consumer 的 HTML/JSON/JSONL/CSV 保存到原私有发布桶，再逐格式回取核对，最后签发原有15分钟免登录链接。原六店领域入口和账号授权消费路径保留。正文、来源引用和跟踪编号会进入分享文件；媒体仅保留原引用，不包含媒体文件。

`publication_share` 原 `{request_id}` 协议不变。Pro 请求严格为 `{request_id,pro_key,operation}`，操作为 `publish`、`verify` 或 `links`。后端从原 ready context 和 ACK group 计算项目，并逐条匹配 receipt；客户端不能指定路径、项目或哈希。一个批次一个不可变包，沿用250000字节总限额。未知发布由包级 intent 阻止重传；“核对云保存”只读回取，确认后需再次显式生成链接。关闭或切换批次不会继续签链，链接不会自动续签。

实现入口：`publication_share.py`、`publication_pro_share.py` 和 `results-ui.js`。私有 intent 与包在运行根目录 `publication-pro-intents/`、`publication-pro-bundles/`；其中不保存签名链接。消费页为原 `china-travel-food/app/pages/materials.tsx`，仍通过私桶签名 GET、字节数、SHA256 和实际报告项目绑定后展示。接受 Pro 项目格式本身不是授权。

回归：在本目录运行 `CROWD_MP_ROOT="$PWD" python3 -m unittest test_publication_pro_share`；在仓库根运行 `node server/crowd/v4/tests/publication-pro-share-ui.mjs server/crowd/v4/multiplatform/results-ui.js`。Next 真实保存文件回归需要明确 `CROWD_SAVED_EXPORTS` 或测试第四参数，不将私有报告捆入源码。代码采用、服务运行、云保存、签链和异机业务验收分别记录在固定 HANDOFF；不要凭本节认定已经上线。
