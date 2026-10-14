# -*- coding: utf-8 -*-
r"""
标注接地器（Annotation Grounding）—— 本工具的核心
====================================================
对应 Drawing-Recode 的 cross-attention + AGL（Annotation Grounding Loss）。

原论文用神经网络学「标注 → 几何」的对应；本实现改用**显式几何推理**，
每一步都可解释、可人工复核：

  1) **比例标定（calibrate）**：不依赖任何先验。把每条直径标注与每个检出圆
     两两配对，得到 mm/px 候选值；真正正确的比例会被大量配对同时命中
     （Φ75↔r=110、Φ150↔r=221、Φ200↔r=293 …），用「最密簇投票」把它选出来。

  2) **引线追踪（_leader_tip）**：直径/半径标注靠一条引线（可带折弯）指向
     被标注要素。在标注框周围开一个 ROI，用短直线 Hough 找出贴着框的线段，
     再按「端点相接 + 近共线」把折线接起来，取最远端作为箭头尖。
     这一步解决「同半径圆无法区分」的问题（本图有 3 个 r≈221 的圆）。

  3) **数值匹配 + 引线消歧**：标注值 × 比例 → 期望像素半径，先按半径筛候选，
     再用引线尖端是否落在候选圆周上定案。

  4) **局部圆弧拟合（_fit_arc_at）**：波浪形外轮廓、倒圆角这类要素不是整圆，
     半径匹配必然落空。这时在引线尖端附近取一段轮廓，做鲁棒圆拟合，
     反算出它「实际是多大」—— 用来核对 Φ300 外缘、R400 圆角。

  5) **线性尺寸接地（_ground_linear）**：沿文本朝向开走廊，合并共线的尺寸线
     段，量出箭头间的跨度，再把两端吸附到最近的圆心 —— 于是「200」被解释为
     「两孔组的中心距」，「550/300」被解释为「外轮廓总长/总宽」。

产出：接地表 —— 每条标注绑定哪个几何要素、怎么绑的、置信度多少。
"""
import numpy as np
import cv2


# ======================================================================
# 1) 比例标定
# ======================================================================
def calibrate(geometry, annotations, known=None):
    """
    标定 mm/px。

    known: {"mm": 550, "px": 1234} → 直接用；否则自动投票推断。
    返回 (mm_per_px, method)
    """
    if known and known.get("px"):
        return known["mm"] / known["px"], "user"

    circles = geometry.get("circles", [])
    lines = geometry.get("lines", [])

    # 主投票：直径/半径标注 × 检出的圆。
    # 不用「线性标注 × 直线」—— 一条图纸有上百条直线，噪声对会把真簇淹没。
    votes = []
    for a in annotations:
        vals = a.get("values") or []
        if not vals:
            continue
        v = vals[-1]
        if a["type"] in ("diameter", "pattern_dia"):
            for c in circles:
                if c["r_px"] > 0:
                    votes.append(v / (2.0 * c["r_px"]))
        elif a["type"] == "radius":
            for c in circles:
                if c["r_px"] > 0:
                    votes.append(v / c["r_px"])

    scale, support = _densest_cluster(votes, rel=0.02)
    if scale is not None and support >= 2:
        refined, n = _refine_scale(scale, geometry, annotations)
        return (refined if n >= 2 else scale), \
               "circle_vote(支持%d/%d)" % (support, len(votes))

    # 兜底：没有直径标注时，用线性标注 × 「就在它旁边的」直线投票
    votes = []
    for a in annotations:
        vals = a.get("values") or []
        if not vals or a["type"] != "linear":
            continue
        v = vals[-1]
        cx, cy = a["center_px"]
        for l in lines:
            mx = (l["p1"][0] + l["p2"][0]) / 2.0
            my = (l["p1"][1] + l["p2"][1]) / 2.0
            if np.hypot(mx - cx, my - cy) <= 500 and l["len_px"] > 0:
                votes.append(v / l["len_px"])
    scale, support = _densest_cluster(votes, rel=0.02)
    if scale is not None and support >= 2:
        return scale, "line_vote(支持%d/%d)" % (support, len(votes))
    return None, "failed"


def _densest_cluster(vals, rel=0.02):
    """找「最密集」的候选值簇：真比例会被大量配对同时命中。"""
    v = np.sort(np.asarray(vals, dtype=float))
    v = v[(v > 1e-4) & (v < 10)]
    if len(v) == 0:
        return None, 0
    best_i, best_n = 0, 0
    for i in range(len(v)):
        n = int(np.sum(np.abs(v - v[i]) <= rel * v[i]))
        if n > best_n:
            best_n, best_i = n, i
    win = v[np.abs(v - v[best_i]) <= rel * v[best_i]]
    return float(np.median(win)), best_n


def _refine_scale(scale, geometry, annotations, tol=0.08):
    """
    用「标注 ↔ 匹配圆」的配对做最小二乘精修 mm/px。
    直径：v ≈ 2·r·s ；半径：v ≈ r·s 。以 r² 加权，等价于对 1/s 做最小二乘。
    """
    circles = geometry.get("circles", [])
    num = den = 0.0
    n = 0
    for a in annotations:
        vals = a.get("values") or []
        if not vals:
            continue
        v = vals[-1]
        if a["type"] not in ("diameter", "pattern_dia", "radius"):
            continue
        k = 1.0 if a["type"] == "radius" else 2.0     # v = k · r · s
        exp_r = (v / scale) / k
        hit = [c for c in circles if abs(c["r_px"] - exp_r) <= tol * exp_r]
        if not hit:
            continue
        r = min(hit, key=lambda c: abs(c["r_px"] - exp_r))["r_px"]
        # s = Σ(r·v) / (k · Σ r²)   ← k 不能丢，否则比例会差整整 k 倍
        num += r * v
        den += k * r * r
        n += 1
    if n == 0 or den == 0:
        return scale, 0
    return num / den, n


