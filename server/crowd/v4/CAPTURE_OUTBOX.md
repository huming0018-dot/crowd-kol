# M1 本地耐久 outbox 与 ACK 水位

第三批引入 `capture-outbox.mjs` 与离线测试；第六批在原队列内增加持久回传尝试、退避与派发互斥，并更新受影响的 checkpoint 集成测试。合同、receiver、预算/checkpoint 业务模块、旧浏览器 outbox、生产协议及正式迁移不变。实现是自有 Node 离线纵切；没有源站请求功能。

运行时已实测 Node `v22.23.2`、SQLite `3.51.3`。使用内置 `node:sqlite`，无新增依赖。**此 Node 版本的 SQLite API 仍标 experimental**，不能据此承诺所有环境兼容。参考 [Node 精确版本 SQLite 文档](https://nodejs.org/download/release/v22.23.2/docs/api/sqlite.html)。

## 文件、事务与作用范围

`openCaptureOutbox(filename, scope)` 返回绑定作用域的实例。文件创建权限为 `0600`；已有文件必须是普通文件、非符号链接且不向 group/others 开放。内容仍是明文，不是凭据库或加密数据库；路径应在当前用户受限目录。队列从不保存 Cookie、token 或源站访问游标本体。

SQLite 设置 WAL、`synchronous=FULL`、外键检查、1000ms 锁等待。每次修改使用 `BEGIN IMMEDIATE`、同步写入和 COMMIT；发生错误显式 ROLLBACK。锁超时和数据库故障返回固定 `outbox_storage_failure`，不回显正文或 SQL。不内置无限重试。

scope 固定字段：`owner_scope, actor_ref, session_ref, task_ref, run_id, lease_epoch, credential_epoch, platform, source_kind, adapter_version`。任务保留 `legacy_v4` bigint 字符串或 `capture_v1` UUID。相同 owner/run 重开时必须与已存 scope 完全一致，不能把新 epoch、来源或解析器版本写进旧 run。新 run 的水位独立；同 owner/capture_id 在本地文件内唯一。

`adapter_version` 在本批绑定于本地 run，而现有信封只包含此前合同字段。它表示可信调用端声明使用的版本，不证明加载了特定二进制。前两批接收器依旧以可信 admission 中的 parser 版本为准；版本注册和执行器构建证明留给后续阶段。

## 可信上下文与身份恢复

每个读写/交付方法要求 context：

```js
{
  owner_scope, actor_ref, session_ref,
  authenticated: true,
  auth_epoch: 1,
  collection_allowed: true,
  delivery_allowed: true
}
```

context 必须由可信调用端从当前登录与授权状态生成，不能接受 UI/请求自行声明的布尔值或代数。本模块没有实现真实认证。`auth_epoch` 是本系统重新认证的单调代数；与源平台 `credential_epoch` 不同，不修改已采集信封。

- 暂停采集：`collection_allowed=false`，禁止提交新的采集页；若 delivery_allowed 仍为 true，可交付旧耐久记录。
- 退出本系统登录：authenticated=false，禁止读取/发送队列以及写回 ACK。传输期间登出时，结果保持 unknown，随后原身份恢复后按原信封重放。
- owner/actor/session 不匹配一律拒绝，不能用新身份发送旧队列。
- 接收端返回 `principal_required / principal_mismatch / actor_not_authorized` 时记录 blocked 及当前 auth_epoch。该 run 的自动待发列表暂停，避免逐条重复撞击同一身份错误。
- 明确完成重新认证后，由可信调用端传入更大的 auth_epoch，调用 `resumeDelivery(context,capture_id)`。仅 blocked 项可恢复为 unknown；旧代数、登出状态、错主体拒绝。随后在剩余尝试额度与退避条件允许时重传完全相同的 capture_id、hash 和信封。重新认证不清零尝试次数或解除旧未知历史冻结。不能用 `applyResult(null)` 绕过恢复步骤。
- `deliverOne` 绑定发出请求时的 auth_epoch。请求在途时若已经完成更高代数的重新认证，旧请求随后返回的身份错误保留当前持久状态（可为 unknown、exhausted 或已对账的 received），附 `reason=stale_auth_response`，不会新增 blocked。信封继续保留；后续重投必须仍有剩余额度并满足退避，使用同 ID/hash。处理返回值前仍检查当前 owner/actor/session、登录及交付许可；在途登出或换主体仍拒绝，不能借“旧响应”绕过授权。
- `admission_revoked / admission_expired / request_reused` 等明确拒绝保留为 rejected，自动交付不再选中。真正历史成功的匹配 ACK仍可确认它；不能用空结果把拒绝抹成未知。人工处理/业务终态对账不是本批功能。

## 页 manifest 与两个本地水位

`stagePage(context, page)` 接受：

```js
{
  sequence: 1,
  cursor_ref: 'cursor:<uuid>', // 或 null，只是受限本地引用
  coverage: 'complete',       // 或 partial
  stop_reason: null,
  items: [
    { kind: 'capture', capture: completeEnvelope },
    // 若有此类失败项，本页必须声明 partial：
    // { kind: 'failure', item_ref: 'item:<uuid>', error_code: 'parse_failed' }
  ]
}
```

序号从 1 连续递增，不比较不透明游标的大小。页最多 20 项，输入继承合同的 262144 UTF-8 字节/复杂度上限。合法游标仅为 `cursor:` 加 UUID，不接受任意 URL、查询串或实际账号令牌。引用如何映射到受保护源游标由后续适配器负责。

有效 capture 先完整规范化并核对 scope。首次写入时，页 manifest、逐项完整信封、稳定 capture_id/hash、显式失败项与 `captured_sequence/captured_cursor` **在同一事务提交**。中途冲突则整页回滚，不留下半页水位。相同序号和相同 manifest 幂等；键顺序不影响摘要。相同页异内容返回 `page_reused`，其他页复用 capture_id 拒绝，避免重复计数。

坏输入不会被自动删掉：调用端必须把已识别失败转换成有界 failure 项，再与有效条一同提交。直接传无效 capture 则整页拒绝。失败代码限 `parse_failed / not_found / private / auth_required / risk_paused / timeout / source_error`，不保留可能泄漏秘密的自由诊断字符串。失败项持久为 failed，不伪标 received。

第二个水位是**本地 ACK 确认水位**：当前页的每个 capture 都取得严格匹配的明确 ACK，且前序页没有未决/失败/拒绝项，才推进 `delivered_sequence/delivered_cursor`。后页先 ACK 不越过前页缺口；部分 ACK 保留逐项集合。所有记录继续保留，不自动删除证据。

此水位不是服务器权威 checkpoint。第五批另有隔离服务器页台账，但真实浏览器清单传输、旧队列封口与 continuation 转移尚未接通，**不支持自动跨设备恢复**。不能使用另一台设备本地 captured_cursor 推断内容已入库。

coverage 只描述目前已存页序列的请求范围，不表示全部作者历史或业务验收。partial 页、显式失败和接收拒绝不能被后续 complete 页抹掉。单条 capture 本身 partial 时，页也必须 partial。全部 partial capture 获得 ACK 后，交付水位可以推进，但 `delivered_coverage` 仍是 partial。failed/rejected 项则持续阻塞水位，待后续明确终态处理；本批不会擅自跳过。

## 交付 API 与 ACK 验证

- `pending(context,limit=20)`：保留为查看原信封的接口，包含退避中、自动次数耗尽及历史次数未知的 pending/unknown；**不是派发许可**。不返回 failed/rejected，run 存在身份 blocked 时返回空列表。只有 `deliverOne` 负责原子预记与派发。
- `deliverOne(context,transport)`：在事务中预记一次尝试、unknown、下次时间与持久 flight token，再调用一次可信 receiver 传输回调。回传失败后再从结束时间收紧退避。返回 received/unknown/blocked/rejected/exhausted；未到时返回 deferred，活跃派发返回 busy，无自动资格返回 idle。不会新建 UUID、清理队列或重抓。
- `applyResult(context,captureId,response)`：接收现有 receiver 的 `{receipt,error}`。严格核对字段、received/stored_unreviewed 状态、capture_id、envelope_hash、run、两个 epoch、admission_id 及 UTC 时间格式。成功后再次收到不同回执拒绝，原回执保持不变。
- `resumeDelivery(...)`：仅在可信重新认证后解除身份 blocked，详见上文。
- `status(context)`：返回两个本地序号/游标、两种 coverage、各状态数量，以及持久 `delivery.in_flight/capture_id/process_id`。第 3 次尚在等待时，即使次数已用完也明确显示在途，不能当成已经结束。
- `itemStates(context)`：返回页/项序号、引用、状态、固定错误码、attempt_count、next_allowed_at、legacy_attempts_unknown，不返回正文。
- `close()`：关闭本地连接，不删除数据。本 handle 仍有在途 `deliverOne` 时抛固定 `delivery_in_flight`，避免丢掉本进程的释放路径；其他观察连接可以关闭，不清活跃派发。

ACK 字段一致性不是密码学证明。transport 必须连接经过认证的可信接收器；本批未接 HTTP、TLS 或签名回执。Node 接收回调可由进程内任意代码伪造，所以不能把离线测试产生的 ACK 称为生产回执。

## 第六批：持久尝试、退避和互斥

新 capture 最多 3 次自动 receiver 回传尝试。第一次未知后至少 5 秒，第二次后至少 20 秒；只用于向本系统 receiver 重投原信封，不是源站请求节奏，不替代生产 guard、四层预算或 30 秒源站间隔。时间使用本机持久 Unix 毫秒；没有 caller 可传的 now/force/reset。系统时钟前跳可能使本地等待提前，后跳可能延长；真实发送器仍需服务端限制，不能把本机时钟当成平台授权。

外调之前同一 SQLite 事务写入 `attempt_count+1`、`next_allowed_at`、unknown 与 run flight token/PID。失败/缺失 ACK/错误格式/在途登出都不退款。回调结束时将下一时间收紧为 `max(已存时间,结束时间+本次退避)`，防止慢失败后立即再发。崩溃保留派发时预记的次数与期限。耗尽后原 underlying 状态仍是未确认的 unknown，读接口明确显示 exhausted，自动选择不再返回；它不是 rejected，更不是 received。未知历史显示 legacy_unknown。失败、拒绝、耗尽均保留信封/manifest及水位缺口。

严格可信 ACK可将未知、耗尽、历史未知或历史拒绝确认成 received，不清零次数。没有任意“强制重试/清零”入口。身份 blocked 必须先用可信更高 auth_epoch 恢复；时间到达不能解锁。旧队列的身份恢复也不清除历史次数未知标记。真实 failed 项没有 capture，不接受伪 ACK；后续处置合同仍待设计。

持久 flight 在同 run 内互斥。不同 handle、不同进程在原进程仍存活时都返回 busy；即使超过退避或 close/reopen，也不抢占活跃派发。仅 `process.kill(pid,0)` 返回 ESRCH（确认 PID 不存在）后，下一次交付可回收未知占用并按剩余额度重投。EPERM/未知异常保留占用；PID 复用也保守阻塞。这只适用于同一台机器的本地 SQLite，不是跨主机租约。没有通用 timeout/Abort 发送器；transport 永不结束而进程仍活着时，状态保持 in_flight，需可信对账或处理该发送器，不能仅凭超时放行另一次调用。

本 handle 的 activeDispatch 只保护连接生命周期；真正派发互斥在数据库。释放只匹配本次 token，不清其他占用。在途无 token 的外部错误/空结果不能清活跃状态；严格匹配的可信成功 ACK允许先完成对账。其后原 transport 返回迟到错误/空结果，只返回实际 received 与 stale_delivery_response，不反转已有回执。旧 auth_epoch 身份错误仍不会污染更高代数的新认证。所有回调后处理仍校验当前身份和交付许可。

## 旧隔离库迁移

开库事务检测旧 items 是否缺 attempt_count，原子追加尝试/期限/历史未知字段及 run flight 字段，不重写信封、manifest或回执。旧代码在每次外调前必将 pending 写成 unknown，且没有把 unknown 变回 pending 的入口，因此旧 pending 可证明未派发，初始化为 0 次。旧 unknown/blocked 无法确定过往外调次数，保守初始化为 3 + legacy_attempts_unknown，冻结自动发送。received/rejected/failed 保持原状态；其旧 attempt_count 不是精确历史统计，不能用于报表声称“确实发了三次”。该值仅是保守自动额度哨兵。

迁移后的新 stagePage 从 0 次开始。旧未知只允许严格可信 ACK对账，本批没有自动查服务端回执的网络接口，也不授权使用新 capture UUID绕过冻结。迁移失败整体回滚，旧数据保留；不支持同时运行旧版本写进程，升级前须停止旧发送器，不能把混合版本写入视为安全迁移。

## 验证

```sh
CROWD_TEST_TOOLS=/private/tmp/crowd-fix-tools node server/crowd/v4/tests/capture-outbox.mjs
```

测试使用真实 SQLite 文件与上一批 PGlite 接收器，不访问源站。覆盖：

- 页连续性、相同页幂等、相同 ID 异 hash、scope 错配、整页事务回滚。
- 两页乱序 ACK、部分 ACK、错误 ACK 不清队；原身份、任务、run、epoch 不串。
- receiver 已落库但 ACK 丢失，关闭重开队列，再以同 ID/hash 重放，原 received_at 与原回执相同。
- 合成源读取计数不增加，重试仅增加 receiver 调用计数。
- 暂停后继续交付、登出禁止发送、传输中登出后保持 unknown。
- 身份 blocked 持久化、重开后仍阻塞、可信更大 auth_epoch 恢复、最终取得历史原回执。
- 在途重新认证后旧身份错误不污染新代数；下一次同信封取得回执。在途登出、换 owner/actor/session、停止交付仍拒绝写回结果。
- 显式失败、真正拒绝和 partial coverage 保留，后续完整页不能填平缺口。
- 真实子进程提交后未正常关闭被 SIGKILL，重开仍有原信封；另一个子进程未 COMMIT 被 SIGKILL，重开回滚未提交水位。

第六批另测：3次封顶、失败后完整5/20秒退避、重启不清零、两连接争抢、真实子进程持有flight时另一进程拒发、SIGKILL后消耗保留、claim写失败不外调、可信ACK先到后旧失败、在途close拒绝、旧schema迁移与新stage。测试通过修改隔离SQLite中的等待时间加速；不修改attempt、不提供生产时钟override。

SIGKILL 验证进程中断恢复，**不是断电、存储硬件损坏或跨主机容灾证明**。多连接 PostgreSQL 接收器和真实网络超时尚未端到端验证。

隔离预算/准入与服务器页台账已在第四/五批单独实现；尚未连通真实执行器。后续仍需：实际认证/重认证代数来源、真实网络发送器/超时、可信旧队列对账/封口、失败项终态治理、清理/删除政策、浏览器或 Python 容器接入。M0 原设备真实两条未完成，本批不得投入生产灰度。
