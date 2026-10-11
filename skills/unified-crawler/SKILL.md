---
name: unified-crawler
description: 使用本机 crowd 统一采集工作台创建多平台任务、跟踪博主、查看和导出已保存资料；复用同一 HTTP 服务与任务状态。
---

# 本机统一采集

定位仓库根目录，再执行 `server/crowd/v4/multiplatform/workbench_cli.py`。这是已运行工作台的 HTTP 客户端，不另建采集器或调度。默认地址 `http://127.0.0.1:45937`，用户指定其他本机端口时传 `--url`。工作台未在线时先说明状态，按该项目 README 启动；不要因超时再发 create/start。

JSON 通过 stdin 输入，输出为 JSON。任务及结果来自与浏览器同一个服务：

```sh
printf '{}' | python3 server/crowd/v4/multiplatform/workbench_cli.py tasks list
printf '{}' | python3 server/crowd/v4/multiplatform/workbench_cli.py results list
```

新建前根据用户目标组装 payload，先调用 `tasks preview`。搜索使用 `targets` 数组；内容/博主链接先调用 `tasks parse_batch`，再用 `targets_by_platform`。平台代码为 `xhs,dy,ks,bili,wb,tieba,zhihu`。用户已跳过的平台不要自行启用。指定内容的裸 ID 必须说明平台；知乎必须是明确类型 URL。

任务输入包括 `platforms, mode, desired_items, max_api_requests, purpose, idempotency_key`；模式为 `search/detail/creator`。搜索每平台内容配置最低20，不擅增总量；没有匹配目标的平台显示等待，其余按预览执行。首次调用生成并保存 idempotency_key，同次创建重试沿用；结果未知先 `tasks list/status` 对账。登录需本人完成，既有会话元数据不能当成登录有效证明。

持续博主观察走 `watchlists preview/create`：`targets_by_platform`、`interval_minutes`、`window_days`、`total_request_budget`、`per_cycle_requests`、`per_cycle_items`、`purpose`、`idempotency_key`。总预算跨周期保留；当前是最新作品观察，不宣称日期完整覆盖。本人停止或未知上一轮不会被调度复活。只预览不会访问来源；创建会使工作台按已授权范围执行。

结果走 `results list/detail/evaluate/export`。评价为 Owner 内容质量，与参与者奖励分开。导出必须 `--output /绝对路径/新文件`，不会覆盖已有文件；同时保存 `.manifest.json`，核对 SHA、固定资料版本、来源与缺失字段。Excel 需工作台 Python 有 openpyxl；本仓库启动器优先使用已装依赖的 bundled Python。

```sh
printf '{"format":"xlsx"}' | python3 server/crowd/v4/multiplatform/workbench_cli.py results export --output /tmp/crowd-results.xlsx
```

`collector` 提供旧采集器 capabilities/list/status/import/start/stop；`media-processing` 提供已有本地媒体的 capabilities/list/status/start/cancel。媒体输入必须是某次导入清单中的文件及本次已有 content_id，不按文件名猜作者或内容归属。OCR/ASR/字幕属于本地派生证据，原文件保留；ASR 需显式本机模型配置，不自动联网下载。分析 CLI 只提供 lookup/status/cancel；外部模型发送仍在现有界面按实际材料和目的地授权。

工程与能力边界读 `server/crowd/v4/multiplatform/README.md` 和 `capability-ledger.json`。本入口是本机机器采集；现有众包身份、outbox、生产 ACK、真人评分和 OTA 仍用原链路。没有生产 ACK 的结果只能报告本地已保存，不能记真人奖励或宣称七平台实源验收通过。

此 skill 可通过直接读取本文件调用；未安装全局发现钩子，不能宣称界面已热注册。