# ======================================================================
# 2) 引线追踪
# ======================================================================
def _seg_dir(p1, p2):
    return np.array([p2[0] - p1[0], p2[1] - p1[1]], dtype=float)


def _arrowness(bw, pt, win=34):
    """
    点附近是否有一个箭头 —— 判据是「两条斜笔画在尖端汇合」。

    尺寸界线、轮廓线都不会有这个特征，因此它能把「真正的引线末端」从
    一串候选折线里挑出来（引线跑偏到尺寸界线上时尤其管用）。
    返回 0~1 的分数。
    """
    from .annotation import remove_lines, _stroke_score
    H, W = bw.shape
    x, y = int(round(pt[0])), int(round(pt[1]))
    x0, y0 = max(0, x - win), max(0, y - win)
    x1, y1 = min(W, x + win), min(H, y + win)
    sub = bw[y0:y1, x0:x1]
    if sub.size == 0 or sub.sum() == 0:
        return 0.0
    clean = remove_lines(sub, min_len=max(24, win // 2), thickness=4)
    n, lab, stats, cents = cv2.connectedComponentsWithStats(clean, 8)
    st = []
    for i in range(1, n):
        bx, by, bw_, bh, area = stats[i]
        if bh < 7 or bh > 2.2 * win or bw_ > 1.5 * win or area < 10:
            continue
        m = (lab[by:by + bh, bx:bx + bw_] == i).astype(np.uint8)
        if _stroke_score(m) > 0.45:
            continue
        st.append(cents[i])
    if len(st) < 2:
        return 0.0
    best = 1e9
    for i in range(len(st)):
        for j in range(i + 1, len(st)):
            best = min(best, float(np.hypot(*(np.array(st[i]) -
                                             np.array(st[j])))))
    if best > 0.9 * win:
        return 0.0
    return round(1.0 - best / (0.9 * win), 3)


def _leader_candidates(bw, box, roi=260, near=70, min_len=45, angle_tol=28.0,
                       keep=5):
    """
    追踪引线，返回**多个**候选末端（按链长降序）。

    为什么不直接选一条：从标注框出发的折线可能有多条（引线、尺寸界线、
    轮廓线都贴着框），中途选错分支是常事。所以把所有候选都交出去，
    由接地环节用「末端是否贴着被标注几何」反推哪条才对 —— 这正是
    显式接地的思路：证据不足时不猜，让下游验证来裁决。
    """
    x, y, w, h = [int(v) for v in box]
    H, W = bw.shape
    x0, y0 = max(0, x - roi), max(0, y - roi)
    x1, y1 = min(W, x + w + roi), min(H, y + h + roi)
    sub = bw[y0:y1, x0:x1]
    if sub.size == 0 or sub.sum() == 0:
        return []
    segs = cv2.HoughLinesP(sub, 1, np.pi / 180, threshold=30,
                           minLineLength=min_len, maxLineGap=8)
    if segs is None:
        return []
    segs = [((int(a) + x0, int(b) + y0), (int(c) + x0, int(d) + y0))
            for a, b, c, d in np.asarray(segs).reshape(-1, 4)]

    def dist_to_box(p):
        dx = max(x - p[0], 0, p[0] - (x + w))
        dy = max(y - p[1], 0, p[1] - (y + h))
        return float(np.hypot(dx, dy))

    starts = []
    for j, (p1, p2) in enumerate(segs):
        d1, d2 = dist_to_box(p1), dist_to_box(p2)
        if d1 <= near or d2 <= near:
            # 引线短时两端都可能贴着框 —— 两个方向都走，交给下游验证裁决
            starts.append((p1, p2, j))
            starts.append((p2, p1, j))
    if not starts:
        return []

    cands = []
    for far, near_pt, j in starts:
        chain_end, length = _walk_chain(far, near_pt, segs, angle_tol,
                                        used_init={j})
        if length >= min_len:
            cands.append((length, chain_end))
    cands.sort(key=lambda t: -t[0])
    out, seen = [], []
    for length, end in cands:
        if any(abs(end[0] - s[0]) < 20 and abs(end[1] - s[1]) < 20 for s in seen):
            continue
        seen.append(end)
        out.append((float(end[0]), float(end[1])))
        if len(out) >= keep:
            break
    return out


def _leader_tip(bw, box, **kw):
    """兼容旧接口：返回第一个（最长的）候选末端。"""
    c = _leader_candidates(bw, box, **kw)
    return c[0] if c else None


def _walk_chain(far, anchor, segs, angle_tol=28.0, step=26, max_steps=16,
                used_init=None):
    """
    从 anchor→far 出发，不断接上「靠近 far 且前进方向相符」的线段。

    两个要点：
      1) 接续判据用「点到线段」距离（折弯处常有缝隙，只看端点会半路掉链）；
      2) 方向基准用**累计位移向量**（从锚点到当前末端的向量），不是单步位移 ——
         否则末端只挪了几个像素，方向就会被带偏，接上旁边的无关线段。
    锚线段自己不能接（used_init），否则会顺着它原路走回去。

    返回 (最终端点, 累计长度)。
    """
    def pt_seg_dist(p, a, b):
        ab = b - a
        L2 = float(np.dot(ab, ab))
        if L2 < 1e-9:
            return float(np.hypot(*(p - a)))
        t = float(np.dot(p - a, ab)) / L2
        t = max(0.0, min(1.0, t))
        return float(np.hypot(*(p - (a + t * ab))))

    used = set(used_init or ())
    cur_far = np.array(far, dtype=float)
    cur_anchor = np.array(anchor, dtype=float)
    vec = cur_far - cur_anchor                 # 累计位移 = 方向基准
    total = float(np.hypot(*vec))
    for _ in range(max_steps):
        L0 = float(np.hypot(*vec))
        if L0 < 1e-6:
            break
        d = vec / L0
        best = None
        for j, (p1, p2) in enumerate(segs):
            if j in used:
                continue
            for a, b in ((np.array(p1, dtype=float), np.array(p2, dtype=float)),
                         (np.array(p2, dtype=float), np.array(p1, dtype=float))):
                if pt_seg_dist(cur_far, a, b) > step:
                    continue
                v = b - a
                L = float(np.hypot(*v))
                if L < 10:
                    continue
                cos = float(np.dot(v / L, d))
                if np.degrees(np.arccos(np.clip(cos, -1, 1))) > angle_tol:
                    continue
                if best is None or L > best[0]:
                    best = (L, j, b)
        if best is None:
            break
        L, j, end = best
        used.add(j)
        step_vec = end - cur_far
        vec = vec + step_vec
        if float(np.hypot(*vec)) < 0.3 * L0:    # 明显在往回折 → 停
            break
        total += max(0.0, float(np.hypot(*step_vec)))
        cur_anchor, cur_far = cur_far, end
    return tuple(cur_far), total


# ======================================================================
# 3) 局部圆弧拟合
# ======================================================================
def _circle_from3(p):
    """三点定圆（三点近共线时返回 None）。"""
    (x1, y1), (x2, y2), (x3, y3) = p
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-6:
        return None
    ux = ((x1 ** 2 + y1 ** 2) * (y2 - y3) + (x2 ** 2 + y2 ** 2) * (y3 - y1) +
          (x3 ** 2 + y3 ** 2) * (y1 - y2)) / d
    uy = ((x1 ** 2 + y1 ** 2) * (x3 - x2) + (x2 ** 2 + y2 ** 2) * (x1 - x3) +
          (x3 ** 2 + y3 ** 2) * (x2 - x1)) / d
    r = float(np.hypot(ux - x1, uy - y1))
    if not np.isfinite(r) or r <= 0:
        return None
    return float(ux), float(uy), r


def _fit_circle_lsq(pts):
    """Kåsa 代数最小二乘圆拟合。"""
    A = np.c_[2 * pts[:, 0], 2 * pts[:, 1], np.ones(len(pts))]
    b = (pts ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy, c = sol
    rr = c + cx * cx + cy * cy
    if rr <= 0:
        return None
    return float(cx), float(cy), float(np.sqrt(rr))


def _fit_circle_ransac(pts, iters=400, inlier=2.5):
    """
    RANSAC 圆拟合。

    引线尖端处的墨迹是「轮廓 + 引到它上面的那条引线」，直接最小二乘会被
    引线的直笔画带偏。RANSAC 只认多数派，能干净地把圆弧挑出来。
    返回 (cx, cy, r, rmse, inlier_ratio, n_in)。
    """
    pts = np.asarray(pts, dtype=float)
    n = len(pts)
    if n < 12:
        return None
    rng = np.random.default_rng(0)
    best = None
    for _ in range(iters):
        idx = rng.choice(n, 3, replace=False)
        c = _circle_from3(pts[idx])
        if c is None:
            continue
        d = np.abs(np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1]) - c[2])
        m = d <= inlier
        k = int(m.sum())
        if best is None or k > best[0]:
            best = (k, c, m)
    if best is None or best[0] < 12:
        return None
    _, c, m = best
    # 用内点重拟合，再迭代收敛
    for _ in range(3):
        fit = _fit_circle_lsq(pts[m])
        if fit is None:
            break
        c = fit
        d = np.abs(np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1]) - c[2])
        m = d <= max(2.5, 1.5 * np.median(d[m]) if m.any() else 3.0)
        if m.sum() < 12:
            break
    d = np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1]) - c[2]
    rmse = float(np.sqrt(np.mean(d[m] ** 2))) if m.any() else 9e9
    return c[0], c[1], c[2], rmse, float(m.sum()) / n, int(m.sum())


