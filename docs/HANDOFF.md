# HANDOFF · 接力包（2026-10-07 晚）

> 写给下一个接手的 agent：先读 `README.md`（仓库地图），再读本文件。
> 本文件只讲**当前状态、凭据、健康检查、未闭环事项、别再踩的坑**。

---

## 1. 系统是什么

两条采集线喂一个食品图鉴：

1. **众包采集**：浏览器扩展（Chrome MV3/Firefox 双形态）在参与者自己设备+账号上，按中枢分配的店铺关键词采小红书公开笔记与口味评分 → Supabase RPC 裁决去重 → 按条计酬（**¥0.01/10 条**，rating ¥1/条）。
2. **KOL 采集**：KOL 只作发现入口与标签，提到的店回真实食客 UGC 核验过 admission 才收录（`server/kol/`）。

**当前真实在跑**：3 台设备（主力 Mac P-6KSZWXEG 日配额 50、mini mac P-PX5S24GZ、安卓手机 P-9WTB6S2H，后两台爬坡中），累计收录 174+ 条，结算已通（4 人 ¥0.17 应收 pending）。

## 2. 四仓边界（改错地方必漂移）

| 仓 | canonical | 同步方向 |
|---|---|---|
| `huming0018-dot/crowd-kol` | 服务端 SQL/脚本 + KOL 子系统 + 设计文档 | → 服务器 / 主项目 |
| `huming0018-dot/crowd-extension` | 扩展源码（v1.0，ponytail 精简版） | → 发布通道 |
| `huming0018-dot/crowd-pages` | 分发页 + 安装产物（GitHub Pages + Releases） | → 公网 |
| `huming0018-dot/china-travel-food` | 食品图鉴主项目 + 运行环境 | 部署终点 |

**纪律**：改代码只动 canonical 仓；部署单向同步；绝不反向手改运行环境。
工作区还有两个 git 真源：`~/Documents/kimi/tasks/2026-10-03/16-42-43-5816bba8/crowd-platform`（扩展+SQL 日常开发仓）和 `…/crawler-extension`（v1.0 发布仓）。

## 3. 当前版本快照（2026-10-07）

- 扩展 **v3.4.14**（生产通道最新）：信封 12 条+已见库预过滤(v3.4.12)、作者昵称净化(v3.4.13)、弹窗评分入口+owner-rate(v3.4.14)
- 安装器 **v5**：手动挂载引导 + 自更新 LaunchAgent/任务计划（**策略通道已死**，见 §7 坑 1）
- 服务端最新迁移：`crowd_fix_v350_owner_taste.sql`（评分体系阶段一）
- 评分体系：阶段一已上线（M1 采集 + M0 owner 端 + S3 骨架 `server/crowd/crowd_score.py`）；阶段二未做（见 §6）
- 结算费率：**note ¥0.001/条（0.01/10 条）**，rating ¥1/条

## 4. 凭据索引（全部不进 git）

| 凭据 | 位置 | 用途 |
|---|---|---|
| SBP 管理令牌 | `~/.food_atlas_credentials.md`（SBP_TOKEN=，sbp_ 前缀） | Management API 执行 SQL：`POST https://api.supabase.com/v1/projects/bdwrhshgdeghgyzwpxnl/database/query` |
| anon/publishable key | 扩展 `src/config.js`、status.html 内（公开可分发） | 参与者端 RPC |
| service_role key | `~/Desktop/桌面 - 胡博文的MacBook Pro/china-travel-food/app/.env.local`（SUPABASE_SERVICE_ROLE_KEY） | publish.sh 上传、管理 SQL |
| 扩展签名私钥 | `~/.food_atlas_credentials/crowd-extension-key.pem`（备份）+ crowd-platform/crowd_extension/key.pem | **crx 自动升级链命根子，丢了全员断链** |
| ops_secret / owner_secret | `~/.food_atlas_credentials/crowd-ops-secret`、`crowd-owner-secret` | 遥测 RPC / owner 评分页 |
| AMO | `~/.food_atlas_credentials.md`（邮箱/密码/TOTP + **API issuer/secret**，签名已可全自动） | Firefox 签名 |
| GitHub | `gh auth token`（huming0018-dot） | 建库/Pages 推送 |
| 服务器 | `~/.ssh/food_cloud_deploy` → ubuntu@49.234.35.92 | cron/部署 |
| Supabase 项目 | bdwrhshgdeghgyzwpxnl（ap-northeast-1） | 全部后端 |

## 5. 健康检查命令（先跑这些再动手）

```bash
# 后端总览（收录/任务/参与者）
curl -s -X POST -H "apikey: $ANON" -H "Authorization: Bearer $ANON" -d '{}' \
  https://bdwrhshgdeghgyzwpxnl.supabase.co/rest/v1/rpc/crowd_status_summary | jq .

# 安装遥测（装不上时直接看死因，不用截图接力）
# SQL: select run_id, step, msg, created_at from crowd_install_log order by id desc limit 20;

# 结算/入库 cron（服务器）
ssh -i ~/.ssh/food_cloud_deploy ubuntu@49.234.35.92 \
  'tail -5 /home/ubuntu/china-travel-food/.pm_dispatch_data/crowd_store_ingest_cron.log; \
   tail -8 /home/ubuntu/china-travel-food/.pm_dispatch_data/crowd_settlement_cron.log'

# 扩展回归（任何扩展代码改动后必跑）
cd crowd-platform/test-harness && npm install && node run-all.js   # 需 47/47

# 评分骨架（只算不写）
SUPABASE_SERVICE_ROLE_KEY=... python3 server/crowd/crowd_score.py
```

