# -*- coding: utf-8 -*-
r"""
几何层提取器（Geometry Layer Extractor）
=========================================
对应 Drawing-Recode 的「几何编码器」（原论文用 CLIP ViT-L/14）。

本实现不依赖神经网络，用「两级传统 CV」替代：

  一级 —— 找圆心（proposal）
     霍夫圆（HoughCircles） + 高圆度轮廓（findContours），两路互相补盲。
     再对每个候选做**圆周覆盖率验证**：真圆的圆周应大部分落在墨线上，
     而文字/交叉线里冒出来的假圆覆盖率极低。这一步把上百个假圆清到个位数。

  二级 —— 找同心圆（refine）
     在一个已验证的圆心上做**径向扫描**，用「最长连续弧」判据找出所有
     同心圆环。这一步能捞出被其它线穿插、一级检测漏掉的圆（如 Φ75 小孔、
     中心 Φ150 内环），因为真圆即使被遮挡也必有较长的一段连续弧。

产出：几何表（每条几何要素的 类型/几何参数/中心坐标）
"""
import cv2
import numpy as np


# ----------------------------------------------------------------------
# 读图 / 二值化
# ----------------------------------------------------------------------
def load_binary(path, denoise=True):
    """读图 → 灰度 → 二值化（黑线白底 → 反转成 线=白）。"""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError("读不到图片: %s" % path)
    # 图纸是纯黑白线图，用全局阈值即可（自适应反而在空白处生噪）
    _, bw = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)
    if denoise:
        bw = cv2.medianBlur(bw, 3)
    return img, bw


def _ink_mask(bw, band):
    """把墨线膨胀 band 像素 —— 用于快速判「某点附近有没有线」。"""
    inv = (bw > 0).astype(np.uint8)
    k = 2 * band + 1
    return cv2.dilate(inv, np.ones((k, k), np.uint8))


def _circum_profile(cx, cy, r, ink, h, w, npoints=720):
    """沿半径 r 的圆周采样，返回布尔命中向量（True=该角度落在墨线附近）。"""
    ang = np.linspace(0.0, 2 * np.pi, npoints, endpoint=False)
    xs = np.round(cx + r * np.cos(ang)).astype(int)
    ys = np.round(cy + r * np.sin(ang)).astype(int)
    valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    hit = np.zeros(npoints, dtype=bool)
    hit[valid] = ink[ys[valid], xs[valid]] > 0
    return hit


def _coverage(cx, cy, r, ink, h, w, npoints=720):
    """圆周落在墨线上的比例（0~1）。"""
    return float(_circum_profile(cx, cy, r, ink, h, w, npoints).mean())


def _longest_arc(hit):
    """环状布尔向量里最长连续 True 段占整圈的比例。"""
    n = len(hit)
    if hit.all():
        return 1.0
    if not hit.any():
        return 0.0
    miss = np.where(~hit)[0]
    rolled = np.roll(hit, -int(miss[0]))
    best = cur = 0
    for v in rolled:
        cur = cur + 1 if v else 0
        if cur > best:
            best = cur
    return best / n


def _refine_circle(cx, cy, r, ink, h, w, band_px=3.0, npoints=720, cov_th=0.72):
    """
    局部微调圆心与半径，最大化圆周覆盖率。

    霍夫给的中心常有几像素偏差，而图纸线条只有 2~3px 宽 —— 直接判覆盖率会
    因这点偏差把真圆误杀。这里在 (cx,cy,r) 附近做小范围网格搜索，取覆盖率
    最高者；若最高覆盖率仍低于 cov_th 则判定为假圆（返回 None）。
    """
    best = None
    for ddx in range(-8, 9, 2):
        for ddy in range(-8, 9, 2):
            for dr in range(-6, 7, 2):
                nx, ny, nr = cx + ddx, cy + ddy, r + dr
                if nr <= 0:
                    continue
                cov = _coverage(nx, ny, nr, ink, h, w, npoints)
                if best is None or cov > best[3]:
                    best = (nx, ny, nr, cov)
                if cov >= 0.999:
                    break
    if best and best[3] >= cov_th:
        return best  # (cx, cy, r, cov)
    return None


