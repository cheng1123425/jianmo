"""用投影原则 §2 轴映射表 + §3 三等关系，自动识别 主/俯/左 三视图。

制图依据（projection-rules.md）：
  §2 主视图读(长,高)、俯视图读(长,宽)、左视图读(宽,高)
  §3 长对正（主↔俯，X）｜高平齐（主↔左，Z）｜宽相等（俯↔左，Y）
  §7 主视图应最能反映形状特征 —— **但"面积最大"这条已被证伪**，改用 §3 的唯一性判据：

      **主视图 = 同时"与某视图长对正"且"与另一视图高平齐"的那个视图**

  它给出 X/Y/Z 三方向，且每个方向有两路可交叉验证（宽相等 = 第三条闭环）。
"""
import sys, os, json, math
sys.path.insert(0, '.')
import pdf_geom as G
import readops as R
import census

from batch import data_root
D = data_root()
pools = json.load(open('pools.json', encoding='utf-8'))
tol = 0.03


def same(a, b):
    return abs(a - b) <= tol * max(a, b, 1.0)


truth_bbox = {}
for st in set(p['name'] for p in pools['parts'].values()):
    f = D + '/' + st + '.STEP'
    if os.path.exists(f):
        c = census.census(f)
        truth_bbox[st] = [round(c['bbox'][i + 3] - c['bbox'][i], 2) for i in range(3)]

print('%-7s %-9s %-46s %-30s %s' % ('图号', '零件', '视图（宽×高）', 'X/Y/Z (mm) 交叉验证', '真值 bbox'))
print('-' * 132)
for pid in sorted(pools['parts']):
    p = pools['parts'][pid]
    g = G.geometry_of(os.path.join(D, p['pdf']))
    views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 8]
    if len(views) < 3:
        views = [v for v in G.cluster_views(g['segments']) if v['n_seg'] >= 4]
    anno = json.load(open('anno/' + p['pdf'].replace('.pdf', '.anno.json'), encoding='utf-8'))
    sc, _ = R.scale_of(R.extents_of(views), R.annos_of(anno))

    # 找主视图：同时与某视图长对正、与另一视图高平齐
    best = None
    for i, V in enumerate(views):
        hz = [j for j in range(len(views)) if j != i and same(views[j]['w'], V['w'])]
        vt = [k for k in range(len(views)) if k != i and same(views[k]['h'], V['h'])]
        if hz and vt:
            # 优先选"那个能同时配套上的"（俯视图与左视图的宽应相等）
            for j in hz:
                for k in vt:
                    if j == k:
                        continue
                    w_ok = same(views[j]['h'], views[k]['w'])
                    score = (2 if w_ok else 1, V['w'] * V['h'])
                    if best is None or score > best[0]:
                        best = (score, i, j, k, w_ok)
    txt = ' '.join('v%d:%.0f×%.0f' % (i, v['w'], v['h']) for i, v in enumerate(views[:5]))
    if not best:
        print('%-7s %-9s %-46s %-30s %s' % (pid, p['name'][:8], txt, '（找不到主视图）', truth_bbox.get(p['name'], '-')))
        continue
    _s, iv, ih, iw, w_ok = best
    V, H, W = views[iv], views[ih], views[iw]
    X1, Z1 = V['w'] / sc, V['h'] / sc
    X2, Y1 = H['w'] / sc, H['h'] / sc
    Y2, Z2 = W['w'] / sc, W['h'] / sc
    dims = '%s×%s×%s' % (round(X1, 1), round((Y1 + Y2) / 2, 1), round((Z1 + Z2) / 2, 1))
    chk = 'X %.1f/%.1f %s | Y %.1f/%.1f %s | Z %.1f/%.1f %s' % (
        X1, X2, '✓' if same(X1, X2) else '✗',
        Y1, Y2, '✓' if same(Y1, Y2) else '✗',
        Z1, Z2, '✓' if same(Z1, Z2) else '✗')
    print('%-7s %-9s %-46s %-30s %s' % (pid, p['name'][:8], txt, chk, truth_bbox.get(p['name'], '-')))
    print('%-7s %-9s   → 主=v%d 俯=v%d 左=v%d  推断 %s' % ('', '', iv, ih, iw, dims))
