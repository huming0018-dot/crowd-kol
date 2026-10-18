# M1 离线四层预算与 detail 准入

本批只实现自有、隔离数据库中的 detail 动作纵切，不请求源站，不接生产或正式迁移，不修改前十个已审文件与旧客户端。代码为 `capture-budget.mjs`；隔离 SQL 为 `tests/fixtures/capture-budget.sql`，须先加载上一批 `capture-receiver.sql`。测试位于 `tests/capture-budget-db.mjs`。

## 与现有生产 guard 的关系

现有 `20261008014820_crowd_v4_safety.sql` 规定最小间隔 30 秒并一次抽样 0–15 秒抖动；账号 detail 日上限 60，还叠加入组年龄折扣、登录/同意、有效租约、全局暂停、验证码/限频冷却、known_note、note reservation 和会话休息。`20261008162901_crowd_v4_idle_session_rest.sql` 已修正足够长空闲后不重复休息。其他 profile 行为还共享旧 detail/会话预算。

**新原型不能替换或绕过这些规则。**它保留最小 30 秒、持久一次抽样、每层单并发、detail 上限不超过 60、任务详情尝试不超过 2，并可额外收紧。但它尚未和旧 guard 的计数、日龄折扣、日界、known_note/profile/冷却状态共用原子控制面。没有生产 guard 桥接、真实授权与原设备验收，禁止给现有源站发送器接入此模块。不能把独立新预算叠加成额外生产额度。

## 可信配置与四层绑定

私有 `capture_budget` schema 保存：

- `tasks`：owner、稳定 task_ref、平台、明确允许的详情 ContentRef 列表、任务桶、平台桶、当前 run/lease_epoch、取消/暂停与服务器到期时间。同 owner/task_ref 唯一，不能创建另一个同名任务记录重置计数。
- `sessions`：owner/actor/session、平台账号引用、设备出口引用、对应账号/设备桶、当前 credential_epoch 与 active。凭据本体不入库。
- `runs`：所属任务/主体/会话、租约和凭证代数、lease_until、来源、parser/normalization 版本和请求字段。
- `buckets`：task、account、device_exit、platform 四种范围的详情/总请求计数、硬上限、并发 slot、最小间隔、持久下一允许时刻、外部封锁时刻、暂停与窗口。平台桶用 `owner_scope=global`，不因参与者变化拆开；任务/账号/设备桶按 owner 与可信引用绑定。
- `actions`：稳定 request_id、请求摘要、run/actor/target、admission_id、实际四桶 ID、一次抽样 jitter、服务器预约/派发截止/消费时刻及状态。

账号/设备/平台 bucket ID 只能从服务器任务和会话配置解析，API 请求不能自选。接收请求后核对每个桶的 kind、owner、subject、platform，不能把同一桶充当两个范围。任务/运行/会话历史绑定有私有 invoker 触发器保护，只允许明确运行状态、当前代数和租约等控制字段变化。

任务、账号和平台名称只是引用，不宣称取得新的采集权限。可信主体仍由外层认证入口提供；本模块再次核对数据库 enabled actor。没有真实 Auth 入口，不能把 fixture 的 principal 对象称为已登录用户。

## 三个动作及精确语义

### `reserveDetail(db, authenticatedPrincipal, request)`

请求只有 `{request_id,run_id,action:'detail',target_ref}`。target_ref 必须是可信任务允许列表中的精确 content 目标；不接受 URL token、客户端时间、预算键或任意 source 参数。search/comment/media 等动作明确拒绝，不存在免费兜底路径。

同一事务中，先锁 actor、可信任务/run/session，再以稳定顺序锁四个桶，验证当前主体、任务、租约、凭证、暂停、时间窗、并发和额度。四层都满足才各预扣一次 detail 和一次总 request、占一个 slot，持久抽样后的等待时刻与 action。任何一层失败或 COMMIT 失败均回滚四层变化。

同 owner/request_id 的相同完整请求只读回原 metadata，不再计费；不同载荷返回 `request_reused`。metadata 始终 `may_dispatch=false`，它不是源站执行授权。真正重试必须使用新的 request_id，占下一次尝试预算；不因换 run、actor、账号或 credential_epoch 清零任务桶。

### `consumeDetail(db, authenticatedPrincipal, requestId)`

第一次消费 reserved 动作，重新核对当前任务/run/session、四桶配置、暂停和服务器窗口。成功时，在同一事务写入既有 `capture_receiver.admissions` 并把动作置 consumed，返回绑定及 `may_dispatch=true`。这是**一次性领取派发准入**。再次 consume 只返回 `may_dispatch=false` 元数据，不再次签发或扣费。

它不控制外部网络副作用，不能强制一个恶意或错误执行器不发第二次请求。未来可信发送器必须仅使用这次领取、紧邻发请求再检查 `dispatch_until`，并纳入取消/源站 guard。没有发送器，本批不能宣称真实源站请求次数已验收。