def _component_at(bw, pt, search=40):
    """
    取 pt 所在的整块连通墨迹（用 floodFill 抓全貌，不受窗口限制）。
    引线尖端落在轮廓上，顺着它能拿到整条轮廓线，圆弧拟合才有足够跨度。
    """
    H, W = bw.shape
    x, y = int(round(pt[0])), int(round(pt[1]))
    # 先找 pt 附近最近的墨点作为种子
    x0, y0 = max(0, x - search), max(0, y - search)
    x1, y1 = min(W, x + search), min(H, y + search)
    sub = bw[y0:y1, x0:x1]
    if sub.sum() == 0:
        return None
    ys, xs = np.nonzero(sub)
    i = int(np.argmin((xs + x0 - x) ** 2 + (ys + y0 - y) ** 2))
    sx, sy = int(xs[i]) + x0, int(ys[i]) + y0

    mask = np.zeros((H + 2, W + 2), np.uint8)
    work = bw.copy()
    cv2.floodFill(work, mask, (sx, sy), 128, flags=8)
    comp = (work == 128)
    if comp.sum() < 20 or comp.sum() > 0.15 * bw.size:
        return None                       # 太大 = 抓到了整幅图框，弃
    return np.argwhere(comp)[:, [1, 0]].astype(float)


def _fit_arc_at(bw, tip, wins=(160, 260, 400, 620), rmse_max=2.5):
    """
    在引线尖端附近拟合局部圆弧 —— 用于波浪外缘、倒圆角这类非整圆要素。
    窗口由小到大试：小窗口精度差但干净，大窗口跨度够但可能跨到相邻弧段；
    取第一个「残差合格 + 内点占比高 + 弧段跨度够」的结果。
    """
    ink = _component_at(bw, tip)
    if ink is None or len(ink) < 20:
        return None
    for win in wins:
        d = np.hypot(ink[:, 0] - tip[0], ink[:, 1] - tip[1])
        sel = ink[d <= win]
        if len(sel) < 20:
            continue
        span = max(sel[:, 0].max() - sel[:, 0].min(),
                   sel[:, 1].max() - sel[:, 1].min())
        if span < 0.8 * win:               # 弧段太短，拟合不可信
            continue
        fit = _fit_circle_ransac(sel)
        if fit is None:
            continue
        cx, cy, r, rmse, ratio, nin = fit
        if rmse <= rmse_max and ratio >= 0.55:
            return {"cx": float(cx), "cy": float(cy), "r_px": float(r),
                    "rmse": round(rmse, 2), "win": win,
                    "inlier_ratio": round(ratio, 2), "npts": int(nin)}
    return None


