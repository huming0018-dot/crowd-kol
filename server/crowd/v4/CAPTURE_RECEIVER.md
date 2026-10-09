# M1 隔离持久接收纵切

状态：自有实现、离线 PGlite 原型，未连接生产。没有 HTTP 入口、认证实现、正式迁移或 Supabase 部署。旧 RPC、SQL、客户端、OTA、outbox、评价、奖励均未修改。

## 文件与调用边界

- `capture-receiver.mjs` 导出 `receiveCapture(db, authenticatedPrincipal, input)`。
- `tests/fixtures/capture-receiver.sql` 在隔离数据库创建私有 `capture_receiver` schema；不是正式 migration。测试先建立 `anon / authenticated` 角色。
- `tests/capture-receiver-db.mjs` 使用已有 PGlite 依赖。无新增包，无平台请求，无第三方采集代码。
- 字段与规范 hash 复用 `capture-contract.mjs`。正文普通公开链接保持原文；来源不自动转成 DOM。

`authenticatedPrincipal={owner_scope,actor_ref}` 必须由将来的可信服务入口从真实认证结果解析。它不能来自 request body、用户自填 metadata、客户端 expected JSON，不能因为方法有一个名为 principal 的参数便视为已认证。本原型只验证形状、请求一致性以及数据库中的 enabled 主体；**真实身份验证尚未接通**。

`db` 使用 PGlite 的 `transaction(callback)` 与参数化 `query()`。事务对象不能让调用者任意注入 SQL。生产数据库驱动适配和连接池模型需要另行验收。

## 信任来源与隔离表

`actors` 记录 owner、actor、enabled（默认 false）。它是接收端的第二道授权门禁，不是自动注册入口。

`admissions` 由可信调度/准入方预先写入。每条冻结以下信息：

- owner、actor、session、task_ref、run_id、lease_epoch、credential_epoch、admission_id、target_ref、source_kind。
- `issued_at / accept_until`：服务器时间窗口。生产应由服务器生成；测试通过 SQL 数据库时间生成。
- `parser_version / normalization_version / requested_fields`：本次动作绑定的版本与字段范围。归一化版本目前只接受 `capture-v1`。
- `revoked`：首次接收禁用开关。冻结触发器只允许修改此字段，不允许重写绑定、版本或时窗。

当前接收器按准入记录保存**预先声明的** parser 版本；并不能远程证明一个外部 worker 确实加载了该二进制版本。执行器注册、构建摘要/版本协商和真实加载校验尚未实现。来源同理：可信准入分配到机器 API 的结果无法改标 DOM，但实际采集方式仍需执行器身份与审计证据保证。

`captures` 把规范信封、可信版本/请求字段、数据库 `received_at` 与首次回执放在同一行。主键 `(owner_scope,capture_id)`；另有唯一 `(owner_scope,admission_id)`。同一次动作最多保存一个内容 capture；换 UUID 不能增加内容数。字段请求表不是全局预算，也没有创建新动作的权限。

表及函数不向 `public / anon / authenticated` 授权；三个表启用 RLS，无客户端策略。唯一触发器函数是私有 `SECURITY INVOKER`，固定 `search_path`。测试以隔离数据库所有者调用，不代表已设计完生产服务角色与最小权限。

## 接收、回放与撤回顺序

1. 复制并验证可信主体参数，调用 `normalizeCapture`。owner/actor 必须与主体完全一致。
2. 事务内锁定主体行，确认 enabled。接收与主体停用互斥，避免检查后停用但仍提交。
3. 先查询该 owner/capture 的持久记录。其他 actor 不可获得回执。同主体、同完整摘要返回原回执；不同摘要返回 `request_reused`，不覆盖原数据。
4. 若是首次接收，锁定可信准入行，确认未撤回，调用 `verifyCaptureBinding`。逐项比对任务、来源、主体、目标、两种 epoch；不采用客户端自报的 expected。
5. 请求字段必须不是 `not_requested`；未请求字段必须是 `not_requested`。请求字段可显式标 `not_visible / not_supported / parse_failed` 并为 null，这是部分观察，不是任务完成。伪造 complete 或把必采字段标成未请求均拒绝。
6. 由数据库 `clock_timestamp()` 判断当前准入窗口。`captured_at` 只能用于拒绝明显不一致的采集时间，不能把过期动作变有效。目前要求它落在 issued_at 与服务器当前时间之间；原型没有时钟偏差容忍参数。正式客户端接入前必须验收设备时钟差，不能自动改写原时间。
7. 再检查动作未被其他 capture 消耗，单条 INSERT 原子写入信封、版本和回执。INSERT 内重查服务器窗口，防止长时间处理后仍凭先前判断接收。
8. 数据库唯一键处理不同 admission 对同 capture 的竞争；冲突后读回持久摘要再分类，不使用内存幂等缓存。数据库异常只返回固定 `receiver_unavailable`，不泄漏 SQL、正文或凭据。