consume 的 ACK 丢失时不能假定没执行而再次抓取。重放 consume 只返回已消费状态，不再次给 true。是否实际发起/完成由后续可信执行器记录和未知状态对账解决；本批不自动恢复这种未知派发。

服务器重新计算等待边界，延迟 consume 后仍把下一次预约推迟至少 `min_interval_seconds+jitter`，不会因预约很早就让两个实际派发相隔不足原本间隔。jitter 从 reserve 持久记录复用，不重抽。

### `finishDetail(db, authenticatedPrincipal, requestId, outcome)`

- `succeeded / failed`：可信执行器确认 consumed 尝试已结束，释放四层 slot，**不退款**。同结果重复通知幂等。
- `unknown`：已消费动作的执行状态未知，保守保留四层 slot 和计数。不能再通过 finish 把 unknown 伪改为失败来自动释放；需要后续可信对账流程。
- `not_started`：只允许尚未 consume 的 reserved 动作，明确不再派发，释放 slot，计数仍不退。取消或过期后的未消费预约可这样关闭，随后 consume 返回 false。已经 consume 的动作不能标 not_started。

预扣可能因取消、超时或崩溃导致没有真实发起源站请求，但计数不会自动退还；这是保守记录未知消耗的取舍。系统没有自动放过 unknown 的后台 TTL。

## 服务器时间、取消与旧结果

服务器数据库 `clock_timestamp()` 决定所有期限。行锁可能等待，因此在拿齐四桶锁后再统一重验任务、租约和桶窗口。reserve 的 `dispatch_until` 取任务、租约、四桶窗口结束与当前服务器时刻后 30 秒的最早值。consume 重新计算最早截止时间，并把它持久化回 action 后再返回；服务器在预约后缩短任务、租约或桶窗口时，发送器不会收到过长的旧期限。最终 action/admission INSERT 与 consume 状态 UPDATE 都带数据库时间条件；即使 admission 暂时写入后等待到过期，最终确认失败也回滚整个消费事务。

独立预审发现过“锁前计算未过期，等锁后却仍签发”的问题；本批已同时修复 reserve 和 consume，并加入故意延迟桶锁查询的回归。已有代码中的 task/run unexpired 早期检查仅作快失败，最终放行依赖锁后复验及 INSERT 时间条件。

任务取消、暂停、旧 lease_epoch、过期租约、session 停用/凭证代数变化都会拒绝新预约或首次 consume。这些更新与动作检查有数据库行锁互斥。

已合法取得的 capture 使用原 admission/run/epoch，通过上一批 outbox/receiver 独立交付；取消任务不会改写原信封或已成功回执。本批没有让任务取消自动撤回所有历史 admission，也不会完成任务或产生人工奖励。

桶窗口到期直接拒绝；本批不自动按日清零，也不允许换会话刷新窗口。`paused` 与 `blocked_until` 仅提供服务器显式 gate。没有自动推测平台 Retry-After、调大限速或实施自适应风控。

## 测试与证据范围

```sh
CROWD_TEST_TOOLS=/private/tmp/crowd-fix-tools node server/crowd/v4/tests/capture-budget-db.mjs
```

测试实际执行 PGlite SQL 和已审 outbox/receiver，覆盖：

- 第一次失败已计费，第二次真正重试再计费，第三次详情拒绝；四层详情/总请求计数一致。
- 稳定请求重放不再扣费，改载荷冲突；同时 consume 仅一次返回 true。
- 合法更换 actor、平台账号、run、credential_epoch 后，原任务额度仍耗尽。
- 四层任意一层额度不足均无部分扣减；并发 slot、防止免费未知动作、外部时间/预算键注入。
- 取消、暂停、租约过期、旧代数、凭证失效、跨 owner/actor 均拒绝新准入。
- 未消费预约取消后释放 slot 不退款；consume 后 unknown 不释放、不退款。
- 预扣或消费等待期间服务器任务到期，不扣费或不签发 admission；COMMIT 失败无残留计数。
- 文件数据库关闭重开后计数不归零；admission → 合成 capture → SQLite outbox → receiver → 原回执重放闭环。
- 私有 schema/表/函数权限与最小间隔硬约束。

为避免每个离线场景都等 30–45 秒，部分测试使用隔离数据库所有者 SQL 把 `next_allowed_at` 移至过去；同时另测原始等待确实存在。这个 fixture 操作不是公开 API，也不模拟平台真实安全阈值。API 没有客户端时间覆盖参数。

PGlite 并发 Promise 在单连接串行处理；尚未覆盖真实 PostgreSQL 多连接的完整预算模块。文件重开不是断电证明。没有调用源站、没有平台账户登录、没有生产回执；测试使用的 SQLite API 仍为 Node experimental。

## 未完成与接入门禁

旧 guard 原子桥接、真实认证、发送器临发检查/取消、日额度窗口和持久退避、unknown 执行对账、平台暂停恢复、全系统请求路径纳管、最小服务角色/删除政策、正式 CLI 生成迁移以及 M0 原设备真实两条验收均未完成。此批通过不表示 M1 或生产采集完成。
