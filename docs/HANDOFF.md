# 接手顺序

1. 读 [当前状态](V4_ITERATION.md) 与根 README 的四仓边界，拉取 main 和工作分支，检查工作区改动。
2. 在 Supabase 项目 `bdwrhshgdeghgyzwpxnl` 只读执行 `server/crowd/v4/health.sql`；分别核对原生产与 v4，诊断超过10分钟标为 stale。旧统计和截图不能证明设备仍在运行。
3. 修改 canonical 源码，执行 [部署说明](DEPLOY.md) 中的回归；只应用新迁移，再单向构建安装产物。
4. 真实 Mac 验收完成之前保持私有试点。不能凭模拟页面测试就宣称已解决现场 page_timeout 或扩大分发。

## 凭据位置索引

下列是历史交接提供的定位线索，**不代表当前执行环境拥有这些凭据**。不得把值写进输出或仓库。

| 用途 | 原位置/取得方式 |
|---|---|
| Supabase 管理与 AMO | `~/.food_atlas_credentials.md`，或已授权连接器 |
| service_role | 主项目私有 `app/.env.local` 中 SUPABASE_SERVICE_ROLE_KEY |
| CRX 签名 | `~/.food_atlas_credentials/crowd-extension-key.pem` |
| ops / owner | `~/.food_atlas_credentials/crowd-ops-secret`、`crowd-owner-secret` |
| GitHub | 配置的 Git 凭据助手或 `gh auth token`，不要打印 token |
| 生产 SSH | `~/.ssh/food_cloud_deploy` |
| 服务器 cron 环境 | `/home/ubuntu/food-cloud/deploy.env`，脚本使用绝对路径 |
| v4 私有试点 | 管理者本机忽略目录 `.crowd-launch`，沿用现有身份/邀请 |

## 未闭环

- 真实参与者使用无邀请更新包，在原浏览器原位更新4.1.1（无需Codex）；已知旧待处理原因unrelated_note。先通过health.sql核对提交摘要与别名修复后的复核结果，避免再次要求用户手工导出正文。17:40北京时间线上4.0.8已停止、旧login_required、服务端接收0；该旧码也由用户打开登录帮助产生，不能当成已证实登录过期；真实入库与睡眠/停止仍待验收。最新结果见状态页，不沿用旧“3台/174条”等数字。
- Kimi的3.4.14产物与公开1.0源码已按AST/行为/线上契约对照；主体能力相同，1.0包含精简差异，不按数字判新旧，详见TASK_SCHEDULING。后续编辑保留canonical源码，不用产物反向覆盖。
- Windows、iOS、Android、原生鸿蒙安装和实机测试分别验证，当前 Mac 候选不能作为这些端已可用的证明。
- 评分阶段二需 owner 样本及独立契约；KOL 相关部署依赖需在实际服务器验证。不自动启动评分、付款、cron 或 KOL 采集。

## 必须保持的契约

有效回执才移除证据；配额是临时等待，不写永久拒绝回执；任务租约不能靠客户端任意扩展；空搜索不等于永久耗尽；已收到不等于已核验。
策略静默安装、修改浏览器私有配置、低版本自动降级不属于当前安装方案。版本化 worker 由构建器生成；安装仍需浏览器本人确认。
所有 v4 诊断须本人开启，仅允许固定状态字段；不采集其他标签页、Cookie 或完整 URL。

故障设备属于参与者，不是管理者的开发机。不要再要求管理者切换本地工作区来代替生产排障；中台问题在线修复，客户端通过已有用户更新包交付，浏览器要求的刷新由参与者确认。
