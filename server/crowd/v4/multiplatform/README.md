# 本地 MediaCrawler 执行桥

这是 Crowd 自有本地桥和工作台。它调用用户另外安装的 MediaCrawler，不包含、复制或修改 MediaCrawler 源码，不接 Crowd 真人奖励、旧采集任务或生产数据库。

当前核对的外部项目：`/Users/hubowen/WorkBuddy/2026-10-08-22-53-19/MediaCrawler`，HEAD `098cae5a00023ad55f00ca9665d22d0f260e2ab2`，本地有 5 个修改文件。不是可无条件再发行的普通宽松许可依赖：其 LICENSE 为 **NON-COMMERCIAL LEARNING LICENSE 1.1**，商业使用须版权所有者书面许可。桥不会自动取得该许可；选择 `licensed_use` 和填写授权依据只是用户声明，未独立核验。

## Owner 使用顺序

1. 双击“打开工作台.command”，首页查看本机采集任务；首次没有任务时点“新建采集”。
2. 选择平台、采集对象和内容。首次使用会打开独立浏览器供本人登录；已有登录资料可直接从列表选择，无需复制编号。
3. 在首页看“等待登录 / 采集中 / 已停止 / 本轮结束”等状态。等待登录时，到采集器打开的浏览器完成登录；不要把等待当作已开始采集。
4. 任务结束后点“查看结果”，阅读内容与评论、下载JSON或实际落盘媒体。停止与失败的任务也可查看已保存部分；零条结果不表示成功采到内容。
5. 执行器目录、平台能力与使用依据在“设置”；请求计数、内部编号等在技术详情。高级数量仍沿用上游限制，不保证取得配置数量。

此页管理本机MediaCrawler作业；原众包参与者、评分和云端KOL台账仍在原系统，尚未合并成同一后台。

## 可运行能力与边界

| 平台值 | 搜索 / 指定内容 / 创作者内容 | 一级评论 | 回复开关 | 媒体下载 | 已知限制 |
|---|---|---|---|---|---|
| xhs | 上游真实入口已接 | 已接 | 已接 | 已接 | 带 `xsec_token` 的 HTTPS 正常定位链接可本地使用；无可用定位符的详情可能失败 |
| dy | 上游真实入口已接 | 已接 | 已接 | 已接 | 登录、风控及分页终点未实机全量验收 |
| ks | 上游真实入口已接 | 已接 | 已接 | 已接 | 当前 store 不保存 parent ID，导入标记 missing_upstream，不伪造完整树 |
| bili | 上游真实入口已接 | 已接 | 已接 | 已接 | 强制 creator 视频分支，不进入关注/粉丝/动态抓取分支；上游描述可能已截断至 500 字 |
| wb | 上游真实入口已接 | 已接 | 已接 | 已接 | 当前上游回复实现主要使用响应内附带回复，不能称完整回复分页 |
| tieba | 上游真实入口已接 | 已接 | 已接 | **不支持** | 上游有 browser HTML/fetch/goto，非纯 API；媒体请求明确拒绝 |
| zhihu | 上游真实入口已接 | 已接 | 已接 | **不支持** | 当前 creator 主要为 answers；桥补 CLI 未绑定 creator URL 列表的内存配置；详情需完整 answer/article/zvideo URL |

“已接”指可调用真实外部入口和参数，不表示 7 平台已经登录并采集验收。真实上游 21 组 CLI 参数解析/类绑定测试不访问平台；21 组生命周期测试使用自有替身，不冒充平台结果。

来源标记 `source_kind=mediacrawler_api` 是外部机器执行通道；每条结果额外标记 `upstream_transport=platform_dependent_api_or_browser_html`，不声称所有上游内容均来自 API，更不标记真人 DOM。始终 `reward_eligible=false`。当前导入内容、评论及已落盘媒体清单；不导入个人创作者资料/粉丝画像。

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

`targets` 最多 10 个：search 是关键词；detail/creator 是平台 ID 或该平台 HTTPS URL。短链域名未接自动展开，请使用原平台完整链接。禁止外站、URL userinfo、端口、fragment 与登录凭据参数。XHS `xsec_token` 是此桥特准的本地导航定位符，仅在 0600 manifest 和子进程内存使用；不进入 OS argv、状态、标准化导出和日志。不会导入或替换原 MC 的登录凭据。

`status` / `stop` / `import` 输入 `{ "run_id": "UUID" }`；`list` 与 `capabilities` 输入 `{}`。

- start 返回 run_id、session_id、starting。
- status 返回平台、模式、阶段、api_attempts、固定 reason 与更新时间。running/waiting_login/collecting/comments/media 是上游固定日志关键词分类的提示，不是来源成功证据。
- stop 写停止意图。监管进程及子进程都检查停止；不根据持久 PID 重新找任意进程杀掉。
- import 只允许已结束或监管丢失且 session 锁已释放。返回 records、media、summary、来源、文件 SHA 与 normalized_path。
- list 返回最近最多 100 个 runs。

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
python3 test_dashboard.py
```

测试覆盖实际上游 21 组 CLI、7 真实 Crawler 类绑定（不访问来源），自有替身 21 组进程/输出、停止、同 session 互斥与复用、发送前限额、响应字节限额、平台/秘密参数边界、媒体清单。独立审查另复现监管丢失并复核子进程停止。发布时以 reviews 下的最终 SHA 与审查报告为准。

待确认：适用授权凭据；各平台本人登录；真实 source 回执与评论树/媒体清单验收；平台变化导致的上游错误；跨机器执行及服务器统一台账均未接入本桥。
