# 接力包核对与 v4.0.6 迭代

本轮阅读了 HANDOFF、DEPLOY、三份设计稿、KOL 路由/可信度/精选池，以及 quota 回执、逐项裁决、known_note_ids 等对应源码。沿用 Ponytail，只修已经发现的根因；文档中的安全阈值、合规判断及“无缝接手”不作为运行证据。

## 权威仓与协议

| 范围 | 权威位置 | 运行边界 |
|---|---|---|
| v4 客户端 | `huming0018-dot/crawler-extension/v4` | 由原 4.0.5 导入后迭代；根目录 v1.0 保留 |
| v4 服务端 | 本仓 `server/crowd/v4` | 私有 schema `crowd_v4`、`crowd_v4_*` RPC |
| v4 私有打包 | `huming0018-dot/crowd-pages/v4` | 只生成本机 ZIP，不自动改 Pages、updates.xml 或签名通道 |
| 原生产 / KOL | 本仓既有 `server/crowd` / `server/kol` | `public.crowd_*` 与 KOL 表保持各自契约 |
| 食品主项目 | `china-travel-food` | 部署终点；原 4.0.5 快照保留，不再在那里开发本次客户端/SQL |

旧文档中的 `huming0018-dot/crowd-extension` 链接错误；该地址本次读取返回 Repository not found，用户指定并成功读取的是 `crawler-extension`。其根 manifest 为1.0.0/提交5b9e327；Pages 产物为3.4.14，不代表该根目录就是最新生产源码。旧47/47测试在本机未提供的 crowd-platform/test-harness 中；本轮不冒称运行过它。

一次性导入来源为 china-travel-food `82cafb76d6b8c1f9709e1ecf53daf86ac4d50d67`，各 v4 目录的 IMPORTED_FROM.json 记录路径与原始SHA256。新代码只在上述权威仓编辑；不建立反向同步。

## 当前事实

2026-10-08 02:07 UTC只读检查：legacy共287条、accepted 278条；v4 received=0、verified=0；两套暂停均false。v4最近诊断是2026-10-07 13:17 UTC的4.0.1/page_timeout。这是旧快照，不是设备此刻仍在运行的证明。使用 `server/crowd/v4/health.sql` 重新核对，不能把旧链路产量算成v4成功。

旧note费率0.01元/10条与v4上限0.10元/100条单条数学费率相同，但**结算批次、身份、核验门、账本不同**。旧rating的1元/条不导入v4；不自动创建评分任务，不改变奖励或付款状态。

## 本次实际改进

1. **有效回执才出队**：4.0.5原来对没有error的空对象也会shift待回传证据。现在要求原request UUID、`gate=received`、互补的inserted/duplicate布尔值、非负整数task_received。空/未知/错UUID/gate字段不符的响应保留原记录并退避；确定拒绝仍移到本机可导出的待处理区。绝不把`verdict`猜作`gate`。
2. **配额不是永久裁决**：v4 claim/submit在daily_quota响应里增加北京时间下一零点reset_at和相对retry_after_ms。客户端到期再用同一UUID及原内容重试；旧服务端无新字段时保守等1小时。SQL验证证明限额拒收不写receipts，额度恢复后同UUID成功，随后仍返回原成功回执；不改采集时间来绕过陈旧证据校验。
3. **减少无效详情访问**：被拒绝proof仍占据全局note_id唯一键，因此guard也跳过它，避免访问后注定duplicate。需要重审时走审核规则，不能换UUID冒充新笔记。
4. **可核对的发布包**：manifest/core版本一致；打包生成`background_v4_0_6.js`并设置唯一入口；release.json保存权威仓、协议、源码摘要和交付文件摘要。私有邀请注入后重新计算交付摘要；安装说明版本不再停在4.0.4。不是声称同名worker一定是此前故障根因。
5. **保留安全和证据边界**：4.0.5的持久化冷却/预算/独立控制、公开正文/阅读互动字段/有界评论、本人主动诊断继续使用。KOL只产生线索和特征，不能成为v4 verified或独立食客声音。未添加隐身指纹、验证码绕过、代理池、自动评分或公开转载。

## 验证

