# 部署与回退

当前版本、支持范围、产量核对和未闭环事项统一见 [V4_ITERATION.md](V4_ITERATION.md)。
旧版部署手册保留在 Git 历史；其中运行环境反向同步、策略静默安装、低版本自动降级、缺失测试目录等步骤已从当前指引移除。

## 1. 修改位置

- 客户端：`crawler-extension/v4`。
- v4 SQL：本仓 `server/crowd/v4/supabase/migrations`。
- 私有安装包：`crowd-pages/v4`。
- 原生产 SQL/cron 与 KOL：本仓 `server/crowd/sql`、`server/crowd/cron`、`server/kol`。
- `china-travel-food` 是食品主项目与部署终点。不得从运行环境反向覆盖上述源码。

## 2. 验证与构建

```sh
# 在 crawler-extension 根目录；可选工具目录包含 Playwright、Chromium、PGlite。
CROWD_TEST_TOOLS=/path/to/test-tools \
CROWD_MIGRATIONS_DIR=/path/to/crowd-kol/server/crowd/v4/supabase/migrations \
node v4/tests/run.cjs
python3 v4/build.py --output /private/crowd-extension.zip

# 在 crowd-kol 根目录
CROWD_TEST_TOOLS=/path/to/test-tools node server/crowd/v4/tests/observations-db.mjs
CROWD_TEST_TOOLS=/path/to/test-tools node server/crowd/v4/tests/scheduling-db.mjs
CROWD_TEST_TOOLS=/path/to/test-tools node server/crowd/v4/tests/safety-db.mjs
CROWD_TEST_TOOLS=/path/to/test-tools node server/crowd/v4/tests/recovery-db.mjs
CROWD_TEST_TOOLS=/path/to/test-tools node server/crowd/v4/tests/diagnostics-db.mjs

# 在 crowd-pages 根目录，使用仍有效的原私有邀请
python3 v4/test_release.py /path/to/crawler-extension/v4
python3 v4/build_trial.py --source /private/crowd-extension.zip \
  --invitation-file /private/mac-trial.json --output /private/Mac轻量内测.zip
```

`release.json` 保存实际版本、源码摘要和交付摘要。私有邀请及产物不进 Git、Pages 或公开 Release。

## 3. 应用后端增量

先查 Supabase 项目 `bdwrhshgdeghgyzwpxnl` 的迁移历史，只应用尚未部署的 canonical 增量。
已部署基线禁止重跑；`server/crowd/sql` 的旧链路文件也不是一个已验证的全新建库脚本。
v4.1.0同时修改客户端与SQL，原RPC名与参数兼容旧客户端，新增观察与主页RPC。观察迁移在前，别名迁移在后。`functions/` 是需要可信配置渲染的模板，不可直接部署占位符。
4.1.1追加已部署的 `20261008093900_crowd_v4_login_diagnostics`，兼容新旧客户端错误码，权限不变。
4.1.2追加已部署的 `20261008103535_crowd_v4_navigation_recovery`，允许上一轮导航摘要与固定调度计数；仍只保存一条当前状态，关闭诊断清除。
4.1.3追加已部署的 `20261008152415_crowd_v4_navigation_commit`，仅增加空白/待提交文档枚举与固定导航失败码，旧客户端兼容。
4.2.0追加已部署的 `20261008155351_crowd_v4_trace_updates`，允许24个严格固定事件节点和更新状态，单个快照上限8192字节；无新授权。
应用后核对函数定义、权限、数据库 advisors 和 `server/crowd/v4/health.sql`。

## 4. Mac 更新与验收

保留原浏览器个人资料和插件安装目录。安装助手只准备/覆盖文件；本人仍需在扩展管理页加载或刷新并确认版本。
不要卸载后重新报名，不要覆盖原生产 v3 个人资料，不要将 v4 接入根目录旧 `updates.xml`。两套系统的扩展公钥/ID相同，协议和身份不同。
浏览器运行且参与者已同意并启动才会执行；系统睡眠时暂停。停止、登录失效和风控暂停都需要本人处理。
验收以真实记录入库、正确字段、停止后不再执行及唤醒恢复为准，不能用打包成功替代。

