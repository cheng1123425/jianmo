"""诊断：各件的【有剖面线的视图】与【pair_of 选出的主视图对】是什么关系。

制图原则（section-analysis.md §30 / drawing-efficiency §38）：
    内部不可见结构用**剖视**表达，剖面线标出"哪里是材料"。
⇒ 找"有剖面线的那个视图"，看它和当前 prof 是不是同一个投影方向。
"""
import sys, os, json, math
sys.path.insert(0, '.')
import pdf_geom as G
import readops as R
import pdf_anno

D = r'D:/桌面文件/胀断器/新建文件夹 (2)/生产图纸/生产图纸'
pools = json.load(open('pools.json', encoding='utf-8'))

print('%-7s %-12s %-30s %-34s %s' % ('图号', '零件', 'pair: prof / thin (axis)',
                                     '有剖面线的视图', '剖面线最多者 bbox'))
print('-' * 128)
for pid in sorted(pools['parts']):
    p = pools['parts'][pid]
    g = G.geometry_of(os.path.join(D, p['pdf']))
    views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 3]
    big = [v for v in views if v['n_seg'] >= 8]
    if len(big) < 2:
        big = [v for v in views if v['n_seg'] >= 4]
    pr = R.pair_of(big)
    if pr:
        A, B, axis = pr
        prof, thin = (A, B) if A['w'] * A['h'] >= B['w'] * B['h'] else (B, A)
        pairtxt = '%.0f×%.0f / %.0f×%.0f (%s)' % (prof['w'], prof['h'], thin['w'], thin['h'], axis)
    else:
        pairtxt = '（无配对）'
    hv = []
    for i, v in enumerate(views):
        f = R.hatch_fill_ratio(g, v)
        if f >= 0.05:
            hv.append('v%d(fill%.0f%%,%.0f×%.0f)' % (i, f * 100, v['w'], v['h']))
    print('%-7s %-12s %-30s %-34s %s' % (
        pid, p['name'][:10], pairtxt, ' '.join(hv) or '（无）', ''))
