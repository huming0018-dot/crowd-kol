# 任务分配：Kimi 两个代码形态与 v4

v4.0.8沿用4.0.7服务端任务协议；新增客户端到期唤醒与评论无进展停止，见[当前状态](V4_ITERATION.md)。

核对日期：2026-10-08。依据是 crowd-pages 提交81eed9e中的 `crowd-extension-latest.zip`（manifest 3.4.14、`src/background_v3414.js`），以及线上 `public.crowd_fetch_tasks` 的完整定义；同时对照 crawler-extension 提交5b9e327（manifest标签1.0.0）的完整JS代码。数字只用于标识输入，不判断先后。v4依据 canonical 客户端与 `crowd_v4_task_scheduling` 迁移。


## 两个 Kimi 输入到底差在哪里

[可复核摘要与行为探针](KIMI_CODE_COMPARISON.json) 保存了输入SHA256和逐文件结果；比较脚本位于 crawler-extension 的 `tools/compare-kimi.cjs`。用 Acorn 去除注释/格式/源码位置后比较AST，并人工复核差异，没有按名称或时间判断。

- **6/9个JS文件AST一致**：content、safety_engine、device_profile、config、popup、sw。公开笔记解析、限速/冷却、设备画像等主体相同。
- **onboarding**：1.0形态删除只赋值、从不读取的pendingPid；同意后保存身份/启动、拒绝后停止的行为保留。
- **sampler**：1.0形态删除pickWeighted/bern；全量JS调用搜索未发现消费者，实际调用的采样函数一致。
- **background**：两者都有known_note_ids、12条上限、关键词轮转、稳定信封ID、quota等待、队列merge、死信和认证熔断。1.0去掉任务内safety_limits空操作、去掉服务端未返回的task_status完成分支，保留顶层safety.limits与keyword_progress完成判定。线上函数已核对这两个字段契约。
- **确实存在的执行差别**：ok=true且rateLimited=true时，1.0先记录风控再记搜索/会话计数；3.4.14顺序相反。隔离行为探针确认该差异，不能笼统声称完全等价。普通成功的已见过滤、失败时风控上报两个探针结果一致。
- **打包差别**：manifest改名、描述、版本标签和worker文件名；不能由此推出功能谁新谁旧。

结论：1.0是包含上述精简差异的代码形态，**不是缺少3.4.14主要能力的旧版**。不拿3.4.14覆盖它。v4此次改进针对自己已证实的缺口，与Kimi标签大小无关；下表共同项已经对两个形态核对。

复核命令（仅开发依赖，不随插件下发）：

```sh
node tools/compare-kimi.cjs /path/to/crowd-pages/crowd-extension-latest.zip /path/to/acorn
```

| 环节 | Kimi 两形态共同的任务机制 | 当前 v4 |
|---|---|---|
| 派发单位 | 关键词包/店铺包，本地逐词轮转；提交进度由服务端维护 | 单个关键词任务、独占20分钟租约；任务目标1–20条 |
| 竞争领取 | 最早创建的可领取任务；FOR UPDATE SKIP LOCKED；排除本机done_task_ids | 先续本人原任务，再领取可用且最久未分配的任务；同样用行锁及SKIP LOCKED |
| 本地缓存 | active_task存在直接返回，返回对象未保存claimed_until；不能据此声称持续续租 | 剩余租约不足3分钟主动续租；同任务同token保留进度，新token清理旧页面状态 |
| 已采预过滤 | 下发包关键词已accepted的note_id，最多500条 | 下发同query已有note_id，最多500条；所有已占用唯一键的状态都排除；详情前guard仍防并发重复 |
| 本轮没新结果 | 主要依赖本地关键词状态和done排除；服务端没有本次新增的available_at退避机制 | 结束本轮后回open，延后15/30/60/120/240/360分钟；有新增记录则重置空轮计数并等15分钟 |
| 避免任务饿死 | 新领取按created_at排序 | 可用任务按last_claimed_at升序，未分配优先；处于延后期的任务不会抢占其他任务 |
| 完成确认 | 包内关键词/KPI及本机完成表 | 服务端received达到target才complete；客户端一轮没候选不能永久标exhausted |
| 暂停与限制 | safety随fetch响应下发；缓存直接返回会跳过这次fetch | 控制检查独立于任务缓存；每次页面动作必须经服务端guard，失败停止新页面动作 |
| 凭证与回执 | participant编号、信封、逐条gate | auth.uid身份、租约token、每条稳定request UUID与原文；有效回执才出队 |

## 本次修复的边界

- `finish`参数不变，旧v4客户端仍可调用。无产出从永久耗尽改为可恢复延期；历史exhausted/closed记录不自动重开。
- 同一租约重复finish只回读结果，不增加空轮数、不再次推迟。新一轮任务轮换token，旧请求不能终止新任务。
- 网络/页面错误仍遵守原退避和连续3次失败暂停；保存原task和seen，避免重领时清空已见笔记。不是把页面超时当成店铺无数据。
- 搜索结果预过滤节省的是重复详情候选和逐条guard等待；不提高搜索/详情/滚动/评论上限，不声称产量提高特定倍数。
- 已知ID列表最多500条，是查询相关的有界提示；其外重复继续由详情guard和数据库全局唯一键兜底，不承诺列表覆盖全部库。
- 任务target按收到的去重记录计数，不表示verified、计酬或付款。公开阅读量不可见时仍为null。

## 验证

`scheduling-db.mjs`：两身份租约归属、同token续租、延期任务让位、重复finish不累计、换token拒绝旧finish、空轮退避、有产出重置、同关键词ID过滤、完成和权限。
`scheduling.cjs`：预过滤、损坏finish回执保留状态、续租保留搜索、新租约清理残留、页面错误保留已见、停止后唤醒不重启。
Chromium固定页面→隔离PostgreSQL真实RPC回归验证采集/回传幂等。测试未对真实小红书执行采集，不能替代Mac现场验收。

部署后用 `server/crowd/v4/health.sql` 看 task_ready、task_deferred 和 next_task_retry；ready含可接管的过期租约，不表示此刻有在线设备执行。没有新增任务队列服务或机器学习打分器，SQL租约与延期足以解决已定位问题。