## 5. 暂停与回退

先辨认协议：原生产暂停用 `public.crowd_config` 的 `global_pause`；v4用已有服务端管理接口 `crowd_v4_admin('control', '{"paused":true}')`（仅 service_role）。两者不互相代替。
v4 每次页面动作都经 guard，控制检查独立于领取任务。服务端不可用时停止新页面动作，待回传原证据保留。

客户端回退：把已验证逻辑作为更高补丁版本构建，再由原浏览器刷新；不承诺降低版本号可自动更新。
SQL回退：用已审阅的补偿迁移恢复函数，不删除 proof/receipt/奖励，不重跑整个历史链。
保留本次新增的调度列不会破坏旧 RPC；不能为回退清空参与身份或原始证据。

凭据位置见 [HANDOFF.md](HANDOFF.md)，所有管理凭据仅用于服务端。


## 4.2.4 KOL上线增量（2026-10-09）

服务端已通过连接器应用 `crowd_v4_kol_watchlist`，实际迁移历史版本为 `20261009011631`。本地迁移由CLI初始生成，发布后仅将文件名前缀对齐服务端实际版本；SQL内容SHA256保持 `41cbedb3a7468bfd1d506154436c8692779b44aa2723e99a78717b9cf9fb8a18`。不要再应用初始工作名20261009001246。

新增13张私有RLS表及经过身份/owner验证的 `public.crowd_v4_kol` RPC。匿名无执行权限。后端部署不启动采集，没有创建生产测试身份或证据；原参与身份、proof/reward和旧RPC保留。接口见 `server/crowd/v4/KOL_RPC.md`。

客户端4.2.4新增名单、CSV、周期/历史有界任务、XHS/B站适配、版本/评论实体、脱敏导出、本人账号导航核验与独立授权后处理。真实账号导航观测仍由客户端申报，不是服务端独立认证平台账号。周期执行依赖插件在线，不承诺完整历史、全评论或绝不封禁。

新增B站host权限和内容脚本，4.2.3更新助手会拒绝自动扩权。发布需要明确的新权限bootstrap，原浏览器本人刷新并确认。保持旧签名channel.json不变，另存本版签名清单供验证；不让所有旧设备反复遭遇permission_change，也不假称原设备已升级。后续同权限版本可沿原签名机制更新。

本机授权工具包括Vision OCR、公开CDN有界下载、TXT/VTT/SRT导入和有条件设备端语音识别。Speech缺本机模型或系统授权时停止，不用云端替代。模型/授权与真实平台数据质量属于发布后验收。

回退：先暂停新KOL来源任务，保留数据库及队列，继续接收合法既有准入结果；不得删除新schema、原身份或本地kol outbox。客户端问题用保留相同权限形状的更高补丁版本恢复逻辑；不降低版本、不重建身份。未达到源站长期验收前，不扩大设备/账号/采集量。


## 4.2.5增量部署（2026-10-09）

按生产历史先20261009040306_crowd_v4_kol_recovery，再20261009040629_crowd_v4_kol_diagnostics，均已应用。服务器保存SQL摘要与本地一致。原RPC保持兼容；新执行器、来源尝试与ACK检查点、明确交接、正常零新增周期、图片评论类型及脱敏KOL状态已接入。未知来源不重发，不清预算；完整覆盖保持未验证。测试见kol-recovery-db.mjs（19组）和kol-db.mjs（33组）。

新bootstrap助手固定channel-kol.json，与旧channel.json隔离。不得直接替换旧通道以强推新权限。保留签名、SHA、sequence、权限检查、握手和回退。原设备一次明确迁移后才可接新通道；公开安装包不等于已经安装。更多平台、全量评论/历史、实机两条与长期质量仍单列。