# ======================================================================
# 4) 外轮廓弧段 + 圆角（非整圆要素）
# ======================================================================
def _group_centers(circles, tol_px=30):
    """把同心圆并成「孔组」，返回组中心列表。"""
    groups = []
    for c in circles:
        for g in groups:
            if np.hypot(c["cx"] - g[0], c["cy"] - g[1]) <= tol_px:
                break
        else:
            groups.append((c["cx"], c["cy"]))
    return groups


def find_contour_arcs(bw, circles, cov_min=0.12, r_step=4, npoints=720):
    """
    找「外轮廓弧段」—— 波浪形外缘这类要素不是整圆，圆周只有一段有墨。

    绕每个孔组中心做径向扫描：某个半径上若有可观比例的圆周被墨覆盖，
    说明这里存在一段以该组为中心、该半径的轮廓弧（如 Φ300 外缘，覆盖率 26%）。
    """
    from .geometry import _coverage
    ink = (bw > 0).astype(np.uint8)
    H, W = ink.shape
    arcs = []
    for (cx, cy) in _group_centers(circles):
        rs = [c["r_px"] for c in circles
              if np.hypot(c["cx"] - cx, c["cy"] - cy) <= 30]
        if not rs:
            continue
        r0 = int(max(rs) * 1.08)
        r1 = int(min(max(rs) * 2.6, 0.9 * min(H, W) / 2))
        prof = []
        for r in range(r0, r1, r_step):
            prof.append((r, _coverage(cx, cy, r, ink, H, W, npoints)))
        # 取覆盖率的局部极大
        for i in range(1, len(prof) - 1):
            r, cov = prof[i]
            if cov < cov_min:
                continue
            if cov >= prof[i - 1][1] and cov >= prof[i + 1][1]:
                arcs.append({"cx": cx, "cy": cy, "r_px": float(r),
                             "coverage": round(float(cov), 3)})
    return arcs


def _arc_ink_ratio(ink, cf, r, t1, t2, samples=48, tol=3.0):
    """沿候选圆弧采样，统计有多少点落在墨迹上（验证这段弧真的存在）。"""
    a1 = np.arctan2(t1[1] - cf[1], t1[0] - cf[0])
    a2 = np.arctan2(t2[1] - cf[1], t2[0] - cf[0])
    d = (a2 - a1 + np.pi) % (2 * np.pi) - np.pi        # 走短弧
    H, W = ink.shape
    hit = 0
    for k in range(samples):
        a = a1 + d * k / (samples - 1.0)
        x = int(round(cf[0] + r * np.cos(a)))
        y = int(round(cf[1] + r * np.sin(a)))
        if not (0 <= x < W and 0 <= y < H):
            continue
        if ink[max(0, y - 3):y + 4, max(0, x - 3):x + 4].any():
            hit += 1
    return hit / float(samples)


def _verify_fillet(bw, elements, r_px, tip, ink_tol=3.0, cover_min=0.70):
    """
    圆角（R 标注）的显式几何验证。

    圆角在图上必然**同时相切于两个已知要素**（圆或外轮廓弧）—— 这是它的
    作图依据。于是：对每对要素 × 4 种相切组合求候选圆心，再沿候选弧采样，
    看墨迹是否真的落在弧上。命中即接地成功，并顺带得到两个切点。
    """
    ink = (bw > 0).astype(np.uint8)
    best = None
    for i in range(len(elements)):
        for j in range(i + 1, len(elements)):
            r1, r2 = elements[i]["r_px"], elements[j]["r_px"]
            c1 = np.array([elements[i]["cx"], elements[i]["cy"]], dtype=float)
            c2 = np.array([elements[j]["cx"], elements[j]["cy"]], dtype=float)
            d = float(np.hypot(*(c2 - c1)))
            if d < 1e-6:
                continue
            for s1 in (+1, -1):
                for s2 in (+1, -1):
                    R1, R2 = r_px + s1 * r1, r_px + s2 * r2
                    if R1 <= 0 or R2 <= 0:
                        continue
                    if abs(R1 - R2) > d or R1 + R2 < d:
                        continue
                    a = (R1 * R1 - R2 * R2 + d * d) / (2 * d)
                    h2 = R1 * R1 - a * a
                    if h2 <= 0:
                        continue
                    h = float(np.sqrt(h2))
                    u = (c2 - c1) / d                       # c1 → c2 单位向量
                    foot = c1 + a * u
                    perp = np.array([-u[1], u[0]])          # 垂直方向
                    for sg in (+1, -1):
                        cf = foot + sg * h * perp
                        # 两个切点（s=+1 外切 / s=-1 内切）
                        v1 = cf - c1; v2 = cf - c2
                        n1 = float(np.hypot(*v1)); n2 = float(np.hypot(*v2))
                        if n1 < 1e-6 or n2 < 1e-6:
                            continue
                        t1 = (c1[0] + s1 * r1 * v1[0] / n1,
                              c1[1] + s1 * r1 * v1[1] / n1)
                        t2 = (c2[0] + s2 * r2 * v2[0] / n2,
                              c2[1] + s2 * r2 * v2[1] / n2)
                        cover = _arc_ink_ratio(ink, cf, r_px, t1, t2)
                        if cover < cover_min:
                            continue
                        # 引线尖端应落在这段候选弧上
                        if tip is not None:
                            on_arc = abs(np.hypot(tip[0] - cf[0],
                                                  tip[1] - cf[1]) - r_px)
                            if on_arc > 12:
                                continue
                        else:
                            on_arc = 0.0
                        score = cover - 0.001 * on_arc
                        if best is None or score > best[0]:
                            best = (score, cf, t1, t2, cover, i, j, s1, s2)
    if best is None:
        return None
    _, cf, t1, t2, cover, i, j, s1, s2 = best
    return {"cx": float(cf[0]), "cy": float(cf[1]), "r_px": float(r_px),
            "cpx": [float(cf[0]), float(cf[1])],
            "coverage": round(float(cover), 3),
            "tangent": [[round(float(t1[0]), 1), round(float(t1[1]), 1)],
                        [round(float(t2[0]), 1), round(float(t2[1]), 1)]],
            "tangent_to": [i, j],
            "tangency": ["外切" if s1 > 0 else "内切",
                         "外切" if s2 > 0 else "内切"]}


