# 云端机器任务与逐条回执

此增量只用于机器采集。原参与者身份、真人 outbox、人工评价、奖励和签名 OTA 不变。机器记录的外层 `source_kind=machine_api`，内层保留 `mediacrawler_api` 来源；`reward_eligible=false`。

## 接口与集成

- Edge：`POST /functions/v1/crowd-machine`，JSON `{action,payload}`，成功 `{ok:true,result}`。
- 项目使用 active publishable `apikey` 路由。`verify_jwt=false`，由独立 Owner/Worker key 认证；不接受无 key、浏览器 Origin、客户端 owner_scope 或 Owner/Worker 双 key。service_role 仅保留在 Edge。
- 私有配置：运行根目录 `cloud-config.json`，权限 0600。字段 `endpoint`、`project_key`、`owner_key`、`worker_key`；`CloudClient(path,role)` 只发送当前角色 key，不能把完整配置或私有 lease 返回网页。
- Owner：`task_preview/task_create/task_list/task_status/task_control/worker_pair/worker_revoke/worker_list/results`。固定服务端 scope 为 `crowd-owner-main`，不是参与者或 Auth 用户 UUID。
- Worker：`claim/heartbeat/capture/receipt/finish/resume_login`。配对 token 存哈希，受平台、有效期、撤销与当前 worker/run/epoch 约束。
- `CloudOwnerAdapter(client)` 兼容 OwnerTasks 的 `preview/create/list/status/stop/resume/start_scheduler/close`，Watchlists 可复用。所有云任务实际调度由 `CloudWorker` 完成。
- `CloudWorker(root,client,runner_callback,session_selector=None,existing_reader=None)`；原 runner 回调 `(action,payload)` 返回 `{ok,result}`。支持 `start/status/stop/import/account_status`；`account_status` 返回 AccountSessions 的状态元数据，不传凭据。`session_selector(lease)` 返回平台匹配的 session UUID。
- `existing_reader(lease)` 只读指定现有 ResultsStore 记录，允许返回 records 列表或 `{records}`。采样引用必须与 cloud `record_refs` 匹配；原始采集文件不修改，不能触发来源请求。
- `worker.status()` 是安全界面摘要：phase、waiting_login_count、last_error、local_run_id 和 outbox 统计。`state.json` 包含私有执行目标和账户绑定，不能直接暴露。

## 状态与幂等

1. 创建任务由 Edge 校验平台、模式、目标和总预算，服务端生成子任务。search 单平台不足 20 条明确等待，不扩大额度；不支持的媒体只阻塞其子任务。homefeed 支持 xhs/bili，trending 只支持 bili。
2. claim 在事务内预留请求预算，90 秒租约；Worker 先落 claim UUID，再发请求。原 UUID 重放固定原 run，不能返回恢复后的新 run。租约过期和来源结果未知不自动重派。
3. 源启动前先持久化 `dispatching`。启动结果丢失进入未知，不能重复 start。授权或连接不可续时停止当前自有 run。
4. 逐条内容先落 SQLite outbox，再查询旧回执，然后发送。ACK 必须精确匹配 capture_id、hash、task/child/run/epoch、machine 来源和 reward=false。响应丢失保留待回传，通过 receipt 找回原 ACK。
5. cached outbox 在最后租约后的 24 小时内可投递，不能续租或授权新采集。已收记录的原 ACK 在同有效 worker 下可重放；撤销 token 后失效。
6. finish 只引用已 ACK 的 capture，正文数量按同 child 跨 run 的实体去重累计。无正文和不足目标量保留 waiting/partial，不能用进程退出 0 冒充完成。
7. 已知来源终态可按注册 Worker 上报的 Python HTTP attempts 释放未用预算；未知结果保留整个预留预算。此计数不涵盖浏览器资源、平台后台实际成本，也不是密码学证明。
8. 登录所致终态记录原 session、账户哈希、generation、local run。旧 outbox 全 ACK 后进入持久登录等待列表，其他平台继续。仅同账户/同代次、旧 run 授权、authenticated/resumed、login_verified、180 秒内核验可 `resume_login`；服务端再核原 worker、原 binding、父任务状态和剩余额度。Owner 继续不能绕过该门禁。账号切换必须走原 AccountSessions 显式确认流程。
9. Owner stop 只停止其任务。Worker 保留其登录上下文，但停止/暂停项不阻塞其他任务；Owner 明确继续后仍需新鲜同账号核验，不能绕过恢复门禁。未知状态、已耗尽预算和不可确认账户均需明确处理。

## 新增 SQL 与部署

`cloud_machine.sql` 是可评审的新增 SQL 源。使用 `supabase migration new crowd_machine` 生成迁移文件后复制最终审查版本；不能自行编造时间戳迁移。新增私有 schema `crowd_machine` 的 workers/tasks/children/claims/captures，启用 RLS、撤销 PUBLIC/anon/authenticated 权限，仅 service_role 可执行 `public.crowd_machine_rpc`。RPC 使用 SECURITY INVOKER 和固定空 search_path。Owner hash 的部署占位为 `__CROWD_MACHINE_OWNER_SHA256__`，只替换哈希，原 key 留本机 0600 配置。

迁移/Edge 的实际部署、云数据库小试和正式上线由统筹执行。SQL/Python 隔离通过不等于生产已部署，也不等于七平台重新实采。`existing_saved` 小试证明旧内容进入云库与逐条 ACK；不得说成新的来源采集。

2026-10-11已实际部署：项目bdwrhshgdeghgyzwpxnl，crowd-machine ACTIVE v1，迁移历史20261011033423/crowd_machine。CLI最初生成20261011031941；MCP执行后本地文件已按实际远端历史重命名为20261011033423_crowd_machine.sql，SQL内容不变，没有repair历史或重跑DDL。后续先用supabase migration list及db push --dry-run核对已有迁移，再生成新迁移。历史任务6f8bf0c6收到2ACK，新采首页推荐任务6287526d收到1ACK、2API尝试。完整证据见工作区outputs/unified-cloud-execution-2026-10-11与reviews/49；不代表七平台全量验收。

## 测试与边界

- `CROWD_TEST_TOOLS=/private/tmp/crowd-fix-tools node tests/cloud-machine.mjs`：隔离 PGlite 真 SQL 与 Edge 调用，覆盖鉴权/越权、角色权限、幂等、租约、逐条 ACK、哈希冲突、停止、撤销、七平台目标、推荐模式、同账号恢复/预算/旧 ACK/旧 claim。
- `python3 -m unittest test_cloud_sync -v`：耐久状态、丢 ACK/claim/start、禁止重采、existing_saved 零 start、账号门禁、登录等待重启和其他平台推进、配置权限与真实 loopback HTTP。无真实来源/模型请求。
- 新 envelope 为 `crowd-machine-capture-v1`，不修改旧参与者 capture 格式。UTF-8/codepoint key 排序、安全整数、控制字符 `\\u00xx`、拒绝重复 JSON key、孤立 surrogate、过深/过大 payload。云端 interval_seconds 目前只收整数秒；非整数必须显式改协议，不能隐式舍入。
- 单个 capture ≤256 KiB，finish ≤2000 capture IDs，outbox 一轮最多2000条。公开任务列表最多200个、云结果最多2000条；当前未提供完整大规模分页。范围扩大前应实现游标分页和冷热结果存储。
- Worker 是当前操作者配置的执行者；本轮没有多租户 Auth 映射、第三方受限 SignSrv、代理轮换、自动下载私有模型或生产设备全平台验收。
