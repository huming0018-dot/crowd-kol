"""KOL 名称核心与长度门槛。
模块名保留供现有消费者导入；不再含米其林浏览器采集/缓存/对账副本。"""

import pathlib

import re

import sys

try:
    import common as C
except Exception:
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    import common as C

_CN_NUM = {"零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
           "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}

def _norm_digits(s):
    """连续≥2 个中文数字 → 阿拉伯（福一零一五→福1015）。"""
    return re.sub(r"[零一二两三四五六七八九]{2,}",
                  lambda m: "".join(_CN_NUM.get(ch, ch) for ch in m.group(0)), s)

def core(s):
    """去括号后缀 → cjk_norm（繁简/异体/小写/去标点）→ 中文数字归一。"""
    s = re.sub(r"[（(].*?[)）]", "", s or "")
    return _norm_digits(C.cjk_norm(s))

def _han(s):
    return "".join(ch for ch in s if "一" <= ch <= "鿿")

def _cjk_count(s):
    return len(_han(s))

def eligible(c):
    j = _cjk_count(c)
    # 2 个汉字已足够特异（唐阁/甬府/言盐）；1 汉字需总长≥3；纯拉丁需≥4（避开 pop/bar）
    return j >= 2 or (j == 1 and len(c) >= 3) or (j == 0 and len(c) >= 4)
