"""KOL 项目所用配置、HTTP、名称归一与品牌守卫。
保留现有语义，不是通用工具；其他美食管线副本已退出，见 docs/KOL-LIB-BOUNDARY.md。"""

import os

import re

import sys

import time

import pathlib

import requests

DEFAULT_APP = os.environ.get(
    "FOOD_APP_DIR",
    "/Users/hubowen/Desktop/桌面 - 胡博文的MacBook Pro/china-travel-food/app",
)

def load_env(app_dir: str = DEFAULT_APP) -> dict:
    env = dict(os.environ)
    p = pathlib.Path(app_dir) / ".env.local"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = load_env()

BASE = ENV.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/") + "/rest/v1"

SERVICE = ENV.get("SUPABASE_SERVICE_ROLE_KEY", "")

ANON = ENV.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")

def headers(use_service: bool = True) -> dict:
    k = SERVICE if use_service else ANON
    if not k:
        sys.exit("缺少密钥：检查 app/.env.local 的 SUPABASE_SERVICE_ROLE_KEY / NEXT_PUBLIC_SUPABASE_ANON_KEY，或设 FOOD_APP_DIR")
    return {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json"}

def req(method: str, path: str, use_service: bool = True, retries: int = 6, **kw) -> requests.Response:
    """带指数退避的 HTTP；429/5xx 自动重试。"""
    url = BASE + path
    last = None
    for i in range(retries):
        try:
            r = requests.request(method, url, headers=headers(use_service), timeout=45, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                last = r
                time.sleep(min(2 ** i, 15))
                continue
            return r
        except requests.RequestException as e:  # DNS/连接抖动
            last = e
            time.sleep(min(2 ** i, 15))
    raise RuntimeError(f"{method} {path} 连续失败: {last}")

def fetch_all(table: str, select: str = "*", page: int = 1000,
              use_service: bool = True, order_col: str = "id", extra: str = "") -> list:
    """分页拉全表（PostgREST 单页上限 1000）。restaurant_cuisines 用 order_col='restaurant_id'。"""
    out, off = [], 0
    while True:
        path = f"/{table}?select={select}&limit={page}&offset={off}&order={order_col}"
        if extra:
            path += "&" + extra
        r = req("GET", path, use_service=use_service)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out.extend(rows)
        if len(rows) < page:
            break
        off += page
        time.sleep(0.12)
    return out

STATUS_CLOSED = "closed"

_t2s = None

try:
    from opencc import OpenCC
    _t2s = OpenCC("t2s")
except Exception:
    _t2s = None

_JP2CN = str.maketrans({
    # 日文和制字 / 新字体（OpenCC 不转）
    "菓": "果", "舖": "铺", "寛": "宽", "沢": "泽", "竜": "龙", "黒": "黑",
    "桜": "樱", "麺": "面", "鶏": "鸡", "焼": "烧", "気": "气", "関": "关",
    "発": "发", "戸": "户", "斎": "斋", "酔": "醉", "剣": "剑", "続": "续",
    "豊": "丰", "栄": "荣", "駅": "驿", "銭": "钱", "舎": "舍", "実": "实",
    "塩": "盐", "弾": "弹", "麹": "曲", "亀": "龟", "働": "动", "枠": "框",
    "鰹": "鲣", "鱈": "鳕", "鯛": "鲷", "鮪": "鲔",
})

def cjk_unify(s) -> str:
    """繁体中文 + 日文汉字 → 简体中文（确定性、幂等）。"""
    s = str(s or "")
    if _t2s is not None:
        s = _t2s.convert(s)
    return s.translate(_JP2CN)

def cjk_norm(s) -> str:
    """跨字形统一归一：cjk_unify + 小写 + 去标点空白。店名/正文/招牌匹配统一用它。"""
    s = cjk_unify(s).lower()
    return re.sub(r"[\s·・•\-—_–'‘’\"“”`（）()【】\[\]+&]+", "", s)

SHOP_SUFFIXES = ("店", "坊", "馆", "苑", "屋", "堂", "房", "铺", "室", "社", "家",
                 "行", "记", "料理", "酒蔵", "酒藏", "軒", "轩", "樓", "楼",
                 "邸", "圃", "庵", "所", "部", "食堂", "茶居", "茶寮")

DISH_WORDS = (
    "可颂", "贝果", "酸种", "酸面包", "欧包", "吐司", "法棍", "恰巴塔", "丹麦",
    "菠萝包", "盐面包", "碱水", "肉桂卷", "司康", "巴斯克", "提拉米苏", "慕斯",
    "布丁", "冰淇淋", "冰激凌", "刨冰", "舒芙蕾", "松饼", "可丽饼", "马卡龙",
    "泡芙", "拿铁", "手冲", "美式", "奶茶", "鸡尾酒", "精酿", "抹茶", "蛋挞",
    "糖水", "鹅肝", "蜗牛", "龙虾", "螃蟹", "生蚝", "三文鱼", "金枪鱼",
    "拉面", "乌冬", "荞麦面", "蘸面", "豚骨", "米粉", "河粉", "粿条", "米线",
    "炒饭", "盖饭", "便当", "定食", "三明治", "汉堡", "披萨", "意面", "烩饭",
    "包子", "饺子", "馄饨", "锅贴", "生煎", "烧麦", "小笼", "汤圆", "春卷",
    "肉夹馍", "葱油饼", "烧饼", "烧鸟", "烤串", "烧肉", "烤肉", "和牛",
    "牛排", "猪排", "炸鸡", "牛肉", "羊肉", "猪肉", "鸭肉", "海鲜", "鳗鱼",
    "天妇罗", "关东煮", "火锅", "辣子鸡", "回锅肉", "麻婆豆腐", "水煮鱼",
    "酸菜鱼", "烤鱼", "佛跳墙", "烧鹅", "烧腊", "点心", "虾饺", "肠粉",
    "牛肉丸", "卤味", "凉菜", "咖喱", "冬阴功", "沙拉",
    "寿喜烧", "铁板", "怀石", "omakase", "pancake", "waffle",
    "croissant", "bagel", "sourdough", "tacos", "steak", "pizza",
    "pasta", "burger", "lobster", "crab", "salmon",
)

GENERIC_META = (
    "总结", "测评", "盘点", "红黑榜", "挑战", "打卡", "攻略", "必吃", "天花板",
    "宝藏", "绝绝子", "口感", "调味", "做法", "分享", "记录", "合集", "排行",
    "同款", "闭眼冲", "第一次", "第二次", "第三次", "年老店", "小而美",
    "咖啡店", "面包店", "甜品店", "试吃", "口味", "标签",
    "简短", "要不要", "再加", "末尾", "一句话", "推荐", "安利", "种草",
    "回购", "私藏", "无广", "真实", "体验", "vlog", "Vlog", "VLOG",
    "一天", "只吃", "五家", "十家", "几家", "哪家",
    "大家", "朋友", "本地", "地道", "正宗",
)

OUT_CITIES = (
    "长沙", "珠海", "北京", "天津", "重庆", "成都", "杭州", "汕头", "淮安",
    "广州", "深圳", "武汉", "西安", "南京", "苏州", "无锡", "宁波", "青岛",
    "大连", "厦门", "福州", "东莞", "佛山", "泉州", "温州", "台州", "常州",
    "合肥", "昆明", "贵阳", "兰州", "乌鲁木齐", "沈阳", "哈尔滨",
    "长春", "郑州", "洛阳", "海南", "三亚", "丽江", "大理",
)

FIELD_LABELS = {
    "门店地址", "地址", "电话", "联系方式", "营业时间", "开门时间",
    "个人cv", "个人CV", "cv", "CV", "菜单", "价格", "人均", "价位",
    "预约", "订座", "外卖", "配送", "停车", "wifi", "WIFI", "卫生间",
    "推荐菜", "招牌", "特色", "门店", "分店",
}

INGREDIENT_WORDS = {
    "提子", "红豆", "绿豆", "抹茶", "芝士", "奶酪", "巧克力", "奶油",
    "肉松", "蒜香", "葱油", "香葱", "火腿", "培根", "玉米", "紫薯",
    "南瓜", "红薯", "地瓜", "芋泥", "芋头", "椰奶", "椰子", "芒果",
    "草莓", "蓝莓", "香蕉", "苹果", "柠檬", "橙子", "葡萄", "水蜜桃",
    "白桃", "乌龙", "红茶", "绿茶", "咖啡", "拿铁", "摩卡", "焦糖",
    "海盐", "黑糖", "红糖", "蜂蜜", "桂花", "玫瑰", "荔枝", "龙眼",
    "桂圆", "山楂", "陈皮", "五香", "麻辣", "香辣", "酸辣", "甜辣",
    "原味", "咸味", "甜味", "双拼", "全家福",
}

PRODUCT_BARE_SUFFIX = (
    "烘焙工坊", "烘焙", "蛋糕", "甜品", "饼干", "曲奇", "泡芙",
    "蛋挞", "布丁", "冰淇淋", "冰激凌", "奶茶", "茶饮", "咖啡", "面包",
)

_SENT_RE = re.compile(r"[？！，。；：、,.!?;:的了是在有我你他她它这那什怎为嘛呢吧啊哦呀]")

_ROAD_RE = re.compile(r"(路|街|道|区|弄|号|村|镇|乡|巷|桥|湾|泾|浜|口)$")

def looks_like_brand(token):
    """确定性判断一个从笔记里抽出的 token 是否像真实店名。返回 (is_brand, reason)。
    默认放行短 token（可能是真店名如 鮨照/sage/Proust），命中确定垃圾才拒绝。"""
    s = (token or "").strip()
    if not s:
        return False, "empty"
    if len(s) > 14:
        return False, "too_long"
    if s in FIELD_LABELS:
        return False, "field_label"
    if s.endswith(SHOP_SUFFIXES):
        return True, "suffix"
    # 仅产品名：<食材/口味>+面包/烘焙 等，前缀非店名 → reject
    for suf in PRODUCT_BARE_SUFFIX:
        if s.endswith(suf) and len(s) > len(suf):
            prefix = s[:-len(suf)].strip()
            if prefix in INGREDIENT_WORDS:
                return False, "product:" + prefix + suf
            if prefix in DISH_WORDS:
                return False, "product_dish:" + prefix + suf
    if _SENT_RE.search(s):
        return False, "sentence"
    if _ROAD_RE.search(s):
        return False, "road"
    for w in DISH_WORDS:
        if w and w in s:
            return False, "dish:" + w
    for w in GENERIC_META:
        if w and len(w) >= 2 and w in s:
            return False, "meta:" + w
    if s in OUT_CITIES:
        return False, "city:" + s
    return True, "plausible"
