# v4 服务端

认证后的独立协议与原生产 public.crowd_* 共存。统一状态见 [V4_ITERATION.md](../../../docs/V4_ITERATION.md)，步骤见 [DEPLOY.md](../../../docs/DEPLOY.md)。

`supabase/migrations` 是迁移真源；只应用未部署的增量。IMPORTED_FROM.json仅记录一次性导入来源，不能从旧主项目反向覆盖当前源码。
任务机制见 [TASK_SCHEDULING.md](../../../docs/TASK_SCHEDULING.md)。health.sql只读区分两条链路，并展示任务可用/延期和诊断新鲜度。

测试使用隔离PGlite，另有客户端Chromium固定页面端到端回归；不在生产创建合成参与者或证据。
Edge函数源码仍需要可信配置渲染，不得直接部署包含占位符的模板。SQL迁移与Edge函数分别记录部署版本和回读证据。

## Pro 参与者评论交付

评论访问继续使用已购 Pro 的原生分页实现，并经过原 live lease、来源预算和账号核验。已保存的评论复用原身份及本地 outbox，通过 `pro_comment_submit`、`pro_comment_receipt` 和 `pro_comment_commit` 取得独立回执及分页封存；每个子对象绑定真实正文 ACK、原 task/install/run，不增加正文 target 或众包奖励。租约到期后仍可交付原已保存对象；撤销参与同意或未批准身份仍拒绝交付，不因此获得新来源权限。

评论开启时，缺少封存的组返回 `comment_capture_pending`，Owner 保留游标。分页 partial/unknown/limit 不能通过 finish 冒充完整完成。纯旧正文页面保留 v1 原组字节；包含评论任务的页面使用 v2，旧组字段仍保持。原 ACK 集合哈希生成处理 context，新集合沿原 Jobs/Consumer 生成新版本，旧 ready 结果保留。

单对象 131072 字节、原 native 帧及 Owner 8MiB 读取限制保留，不截断正文或评论。Python canonical JSON 与 PostgreSQL jsonb 文本编码不同，中央有效对象上限可能略严；边界拒绝保留原保存记录及错误，不冒完成。Pro 原生评论上限和回复开关须在请求/封存中明示，不能暗加采集数量限制；媒体引用和媒体文件字节分别验收。

隔离回归：设置现成 PGlite 依赖目录 `CROWD_TEST_TOOLS`，并将 `CROWD_COMMENT_MIGRATION` 指向本次正式迁移，再运行 `supabase/tests/pro-comments/test_pro_comments.mjs`；设置 `CROWD_COMMENT_EDGE` 指向 `supabase/functions/crowd-machine/participant_pro_receipts.mjs` 后运行同目录 `test_pro_comment_feed.mjs`。默认 fixture 为合成35评论/13页，无网络或生产回退；真实保存输入和生产回执另列证据。正式采用顺序为支持两协议的 Owner、中央迁移/Edge、匹配的参与者 Python/扩展/原生助手；本节不代表已部署或已取得新来源回执。
