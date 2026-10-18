# 隔离服务器页台账与恢复建议（M1 第五批）

## 结论与运行边界

本批新增服务器持久页清单、按服务器 capture 回执计算的连续 ACK 水位，以及同 actor、同平台会话、不同 run 的受控只读恢复建议。没有 HTTP/Auth 接口、生产迁移、真实执行器、源站请求或自动交接。真实浏览器的清单导出与传输尚未接入；集成测试从同一合成页构造两侧数据，保持 cursor/coverage/items 一致。此前合同、receiver、SQLite outbox、共享预算文件不修改。

`tests/fixtures/capture-checkpoint.sql` 仅为隔离实验 SQL，依赖 receiver、budget 两份 fixture。数据库服务调用方必须先完成真实身份认证，再传入 `authenticatedPrincipal={owner_scope,actor_ref}`；禁止由请求 body 推导 principal。测试使用数据库所有者写可信任务/run/恢复授权，不能当成生产认证已经接通。

## 接口

三接口均返回 `{data,error}`，失败只返回固定错误码，不回显正文、SQL、凭据。

- `submitCheckpointPage(db, principal, manifest)`：接收不可变历史页声明；返回服务器算出的 `manifest_hash` 与刷新后的 checkpoint。
- `readCheckpoint(db, principal, runId)`：返回可信 run binding、binding hash 与连续 ACK 台账。会事务刷新缓存水位，语义是读取服务器已接收证据。
- `readRecoveryAdvice(db, principal, grantId)`：读取明确服务器授权的源 run 台账，核对目标当前运行条件，返回候选元数据和阻塞原因。始终 `automatic_resume_allowed=false`。

`db` 复用已有 `query` / `transaction(callback)` 接口。没有新依赖。每次事务首先锁定仍启用的 actor；停用该 actor 的更新与事务互斥。run/task/session/grant 行锁保护授权配置；恢复时在台账查询之后以数据库 `clock_timestamp()` 再验证 grant 与目标 lease/task 时间。

## 清单合同

`manifest_version=1`，`binding` 必须与服务器登记的完整 binding 相同。包括 owner、actor、平台 session、task ID/ref、run ID、lease/credential epoch、platform、source kind、parser/normalizer、requested fields，以及服务器 `allowed_targets` 的摘要。不能把另一个 KOL/task 的游标当成本任务进度。

`page` 精确字段：

| 字段 | 约束 |
| --- | --- |
| `page_id` | 稳定 UUID；重传保留 |
| `sequence` | 1–1000 的整数；不比较 opaque cursor 排序 |
| `previous_page_hash` | 第一页为 null，后页为上一页服务器定义的完整清单 SHA256 |
| `cursor_ref` | null 或 `cursor:UUID`；没有 URL、token、平台凭据 |
| `reported_coverage` | `complete` / `partial`，仅客户端声明范围 |
| `stop_reason` | complete 时 null；partial 时 partial_failure / partial_capture / truncated_by_budget / source_incomplete |
| `items` | 最多 20 项；capture 或显式 failure，不接收自报 ACK |

Capture 项只有 `kind,capture_id,envelope_hash`。Failure 项只有 `kind,item_ref,error_code`，`item_ref=item:UUID`，错误码白名单。完整清单使用既有 `canonicalJson`，摘要为 SHA256(`crowd-checkpoint-v1\n` + canonical JSON)。键序不影响摘要。`(owner,run,sequence)` 与 page ID 均唯一；同摘要重放，不同摘要 `page_reused`。每个 capture 在同 run 中最多列一次，避免多个页重复计数。

服务器可先收到页，后收到 capture；也可反过来。允许乱序页落盘，已知相邻页必须 hash 链一致。页、全部 items、水位更新在同一事务；COMMIT 失败不得留下部分页。

## ACK 与覆盖语义

刷新从序号 1 起逐页核对服务端 `capture_receiver.captures`。capture hash、身份/session/task/run/epochs、目标范围、平台/source、parser/normalizer/requested fields 均须匹配；存储 receipt 的 received 状态、hash、capture/run/epochs/admission 也须对应。调用者填写的 ACK 不参与判断。