# ======================================================================
# 5) 接地主流程
# ======================================================================
def ground(geometry, annotations, mm_per_px, img_path=None, tol=0.08):
    """
    标注接地：把每条标注绑定到几何要素。
    返回 [{annotation, target, target_mm, method, confidence}, ...]
    """
    from .geometry import load_binary
    bw = None
    if img_path:
        _, bw = load_binary(img_path)

    circles = geometry.get("circles", [])
    lines = geometry.get("lines", [])

    # 外轮廓弧（波浪外缘等）也算进「可绑定要素」，供直径/圆角接地使用
    arcs = find_contour_arcs(bw, circles) if bw is not None else []
    geometry.setdefault("arcs", arcs)
    elements = circles + arcs

    out = []
    for a in annotations:
        kind = a["type"]
        vals = a["values"] or []
        tips = _leader_candidates(bw, a["box_px"]) if bw is not None else []
        res = None

        if kind in ("diameter", "pattern_dia") and vals:
            res = _ground_diameter(elements, bw, a, vals[-1], mm_per_px, tips, tol)
        elif kind == "radius" and vals:
            res = _ground_radius(elements, bw, a, vals[0], mm_per_px, tips, tol)
        elif kind == "linear" and vals:
            res = _ground_linear(lines, circles, bw, a, vals[0], mm_per_px, tips)

        if res is None:                       # 兜底：就近
            res = _nearest_geometry(circles, a["center_px"]) or {}

        rec = {"annotation": a, "method": res.get("method", "unmatched"),
               "confidence": res.get("conf", 0.0)}
        if res.get("target"):
            rec["target"] = res["target"]
        if res.get("leader_tip"):
            rec["leader_tip_px"] = [round(float(v), 1) for v in res["leader_tip"]]
        if res.get("measured_mm") is not None:
            rec["measured_mm"] = res["measured_mm"]
        if res.get("note"):
            rec["note"] = res["note"]
        out.append(rec)
    return out


def _target_of(el, mm_per_px):
    """把「可绑定要素」（整圆 或 外轮廓弧）转成接地目标描述。"""
    is_arc = "coverage" in el
    t = {"kind": "arc" if is_arc else "circle",
         "cx": round(float(el["cx"]), 1),
         "cy": round(float(el["cy"]), 1),
         "r_px": round(float(el["r_px"]), 1),
         "d_mm": round(2 * el["r_px"] * mm_per_px, 2)}
    if is_arc:
        t["coverage"] = el["coverage"]
    return t


def _tip_on_circle(cands, tips, tol_px):
    """
    在「候选圆 × 候选引线末端」里找最贴合的一对。
    只有真正指着该圆的引线，末端才会落在它的圆周上 —— 借此消歧同半径多圆。
    返回 (圆, 末端) 或 (None, None)。
    """
    best = None
    for tip in tips:
        for c in cands:
            d = abs(np.hypot(tip[0] - c["cx"], tip[1] - c["cy"]) - c["r_px"])
            if best is None or d < best[0]:
                best = (d, c, tip)
    if best is not None and best[0] <= tol_px:
        return best[1], best[2]
    return None, None


def _ground_diameter(elements, bw, a, mm, mm_per_px, tips, tol):
    exp_r = (mm / mm_per_px) / 2.0
    cands = [e for e in elements if abs(e["r_px"] - exp_r) <= tol * exp_r]
    if cands:
        tip_r_px = max(14.0, 0.03 * exp_r)
        pick, tip = _tip_on_circle(cands, tips, tip_r_px)
        how = "leader"
        if pick is None:                       # 引线指不准 → 退化为按位置就近
            pick, how = _pick_by_tip(cands, tips[0] if tips else None,
                                     a["center_px"])
        err = abs(pick["r_px"] - exp_r) / exp_r
        is_arc = "coverage" in pick
        return {
            "target": _target_of(pick, mm_per_px),
            "method": ("dia+leader" if how == "leader" else "dia+radius") +
                      ("/arc" if is_arc else ""),
            "conf": round(1.0 - err, 3),
            "leader_tip": list(tip) if tip else (tips[0] if tips else None),
            "measured_mm": round(2 * pick["r_px"] * mm_per_px, 2),
            "note": ("外轮廓弧段（圆周覆盖 %.0f%%），非整圆"
                     % (100 * pick["coverage"])) if is_arc else None,
        }
    # 半径匹配落空 → 波浪外缘/非整圆：在引线末端做局部圆弧拟合兜底
    for tip in (tips or []):
        arc = _fit_arc_at(bw, tip) if bw is not None else None
        if arc:
            err = abs(arc["r_px"] - exp_r) / exp_r
            if err <= tol:
                return {
                    "target": {"kind": "arc",
                               "cx": round(arc["cx"], 1),
                               "cy": round(arc["cy"], 1),
                               "r_px": round(arc["r_px"], 1),
                               "d_mm": round(2 * arc["r_px"] * mm_per_px, 2)},
                    "method": "dia+arcfit",
                    "conf": round(max(0.0, 1.0 - err), 3),
                    "leader_tip": list(tip),
                    "measured_mm": round(2 * arc["r_px"] * mm_per_px, 2),
                    "note": "弧拟合：残差 %.2fpx，窗口 %dpx"
                            % (arc["rmse"], arc["win"]),
                }
    return None