客户端：

```bash
cd /path/to/crawler-extension
CROWD_TEST_TOOLS=/path/to/existing-test-tools \
CROWD_MIGRATIONS_DIR=/path/to/crowd-kol/server/crowd/v4/supabase/migrations \
node v4/tests/run.cjs
```

服务端：

```bash
cd /path/to/crowd-kol
CROWD_TEST_TOOLS=/path/to/existing-test-tools node server/crowd/v4/tests/safety-db.mjs
CROWD_TEST_TOOLS=/path/to/existing-test-tools node server/crowd/v4/tests/recovery-db.mjs
CROWD_TEST_TOOLS=/path/to/existing-test-tools node server/crowd/v4/tests/diagnostics-db.mjs
```

工具目录需要现有 Playwright、Chromium、PGlite，仅用于开发，不随插件分发。上述实际通过：生命周期/停机恢复、原生桥源码、Chrome/Firefox源码适配、坏回执不丢证据、配额到期重裁、预算/冷却/去重/权限、Chromium固定DOM→隔离PostgreSQL真实claim/guard/submit/finish及丢回执幂等。浏览器夹具不是实机；可选外部空数据库完整业务测试未配置，跳过。新Mac包只含Chrome/Edge形态，未签发Firefox/手机成品。

## 单向构建与部署

```bash
cd /path/to/crawler-extension
python3 v4/build.py --output /tmp/crowd-extension-v4.0.6.zip
cd /path/to/crowd-pages
python3 v4/test_release.py /path/to/crawler-extension/v4
python3 v4/build_trial.py --source /tmp/crowd-extension-v4.0.6.zip \
  --invitation-file /private/mac-trial.json --output /private/Mac轻量内测-v4.0.6.zip
```

私有邀请码和管理员密钥不进git、Pages或公开Release。沿用原邀请，不新增报名、不覆盖v3个人资料、不调用旧根目录publish.sh。安装助手校验文件后更新原v4目录，参与者仍需在原浏览器刷新并确认版本。安装包不是“静默更新成功”的证明。

`server/crowd/v4/supabase/migrations`是v4迁移真源，旧文件为已部署历史，不在生产重跑。只应用本次`crowd_v4_receipt_recovery`增量；其锚点不符合当前函数时整笔回滚，保留search_path、权限和幂等逻辑。`functions/`是4.0.5既有Edge源码基线，本轮不改部署配置或重新发布Edge；其中配置占位符仍由受信部署流程渲染，不能直接部署模板。

## 尚待闭环

- 原Mac更新到4.0.6，真实搜索→详情→标准/非标/证据回传，停止及睡眠恢复验收。v4尚无真实产量，不能开放全员升级。
- 3.4.14生产源码与根v1.0之间仍需单独合并核对；当前三个PR只推进隔离的v4候选，不替换旧生产。
- 评分阶段二需要owner样本和单独的S2输入契约；本轮不启动LLM情感提取，不让采集器直接修改口味分。
- KOL镜像独有四文件已经在本仓，现有部署依赖仍需在对应容器/服务器验证；没有连接用户Mac或生产SSH来伪称cron、KOL运行成功。

## 交付与线上回验 · 2026-10-08

迁移 `20261008021710_crowd_v4_receipt_recovery` 已成功部署；只读确认 claim/submit 均有retry_after_ms，anon不能执行guard/submit，authenticated允许submit但不能直接读proofs。无新公开权限；既有 [authenticated SECURITY DEFINER提示](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable) 由auth.uid本人校验、空search_path和私有表权限限定。本次不调整无关旧模块告警。

02:19 UTC重新执行health.sql：legacy accepted仍278，近24小时189；v4仍0，诊断明确stale=true。没有把历史快照报成实时成功。

私有Mac候选包 `/workspace/Mac轻量内测-v4.0.6.zip` 为44,846字节，SHA256 `afa5298cafc1d393166149857eb4b277ddf08f4fd11387252e0d6366ae7d6708`。保留原扩展ID和邀请、2条/日试点配额，未生成新参与身份。release.json与SHA256SUMS逐项校验通过，未含管理密钥。此包不上传公开仓。