缺页、缺 capture、hash/绑定不符、failure 均卡住连续水位。空页返回 `empty_page_unverified`，不能因为零项均存在就承认任意游标。没有失败项处置/补采协议，本批不会删除失败项或假装其成功；必要时后续另立获授权的修复 run。

`partial_capture` 表示本页字段不全：所列条目的交付台账可以推进，但 reported coverage 永久保留 partial。`source_incomplete`、`truncated_by_budget`、`partial_failure` 表示发现仍有缺口：本页所列 capture 全部 ACK 后记录该页的交付状态，停止跨越后续页；恢复候选游标为空。后面的 complete 页不能抹去任何已知 partial。底层 capture 自身为 partial 也会使 reported coverage 变为 partial。

所有返回的 `source_coverage` 固定为 `unverified`。客户端 complete、非空清单、已确认全部已列 capture，都无法证明源站没有漏项/未枚举项。页台账中的 cursor 只是所声明页面对应的引用，不是已经验证可使用的平台 continuation。

## 停止、历史交付与恢复授权

历史交付与新源站动作分开：仍具有效系统交付身份的原 actor 可在租约过期、任务取消、切换 current run 后，首次补交旧 run 页清单，并核对 receiver 合法保存的迟到结果。它只改变旧 run 台账，不改新 run 水位、不恢复任务、不重置预算。系统 actor 被停用时，历史读取/补交一并拒绝。现有 receiver 的 admission 接收期限仍单独生效，本模块不会延长它。

可信服务器事先登记 `recovery_grants`：绑定 owner/actor、源/目标 run 的完整 binding hash、server issued_at/expires_at，可撤销且其余字段不可变。初版只支持同 actor、同逻辑 task、同 session/credential epoch、platform/source/parser/normalizer/target scope、**同规范 requested_fields 数组**。字段数组重排也保守拒绝。源与目标 lease_epoch 可以不同；每个 binding 各自精确匹配。目标必须仍为任务 current run、lease_epoch 当前、session active、credential epoch 当前、任务/run 未暂停或取消、server lease/task 尚有效。

返回 `acknowledged_prefix`、可选 `candidate_cursor_ref`、`blockers`。partial 或发现缺口时不给候选 cursor。即使全部已知页 ACK，也始终返回：

- `automatic_resume_allowed=false`
- `old_outbox_drain=unverified`
- `source_coverage_unverified`、`old_outbox_drain_unverified` 阻塞

原因：服务器不能凭已上报页判断原设备是否仍有未上报 outbox，也未保存真实 continuation。该建议不允许新执行器直接重抓、跳过未交付本地游标、清空旧队列或预算。未来执行层需可信封口/交接与可携带 continuation，另行设计验证；本批没有实现跨设备可靠执行恢复。跨 actor、账号/session、credential、parser、字段范围不兼容时明确拒绝，而非自动借用旧游标。

## 验证

```sh
CROWD_TEST_TOOLS=/private/tmp/crowd-fix-tools node crowd-kol/server/crowd/v4/tests/capture-checkpoint-db.mjs
node --check crowd-kol/server/crowd/v4/capture-checkpoint.mjs
```

测试使用真实隔离 PGlite SQL 和现有 SQLite outbox/receiver；覆盖清单先到/回执先到、页乱序、缺回执、完整绑定、同页重放、篡改/伪 ACK、错误身份、迟到历史补交、独立新 run 水位、COMMIT 失败全回滚、磁盘关闭重开、丢 ACK 仅重投原 capture、恢复授权撤回/过期/在途过期、目标 lease 失效、字段/凭证/parser 不兼容、partial 不被后页抹掉。

Node v22.23.2 内置 `node:sqlite` 为 experimental；测试会明确打印警告。PGlite 单连接 Promise 并发不能证明 PostgreSQL 多连接锁竞争。该边界需独立审查的真实 PostgreSQL probe 补证。未做断电恢复试验；本批关闭重开不能称为断电证明。

## 待确认/后续门禁

正式迁移、可信 Auth/RPC、生产 RLS 策略、trusted discovery、原 outbox 封口/转移、游标可携带与失效处理、失败项 disposition、跨 actor/账号交接均未实现。现有生产 guard、奖励、签名升级、旧扩展不受本批修改。M0 两条真实来源回执验收未完成前不扩大生产灰度。独立审查未通过前不宣布本批完成，更不宣布 M1/生产完成。
