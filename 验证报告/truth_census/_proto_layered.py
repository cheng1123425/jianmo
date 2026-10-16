"""原型：**分层拉伸**（按制图规范「台阶突变处 ⇒ 回邻接视图量转折坐标」）。

思路：把"厚度方向的台阶"画在**薄视图**上（thin）——
用**扫描线**把 thin 轮廓切成若干层 `(z0, z1, [x区间...])`，
每层取"主视图轮廓 ∩ 该层的 x 条带"，再分别拉伸该层厚度、按 z 堆叠、求并。

本文件是原型验证，不改主干；通过后再把逻辑搬进 `views_to_3d.py`。
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pdf_geom as G
import readops as R
import census
from build123d import Polyline, make_face, extrude, Rectangle, Pos

DATA = r'D:/桌面文件/胀断器/新建文件夹 (2)/生产图纸/生产图纸'


def scanline(poly, y):
    """多边形与水平线 y 的交点 → 配对成 x 区间列表（标准扫描线）。"""
    xs = []
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 <= y < y2) or (y2 <= y < y1):
            t = (y - y1) / (y2 - y1)
            xs.append(x1 + t * (x2 - x1))
    xs.sort()
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def layers_of(thin_poly, sc, min_h=0.5):
    """thin 轮廓 → `[(z0, z1, [x区间])]`（mm）。"""
    tx0 = min(p[0] for p in thin_poly)
    ty0 = min(p[1] for p in thin_poly)
    ys = sorted({round(p[1], 3) for p in thin_poly})
    out = []
    for i in range(len(ys) - 1):
        y0, y1 = ys[i], ys[i + 1]
        if y1 - y0 < min_h:
            continue
        ivs = scanline(thin_poly, (y0 + y1) / 2.0)
        if not ivs:
            continue
        out.append(((y0 - ty0) / sc, (y1 - ty0) / sc,
                    [((a - tx0) / sc, (b - tx0) / sc) for a, b in ivs]))
    return out


def build_layered(prof_poly, thin_poly, sc):
    px0 = min(p[0] for p in prof_poly)
    py0 = min(p[1] for p in prof_poly)
    prof_mm = [((p[0] - px0) / sc, (p[1] - py0) / sc) for p in prof_poly]
    H = max(p[1] for p in prof_mm) + 1.0
    base = make_face(Polyline(*prof_mm, close=True))

    layers = layers_of(thin_poly, sc)
    solid = None
    for (z0, z1, ivs) in layers:
        f = base
        for (a, b) in ivs:
            bar = Pos((a + b) / 2.0, H / 2.0, 0) * Rectangle(max(b - a, 1e-6), H * 3.0)
            f = f & bar
        try:
            piece = extrude(f, amount=z1 - z0)
        except Exception as exc:
            print('     层 %.2f~%.2f 拉伸失败: %s' % (z0, z1, str(exc)[:40]))
            continue
        if piece.volume < 1e-9:
            continue
        piece = Pos(0, 0, z0) * piece
        solid = piece if solid is None else (solid + piece)
    return solid, layers


def main():
    for name, st in [('sj-007(抗剪块)', '抗剪块'),
                     ('sj-008(底座)', '底座'),
                     ('sj-004(顶部胀断反馈)', '顶部胀断反馈'),
                     ('sj-002(顶部垫片)', '顶部垫片')]:
        pdf = DATA + '/' + name + '-模型.pdf'
        if not os.path.exists(pdf):
            print('%s 缺 PDF' % name)
            continue
        g = G.geometry_of(pdf)
        views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 3]
        big = [v for v in views if v['n_seg'] >= 8]
        if len(big) < 2:
            big = [v for v in views if v['n_seg'] >= 4]
        pr = R.pair_of(big)
        if not pr:
            print('%s 无配对' % name)
            continue
        A, B, axis = pr
        prof, thin = (A, B) if A['w'] * A['h'] >= B['w'] * B['h'] else (B, A)
        anno = json.load(open('anno/' + name + '-模型.anno.json', encoding='utf-8'))
        sc, _ = R.scale_of(R.extents_of(big), R.annos_of(anno))
        pp, d1 = R.loop_of(R.segs_in_view(g, prof), prof['bbox'])
        tp, d2 = R.loop_of(R.segs_in_view(g, thin), thin['bbox'])
        if not pp or not tp:
            print('%s 轮廓失败 prof=%s thin=%s' % (name, d1, d2))
            continue
        print('=== %s  sc=%.3f  axis=%s  prof=%d点(%s)  thin=%d点(%s)' % (
            name, sc, axis, len(pp), d1, len(tp), d2))
        solid, layers = build_layered(pp, tp, sc)
        print('   层数 %d' % len(layers))
        for z0, z1, ivs in layers:
            print('      z %.2f~%.2f  x区间 %s' % (z0, z1, ['%.1f~%.1f' % t for t in ivs]))
        if solid is None:
            print('   建体失败')
            continue
        t = census.census(DATA + '/' + st + '.STEP')
        print('   ★ 分层拉伸 体积 %.1f ｜ 真值 %.1f ｜ 差 %+.1f%%' % (
            solid.volume, t['volume'], (solid.volume - t['volume']) / t['volume'] * 100))


if __name__ == '__main__':
    main()
