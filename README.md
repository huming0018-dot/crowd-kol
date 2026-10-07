# crowd-kol · 众包采集 + KOL 采集协作仓库

> 单一事实源（canonical）：众包采集系统的**服务端**与 **KOL 采集子系统**的协作主仓。
> 本仓是协作入口；代码真源按「仓库地图」分仓管理，杜绝多点漂移。

## 仓库地图（什么代码以哪个仓为准）

| 仓 | 内容 | 地位 |
|---|---|---|
| **本仓 crowd-kol** | 众包服务端（SQL 迁移链 / 播报 / 评分 / 结算 cron）+ KOL 子系统（路由/监控/身份/评级/回灌 + 精选池 + 库迁移） | **canonical** |
| [crawler-extension](https://github.com/huming0018-dot/crowd-extension) | 浏览器扩展（Chrome MV3 / Firefox 双形态，v1.0） | 扩展 canonical |
| [crowd-pages](https://github.com/huming0018-dot/crowd-pages) | 分发面（安装页/提交页/状态页/owner 评价页 + GitHub Pages 托管 + 安装产物 Releases） | 分发 canonical |
| [china-travel-food](https://github.com/huming0018-dot/china-travel-food) | 食品图鉴主项目（主库 score_diner、KOL 运行环境、食物 DB） | 主项目（本仓的 KOL 与 crowd cron 部署到这里/对应服务器运行） |

**协作纪律**：改代码先改 canonical 仓；部署是单向同步（canonical → 运行环境），绝不反向手改运行环境。

## 目录

```
server/
  crowd/            # 众包服务端（Supabase Postgres + RPC + 定时任务）
    sql/            # 迁移链 v3.2.3 → v3.5.0（幂等，按序执行；生产执行记录见各文件头）
    cron/           # 播报(每3h)/结算(周一)/入库(每日) —— 服务器 crontab 已挂
    crowd_tracking.py   # 每 3 小时 TG 播报（Supabase 中继）
    crowd_score.py      # 口味评分 S3：Beta 后验 + BT 排名 + CI（确定性可复算）
  kol/              # KOL 采集子系统（发现入口，非口味证据）
    kol_identity.py     # KOL 身份解析（跨平台同一人归并）
    kol_router.py       # 采集路由/调度
    kol_monitor.py      # KOL 内容监控
    kol_cross.py        # 跨平台交叉验证
    kol_trust_grade.py  # 可信度分级
    kol_context_backfill.py # 上下文回灌
    kol_post_ingest.py  # 入库后处理
    _lib/               # 依赖支撑（common.py / authority_sitemap.py / common_core.py）
    db/migrations/      # KOL 表迁移（011_bili_kol / 013_kol / 016_kol_handles / 023_kol_identity）
    research/authority/ # KOL 精选池（kol_seed + kol_curated_pool：立场清晰、口碑可验证）
docs/
  DEPLOY.md         # 众包系统完整部署手册（凭据索引/发版/回滚/熔断/踩坑表）
  designs/          # 设计稿：安全线 v2 类人调度 / 口味评分体系 v1 / 多源合规评估
```

## 两条采集线的关系（不要混淆）

1. **众包采集**（`crawler-extension` + 本仓 crowd/）：参与者用自有账号/设备/网络，按中枢分配的店铺关键词采小红书公开笔记与口味评分，服务端裁决去重、按条计酬（¥0.01/10 条）。目标是**真实食客 UGC**。
2. **KOL 采集**（本仓 kol/）：KOL 只作**发现入口与特征标签**——KOL 提到的店必须回到真实食客 UGC 核验、过 admission（≥2 独立声音、均分≥3.5）才收录。精选池立场标准见 `server/kol/research/authority/kol_curated_pool.md`。

## 快速上手

```bash
# 服务端迁移（Supabase Management API 或 SQL Editor，按文件名序执行）
psql < server/crowd/sql/crowd_fix_v323_reconcile.sql  # …按序到 crowd_fix_v350_owner_taste.sql

# KOL 表迁移（食品主库）
psql < server/kol/db/migrations/011_bili_kol.sql  # …按序到 023_kol_identity.sql

# 定时任务（服务器 crontab 样例）
7 */3 * * *   cloud/cron/crowd_tracking_cron.sh     # 每 3 小时播报
30 6 * * *    cloud/cron/crowd_store_ingest_cron.sh # 每日证据入库
0 9 * * 1     cloud/cron/crowd_settlement_cron.sh   # 周一结算
```

## 运行状态入口

- 实时状态页：https://huming0018-dot.github.io/crowd-pages/status.html
- owner 评分页：https://huming0018-dot.github.io/crowd-pages/owner-rate.html
- 安装遥测：`crowd_install_log` 表（装不上时直接看死因，不用截图接力）
- 熔断：`update crowd_config set value='true' where key='global_pause';`

## 凭据（一律不进任何仓库）

`~/.food_atlas_credentials.md`（SBP 管理令牌、AMO）、`~/.food_atlas_credentials/`（扩展签名私钥、ops_secret、owner_secret）、`~/.ssh/food_cloud_deploy`（生产服务器）、`~/.config/gh`（GitHub token）。详见 docs/DEPLOY.md 凭据索引。

## License

MIT
