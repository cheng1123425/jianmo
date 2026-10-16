"""基础形体的「二维↔三维」对照练习（用户 2026-10-16 建议）。

目的**不是**再造一个建模器，而是**用退化/极简形体检验我的读图判据**：
球（三视图全是圆）、正方体（三视图全同）、圆柱（两视图同尺寸）这些**对称退化**情形，
最容易暴露判据的盲区。

做法：build123d 造体 → `project_to_viewport` 出**真投影** → 按第一角摆放
（长对正/高平齐/宽相等）→ 跑 `readops.three_views` 等算子 → 与"应有的结论"对照。
"""
import sys, os, json, math
sys.path.insert(0, '.')
from build123d import Sphere, Box, Cylinder, Pos, Align
import readops as R

LAYER = "粗实线层"


def proj_segs(shape, origin, up, n=32):
    """形体 → 某方向的投影线段（含隐藏线，统一放"粗实线层"，够判据用）。"""
    vis, hid = shape.project_to_viewport(origin, viewport_up=up, look_at=shape.center())
    out = []
    for e in list(vis) + list(hid):
        pts = [e @ (i / n) for i in range(n + 1)]
        for a, b in zip(pts, pts[1:]):
            out.append(((a.X, a.Y), (b.X, b.Y)))
    return out


def bbox_of(segs):
    xs = [v for s in segs for v in (s[0][0], s[1][0])]
    ys = [v for s in segs for v in (s[0][1], s[1][1])]
    return [min(xs), min(ys), max(xs), max(ys)]


def shift(segs, dx, dy):
    return [((p[0] + dx, p[1] + dy), (q[0] + dx, q[1] + dy)) for p, q in segs]


def layout_first_angle(V, H, Wv, gap=20.0):
    """第一角布局：俯视图在主视图**下方**（长对正）、左视图在主视图**右方**（高平齐）。"""
    bv, bh, bw = bbox_of(V), bbox_of(H), bbox_of(Wv)
    # 俯视图：x 与主视图对齐
    H2 = shift(H, bv[0] - bh[0], (bv[1] - gap) - bh[3])
    # 左视图：y 与主视图对齐
    W2 = shift(Wv, (bv[2] + gap) - bw[0], bv[1] - bw[1])
    return V, H2, W2


def make_views(V, H, Wv):
    out = []
    for segs in (V, H, Wv):
        b = bbox_of(segs)
        out.append({"w": b[2] - b[0], "h": b[3] - b[1], "bbox": [round(v, 2) for v in b],
                    "n_seg": len(segs), "segs": [{"p1": list(p), "p2": list(q), "layer": LAYER,
                                                  "lw": 1.0, "rgb": [0, 0, 0]} for p, q in segs]})
    return out


class FakeG:
    """喂给 readops 的最小 `g`（它只用到 `segments`）。"""
    def __init__(self, segs_all):
        self.segments = segs_all
        self.layers = {LAYER: {"n": len(segs_all)}}


cases = [
    ("球 SØ60", Sphere(30), "三视图全是 Ø60 圆"),
    ("正方体 40³", Box(40, 40, 40), "三视图全是 40×40 方"),
    ("长方体 60×40×20", Box(60, 40, 20), "主60×20 俯60×40 左40×20"),
    ("圆柱 Ø60×80", Cylinder(30, 80), "主60×80 俯Ø60 左60×80"),
    ("L 形组合体", Box(60, 40, 20) - Box(30, 40, 20).moved(Pos(15, 0, 10)), "三视图为 L 形"),
    ("带通孔板 80×50×10 −Ø20", Box(80, 50, 10) - Cylinder(10, 30), "矩形+圆（孔）"),
]

print('%-22s %-26s %-30s %-24s %s' % ('形体', '期望', '三视图 w×h（pt）', 'three_views 判定', '合理?'))
print('-' * 132)
results = []
for name, shape, expect in cases:
    V = proj_segs(shape, (0, -1000, 0), (0, 0, 1))      # 前视
    H = proj_segs(shape, (0, 0, 1000), (0, 1, 0))       # 俯视
    Wv = proj_segs(shape, (-1000, 0, 0), (0, 0, 1))     # 左视
    V, H, Wv = layout_first_angle(V, H, Wv)
    views = make_views(V, H, Wv)
    g = FakeG(views[0]["segs"] + views[1]["segs"] + views[2]["segs"])

    tv = R.three_views(g, views, tol=0.03, min_edge_frac=0.05)
    sizes = ' '.join('v%d:%.0f×%.0f' % (i, v['w'], v['h']) for i, v in enumerate(views))
    if tv is None:
        verdict = '未判定'
        judge = '—'
    else:
        iv = views.index(tv[0])
        # 合理性：主视图应满足「读长与高」——即它与另两视图分别共享一个方向
        judge = 'v%d 主视 / v%d 俯视 / v%d 左视 (宽相等=%s)' % (
            iv, views.index(tv[1]), views.index(tv[2]), tv[3])
        verdict = 'v%d' % iv
    b = shape.bounding_box()
    dims = [round(b.size.X, 1), round(b.size.Y, 1), round(b.size.Z, 1)]
    print('%-22s %-26s %-30s %-24s %s' % (name, expect, sizes, verdict, judge))
    results.append((name, dims, sizes, judge))

print()
print('=== 关键：这些形体在【建体路线】上会怎样（现有 route_extrude 的前提是"单一截面 × 均匀厚度"）===')
for name, dims, sizes, judge in results:
    note = ''
    if name.startswith('球'):
        note = '❌ **三视图全同（圆）⇒ 判不出主视、且 extrude 圆 = 圆柱，不是球** —— 需专门路线'
    elif name.startswith('圆柱'):
        note = '⚠️ 主视与左视**同尺寸**（60×80）⇒ 靠三等关系仍能定，但少了尺寸唯一性约束'
    elif name.startswith('正方体'):
        note = '△ 三视图全同 ⇒ 判据无法区分方向（对建体无害，对"取哪个做剖面"成了任意选）'
    else:
        note = '✓ 三视图尺寸互不同或关系明确'
    print('  %-22s %s' % (name, note))