def _ground_radius(elements, bw, a, mm, mm_per_px, tips, tol):
    exp_r = mm / mm_per_px
    cands = [e for e in elements if abs(e["r_px"] - exp_r) <= tol * exp_r]
    if cands:
        tip_r_px = max(14.0, 0.03 * exp_r)
        pick, tip = _tip_on_circle(cands, tips, tip_r_px)
        if pick is None:
            pick, tip = _pick_by_tip(cands, tips[0] if tips else None,
                                     a["center_px"])
        err = abs(pick["r_px"] - exp_r) / exp_r
        return {
            "target": _target_of(pick, mm_per_px),
            "method": "rad+leader" if tip is not None else "rad+radius",
            "conf": round(1.0 - err, 3),
            "leader_tip": list(tip) if tip else (tips[0] if tips else None),
            "measured_mm": round(pick["r_px"] * mm_per_px, 2),
        }
    # 圆角：必然同时相切于两个已知要素 —— 用相切条件反解圆心再验证
    if bw is not None:
        for tip in (tips or []):
            fil = _verify_fillet(bw, elements, exp_r, tip)
            if fil:
                return {
                    "target": {"kind": "fillet",
                               "cx": fil["cx"], "cy": fil["cy"],
                               "r_px": round(fil["r_px"], 1),
                               "d_mm": round(2 * fil["r_px"] * mm_per_px, 2),
                               "tangent_px": fil["tangent"],
                               "coverage": fil["coverage"]},
                    "method": "rad+tangent",
                    "conf": round(0.85 + 0.15 * fil["coverage"], 3),
                    "leader_tip": list(tip),
                    "measured_mm": round(fil["r_px"] * mm_per_px, 2),
                    "note": "圆角：相切求解，弧上墨迹覆盖 %.0f%%"
                            % (100 * fil["coverage"]),
                }
    for tip in (tips or []):
        arc = _fit_arc_at(bw, tip, wins=(380, 560, 800)) if bw is not None else None
        if arc:
            err = abs(arc["r_px"] - exp_r) / exp_r
            if err <= 0.15:                    # 大半径弧拟合精度放宽
                return {
                    "target": {"kind": "arc",
                               "cx": round(arc["cx"], 1),
                               "cy": round(arc["cy"], 1),
                               "r_px": round(arc["r_px"], 1),
                               "d_mm": round(2 * arc["r_px"] * mm_per_px, 2)},
                    "method": "rad+arcfit",
                    "conf": round(max(0.0, 1.0 - err), 3),
                    "leader_tip": list(tip),
                    "measured_mm": round(arc["r_px"] * mm_per_px, 2),
                    "note": "大半径弧拟合：残差 %.2fpx" % arc["rmse"],
                }
    return None


def _pick_by_tip(cands, tip, box_center):
    """同半径多候选：用引线尖端落在哪个圆周上来定案。"""
    if tip is not None:
        best, bd = None, 1e18
        for c in cands:
            d = abs(np.hypot(tip[0] - c["cx"], tip[1] - c["cy"]) - c["r_px"])
            if d < bd:
                bd, best = d, c
        if best is not None and bd <= 12:
            return best, "tip"
    # 退化：离标注框最近
    return min(cands, key=lambda c: np.hypot(c["cx"] - box_center[0],
                                             c["cy"] - box_center[1])), "near"


# ----------------------------------------------------------------------
# 线性尺寸：量尺寸线跨度 + 两端吸附
# ----------------------------------------------------------------------
def _ground_linear(lines, circles, bw, a, mm, mm_per_px, tip, tol=0.10):
    x, y, w, h = [float(v) for v in a["box_px"]]
    cx, cy = x + w / 2.0, y + h / 2.0
    horizontal = w >= h
    exp_span = mm / mm_per_px

    # 首选：尺寸界线（垂直于尺寸线、从被测要素引出，位置即尺寸端点）
    span = None
    if bw is not None:
        span = _dim_boundaries(bw, a["box_px"], exp_span, tol)
    # 兜底 1：箭头尖（界线被遮挡时）
    if span is None and bw is not None:
        span = _dim_span_by_arrows(bw, a["box_px"], exp_span, tol)
    # 兜底 2：量尺寸线本身的跨度
    if span is None:
        span = _dim_span(lines, (cx, cy), horizontal, exp_span, tol)
    if span is None:
        return None
    p, q = span

    ends = []
    for pt in (p, q):
        hit = None
        for i, c in enumerate(circles):
            if np.hypot(pt[0] - c["cx"], pt[1] - c["cy"]) <= 35:
                hit = {"what": "center", "index": i,
                       "pt": [round(float(c["cx"]), 1), round(float(c["cy"]), 1)]}
                break
        ends.append(hit or {"what": "outline",
                            "pt": [round(float(pt[0]), 1), round(float(pt[1]), 1)]})

    measured = float(np.hypot(q[0] - p[0], q[1] - p[1])) * mm_per_px
    err = abs(measured - mm) / max(mm, 1e-6)
    if err > 0.10:
        return None

    if ends[0]["what"] == "center" and ends[1]["what"] == "center":
        desc = "圆心距 #%d—#%d" % (ends[0]["index"], ends[1]["index"])
    elif ends[0]["what"] == "center" or ends[1]["what"] == "center":
        desc = "圆心—轮廓"
    else:
        desc = "轮廓范围"
    return {
        "target": {"kind": "distance", "p1": [round(float(p[0]), 1), round(float(p[1]), 1)],
                   "p2": [round(float(q[0]), 1), round(float(q[1]), 1)],
                   "len_px": round(float(np.hypot(q[0] - p[0], q[1] - p[1])), 1),
                   "len_mm": round(measured, 2), "ends": ends},
        "method": "dim_line+" + desc,
        "conf": round(max(0.0, 1.0 - err), 3),
        "measured_mm": round(measured, 2),
        "note": desc,
    }


