# v4 服务端

认证后的独立协议与原生产 public.crowd_* 共存。统一状态见 [V4_ITERATION.md](../../../docs/V4_ITERATION.md)，步骤见 [DEPLOY.md](../../../docs/DEPLOY.md)。

`supabase/migrations` 是迁移真源；只应用未部署的增量。IMPORTED_FROM.json仅记录一次性导入来源，不能从旧主项目反向覆盖当前源码。
任务机制见 [TASK_SCHEDULING.md](../../../docs/TASK_SCHEDULING.md)。health.sql只读区分两条链路，并展示任务可用/延期和诊断新鲜度。

测试使用隔离PGlite，另有客户端Chromium固定页面端到端回归；不在生产创建合成参与者或证据。
Edge函数源码仍需要可信配置渲染，不得直接部署包含占位符的模板。本次兼容更新只修改SQL。
