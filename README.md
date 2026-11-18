# 众包 / KOL 项目快照：整理期入口

当前暂停采集开发与部署。下方原 README、docs/DEPLOY.md 与 docs/HANDOFF.md 是历史说明，不是本轮执行指令；不据此安装、跑迁移、恢复定时任务或访问生产。

## 代码属性与去留

业务筛选基线：[0ce911159a4b2f6d78d9f19145deb958d4c5efd0](https://github.com/huming0018-dot/crowd-kol/tree/0ce911159a4b2f6d78d9f19145deb958d4c5efd0)。本批覆盖下表八个业务脚本；`kol_cross.py` 由另一批处理，SQL 链、线上服务和调度不在本批验收范围。

完整性、价值与归属分别判断：以下有真实输入输出的项目核心保留；校准缺项或局部反例限制其承诺范围，不据此删除整套业务代码。所有保留项属**项目**，本批不新增模型、共享基建或通用工具资产。

| 范围 | 完整性与保留价值 | 边界 |
|---|---|---|
| `server/crowd/crowd_score.py` | rating/owner/task → 证据池化、Beta 后验/CI、菜系内排名、输入版本；折扣和 owner 锚具有项目语义。保留离线计算核心。 | 校准恒等、note 不入池、all/owner BT 证据相同是源码明确的骨架范围；准入/发布产品未闭合。DELETE 后 POST 的远端写入非事务，不验收或恢复写库。 |
| `server/kol/kol_monitor.py` | 餐厅索引保留多分店，唯一名/明确区线索可锚定，无消歧信息则留空；未知线索另路由，具有项目防错绑用途。 | 词表情感不是准确情感模型；已知 mid、结果缺 mid 仍会通过作者过滤，不能宣称严格身份核验完成。渠道可达性未测。 |
| `server/kol/kol_post_ingest.py` | 唯一店名/别名最长匹配、归属窗口、帖子与提及载荷映射均有实际实现，保留项目机械归档核心。 | 同名店折为首项；“不好吃”判正；重复提及未逐次定位，会串配后续情感。不能作为可靠消歧/情感工具；两次归档请求不是原子事务。 |
| `server/kol/kol_identity.py` | 搜索结果、已知 mid、公众号发布者 → handles 计划；同名多结果和 mid 冲突有真实拒绝分支，保留项目身份核对流程。 | `merged.update(new)` 会覆盖已有平台键，与文件承诺的“已写平台跳过”不符；不能宣称幂等保留既有绑定。未执行搜索或 PATCH。 |
| `server/kol/kol_router.py` | 线索守卫、独立 KOL 聚合、可选地图核对与分级是项目发现规则，不直接建店或写 taste。 | `幸福饭店` 被尾缀规则全剥离后拒绝；地图适配不在仓内，缓存无保鲜。守卫是启发式，不等于实体真实性判定。 |
| `server/kol/kol_trust_grade.py` | 人工精选池/别名 → trust 变更计划；S/A→high、B→mid 是完整的项目政策映射。 | 包含匹配只限制池名字数，“甲”可命中“甲作者”；不能作为身份认证或可信度模型。精选池内容未重新背书。 |
| `server/kol/kol_context_backfill.py` | 精确店名 → 前后各 40 字；找不到留空。保留小型项目数据回填规则。 | 只定位首次原文精确出现，不承诺别名/语义匹配；数据库入口未运行。独立维护为通用库收益不足。 |
| `server/crowd/crowd_tracking.py` | 三表 → 任务缺口、回流/活跃聚合、时区正确的 24h 窗口与报告；业务统计有用。 | notifier 为仓外依赖，通知/账本/cron 未验收或恢复；不能把聚合可测等同播报交付完成。 |
| `_lib`、cron、SQL、设计/研究材料 | `_lib` 保留边界见 [已有报告](docs/KOL-LIB-BOUNDARY.md)；其余按项目运行编排/数据契约/历史材料保留待各自范围验收。 | 本批不重审 `_lib`，不执行 SQL；结算/入库 cron 仍依赖仓外入口，不据此声称整个项目独立闭合。 |

本批不删除业务实现：其核心有项目用途，反例不足以证明整体无价值；不为整理而补做采集、身份、情感或评分功能开发。启发式经验不单独晋升共享实现。

离线复验（只用合成输入，HTTP/通知边界隔离，不读本机凭据）：

```bash
python3 -B -m unittest discover -s tests -p test_project_core_contracts.py -v
python3 -B server/crowd/crowd_score.py --dry-run
```

16 项新增检查验证正常契约，不掩盖上表反例；mock 仅替代外部 I/O，不证明真实渠道或数据库可用。KOL 各 CLI 即使默认 dry-run 也可能读库/搜索，不能当作离线检查命令运行。

已合并退出范围：[PR2](https://github.com/huming0018-dot/crowd-kol/pull/2) 删除一份同 blob SQL 备份；[PR3](https://github.com/huming0018-dot/crowd-kol/pull/3) 裁剪 `_lib` 中的跨项目副本并保留实际依赖核心。[整理前恢复点](https://github.com/huming0018-dot/crowd-kol/tree/3b75121e18631acb4d30524d5feea8b1fe8ad277)。本批未修改业务源码、线上分发、生产、采集或结算；不宣称全仓或产品验收完成。

---

## 历史 README（非当前操作指令）

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
