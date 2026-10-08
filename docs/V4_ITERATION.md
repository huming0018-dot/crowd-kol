# 当前版本与交付状态

更新时间：2026-10-08。这是四仓的当前状态入口；部署见 [DEPLOY.md](DEPLOY.md)，接手见 [HANDOFF.md](HANDOFF.md)，代码与调度对照见 [TASK_SCHEDULING.md](TASK_SCHEDULING.md)。

## 代码与版本

| 范围 | 当前事实 |
|---|---|
| 本次候选 | v4.0.7，crawler-extension/v4；manifest/core/构建worker/release.json一致 |
| v4 后端 | crowd-kol/server/crowd/v4；兼容调度迁移 `20261008033028_crowd_v4_task_scheduling` 已部署 |
| 私有分发 | crowd-pages/v4；保留原邀请、扩展ID与2条/日试点，不公开发布 |
| Kimi公开源码 | crawler-extension根目录，manifest标签1.0.0；不能据标签断言较旧 |
| Kimi分发产物 | crowd-pages根目录ZIP，manifest标签3.4.14；与上述源码主体相同，细节差异见代码比较 |
| 食品主项目 | china-travel-food，部署终点；后续客户端/SQL在canonical仓修改 |

三仓延续分支名仍是 `codex/v4.0.6-handoff`；这是分支名，不是当前版本号。原始导入清单IMPORTED_FROM.json只用于来源审计。
Kimi两形态已实际逐文件比对：6/9 JS的AST一致，其余三文件差异人工核对，并用固定输入验证普通采集预过滤与风控顺序。根1.0保留精简，不把3.4.14盲目覆盖回去。

## v4.0.7实际改动

1. 领任务附同关键词已存在note_id（最多500条），搜索结果先过滤，详情guard和数据库去重继续兜底。
2. 一轮没新候选只延后任务，15分钟起、连续无新增逐步延长至6小时；其他可用任务按最久未分配优先。有产出重置空轮计数。达目标才完成，历史关闭记录不自动重开。
3. finish重试不重复推迟；新一轮轮换租约token。相同租约续做不清空进度，新租约清理旧页面状态。页面失败保留task与seen，依旧遵守退避和三次失败暂停。
4. 重写README/HANDOFF/DEPLOY和契约入口，移除失效安装/回退/测试命令及重复历史状态。安装说明从manifest生成版本，不再拿旧版本号作文本替换锚点。

既有有效回执确认、原UUID/原证据重试、北京时间配额重置、控制检查、风控暂停和只读公开字段采集继续生效。未提高预算，未改变计酬或付款，KOL仍只作为线索。

## 线上只读核对

2026-10-08 **03:32:13 UTC**（北京时间11:32）执行health.sql：

| 链路 | 接收 | 核验/accepted | 近24小时 |
|---|---:|---:|---:|
| 原生产 public.crowd_* | 303 | accepted 294 | accepted 199 |
| v4 crowd_v4 | 0 | verified 0 | received 0 |

v4有3个可领取任务（含1个已过期租约），无延期任务。最新诊断仍为2026-10-07 13:17 UTC的4.0.1/page_timeout，**stale=true，不能证明设备当前状态**。两链路paused=false。旧链路产量不算v4成果。

迁移回验确认known_note_ids、公平排序、延后finish均已进入线上函数；anon不能claim，authenticated可finish但不能直接读取私有tasks。数据库advisors保留既有 [authenticated SECURITY DEFINER提示](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable)（由auth.uid、同意/审批与空search_path约束）及 [私有schema无RLS策略提示](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy)（有意拒绝直接访问）。未新增公开表权限。

## 交付与验证

私有Mac包：`/workspace/Mac轻量内测-v4.0.7.zip`，45,065字节。
SHA256：`b8ca44596936e5b4b544d3800f2c5d3eab181e9830f0d2d03b3d5785b29b89de`。
保留原扩展ID `licijehcpohikchlnkbpjdjdfkcocndg`。此包不上传公开仓；安装者须在原浏览器刷新，不卸载重报。

已验证：客户端生命周期/调度/回执/风控；隔离PostgreSQL调度/权限/冷却/配额/诊断；Chromium固定DOM→真实隔离SQL的搜索、详情、采集和幂等回传；跨仓打包可重复、版本/文件摘要、篡改拒绝。Kimi代码比对工具另有固定输入行为探针。
外部完整业务并发数据库未配置，该项明确SKIP。上述固定页面与隔离数据库测试不是Mac实机或真实平台验收。

## 尚待实际验收

原Mac升级到4.0.7，核对真实搜索→详情→记录入库、标准/非标/证据字段、停止、睡眠/浏览器重启恢复。当前v4真实入库仍0，不能宣称现场采集成功或扩大分发。
Windows/iOS/Android/原生鸿蒙的可安装产物与硬件验收分别处理；评分阶段二及KOL生产容器依赖不在本次修复验收中。
