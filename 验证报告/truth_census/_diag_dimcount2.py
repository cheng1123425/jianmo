"""精确验证：**主视图 = 标注（尺寸数字）最多的那个视图**。

上一版失败原因：文字坐标与线段坐标**不在同一空间**（这批 PDF 内容流有 `/cm` 全局缩放，
pypdf 的 visitor 累积的 cm 与 `pdf_geom` 的 CTM 不同源）。
本版改为**自动标定**：用"线段整体范围 / 文字整体范围"求线性映射，把文字投到线段空间，
再按视图 bbox 归属、统计标注 token 数。

制图依据（用户补充 2026-10-16）：
  「面积最大不一定是主视图，**主视图一般是标注尺寸最多的那个视图**」
  —— 它正是 `projection-rules.md §7`「主视图最能反映形状特征」的可执行代理指标：
     尺寸按 `dimension-placement.md`「特征集中 / 反映实形」原则，都往表达最清楚的那个视图上标。
"""
import sys, os, json, re, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '.')
from pypdf import PdfReader
import pdf_geom as G
import readops as R

from batch import data_root
D = data_root()
pools = json.load(open('pools.json', encoding='utf-8'))


def mul(a, b):
    return [a[0]*b[0]+a[1]*b[2], a[0]*b[1]+a[1]*b[3],
            a[2]*b[0]+a[3]*b[2], a[2]*b[1]+a[3]*b[3],
            a[4]*b[0]+a[5]*b[2]+b[4], a[4]*b[1]+a[5]*b[3]+b[5]]


def positioned_text(pdf_path):
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


# ★ 放宽：只要**含数字**就算"标注的载体"。
#   踩过的坑：先用"整段必须是纯数字"的严格正则 ⇒ 每视图只数到 0~2 个，
#   因为 PDF 里一段文字常含多个数字（如 "48.5 40"）、或带前缀/后缀被拆开。
#   归属按**整段文字**算（不逐数字切分），足够区分"哪个视图标注多"。
DIM_RE = re.compile(r'\d')


def count_in(items_mapped, bbox, pad=3.0):
    x0, y0, x1, y1 = bbox
    return sum(1 for t, x, y in items_mapped
               if x0-pad <= x <= x1+pad and y0-pad <= y <= y1+pad and DIM_RE.search(t))


print('%-7s %-9s %-34s %-24s %-6s %s' % ('图号', '零件', '投影原则定的主视图', '标注最多者', '标定', '一致?'))
print('-' * 110)
for pid in sorted(pools['parts']):
    p = pools['parts'][pid]
    pdf = os.path.join(D, p['pdf'])
    g = G.geometry_of(pdf)
    views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 3]
    raw = positioned_text(pdf)

    # ---- 自动标定：文字空间 → 线段空间 ----
    segs = g['segments']
    lx = [v for s in segs for v in (s['p1'][0], s['p2'][0])]
    ly = [v for s in segs for v in (s['p1'][1], s['p2'][1])]
    tx = [t[1] for t in raw]
    ty = [t[2] for t in raw]
    ok_cal = False
    mapped = []
    if raw and tx and (max(tx) - min(tx)) > 1e-6 and (max(ty) - min(ty)) > 1e-6:
        sx = (max(lx) - min(lx)) / (max(tx) - min(tx))
        sy = (max(ly) - min(ly)) / (max(ty) - min(ty))
        ok_cal = abs(sx - sy) <= 0.15 * max(sx, sy)          # 各向同性才算标定可信
        mapped = [(t, min(lx) + (x - min(tx)) * sx, min(ly) + (y - min(ty)) * sy)
                  for t, x, y in raw]

    counts = {i: (count_in(mapped, v['bbox']) if ok_cal else -1) for i, v in enumerate(views)}
    top = max(counts, key=lambda k: counts[k]) if (counts and ok_cal) else None

    tv = R.three_views(g, views)
    if tv is not None:
        iv = views.index(tv[0])
        vtxt = 'v%d(%.0f×%.0f)' % (iv, tv[0]['w'], tv[0]['h'])
    else:
        iv, vtxt = None, '（未定出）'
    ttxt = 'v%d(%d个)' % (top, counts.get(top, 0)) if top is not None else '-'
    ok = '✓' if (iv is not None and iv == top) else ('—' if iv is None else '✗')
    print('%-7s %-9s %-34s %-24s %-6s %s' % (pid, p['name'][:8], vtxt, ttxt,
                                             ('ok' if ok_cal else '失败'), ok))
    if ok_cal:
        print('%-7s %-9s  各视图标注数: %s' % ('', '', {('v%d' % k): v for k, v in sorted(counts.items())}))
