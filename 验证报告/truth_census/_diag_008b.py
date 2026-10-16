"""诊断 sj-008：three_views 已定出 主=V / 俯=H，为何 extrude 仍建不出体。"""
import sys, os, json
sys.path.insert(0, '.')
import pdf_geom as G
import readops as R
import profile as P
import pdf_anno

D = r'D:/桌面文件/胀断器/新建文件夹 (2)/生产图纸/生产图纸'
pools = json.load(open('pools.json', encoding='utf-8'))
p = pools['parts']['sj-008']
g = G.geometry_of(os.path.join(D, p['pdf']))
views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 3]
anno = pdf_anno.anno_of(os.path.join(D, p['pdf']))
annos = R.annos_of(anno)

tv = R.three_views(g, views)
V, H, W, wide_ok = tv
print('three_views: V(主)=%.1f×%.1f bbox=%s | H(俯)=%.1f×%.1f bbox=%s | wide_ok=%s' % (
    V['w'], V['h'], [round(t) for t in V['bbox']],
    H['w'], H['h'], [round(t) for t in H['bbox']], wide_ok))

ext = sorted({round(v['w'], 1) for v in views} | {round(v['h'], 1) for v in views})
sc, _ = R.scale_of(ext, annos)
print('sc=%.4f  厚度(B.h)=%.2fmm' % (sc, H['h'] / sc))

poly, deg = R.loop_of(R.segs_in_view(g, V), V['bbox'])
tp, td = R.loop_of(R.segs_in_view(g, H), H['bbox'])
print('主视图轮廓: %d点 deg=%s 面积=%.1fmm²' % (
    len(poly) if poly else 0, deg, (P.poly_area(poly) if poly else 0) / sc / sc))
print('  轮廓 bbox=%s' % ([[round(min(q[i] for q in poly)), round(max(q[i] for q in poly))] for i in (0, 1)] if poly else '-'))
print('  视图 bbox=%s' % [round(t) for t in V['bbox']])
print('俯视图轮廓: %d点 deg=%s has_step=%s' % (
    len(tp) if tp else 0, td, P.has_step(tp, axis='x') if tp else None))
if tp:
    lys = P.layers_of(tp, sc, axis='x')
    print('  层数=%d' % len(lys))
    for z0, z1, ivs in lys[:8]:
        print('    z %.2f~%.2f  x区间=%s' % (z0, z1, [('%.1f~%.1f' % (a, b)) for a, b in ivs]))
    # 手算交集：base 的 x 范围（减自己 min 后）与 layers 区间（减 base_o 后）
    x0 = min(q[0] for q in poly)
    off = x0 / sc
    print('  base x 范围 = [0, %.1f] mm   layers 对齐后 x = %s' % (
        (max(q[0] for q in poly) - x0) / sc,
        [('%.1f~%.1f' % (a - off, b - off)) for _z0, _z1, ivs in lys[:3] for a, b in ivs]))
