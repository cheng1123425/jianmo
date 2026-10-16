"""诊断 sj-004 / sj-008 的视图与建体参数（临时脚本）。"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pdf_geom as G
import readops as R
import profile as P
import census
from batch import data_root

DATA = data_root()


def main():
    pools = json.load(open('pools.json', encoding='utf-8'))
    for pid, st in [('sj-004', '顶部胀断反馈'), ('sj-008', '底座')]:
        p = pools['parts'][pid]
        pdf = os.path.join(DATA, p['pdf'])
        g = G.geometry_of(pdf)
        views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 3]
        print('=== %s %s 全部视图 ===' % (pid, p['name']))
        for i, v in enumerate(views[:6]):
            cen = len(R.segs_in_view(g, v, '中心线层'))
            hat = len(R.segs_in_view(g, v, '剖面线层'))
            print('   v%d %.0fx%.0f %4d段 中心线%d 剖面线%d bbox=%s' % (
                i, v['w'], v['h'], v['n_seg'], cen, hat, [round(t) for t in v['bbox']]))
        big = [v for v in views if v['n_seg'] >= 8]
        if len(big) < 2:
            big = [v for v in views if v['n_seg'] >= 4]
        A, B, axis = R.pair_of(big)
        prof, thin = (A, B) if A['w'] * A['h'] >= B['w'] * B['h'] else (B, A)
        anno = json.load(open('anno/' + p['pdf'].replace('.pdf', '.anno.json'), encoding='utf-8'))
        sc, _ = R.scale_of(R.extents_of(big), R.annos_of(anno))
        pp, d1 = R.loop_of(R.segs_in_view(g, prof), prof['bbox'])
        ar = P.poly_area(pp) / (sc * sc) if pp else 0
        th = (thin['h'] if axis == 'x' else thin['w']) / sc
        print('   pair axis=%s prof %.0fx%.0f thin %.0fx%.0f sc=%.3f' % (
            axis, prof['w'], prof['h'], thin['w'], thin['h'], sc))
        print('   -> 轮廓 %.1fmm2 x 厚度 %.1fmm = %.1fmm3' % (ar, th, ar * th))
        c = census.census(os.path.join(DATA, st + '.STEP'))
        dims = [round(c['bbox'][i + 3] - c['bbox'][i], 2) for i in range(3)]
        print('   真值 vol=%.1f dims=%s' % (c['volume'], dims))
        print()


if __name__ == '__main__':
    main()