def _dim_axis(bw, center, horizontal, corridor, reach):
    """
    在文字附近找「尺寸线轴线」，返回它在横向上的坐标
    （水平尺寸 → 轴线的 y；竖直尺寸 → 轴线的 x）。

    尺寸线是走廊内 **沿标注方向贯穿** 的那条线 —— 用「沿方向的墨迹覆盖率」
    找峰（轮廓线往往也贯穿，所以再按「离文字中心近」加权：国标允许文字
    甩到尺寸线外侧，但不会甩太远）。
    """
    H, W = bw.shape
    cx, cy = center
    corridor, reach = int(corridor), int(reach)
    if horizontal:
        x0, x1 = max(0, int(cx - reach)), min(W, int(cx + reach))
        y0, y1 = max(0, int(cy - corridor)), min(H, int(cy + corridor))
    else:
        x0, x1 = max(0, int(cx - corridor)), min(W, int(cx + corridor))
        y0, y1 = max(0, int(cy - reach)), min(H, int(cy + reach))
    sub = bw[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    span = sub.shape[1] if horizontal else sub.shape[0]
    prof = (sub > 0).sum(axis=1 if horizontal else 0) / float(max(span, 1))
    if prof.max() <= 0.15:
        return None
    c_local = (cy - y0) if horizontal else (cx - x0)
    idx = np.arange(len(prof))
    score = prof * np.exp(-np.abs(idx - c_local) / max(corridor * 1.5, 1.0))
    k = int(idx[int(np.argmax(score))])
    return (k + y0) if horizontal else (k + x0)


def _dim_thickness(bw, axis, horizontal, center, reach, band):
    """
    沿尺寸线量「横向墨迹厚度」剖面。

    对竖直尺寸线（horizontal=False）：
      - 尺寸线本身    ：横向 2~4px          → 厚度 ≈ 3（低于阈值）
      - 尺寸界线(水平)：沿轴方向只占一个线宽 → 厚度鼓一个**窄尖刺**（区段 2~8px）
      - 箭头(实心三角)：沿轴方向 20~40px     → 厚度鼓一个**宽包**（区段 ≥10px）
    对水平尺寸线同理（横竖互换）。
    返回 (thick, t0, band_px)；无效时 thick 为 None。
    """
    H, W = bw.shape
    cx, cy = center
    t_c = cx if horizontal else cy
    t_max = W if horizontal else H
    t0 = int(max(0, t_c - reach))
    t1 = int(min(t_max, t_c + reach))
    if t1 - t0 < 8:
        return None, None, 0.0
    u = int(round(axis))
    if horizontal:
        lo, hi = max(0, u - band), min(H, u + band + 1)
        if hi <= lo:
            return None, None, 0.0
        thick = (bw[lo:hi, t0:t1] > 0).sum(axis=0)
    else:
        lo, hi = max(0, u - band), min(W, u + band + 1)
        if hi <= lo:
            return None, None, 0.0
        thick = (bw[t0:t1, lo:hi] > 0).sum(axis=1)
    return thick.astype(float), t0, float(hi - lo)


def _segments(marks):
    """把布尔数组切成连续 True 区段，返回 [(i, j), ...]"""
    segs, i, n = [], 0, len(marks)
    while i < n:
        if marks[i]:
            j = i
            while j + 1 < n and marks[j + 1]:
                j += 1
            segs.append((i, j)); i = j + 1
        else:
            i += 1
    return segs


def _dim_boundaries(bw, box, exp_span, tol):
    """
    **尺寸界线法**（首选）。

    尺寸界线垂直于尺寸线、从被测量要素直接引出 —— 它的位置就是尺寸端点，
    比「箭头尖」精确得多（箭头尖受绘制粗细影响，界线不会）。

    判据：在尺寸线的厚度剖面上，尺寸界线是**窄尖刺**（沿轴方向只占一个
    线宽 2~8px），箭头是宽包（≥10px），尺寸线本身低于阈值 —— 三者被
    区段宽度干净分开，不会互相误认。
    """
    x, y, w, h = [float(v) for v in box]
    cx, cy = x + w / 2.0, y + h / 2.0
    corridor = max(2.5 * max(w, h), 90.0)
    reach = exp_span * 0.85 + 3.0 * max(w, h) + 90.0
    band = int(max(10, 0.45 * max(w, h)))

    best, berr = None, None
    for horizontal in (True, False):
        axis = _dim_axis(bw, (cx, cy), horizontal, corridor, reach)
        if axis is None:
            continue
        thick, t0, band_px = _dim_thickness(bw, axis, horizontal,
                                            (cx, cy), reach, band)
        if thick is None:
            continue
        base = float(np.percentile(thick, 30))
        thr = max(base + 4.0, 0.28 * band_px, 8.0)
        cands = [float(t0 + (i + j) / 2.0) for i, j in _segments(thick >= thr)
                 if 2 <= (j - i + 1) <= 8]
        if len(cands) < 2:
            continue

        c = cx if horizontal else cy
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                lo, hi = min(cands[i], cands[j]), max(cands[i], cands[j])
                # 尺寸必须把文字夹在中间（文字在尺寸线上/旁，不会跑到外侧）
                if not (lo <= c + 0.45 * exp_span and
                        hi >= c - 0.45 * exp_span):
                    continue
                err = abs((hi - lo) - exp_span) / max(exp_span, 1e-6)
                if err <= tol and (berr is None or err < berr):
                    berr, best = err, (horizontal, axis, lo, hi)
    if best is None:
        return None
    horizontal, axis, lo, hi = best
    if horizontal:
        return (lo, float(axis)), (hi, float(axis))
    return (float(axis), lo), (float(axis), hi)


def _dim_span_by_arrows(bw, box, exp_span, tol):
    """
    箭头尖法定尺寸跨度（**兜底**：尺寸界线被遮挡/连成一体时用）。

    同一厚度剖面上，箭头是**宽鼓包**（沿轴 10~90px），鼓包内厚度最小处即
    三角形尖端。文字横排不代表尺寸线水平（50/20/50 在图纸上是竖标的），
    所以水平、垂直两个方向都检。
    """
    x, y, w, h = [float(v) for v in box]
    cx, cy = x + w / 2.0, y + h / 2.0
    corridor = max(2.5 * max(w, h), 90.0)
    reach = exp_span * 0.85 + 3.0 * max(w, h) + 90.0
    band = int(max(10, 0.45 * max(w, h)))
    best, berr = None, None
    for horizontal in (True, False):
        axis = _dim_axis(bw, (cx, cy), horizontal, corridor, reach)
        if axis is None:
            continue
        thick, t0, band_px = _dim_thickness(bw, axis, horizontal,
                                            (cx, cy), reach, band)
        if thick is None:
            continue
        base = float(np.percentile(thick, 30))
        thr = max(base + 4.0, 0.28 * band_px, 8.0)
        tips = []
        for i, j in _segments(thick >= thr):
            L = j - i + 1
            if L < 10 or L > 90:
                continue
            seg = thick[i:j + 1]
            k = int(np.argmin(seg))                 # 细的一端 = 尖端
            if L >= 8:
                d = np.abs(np.arange(L) - k).astype(float)
                sd, dd = seg.std(), d.std()
                if sd > 1e-6 and dd > 1e-6:
                    r = float(((seg - seg.mean()) *
                               (d - d.mean())).mean() / (sd * dd))
                    if r < 0.55:                    # 不是楔形 → 不是箭头
                        continue
            t = float(t0 + i + k)
            tips.append((t, float(axis)) if horizontal else (float(axis), t))
        if len(tips) < 2:
            continue
        along = (lambda p: p[0]) if horizontal else (lambda p: p[1])
        c = along((cx, cy))
        for i in range(len(tips)):
            for j in range(i + 1, len(tips)):
                a1, a2 = along(tips[i]), along(tips[j])
                lo, hi = min(a1, a2), max(a1, a2)
                if not (lo <= c + 0.35 * exp_span and
                        hi >= c - 0.35 * exp_span):
                    continue
                err = abs((hi - lo) - exp_span) / max(exp_span, 1e-6)
                if err <= tol and (berr is None or err < berr):
                    berr, best = err, (tips[i], tips[j])
    if best is None:
        return None
    return best[0], best[1]

def _dim_span(lines, center, horizontal, exp_span, tol, corridor=90, reach=1.3):
    """
    量尺寸线的跨度：沿文本朝向开走廊，把走廊内共线的线段并起来，
    取并集的两个端点。走廊宽度按「期望跨度」缩放，避免吸到无关的长线。
    """
    cx, cy = center
    reach_px = max(exp_span * reach, 260.0)

    def perp(p):
        return abs(p[1] - cy) if horizontal else abs(p[0] - cx)

    def along(p):
        return p[0] if horizontal else p[1]

    def para(p1, p2):
        dx, dy = abs(p2[0] - p1[0]), abs(p2[1] - p1[1])
        return dx >= dy if horizontal else dy >= dx

    segs = []
    for l in lines:
        p1, p2 = l["p1"], l["p2"]
        if not para(p1, p2):
            continue
        if max(perp(p1), perp(p2)) > corridor:
            continue
        a, b = along(p1), along(p2)
        lo, hi = min(a, b), max(a, b)
        if hi < along((cx, cy)) - reach_px or lo > along((cx, cy)) + reach_px:
            continue
        segs.append((min(lo, hi), max(lo, hi)))
    if not segs:
        return None

    # 合并重叠/相接的区间
    segs.sort()
    merged = [list(segs[0])]
    for lo, hi in segs[1:]:
        if lo <= merged[-1][1] + 12:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    # 取包含文本、长度最接近期望跨度的那一段
    c = along((cx, cy))
    best, berr = None, None
    for lo, hi in merged:
        if not (lo - 40 <= c <= hi + 40):
            continue
        err = abs((hi - lo) - exp_span) / max(exp_span, 1e-6)
        if err <= tol and (berr is None or err < berr):
            berr, best = err, (lo, hi)
    if best is None:
        return None
    lo, hi = best
    if horizontal:
        return (lo, cy), (hi, cy)
    return (cx, lo), (cx, hi)


def _nearest_geometry(circles, center):
    """兜底：标注中心离哪个圆周最近。"""
    best = None
    for i, c in enumerate(circles):
        d = abs(np.hypot(c["cx"] - center[0], c["cy"] - center[1]) - c["r_px"])
        if best is None or d < best[0]:
            best = (d, i, c)
    if best is None or best[0] > 260:
        return None
    d, i, c = best
    return {"target": {"kind": "circle",
                       "cx": round(float(c["cx"]), 1),
                       "cy": round(float(c["cy"]), 1),
                       "r_px": round(float(c["r_px"]), 1)},
            "method": "nearest",
            "conf": round(1.0 / (1.0 + d / 120.0), 3)}


def attach_mm(grounded, mm_per_px, geometry=None):
    """把几何的像素尺度换算成 mm，写回接地结果。"""
    for g in grounded:
        t = g.get("target")
        if not t:
            continue
        if t["kind"] in ("circle", "arc"):
            t.setdefault("d_mm", round(2 * t["r_px"] * mm_per_px, 2))
            t["r_mm"] = round(t["r_px"] * mm_per_px, 2)
        elif t["kind"] == "line":
            t.setdefault("len_mm", round(t["len_px"] * mm_per_px, 2))
        elif t["kind"] == "distance":
            t.setdefault("len_mm", round(t["len_px"] * mm_per_px, 2))
    return grounded
