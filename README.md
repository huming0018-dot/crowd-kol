# 众包服务端与 KOL 协作仓

这是服务端与 KOL 的权威源码仓。当前状态和版本只认 [V4_ITERATION.md](docs/V4_ITERATION.md)，部署按 [DEPLOY.md](docs/DEPLOY.md)，接手按 [HANDOFF.md](docs/HANDOFF.md)。

| 范围 | 权威位置 |
|---|---|
| 众包服务端、KOL | 本仓 `server/crowd`、`server/kol` |
| 浏览器客户端 | [crawler-extension](https://github.com/huming0018-dot/crawler-extension)，当前迭代在 `v4/` |
| 页面与安装产物 | [crowd-pages](https://github.com/huming0018-dot/crowd-pages)，私有 v4 构建在 `v4/` |
| 食品图鉴主项目、运行环境 | [china-travel-food](https://github.com/huming0018-dot/china-travel-food)，接受单向部署 |

代码只在对应权威仓修改。分支 `codex/v4.0.6-handoff` 是延续分支名称，不是当前版本号；客户端版本以 `v4/manifest.json` 和包内 `release.json` 为准。

## 三个独立范围

- 原生产：`server/crowd/sql`、cron、tracking、score，对应 `public.crowd_*`；保留现有运行链。
- v4 内测：`server/crowd/v4`，使用认证后的 `crowd_v4_*` RPC、私有 `crowd_v4` schema。接收、核验、奖励是不同状态，不得把原生产数量算作 v4 产量。
- KOL：`server/kol`，只产生发现线索与特征标签，不直接充当口味证据。身份、路由、监控、跨平台核验、可信度、回灌、入库后处理、四个迁移与精选池均在本仓；食品库准入仍须独立食客证据。

[设计稿](docs/designs/README.md) 是设计依据，不是上线状态证明。当前任务机制与 Kimi 的对照见 [TASK_SCHEDULING.md](docs/TASK_SCHEDULING.md)。

## 数据与奖励

v4 标准字段、非标字段和原文证据保存到 `crowd_v4.proofs.record`，初始状态 received，审核后才是 verified；奖励按每100条已核验且全局去重的记录0.10元累计。未核验、重复或仅发送成功不代表可结算，付款另记。
原生产 note 的0.01元/10条与其单条数学费率一致，但账本/批次/身份不同；原生产 rating 费率不能用于 v4。

管理密钥、签名私钥、私人邀请不进仓库。MIT。
