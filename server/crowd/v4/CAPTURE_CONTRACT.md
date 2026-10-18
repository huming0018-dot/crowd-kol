# Capture v1：离线接收合同

状态：M1 首批自有实现，仅有纯函数与 Node 离线测试。尚未接入 HTTP、数据库、客户端、worker 或生产。原 v4 RPC、SQL、outbox 和回执不变。

## 使用与信任边界

`normalizeCapture(input)` 校验字段、复制输入、计算摘要，返回带 `envelope_hash` 的新对象；不修改原对象。未知字段拒绝，不做静默裁剪，不填充不可见计数。

`verifyCaptureBinding(input, expected)` 在规范化后，对齐租户、执行主体、会话、任务、run、租约代数、凭证代数、动作准入、目标和来源。`expected` 必须由可信接收端从认证、任务、run、准入记录读取；禁止接受请求中的同名对象作为可信上下文。这一步不是授权：接收端仍须验证同意范围、任务归属、撤销状态、准入时刻、迟到窗口与当前时间。时间字段目前只做格式和真实日历校验，不证明客户端时间可信。

`classifyCaptureReplay(input, storedBinding)` 仅比较摘要，返回 `new / duplicate / request_reused`。`storedBinding` 来自持久层，只有 `owner_scope, capture_id, envelope_hash`。键不同抛出 `capture_key_mismatch`，禁止跨租户复用查询结果。该函数不生成回执、不预留唯一键。未来接收事务必须以 `(owner_scope, capture_id)` 原子去重：同摘要读回原逐条回执；异摘要返回 `request_reused`，不覆盖原数据。同一份内存判断不能解决并发提交。

来源枚举为 `rendered_public_dom / platform_api / authorized_export`。不支持别名、推断或 API 到 DOM 的降级转换。纯函数无法判断实际采集方法；接收端须把 `expected.source_kind` 绑定到经过准入的执行器身份和合同。此合同没有人工评价、奖励、accepted 或任务完成字段。

## 最小字段

信封必填：`contract_version=1, capture_id, owner_scope, actor_ref, session_ref, task_ref, run_id, lease_epoch, credential_epoch, admission_id, target_ref, source_kind, captured_at, payload_schema=content.v1, payload, completeness`。首次提交可省略摘要；有摘要时必须与计算值完全一致。信封无凭证槽位。

- `task_ref={namespace:'legacy_v4',legacy_task_id:'9007199254740993'}`：正整数十进制字符串，不允许前导零，最大 `9223372036854775807`。不经 JavaScript Number 转换。
- 新任务使用 `{namespace:'capture_v1',id:<uuid>}`；UUID 为小写标准文本、版本 1–8、RFC variant。
- `owner_scope / actor_ref / session_ref` 是最长 128 字符的本地引用，字符集为字母、数字、点、下划线、冒号、短横线。它们不是 token。
- `lease_epoch / credential_epoch` 是从 1 开始的安全整数。
- `target_ref={platform,kind,id}`；kind 为 `content / creator / search`。search 的 id 是服务器保存的目标引用，不接受原始任意查询对象。
- 平台枚举：`xiaohongshu / bilibili / douyin / kuaishou / weibo / zhihu / tieba`。这只表示身份命名空间，不声明对应采集器上线。
- 内容 ID 是不透明字符串，最长 256 字符，不做 XHS 24 位 hex 假设。不允许空白、URL 路径/查询分隔符和百分号。目标为 content 时精确匹配内容 ID；creator 时精确匹配作者 ID。search 的内容相关性由可信接收端另验。

payload 必填：`platform, content_id, creator_id, canonical_url, content_type, title, title_origin, body, published_at, metrics`。`creator_id` 可以为 null。类型为 `note / video / article / answer / post`。本次未实现媒体、评论、KOL 列表或适配器；后续须增加独立版本合同，不把任意原始 API JSON 塞进 payload。

`title / body / published_at` 使用 `{value,status}`，status 为 `observed / not_visible / not_supported / not_requested / parse_failed`。observed 必须有值，其余必须为 null。标题上限 2048 UTF-16 单元，正文上限 100000；`title_origin` 为 `original / generated_excerpt`，未观察标题时为 null。所有时间固定为合法 UTC `YYYY-MM-DDTHH:mm:ss.sssZ`。

metrics 固定五项：`likes / collects / comments / shares / views`。每项为 `{value,status,precision,raw_display}`：观察值为非负安全整数，precision 为 exact 或 approximate；approximate 必须保留最长 64 字符的原始显示值。未观察时 value、precision、raw_display 必须同时为 null。观察到 0 与不可见严格分开。

`completeness={status,scope:'single_content',reason}`。complete 仅允许所有字段为 observed 或 not_requested，reason 为 null；partial 的 reason 为 `field_unavailable / content_truncated`。complete 只描述本次单条请求，不证明作者历史或全站内容完整。

## 规范编码与摘要

1. 只接受无 getter/setter 的普通 JSON 对象、稠密数组、字符串、null、布尔值、安全整数。拒绝负零、浮点、NaN、Infinity、BigInt、undefined、函数、Date、自定义原型、符号属性、隐藏字段、循环、孤立代理字符。
2. 对象键按 JavaScript UTF-16 词典序排序，数组顺序保留，字符串按 JSON 转义。不做 Unicode 正规化，不合并不同原始文本。
3. 删除信封 `envelope_hash` 后编码为 canonical JSON。`SHA256(UTF8('crowd-capture-v1\n' + canonical_json))` 得到 64 字符小写 hex。键顺序变化不影响 hash，身份、来源、任务或内容变化影响 hash。
4. 深度最多 12，节点最多 5000，完整已加摘要信封最多 262144 UTF-8 字节。入口未来须在 JSON.parse 之前限制请求体；纯函数不能替代流式 HTTP 体积限制。

## 凭证与 URL

canonical_url 只接受明确平台域名的 HTTPS 原型 URL，不接受用户信息、端口、查询、片段、编码定位符、短链或非规范拼写。不静默删除 token 后假装原 URL 仍可访问。URL 与平台内容 ID 的具体路由映射仍由各平台 `validateTarget` 验证；此合同不声称 URL 与内容 ID 已经被源站证实。

正文中的 HTTP(S) URL 允许普通公开查询和片段，原文完整保留并参与摘要，不自动裁剪或改写。URL 用户信息仍拒绝；query 和 fragment 经一次标准百分号解码后检查常见 Cookie、Authorization、token、API key、password 赋值，大小写不敏感，带路由的 fragment 同样检查。非法百分号编码拒绝。原始正文中的这些赋值、Bearer 凭证和私钥标记也触发拒绝，错误只含固定代码，不回显输入。该检测不是通用 DLP，不能识别无标签或特殊多层编码的任意秘密；可信适配器必须从公开允许字段白名单构造 payload，不能传递响应头、凭证或请求上下文。canonical_url 的严格规则保持不变。

## 验证

```sh
node server/crowd/v4/tests/capture-contract.mjs
```

使用 Node 22 标准库，零依赖、零网络。覆盖 legacy bigint、多平台同 ID、原始 0 与不可见、键序稳定、逐项身份/准入绑定、同 ID 异载荷、来源冲突、凭证 URL、长度/复杂度/时间/计数与非法 JS 对象。运行成功不表示 M1 完成，也不表示已取得任何真实来源或生产回执。

未完成：接收端认证/授权、持久幂等事务、逐条回执、outbox/检查点映射、预算准入与取消、崩溃/丢 ACK 集成测试、真实两条验收。独立审查通过前不接入生产。