## 6. 未闭环事项（按优先级）

| # | 事项 | 状态/下一步 |
|---|---|---|
| 1 | **信封×2 产出率验证** | v3.4.12 上线后观察 24h：status.html 今日+N 与去重占比；未达预期 → 做中枢按剩余供给智能分配（枯竭词降权，设计在会话记录里） |
| 2 | **评分体系阶段二** | 校准映射（isotonic，需 owner 数据积累）、note 情感抽取（需 LLM 授权）、菜系 taxonomy、准入裁决（§4.1 G1–G4）、BT 的 CI、rating 是否占 note 配额 |
| 3 | **机队落地** | 5 张最低档流量卡（~125 元/月）+ 二手安卓机（别同型号同批），流量卡/手机/账号固定配对，宽带最多带 2 台 |
| 4 | v7 模糊关键词沙盒 | `crowd-platform` git 分支 `sandbox/v7-fuzzy-keywords`（admin.html），本地化沙盒未发布 |
| 5 | iOS 快捷指令重写 | 旧版 6 层致命缺陷已下架；用 cherri 等真实工具链重建+真机回归；iOS 现只有网页版 |
| 6 | owner 用 owner-rate.html 开始评分 | 密钥在 `~/.food_atlas_credentials/crowd-owner-secret`，S3 需要 owner 证据做锚 |
| 7 | Windows 真机首测 | v5 .bat 未真机验证（任务计划自更新 + 手动挂载引导） |
| 8 | 分发/拉新 | 5 人阵容目标（现 3 台）；邀请卡 `分发物料/邀请卡-扫码参与.png` |

## 7. 别再踩的坑（血泪史，每条都踩过）

1. **Chrome 企业策略通道已死**：非企业机（无 MDM/域/Enterprise Core）强制安装非商店扩展一律 `[BLOCKED]`（chrome://policy 实锤）。唯一活路 = v5 手动挂载 + 自更新器。
2. **`--load-extension` 被 Chrome 154+ 拒绝**（`extension_service.cc:423` 官方日志）；Secure Preferences 有 MAC 校验，脚本注入注册会被清。
3. **Chrome 缓存同名 SW 脚本**：改 background 内容必须**连文件名一起改**（background_vXXXX.js）+ 升版本号，否则悄悄跑旧代码。
4. **Supabase Storage 对 text/\* 强制 text/plain**：updates.xml 走这里会杀死 Chrome 更新通道——**Chrome 更新产物（xml/crx）只走 GitHub Pages**；bucket 只放二进制。
5. **服务端契约字段**：结果数组字段叫 `gate`（不是 `verdict`）；写契约注释必须与实现一致。
6. **quota_exceeded 是时效信号不是裁决**：幂等回执缓存会把时效拒绝永久毒化——服务端已对 quota 类回执做删除重裁。
7. **服务器 cron 的密钥路径**：统一用绝对路径 `/home/ubuntu/food-cloud/deploy.env`（相对路径 `./cloud/deploy.env` 不存在，曾致结算/入库静默死数月）。
8. **结算取数用 `coalesce(accepted_at, created_at)`**：submit_proof 历史上不写 accepted_at。
9. **扩展私钥 key.pem 永不进 git**；AMO/TG/GitHub token 同理（AMO API 凭据已存 `~/.food_atlas_credentials.md`，签名脚本可复用）。
10. **KOL ≠ 口味证据**：KOL 只作发现入口；收录必须回真实食客 UGC 过 admission。

## 8. 高频操作速查

```bash
# 发扩展新版：改码 → manifest 版本+SW 文件名 → cd crowd-platform/crowd_extension
#   export CROWD_SERVICE_KEY=<service_role> && ./publish.sh   # Chrome 通道+Pages 同步
# Firefox 签名（AMO API，凭据在 ~/.food_atlas_credentials.md）：
#   上传→校验→建版本→轮询 public→下载→PUT 到 bucket crowd/crowd-extension-v<ver>-firefox-signed.xpi
# 执行 SQL 迁移：python + SBP_TOKEN POST Management API（§4）；迁移文件按 cloud/sql/ 序归档
# Pages 页面更新：gh api PUT /repos/huming0018-dot/crowd-pages/contents/<file>（gh auth token）
# 熔断：update crowd_config set value='true' where key='global_pause';（全员 ≤3min 停，含网页通道）
# 远程收紧安全线：update crowd_config set value='{"quota_day":N}' where key='safety_limits';（只紧不松）
```

—— 交接完毕。先跑 §5 的健康检查，再按 §6 的优先级动手。
