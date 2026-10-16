"""诊断 sj-008：剖视图（有剖面线者）与 pair 选出的 prof/thin 的几何关系。

制图原则（section-analysis.md §30）：
    「剖视图中被剖开的腔体边界，在另一个视图上必然对应一条虚线或实线轮廓」
⇒ 先确认"剖视图"是哪一张、它的投影方向、以及它的剖面线扫描能否读出内部腔。
"""
import sys, os, json, math
sys.path.insert(0, '.')
import pdf_geom as G
import readops as R

from batch import data_root
D = data_root()
for name in ['sj-008(底座)', 'sj-006(上层限位口)', 'sj-007(抗剪块)', 'sj-002(顶部垫片)']:
    g = G.geometry_of(D + '/' + name + '-模型.pdf')
    views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 3]
    views.sort(key=lambda v: -v['n_seg'])
    print('=== %s ===' % name)
    for i, v in enumerate(views[:6]):
        f = R.hatch_fill_ratio(g, v)
        cen = len(R.segs_in_view(g, v, '中心线层'))
        print('   v%d bbox=%-26s %.1f×%.1f %4d段  fill=%.2f 中心线%d' % (
            i, str([round(t) for t in v['bbox']]), v['w'], v['h'], v['n_seg'], f, cen))
    big = [v for v in views if v['n_seg'] >= 8]
    if len(big) < 2:
        big = [v for v in views if v['n_seg'] >= 4]
    pr = R.pair_of(big)
    if pr:
        A, B, axis = pr
        prof, thin = (A, B) if A['w'] * A['h'] >= B['w'] * B['h'] else (B, A)
        print('   pair: prof bbox=%s (%.1f×%.1f)  thin bbox=%s (%.1f×%.1f)  axis=%s' % (
            [round(t) for t in prof['bbox']], prof['w'], prof['h'],
            [round(t) for t in thin['bbox']], thin['w'], thin['h'], axis))
        print('   thin 的 fill = %.2f' % R.hatch_fill_ratio(g, thin))
    print()
