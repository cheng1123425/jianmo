"""原型：**剖视图驱动** —— 用"有剖面线的视图"当剖面源。

制图原则依据：
  · `section-analysis.md §30`：「剖视图中被剖开的**腔体边界**，在另一个视图上必然对应
    一条虚线或实线轮廓」⇒ 剖视图是**表达内部结构的那张图**，应当从它读截面。
  · `drawing-efficiency.md §38`：「内部不可见部分改为剖视/断面 → 打剖面线」。
  · `section-analysis.md §4` 表：「台阶状突变 ⇒ 复杂轮廓一次成型」。

判据：**剖面应取自"打了剖面线的那张视图"**（设计师亲手剖开表达的截面），
      厚度取自"与它长对正/高平齐"的另一视图的**非共同方向**尺寸。

本脚本只做验证，不改主干。
"""
import sys, os, json, math
sys.path.insert(0, '.')
import pdf_geom as G
import readops as R
import profile as P
import census

from batch import data_root
D = data_root()


def hatch_cells(g, view, axis):
    """剖面线扫描 → 一组 (a, b, c, d) 矩形格子（材料区）。

    `axis` = **共同方向**（与配对视图相同的那个方向）：
      axis='x' ⇒ 共同方向 x，被剖切方向 y ⇒ 对每个 y 求剖面线的 x 交点区间。
      axis='y' ⇒ 反之。
    """
    hs = R.segs_in_view(g, view, '剖面线层')
    if not hs:
        return []
    b = view['bbox']
    if axis == 'x':
        t0, t1 = b[1], b[3]          # 被剖切方向是 y
    else:
        t0, t1 = b[0], b[2]
    nb = max(8, int(t1 - t0))
    out = []
    for i in range(nb):
        ta = t0 + (t1 - t0) * i / nb
        tb = t0 + (t1 - t0) * (i + 1) / nb
        ivs = P.scanline_intervals(hs_as_poly(hs), (ta + tb) / 2.0, axis=axis)
        for (a, c) in ivs:
            out.append((ta, tb, a, c) if axis == 'x' else (a, c, ta, tb))
    return out


def hs_as_poly(segs):
    """把剖面线段当成"两点多边形"喂给 scanline_intervals（它按边遍历求交）。"""
    return [tuple(s['p1']) for s in segs] + [tuple(s['p2']) for s in segs]


def build(g, name, sc, verbose=True):
    views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 3]
    big = [v for v in views if v['n_seg'] >= 8]
    if len(big) < 2:
        big = [v for v in views if v['n_seg'] >= 4]

    # 1) 找"有剖面线"的视图
    hatched = [v for v in big if R.hatch_fill_ratio(g, v) >= 0.05]
    if verbose:
        print('  有剖面线的视图: %s' % [
            '%.0f×%.0f(fill%.2f)' % (v['w'], v['h'], R.hatch_fill_ratio(g, v)) for v in hatched])

    # 2) 在 hatched 里选 prof（面积最大者），并找与它长对正/高平齐的 thin
    prof = thin = axis = None
    for cand in sorted(hatched, key=lambda v: -v['w'] * v['h']):
        for v in sorted(big, key=lambda v: -v['w'] * v['h']):
            if v is cand:
                continue
            if abs(v['w'] - cand['w']) <= 0.03 * max(v['w'], cand['w'], 1.0):
                prof, thin, axis = cand, v, 'x'
                break
            if abs(v['h'] - cand['h']) <= 0.03 * max(v['h'], cand['h'], 1.0):
                prof, thin, axis = cand, v, 'y'
                break
        if prof:
            break
    if prof is None:
        return None, '没有可配对的剖视图'

    thick_pt = thin['h'] if axis == 'x' else thin['w']
    thick = thick_pt / sc
    cells = hatch_cells(g, prof, axis)
    if verbose:
        print('  prof=%.1f×%.1f  thin=%.1f×%.1f  axis=%s  厚=%.2fmm  剖面线格子=%d 个' % (
            prof['w'], prof['h'], thin['w'], thin['h'], axis, thick, len(cells)))
    if not cells:
        return None, '剖面线扫描无格子'

    from build123d import Rectangle, Pos, Box
    x0 = min(min(c[0], c[1]) for c in cells)
    y0 = min(min(c[2], c[3]) for c in cells)
    solid = None
    for (a, b, c, d) in cells:
        w = max(b - a, 1e-6) / sc
        h = max(d - c, 1e-6) / sc
        if w < 1e-6 or h < 1e-6:
            continue
        cell = Box(w, h, thick) if solid is None else None
        piece = Pos((a - x0) / sc + w / 2, (c - y0) / sc + h / 2, thick / 2) * Box(w, h, thick)
        solid = piece if solid is None else (solid + piece)
    if solid is None:
        return None, '建体失败'
    return {'solid': solid, 'prof': [prof['w'], prof['h']], 'thin': [thin['w'], thin['h']],
            'axis': axis, 'thickness_mm': thick, 'cells': len(cells)}, None


pools = json.load(open('pools.json', encoding='utf-8'))
for pid, st in [('sj-008', '底座'), ('sj-002', '顶部垫片'), ('sj-007', '抗剪块')]:
    pdf = D + '/' + pools['parts'][pid]['pdf']
    g = G.geometry_of(pdf)
    anno = json.load(open('anno/' + pools['parts'][pid]['pdf'].replace('.pdf', '.anno.json'), encoding='utf-8'))
    annos = R.annos_of(anno)
    views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 3]
    sc, _ = R.scale_of(R.extents_of(views), annos)
    t = census.census(D + '/' + st + '.STEP')
    print('=== %s %s  sc=%.4f  真值 vol=%.1f ===' % (pid, st, sc, t['volume']))
    res, err = build(g, pid, sc)
    if err:
        print('  失败:', err)
    else:
        v = res['solid'].volume
        print('  ★ 体积 %.1f  vs 真值 %.1f  ⇒ **差 %+.2f%%**' % (v, t['volume'], (v - t['volume']) / t['volume'] * 100))
    print()