# ----------------------------------------------------------------------
# 一级：找圆心
# ----------------------------------------------------------------------
def _propose_by_hough(bw, min_radius_px, max_radius_px,
                      param2=100, min_dist_ratio=0.02):
    h, w = bw.shape
    min_dist = max(20, int(min(h, w) * min_dist_ratio))
    circles = cv2.HoughCircles(
        bw, cv2.HOUGH_GRADIENT, dp=2, minDist=min_dist,
        param1=150, param2=param2,
        minRadius=min_radius_px, maxRadius=max_radius_px,
    )
    if circles is None:
        return []
    return [(float(x), float(y), float(r))
            for x, y, r in np.round(circles[0]).tolist()]


def _propose_by_contour(bw, min_area=3000, min_circ=0.85, max_rstd=0.06):
    """高圆度轮廓 → 圆心候选（补霍夫的盲）。"""
    cnts, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cnts:
        area = cv2.contourArea(c)
        peri = cv2.arcLength(c, True)
        if area < min_area or peri < 100:
            continue
        circ = 4 * np.pi * area / (peri * peri)
        (cx, cy), r = cv2.minEnclosingCircle(c)
        pts = c.reshape(-1, 2).astype(float)
        d = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
        rstd = d.std() / max(d.mean(), 1e-6)
        if circ > min_circ and rstd < max_rstd:
            out.append((float(cx), float(cy), float(r)))
    return out


def _merge_centers(cands, tol_px=40):
    """把圆心靠得很近（绝对像素距离）的候选合并成一个（保留半径大的）。"""
    kept = []
    for cx, cy, r in sorted(cands, key=lambda c: -c[2]):
        if not any(abs(cx - kx) < tol_px and abs(cy - ky) < tol_px
                   for kx, ky, kr in kept):
            kept.append((cx, cy, r))
    return kept


# ----------------------------------------------------------------------
# 二级：在圆心上径向扫描，找所有同心圆
# ----------------------------------------------------------------------
def _radial_sweep(cx, cy, ink, h, w, r_min, r_max,
                  cov_th=0.70, arc_th=0.45, max_segs=6, npoints=720):
    """
    在圆心 (cx,cy) 上从 r_min 到 r_max 逐半径扫描，
    用「覆盖率 + 最长连续弧 + 弧段数」判据挑出真圆环。
    同一个圆环会有连续几个半径都通过 —— 取其中最好的一个。
    """
    hits = []
    for r in range(int(r_min), int(r_max) + 1):
        prof = _circum_profile(cx, cy, r, ink, h, w, npoints)
        cov = float(prof.mean())
        if cov < cov_th:
            continue
        arc = _longest_arc(prof)
        if arc < arc_th:
            continue
        segs = _count_segments(prof)
        if segs > max_segs:
            continue
        score = cov * 0.5 + arc * 0.5
        hits.append((r, cov, arc, segs, score))

    # 相邻半径的通过点聚成一个环，取 score 最高者
    rings = []
    cur = []
    for rec in hits:
        if cur and rec[0] - cur[-1][0] <= 3:
            cur.append(rec)
        else:
            if cur:
                rings.append(max(cur, key=lambda x: x[4]))
            cur = [rec]
    if cur:
        rings.append(max(cur, key=lambda x: x[4]))
    return rings


def _count_segments(hit):
    """环状布尔向量里的连续 True 段数。"""
    if hit.all():
        return 1
    if not hit.any():
        return 0
    arr = np.concatenate([hit, hit[:1]])  # 首尾相接闭合
    return int(np.sum((~arr[:-1]) & arr[1:]))


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------
def extract(path, min_radius_px=25, max_radius_px=1600,
            band=2, cov_th=0.72, verbose=False, **kw):
    """
    提取几何层。

    参数
    ----
    min_radius_px / max_radius_px : 霍夫候选的半径范围（放大默认值以适配大图）
    band        : 判「点在墨线上」的容差半径（像素）
    cov_th      : 一级圆心验证的圆周覆盖率阈值
    """
    gray, bw = load_binary(path)
    h, w = bw.shape
    ink = _ink_mask(bw, band)

    # ---- 一级：圆心候选 ----
    cands = _propose_by_hough(bw, min_radius_px, max_radius_px) \
        + _propose_by_contour(bw)
    if verbose:
        print("[几何] 圆心候选(原始): %d" % len(cands))

    # 圆周覆盖率验证（带局部微调）：真圆的圆周应大部分在墨线上
    verified = []
    for cx, cy, r in cands:
        ref = _refine_circle(cx, cy, r, ink, h, w, cov_th=cov_th)
        if ref:
            verified.append((ref[0], ref[1], ref[2]))
    centers = _merge_centers(verified)
    if verbose:
        print("[几何] 圆心候选(验证后): %d" % len(centers))

    # ---- 二级：径向扫描，捞全部同心圆 ----
    circles = []
    for cx, cy, r0 in centers:
        rings = _radial_sweep(cx, cy, ink, h, w,
                              r_min=min_radius_px, r_max=max_radius_px)
        for r, cov, arc, segs, score in rings:
            circles.append({
                "cx": round(cx, 1), "cy": round(cy, 1), "r_px": float(r),
                "coverage": round(cov, 3), "arc": round(arc, 3),
                "segments": segs,
            })
    circles = _dedup_circles(
        [(c["cx"], c["cy"], c["r_px"]) for c in circles])

    # ---- 直线 & 轮廓 ----
    lines = extract_lines(bw)
    contours = extract_contours(bw)

    return {
        "image_size": [int(w), int(h)],
        "circles": [{"cx": cx, "cy": cy, "r_px": r} for cx, cy, r in circles],
        "lines": [{"p1": [x1, y1], "p2": [x2, y2], "len_px": ln}
                  for x1, y1, x2, y2, ln in lines],
        "contours": contours,
    }


