"""验证用户给的判据：**主视图 = 标注（尺寸）最多的那个视图**。

制图依据：
  · `projection-rules.md §7`「主视图应最能反映零件形状特征」—— 但"形状特征"不可直接执行；
  · `dimension-placement.md`「**特征集中**」与「反映实形」⇒ 尺寸都往表达最清楚的那个视图上标
    ⇒ **"该视图内的标注数"是"形状特征充分度"的可执行代理指标**。
  · 用户补充（2026-10-16）：「面积最大不一定是主视图，主视图一般是标注尺寸最多的那个」。

做法：把带坐标的文字按视图 bbox 归属，统计每个视图里的标注 token 数，与
`readops.three_views` 用三等关系定出的主视图比对。
"""
import sys, os, json, math, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '.')
from pypdf import PdfReader
import pdf_geom as G
import readops as R

D = r'D:/桌面文件/胀断器/新建文件夹 (2)/生产图纸/生产图纸'
pools = json.load(open('pools.json', encoding='utf-8'))


def mul(a, b):
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


def positioned_text(pdf_path):
    """→ [(text, x, y)]，坐标用完整 CTM 合成，与 `pdf_geom` 的线段同空间。"""
    out = []

    def vis(text, cm, tm, fd, fs):
        t = (text or '').strip()
        if not t:
            return
        m = mul([cm[0], cm[1], cm[2], cm[3], cm[4], cm[5]],
                [tm[0], tm[1], tm[2], tm[3], tm[4], tm[5]])
        out.append((t, m[4], m[5]))

    PdfReader(pdf_path).pages[0].extract_text(visitor_text=vis)
    return out


import re
DIM_RE = re.compile(r'^(?:[ØøΦφ⌀]|%%c|R|M)?\s*\d+(?:\.\d+)?(?:±\d+(?:\.\d+)?)?$')


def count_dims_in_view(items, bbox, pad=2.0):
    x0, y0, x1, y1 = bbox
    n = 0
    for t, x, y in items:
        if x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad:
            if DIM_RE.match(t):
                n += 1
    return n


print('%-7s %-9s %-30s %-26s %s' % ('图号', '零件', '投影原则定的主视图', '标注最多的视图', '一致?'))
print('-' * 108)
for pid in sorted(pools['parts']):
    p = pools['parts'][pid]
    pdf = os.path.join(D, p['pdf'])
    g = G.geometry_of(pdf)
    views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 3]
    items = positioned_text(pdf)

    # 各视图的标注数
    counts = {}
    for i, v in enumerate(views):
        counts[i] = count_dims_in_view(items, v['bbox'])
    top = max(counts, key=lambda k: counts[k]) if counts else None

    tv = R.three_views(g, views)
    if tv is not None:
        V = tv[0]
        iv = views.index(V)
        vtxt = 'v%d(%.0f×%.0f, %d标注)' % (iv, V['w'], V['h'], counts.get(iv, 0))
    else:
        iv, vtxt = None, '（未定出）'

    ttxt = 'v%d(%d标注)' % (top, counts.get(top, 0)) if top is not None else '-'
    ok = '✓' if (iv is not None and iv == top) else ('—' if iv is None else '✗')
    print('%-7s %-9s %-30s %-26s %s' % (pid, p['name'][:8], vtxt, ttxt, ok))
    if len(views) > 1:
        print('%-7s %-9s  各视图标注数: %s' % ('', '', {('v%d' % k): v for k, v in counts.items()}))