首次回执为 `{capture_id,status:'received',verdict:'stored_unreviewed',received_at,envelope_hash,run_id,lease_epoch,credential_epoch,admission_id}`。回放完全保持原 `received_at` 和原状态；不再造一个 duplicate 回执，不宣称业务采用或可计酬。回执只含元数据，不含正文、URL、凭证。

**过期/撤回的边界：**已经持久成功的原回执，在准入过期或撤回后，仍允许有效、已认证的原 owner/actor 按原摘要对账。它不会重新入库、恢复采集或增加配额。首次新 capture 在过期/撤回后拒绝。主体停用或本系统登录授权失效时，应禁止对账；原型覆盖数据库 enabled 停用，真实退出登录会话校验留给可信入口。

旧 epoch 的合法迟到结果仍归原 run。此模块不创建或更新任何任务进度表，不把原记录包装成新 epoch，也不完成任务。能接收旧结果不代表允许旧租约继续访问源站。

冻结触发器在本地原型中阻止更新/删除 capture，以防回执重写。它不是生产数据保留政策；正式投产前必须补充经过审查的删除/保留流程，不能无限保存或绕过合法删除要求。

## 实际验证与边界

```sh
CROWD_TEST_TOOLS=/private/tmp/crowd-fix-tools node server/crowd/v4/tests/capture-receiver-db.mjs
node server/crowd/v4/tests/capture-contract.mjs
```

隔离 SQL 测试覆盖：

- 实际事务插入规范信封和回执；0 与不可见 null；版本、请求字段与旧 epoch 持久。
- 同 capture 并发调用/丢 ACK 重放返回同一原回执；不同 admission 同 capture、不同正文、换 UUID 复用 admission 不增加记录。
- owner/actor 越权、未知/停用主体、无准入、来源/会话/run/epoch 错配。
- 数据库窗口过期、未来 issued_at、前后伪造 captured_at、准入撤回；成功后过期/撤回仍可对账。
- 请求字段缺失、超范围字段、虚假 complete；真实部分观察仍按部分语义保存。
- INSERT 已执行后的 deferred trigger 制造 COMMIT 失败，验证没有残留信封或回执，同 admission 随后能成功重试。
- PGlite 文件库关闭重开后重放，校验原 received_at、原回执、原信封不变。
- RLS、schema/table/function 权限拒绝、触发器冻结。

PGlite 通过一个连接串行执行 transaction。测试中的并发 Promise 验证调用竞争和数据库唯一约束行为，**未验证真实 PostgreSQL 多连接锁竞争、死锁恢复或生产隔离级别**。关闭重开验证落盘持久性，不等同于 OS 断电/磁盘损坏测试。未调用源站，因此不能将这些结果描述为真实内容采集或生产入库回执。

未完成：真实认证/登录撤销、准入签发与全局预算、调度/取消、outbox/checkpoint、公开 API、批处理错误隔离、production roles、数据生命周期、正式 CLI 生成迁移、多连接 PostgreSQL 测试、M0 原设备真实两条验收。独立审查通过前不接生产；本批通过也不表示 M1 整体完成。

参考：[Supabase API 安全](https://supabase.com/docs/guides/api/securing-your-api)、[PGlite transaction](https://pglite.dev/docs/api#transaction)。本轮已读取官方文档；changelog 的 Markdown URL 在 web 工具中返回不支持内容类型，相关变更由主任务此前已核对的官方记录补充。