def extract_circles(bw, min_radius_px=25, max_radius_px=1600,
                    param2=100, min_dist_ratio=0.02, band=2, cov_th=0.72):
    """兼容旧接口：返回 [(cx, cy, r_px), ...]"""
    h, w = bw.shape
    ink = _ink_mask(bw, band)
    wband = _ink_mask(bw, band + 2)   # 宽容带，用于廉价预筛
    cands = _propose_by_hough(bw, min_radius_px, max_radius_px,
                              param2, min_dist_ratio) \
        + _propose_by_contour(bw)
    verified = []
    seen = []
    for cx, cy, r in cands:
        # 廉价预筛：宽容带下覆盖率都不够 → 直接丢
        if _coverage(cx, cy, r, wband, h, w, npoints=180) < 0.55:
            continue
        # 已接受过同一处圆 → 不重复微调
        if any(abs(cx - sx) < 30 and abs(cy - sy) < 30 for sx, sy in seen):
            continue
        ref = _refine_circle(cx, cy, r, ink, h, w, cov_th=cov_th)
        if ref:
            verified.append((ref[0], ref[1], ref[2]))
            seen.append((ref[0], ref[1]))
    centers = _merge_centers(verified)
    out = []
    for cx, cy, _ in centers:
        for r, cov, arc, segs, score in _radial_sweep(
                cx, cy, ink, h, w, min_radius_px, max_radius_px):
            out.append((cx, cy, float(r)))
    return _dedup_circles(out)


def extract_lines(bw, min_len_ratio=0.05, max_gap=6):
    """概率霍夫线检测。返回 [(x1,y1,x2,y2,len_px), ...]"""
    h, w = bw.shape
    min_len = int(min(h, w) * min_len_ratio)
    lines = cv2.HoughLinesP(bw, 1, np.pi / 180, threshold=80,
                            minLineLength=min_len, maxLineGap=max_gap)
    out = []
    if lines is not None:
        arr = np.asarray(lines).reshape(-1, 4)
        for x1, y1, x2, y2 in arr.tolist():
            ln = float(np.hypot(x2 - x1, y2 - y1))
            out.append((float(x1), float(y1), float(x2), float(y2), ln))
    return out


def extract_contours(bw, min_area_ratio=0.002):
    """轮廓 + 多边形逼近（用于找外轮廓 / 视图边界）。"""
    h, w = bw.shape
    min_area = h * w * min_area_ratio
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < min_area:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        x, y, ww, hh = cv2.boundingRect(c)
        out.append({
            "bbox_px": [int(x), int(y), int(ww), int(hh)],
            "area_px": float(a),
            "vertices_px": approx.reshape(-1, 2).tolist(),
            "approx_sides": int(len(approx)),
        })
    return out


def _dedup_circles(circles, tol_ratio=0.05):
    """
    同心圆去重：圆心接近且半径接近的算同一个。
    注意：同心但半径不同（如 φ300 / φ150 / φ200）**必须保留** ——
          只去掉「圆心+半径都接近」的重复检出。
    """
    kept = []
    for cx, cy, r in sorted(circles, key=lambda c: -c[2]):
        dup = False
        for kx, ky, kr in kept:
            if (abs(cx - kx) < kr * tol_ratio and
                    abs(cy - ky) < kr * tol_ratio and
                    abs(r - kr) < kr * tol_ratio):
                dup = True
                break
        if not dup:
            kept.append((cx, cy, r))
    return kept
