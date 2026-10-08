# 众包插件：本地 Mac 接力

## 4.2.0当前交付

- [原设备一次接通说明](https://raw.githubusercontent.com/huming0018-dot/crowd-pages/00fcaff0d1b86114abca472b6997ae38ac8f2f87/v4/releases/crowd-v4.2.0-bootstrap-mac.txt)。macOS14+；命令自动下载、校验、原位更新与安装助手，原浏览器须首次刷新一次。以后走签名通道，仅重载插件。
- 接通包176,871字节，SHA256 `decb62719219bdce65e19fb73845bb41514d32e3158c5b267e618d75fe573be6`，已从公开固定提交实下校验。生产助手已实际验证线上清单。
- 客户端`6ff00ed1cd913419eada357587ee88c1330cdcc2`；服务端`e2b72798ddc31ecf8033d12487d25a87837bb729`；分发`00fcaff0d1b86114abca472b6997ae38ac8f2f87`。三仓仍为同一交接分支，草稿PR#1。
- 2026-10-09 00:01真实隔离Chrome升级/坏代码回退通过，身份与证据保留，未重启浏览器。00:07后台原设备仍4.1.2/session_rest，真实入库0，未首次接通。不得扩大招募或声称采集已恢复。

> 最新2026-10-09：4.2.0自动更新助手与诊断链已实现并完成隔离Chrome升级/回退测试；原故障设备仍待一次接通，真实入库0。详见V4_ITERATION.md。

> 历史2026-10-08 23:25更新：已在Darwin执行真正安装扩展的Puppeteer测试并形成4.1.3候选。故障设备是另一台设备，首次导航故障仍未定位，真实接收0。新增导航诊断兼容迁移已部署。当前状态详见[V4_ITERATION.md](V4_ITERATION.md)；用户要求解决反复手动更新及诊断不足，审计见[UPDATE_DIAGNOSTICS.md](UPDATE_DIAGNOSTICS.md)。下面4.1.2提交、Linux状态和18:36快照均为接力时的历史，不是当前执行位置。

用户现在明确要求把本任务转到本地 Mac 开发与运行。此请求允许切换开发环境，不代表这台 Mac 就是出故障的参与者设备；不要让真实参与者安装 Codex，也不要把管理员浏览器身份当作参与者身份。

## 先确认执行位置

当前原会话实际执行位置仍是 Linux `/workspace`，尚未完成迁移。不要凭会话标题、历史 `/Users/...` 路径或浏览器截图认定已在 Mac。
进入本地工作区后先执行 `uname -s`、`pwd`，确认 Darwin 和用户指定的项目目录；检查本地 AGENTS.md 与未提交改动。历史目录尚未核实，不能打开另一个无关任务目录代替。

## 源码与交付

三仓工作分支均为 `codex/v4.0.6-handoff`，分支名不是版本号。以下提交已推送；如本地存在更新提交，先审阅差异，不能覆盖用户修改。

| 仓库 | 负责内容 | 4.1.2 已确认提交 |
|---|---|---|
| huming0018-dot/crawler-extension | 客户端 canonical，代码在 v4/ | 7eec05f26b4872e9c519590ef69637008a17565b |
| huming0018-dot/crowd-kol | 服务端、迁移、健康查询与交接 | e9e7f2dea97c4fc1442ca4d960fb7034e974b2ca，之后仅追加本接力文档 |
| huming0018-dot/crowd-pages | 构建与分发面 | 7f31987c87beae43f772dcc68e61946ead28c9c0 |

china-travel-food 是食品主项目及部署终点，不能反向覆盖三个 canonical 仓。Kimi 根目录生产扩展和 v4 协议不同，不能混装或按版本数字猜新旧。

- [现有参与者一条命令更新说明](https://raw.githubusercontent.com/huming0018-dot/crowd-pages/7f31987c87beae43f772dcc68e61946ead28c9c0/v4/releases/crowd-v4.1.2-update-mac.txt)
- [不含邀请的更新包](https://raw.githubusercontent.com/huming0018-dot/crowd-pages/aa244491e274f57ba195db19bcd9a5715f4aeb34/v4/releases/crowd-v4.1.2-update-mac.zip)
- ZIP 48,712 字节，SHA256 `55a63bdb0d0b9107602da331ba4befe2aab412d67a5f52e7f7fc40847a1db206`。公开地址已实际下载并校验。
- 原扩展 ID `licijehcpohikchlnkbpjdjdfkcocndg`；更新保留原浏览器个人资料、参与身份和进度。不得卸载重报，不公开旧的含邀请试点包。

## 已修复与仍未证明的部分

1. `document_end` 接收器在网页解析被同步脚本阻塞时根本未安装，即使已有可见搜索结果。现改为 `document_start` 接入，按实际可见内容检查就绪与验证门。
2. 搜索导航后才保存阶段，后台进程若在两者之间消失会重复导航、重复消耗准入次数。现先保存阶段与期限再导航，恢复时继续探测。
3. 新标签页先登记归属再导航，防止快速导航事件漏记；重试保留上一轮导航摘要、失败次数和调度等待，退出诊断全部清除。

前两项回归已分别证明旧代码失败、新代码通过。客户端/恢复/身份/预算/诊断退出、Chromium 固定页面到隔离 PostgreSQL 入库与幂等回执、构建摘要验证通过。
云 Chromium 的管理员策略禁止安装未打包扩展；加载用例使用真实网页解析过程、按 manifest 模拟注入时机，**没有验证真实扩展引擎或 Mac 实机**。外部完整业务并发数据库未配置，明确 SKIP。
这些缺陷存在不等于已证明现场全部原因；不要再把启动、心跳或固定页面测试叫作真实采集验收。

## 后台与最新已知状态

Supabase 项目 `bdwrhshgdeghgyzwpxnl`。数据区 `crowd_v4` 与 `crowd_observation`，旧生产 `public.crowd_*` 的产量不能混计。
迁移 `20261008103535_crowd_v4_navigation_recovery` 已部署、权限回验通过，勿重跑。此前观察区、别名和登录诊断迁移也已部署。
凭据用现有授权连接器或本地已配置环境，不从交接文件索取密码，不打印/复制用户 Cookie、令牌或私钥。

最后一次已确认只读查询为 2026-10-08 18:36:43 北京时间：设备仍 4.1.1，连续失败后 enabled=false，page_loading、started、no_receiver，真实接收 0。这是历史快照，接手必须刷新 `server/crowd/v4/health.sql`，不能当作实时状态。
旧待处理记录解析版本 4.0.7，已按原证据复核一次，仍 unrelated_note；不是新版成功采集的证明。

## 本地下一步

1. 确认 Darwin、项目目录和三个仓的实际提交，读取 [HANDOFF.md](HANDOFF.md)、[V4_ITERATION.md](V4_ITERATION.md)、[DEPLOY.md](DEPLOY.md)。
2. 在独立测试浏览器资料中验证真正的扩展安装、后台标签页导航、早期内容脚本接入、worker 回收恢复；不要复制或修改参与者的真实浏览器资料。
3. 只读刷新后台，确认真实参与者是否更新到 4.1.2，并核对 nav/probe 状态、上一轮摘要及真实 proof。没有更新时不能声称客户端修复已生效。
4. 以真实搜索→详情→标准/非标/证据字段入库、回执去重、停止、唤醒恢复为验收；遇验证或限流仍暂停，不绕过，不扩大招募。

本地代码改动继续提交 canonical 仓，再单向构建更新包；相关草稿 PR 为三个仓的 #1，已附在原会话。
