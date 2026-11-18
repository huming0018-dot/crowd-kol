# KOL 基础代码边界筛选

## 范围与属性
固定本仓 [5a940fbe6fa8134eabafea14394e1d51a5b838b4](https://github.com/huming0018-dot/crowd-kol/tree/5a940fbe6fa8134eabafea14394e1d51a5b838b4)。完整读三份_lib实现及9个Python消费者；本次只改common.py、authority_sitemap.py，新增离线测试。未审SQL迁移链，不声称全仓验收。

四类归属：三份都是项目支撑代码，不是模型；HTTP配置虽有基建形态，但带本项目路径/凭据/业务约定，留项目，不晋升共享基建；本次无新工具仓。

两份原文件与美食仓固定1dddf6e5dbca45b77a9e4e894010a463426b863d的cloud/vendor/pipeline对应文件逐字相同：common blob06360e2ba9cdc25a41b308ece56bd0db7ff76824；authority_sitemap blob1b79127778786ec042b403ca114361d5f9c71ae5。不是仅凭同名推断副本。完整原件保留在两仓Git历史，本次不改美食仓或部署。

## 保留的核心
|范围|输入→输出 / 依赖|价值与完整性|
|---|---|---|
|common.load_env/headers/req/fetch_all|环境/配置文件→请求配置；HTTP响应→分页行；requests+标准库|KOL实际消费的项目数据访问边界，正常分页/重试路径完整，原函数AST不改。不是通用SDK；真实服务、并发快照及配置运维未验收。|
|common.cjk_unify/cjk_norm|名称→跨字形、小写与去标点文本；可选OpenCC|多个真实KOL消费者使用，直接保留实现及可选转换行为，不升级为全语言归一承诺。|
|common.looks_like_brand及词表/OUT_CITIES/STATUS_CLOSED|token→布尔/原因；本地美食业务词表|KOL明确依赖的候选守卫，留项目，原规则不改；启发式不是实体真实性证明，不声称覆盖所有店名。|
|authority_sitemap.core/eligible及_norm_digits/_han/_cjk_count|名称→品牌核心/长度门槛；依赖common.cjk_norm|monitor/router只用这两个公开函数；核心完整，保留原行为。模块名暂保留以不改消费者导入，不再夹带米其林网络流程。|
|common_core全文件|配置/HTTP/日志/通知/管线定位|tracking使用config/fetch_all/log，保留不动。正常路径与局部限制区分：用假秘密验证_redact只替换标记而保留值；不据此把整模块判无价值，也不在本次修功能。不得当通用脱敏库。|

## 退出的副本与理由
|原组|判定|
|---|---|
|authority的浏览器导航、sitemap分页、缓存、主列表/详情、reconcile/run/reconcile_cached|上海米其林项目专用完整流程形态，依赖bu、权威底册与数据库；KOL只消费文本核心，不承担此来源渠道。退出跨项目副本而非宣称流程全坏；缓存/网络真实性未运行。|
|authority.make_matcher/slug_brand_cores/_distinct/_han_abbrev_hit等匹配辅助|服务上述对账，KOL没有调用。离线同名不同区输入被选首项exact，不能作为独立实体识别工具；随对账副本退出，历史可恢复。|
|common电话清洗/分类、地点编码解析、上海边界/价格档/菜品清洗|属于美食入库/前端数据管线而非KOL核心。本身有正常可用功能，不以未调用认定残缺；完整同字节实现在美食历史可得，避免本仓维护第二份。parse_location字典lng=0返回None而列表0正常，仅记录边界，不为修它扩本轮范围。|
|common norm_name/addr_core/normalize_brand_name/note_is_out_of_shanghai/quote_has_substance/source_kind|未被本仓KOL消费的美食特定规则；不是成熟通用能力。source_kind把无关域名查询串中的dianping.com判ugc，不能作域名权威校验。保留真正消费的cjk/品牌守卫，不整包挪工具仓。|
|common read_jsonl/write_jsonl/today/to_int及其独立常量|标准库薄壳或上述管线辅助，独立维护收益不足，随项目副本退出；不声称这些函数都残缺。|

## 验证与边界
- 12个保留函数的AST与原件完全相同，参数/函数体不改；依赖闭包保留必要导入、常量及OpenCC可选初始化。
- 17类输入×4函数，共68个原件/裁剪后差分一致（含空值、别名、中文数字、短名、品牌/菜品）。这是行为保持，不证明启发式全正确。
- 6项离线测试通过：名称/门槛、退出API不可见、合成配置、HTTP重试、分页、现仓7个kol消费者要求的C/S属性全部仍在。
- requests在测试中为mock模块，所有HTTP为假响应，不需要密钥；没有执行采集、数据库或浏览器调用。正常库仍依赖真实requests，测试不冒充服务验收。
- 扫描基于当前仓Python显式C/S属性；仓外动态消费者未核。未改部署脚本、业务消费者或common_core，不可直接推断生产可无审部署。

复验：`python -m unittest discover -s tests -p test_kol_lib_boundary.py -v`。恢复完整旧_lib用上方固定Git树，不要另复制活动旧包。
