# -*- coding: utf-8 -*-
r"""readops.py —— 读图算子库（图元 → 几何量）

## 为什么单独一层

建模算子（extrude / revolve / cut / hole / fillet…）在 `z2c_conv/op_lib.py` 已有 19 个。
本轮「12 件 → 三维」循环跑了 9 轮，**一次都没因缺建模算子失败** ——
失败全发生在「从图元里量出几何量」这一步（9 轮里我手写的适配代码，`segs_of` 抄了 3 份、
标注收集抄了 2 份、`solve_scale` 调用 2 处、`detect_circles` 改了 4 版、`solve_scale` 改了 5 版）。

而 Zero-to-CAD 的候选榜 top30 **全是建模动词**（extrude 84% / chamfer 73% / hole 58% /
revolve 17%…），**一个读图算子都没有**：Z2C 是「代码/文本 → CAD」，IR 是**给定的**，
它不需要读图。⇒ 这一族只能自己从真实图纸里挖，无现成答案可抄。本文件就是它的落点。

## 算子清单（全部纯函数：输入图元/标注，输出几何量，无副作用）

空间分派
    `by_view`        图元 → {视图索引: 线段列表}（first-match，用于"这条线属于哪个视图"）
    `segs_in_view`   图元 → 某视图内的线段子集（无 break，用于"把这个视图的东西全拿来"）
    `extents_of`     视图集合 → 全部实测跨度（宽/高）

几何提取
    `circle_of`      线段集合 → 同心圆半径
    `loop_of`        线段集合 → 闭合轮廓（含退化到外接矩形的显式标记）
    `profile_from_hatch` 剖面线层 → **材料截面轮廓**（孔自动被排除）
    `half_profile_of` 闭合轮廓 + 轴线 → **半剖轮廓**（补上轴线上的端点）
    `axis_view_of`   视图集合 → 带回转轴的视图 (view, 轴位置, 竖/横)
    `pair_of`        视图集合 → 投影相关的一对（长对正 / 高平齐）

数值标定
    `annos_of`       标注 → 候选值集合（并 Ø / 2R / 裸数字）
    `scale_of`       实测跨度 + 标注 → 比例 pt/mm
    `snap_to`        实测值 + 标注 → 吸附后的值

## 纪律

判据一旦定下就冻结。改进要走「改判据 + 写清为什么改」，**不允许为单件零件偷偷调参** ——
历史上的间隙阈值（0.12·rmax）与角度容差（±5%·rmax）都吃过这个亏：
为了让一件零件过，调了参数，结果另一件被误杀，来回改了好几轮。
"""
import math
import os
import sys

# 让 readops 可被独立 import（loop_of 内部要用同目录的 profile.py）
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

__all__ = [
    "by_view", "segs_in_view", "extents_of",
    "circle_of", "circles_in_view", "concentric_groups", "pick_holes",
    "components", "point_in_polygon", "circle_inside", "arrow_count_of",
    "loop_of", "profile_from_hatch", "section_outer_of_hatch",
    "stepped_profile", "half_profile_of",
    "axis_view_of", "pair_of", "three_views", "hatch_coverage", "hatch_fill_ratio",
    "centered_axis_of", "hatch_axial_span", "axisymmetric_section_of",
    "full_section_view_of",
    "pick_profile",
    "annos_of", "scale_of", "snap_to",
]


# ================================================================ 空间分派
def by_view(g, views, layer="粗实线层"):
    """图元 → {视图索引: 线段列表}。

    判据：线段**起点**落在某个视图 bbox 内（外扩 1pt 容差）就归给它，**first-match**。
    为什么用起点而不是两端、为什么 first-match：
      1. 用起点 ⇒ 跨视图边界的线段归属唯一，不会被两个视图重复计数；
      2. first-match ⇒ 与原 `route_annular.view_of` 语义一致（视图按顺序枚举）。
    """
    out = {}
    for s in g["segments"]:
        if s.get("layer") != layer:
            continue
        x, y = s["p1"]
        for i, v in enumerate(views):
            b = v["bbox"]
            if b[0] - 1 <= x <= b[2] + 1 and b[1] - 1 <= y <= b[3] + 1:
                out.setdefault(i, []).append(s)
                break
    return out


def segs_in_view(g, view, layer="粗实线层"):
    """某视图内的线段子集（**无 break**：一条线段可同时落在多个视图 bbox 里）。

    与 `by_view` 的差别不是笔误，是两个语义：
      · `by_view`     回答「这条线属于哪个视图」⇒ 必须唯一，用 first-match；
      · `segs_in_view` 回答「这个视图里有什么线」⇒ 按 bbox 取全集。
    """
    b = view["bbox"]
    return [s for s in g["segments"] if s.get("layer") == layer
            and b[0] - 1 <= s["p1"][0] <= b[2] + 1
            and b[1] - 1 <= s["p1"][1] <= b[3] + 1]


def extents_of(views):
    """视图集合 → 全部实测跨度（宽/高，四舍五入 0.1pt 去重，升序）。"""
    return sorted({round(v["w"], 1) for v in views}
                  | {round(v["h"], 1) for v in views})


# ================================================================ 几何提取
def circle_of(segs):
    """线段集合 → 同心圆。返回 `(圆心, [半径降序])`；认不出返回 `(None, [])`。

    做法：以质心为中心算所有端点到中心的距离，**按排序后的半径做间隙聚类**，
    每个簇就是一个同心圆。

    ★ 判据的演进（四次踩坑，每次都写清了根因）
      1. 先用"距离直方图找峰值" —— **不稳健**：圆被离散成弧段后，弦近似使半径在
         `[R·cos(π/n), R]` 内散布，峰值判据漏掉外圆（只认出 Ø6.5）。
      2. 改**排序半径的间隙聚类**：同心圆的半径天然分成间隔很开的簇
         （实测合金管垫片：Ø6.5 的 ~43 与 Ø12 的 ~74–80，中间有 30 的空白）。
      3. 加**角度覆盖校验**：真圆的点要绕中心铺开近 360°。不加这条会到处报假圆 ——
         sj-003 的 79pt 方块里报出 Ø94.8（半径超块宽，物理不可能）、sj-009 矩形报 Ø165.3。
         根因：矩形点的半径是**连续分布**，被间隙聚类切成了假簇。
      4. 角度校验的容差必须用**簇自身半径范围 [min(c), max(c)]**：外圆的簇内散布可达
         7.5%（r=80 时 74→80），早期卡 ±5%·rmax 会把外圆点滤掉大半 ⇒ 角度铺不满 ⇒ 真圆被误否。

    半径取**簇内最大值**：弧段端点恰好落在真半径上，取 max 比取均值更接近真值
    （均值被弦缩效应压低 ~0.24%）。
    """
    pts = []
    for s in segs:
        pts.append(s["p1"])
        pts.append(s["p2"])
    if len(pts) < 8:
        return None, []
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    rs = sorted(math.hypot(p[0] - cx, p[1] - cy) for p in pts)
    rmax = rs[-1]
    if rmax <= 0:
        return None, []

    # 间隙判据必须**相对**，不能按 rmax 取固定比例：
    # 底部垫片有 Ø12/Ø7.5/Ø6.5，Ø7.5 与 Ø6.5 只差 15%，用 0.12·rmax 会把这两条并成一簇，
    # 导致「没找到圆视图」。弦缩散布只有 ~0.5%（32 段圆 cos(π/32)=0.9952），4% 足够分开。
    clusters, cur = [], [rs[0]]
    for a, b in zip(rs, rs[1:]):
        if b - a > 0.04 * max(a, 1e-6):
            clusters.append(cur)
            cur = [b]
        else:
            cur.append(b)
    clusters.append(cur)

    out = []
    for c in clusters:
        if len(c) < 8:
            continue
        r = max(c)
        if r < 0.02 * rmax:
            continue
        lo, hi = min(c), max(c)
        angs = sorted(math.atan2(p[1] - cy, p[0] - cx) for p in pts
                      if lo - 1e-9 <= math.hypot(p[0] - cx, p[1] - cy) <= hi + 1e-9)
        if len(angs) < 8:
            continue
        gaps = [b - a for a, b in zip(angs, angs[1:])]
        gaps.append(angs[0] + 2 * math.pi - angs[-1])
        if max(gaps) > math.radians(45):
            continue                              # 铺不满一圈 ⇒ 不是圆
        out.append(round(r, 3))

    ded = []
    for r in sorted(out, reverse=True):
        if not ded or ded[-1] - r > rmax * 0.05:
            ded.append(r)
    return (cx, cy), ded


def loop_of(segs, bbox, frac=0.004, degrade=False):
    """线段集合 → 闭合外轮廓。返回 `(poly, degraded)`。

    degraded 语义：
      · `(poly, None)`    真轮廓
      · `(rect, "bbox")`  走环失败/退化 且 degrade=True ⇒ **显式降级**到外接矩形
      · `(None, 原因)`    走环失败 且 degrade=False

    ★ 为什么要"显式降级"：实测 sj-003（82 点环）与 sj-008（4 点环）走出的环面积为 0
      ⇒ 拉伸得到空体。宁可出一个"外接矩形剖面"的近似体**并如实标记**，
      也不要出空体 —— 这样偏差是可量化的，而不是一个 0。

    simplify 容差按视图尺寸的 frac 取（实测 0.4% 能压掉离散化毛刺又保住圆角）。
    """
    import profile as P

    # ★ **逐连通组走环，取面积最大的那个环**。
    #
    # 制图原则：「**一个视图对应一个投影**」⇒ 真外轮廓应在**同一个连通组**里。
    # 把整张视图的线段一次性喂给走环，不同图形会互相干扰 —— 实测 sj-003：
    #   视图块 79×79 里有 **9 个连通组**（200段真轮廓 / 317段+312段的 4×4 密集团 /
    #   若干 32 段的圆），直接整体走环时，**45×45 的小圆反而被选成"最大面"**，
    #   真轮廓（200 段那组，占视图 100%）走不出来。
    best = None
    span = max(bbox[2] - bbox[0], bbox[3] - bbox[1], 1.0)

    # ★ 先滤掉**文字 / 符号组**。
    #   制图规范（GB/T 4457.4）：「**粗实线 = 可见轮廓线**」，是**连续的长线段**；
    #   文字、符号则是**短线段的笔画密集聚集**。
    #
    #   判据必须是**相对的（段长 / 该组自身对角线）**，不能用绝对段长 ——
    #   踩过一次坑：圆的轮廓被离散成 200 段后，平均段长只有 1.24pt，
    #   比文字组的 0.8pt 大不了多少，用绝对阈值会把**真轮廓误当文字滤掉**。
    #
    #   实测 sj-003：
    #     文字组   4×4pt   / 317 段 / avg 0.8pt  ⇒ avg/diag = **0.14**
    #     真轮廓  79×79pt  / 200 段 / avg 1.24pt ⇒ avg/diag = **0.011**
    #   相差一个数量级 ⇒ 用 `avg/diag > 0.05` 判文字，两边都留足余量。
    groups = []
    for gp in components(segs):
        if len(gp) >= 4:
            gx = [p[0] for s in gp for p in (s["p1"], s["p2"])]
            gy = [p[1] for s in gp for p in (s["p1"], s["p2"])]
            diag = math.hypot(max(gx) - min(gx), max(gy) - min(gy))
            avg = sum(math.hypot(s["p2"][0] - s["p1"][0], s["p2"][1] - s["p1"][1])
                      for s in gp) / len(gp)
            # ⚠️ 阈值试过 0.05 → **0.10**：0.10 确实修好了一个真 bug
            #   （**被离散成 32 段的圆** avg/diag = 0.069，被 0.05 误当文字滤掉 ——
            #    sj-006 的 Ø96 内腔圆正因此丢失），
            #   **但它连带改变了 `_occ`（轮廓实占率）⇒ `profile_pick` 的判据被搅乱**，
            #   净效果是三件变差（sj-004 −41→−47、sj-006 −95→+281、sj-008 −8→−18）。
            #   ⇒ **回退到 0.05**（保持已验证的稳定基线），
            #   把"圆与文字的区分"留到专门的下一轮，与 pick 判据一起改。
            if diag > 1e-9 and avg / diag > 0.05:      # 笔画相对自身偏长 ⇒ 文字/符号
                continue
        groups.append(gp)
    if not groups:
        groups = components(segs)

    # ★ 比较必须用 **|面积|**：`poly_area` 是**有向面积**（逆时针正、顺时针负）。
    #   踩过的坑：sj-006 上层限位口的最外轮廓（Ø96pt 的圆）方向是**顺时针**，
    #   用带符号面积比较时它是负值 ⇒ 被跳过 ⇒ 选中了一个 122pt² 的小面
    #   ⇒ 建出的体只有真值的 4.6%（−95.4%）。
    # ★ 优先找**贴着视图边界、但走环退化**的组 —— 那就是"真外轮廓没走到环"。
    #   判据必须收窄到"该组的 bbox ≈ 视图 bbox"（≥0.9），
    #   否则内部的大圆也会被拿去降级（第 10 轮用"最大面填充率<0.9"太宽 ⇒ 大面积回归）。
    #   实测 sj-006 上层限位口：真外轮廓组（107×112pt、67 段、bbox = 视图 bbox）
    #   走环得 100 点但**面积 0**（有 3 个度为 1 的端点 + 1 个分支点），
    #   于是"最大面"落到了内部的 Ø96 内腔圆上 ⇒ 建出的体只有真值的 4.6%（−95.4%）。
    bw = max(bbox[2] - bbox[0], 1e-9)
    bh = max(bbox[3] - bbox[1], 1e-9)
    for gp in groups:
        gx = [p[0] for s in gp for p in (s["p1"], s["p2"])]
        gy = [p[1] for s in gp for p in (s["p1"], s["p2"])]
        if ((max(gx) - min(gx)) * (max(gy) - min(gy))) / (bw * bh) < 0.9:
            continue                           # 不贴边 ⇒ 不是外轮廓组
        pl = P.outer_loop(gp)
        if pl is not None and abs(P.poly_area(pl)) > 1e-6:
            continue                           # 走环成功 ⇒ 不用降级
        hull = P.convex_hull([p for s in gp for p in (s["p1"], s["p2"])])
        if len(hull) >= 3 and P.poly_area(hull) > 1e-6:
            return hull, "hull"

    for gp in groups:
        pl = P.outer_loop(gp)
        if not pl:
            continue
        a = abs(P.poly_area(pl))
        if best is None or a > best[0]:
            best = (a, pl)
    poly = best[1] if best else None
    if poly is not None and P.poly_area(poly) < 0:
        poly = poly[::-1]                 # 统一成逆时针，供下游建面
    # ⚠️ 试过"最大面填充率 <0.9 ⇒ 改用凸包"（想救 sj-006 的内腔圆问题），
    #   **实测大面积回归，已回退**：凸包会把**凹处填满** ——
    #   sj-001 +106→+193、sj-004 −41→+300、sj-005 +60→+234、sj-008 −8→+228。
    #   凸包只保留在"走环彻底失败/退化"的降级路径里（那时才确实没有更好的选择）。
    if not poly:                     # 回退：整体走环 → 旧墙面跟随
        poly = P.outer_loop(segs) or P.trace_outer_loop(segs)
    if poly:
        poly = P.simplify(poly, max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * frac)
    if not poly or P.poly_area(poly) < 1e-6:
        if not degrade:
            return None, "走环失败"
        # ★ 降级顺序：**凸包** 优先于 **外接矩形**。
        #   实测 sj-006 上层限位口的真外轮廓组（107×112pt）走环得到 100 点但**面积 0**
        #   —— 它有 **3 个度为 1 的端点**（`_CLOSE_OPEN` 只处理"恰好 2 个"的情形），
        #   走环在端点间来回折返、有向面积抵消。
        #   降到外接矩形会明显偏大；**凸包**贴合（Ø20 圆盘 + 凸缘 ≈ 真轮廓）。
        #   凹形零件凸包会填掉凹处 ⇒ 只作降级，并返回 `degraded='hull'` 如实标记。
        pts_all = [p for s in segs for p in (s["p1"], s["p2"])]
        hull = P.convex_hull(pts_all)
        if len(hull) >= 3 and P.poly_area(hull) > 1e-6:
            return hull, "hull"
        return ([(bbox[0], bbox[1]), (bbox[2], bbox[1]),
                 (bbox[2], bbox[3]), (bbox[0], bbox[3])], "bbox")
    return poly, None


def _step_segments(prof, step_tol):
    """把逐 bin 的 `(t, lo, hi)` 压成**台阶段**，抗"剖面线间隔"造成的锯齿。

    ★ 为什么必须做这一步：剖面线彼此有间距（通常 2-3mm），逐 bin 扫描出的
    `lo`/`hi` 会来回跳（实测 sj-009 外缘在 76.4 / 77.4 / 78.4 / 79.4 之间跳），
    直接回转/拉伸会让体积偏小（实测 −17.5%）。

    判据：`hi` 相对上一个 bin 跳变 > `step_tol` ⇒ 是台阶，切段；段内取 `lo=min`、`hi=max`。
    段边界取相邻段中点，避免重叠或留缝。
    """
    segs_out = []
    cur = None
    for (t, lo, hi) in prof:
        if cur is None or abs(hi - cur["hi_last"]) > step_tol:
            if cur:
                segs_out.append(cur)
            cur = {"t0": t, "t1": t, "hi_last": hi, "lo": lo, "hi": hi}
        else:
            cur["t1"] = t
            if hi > cur["hi"]:
                cur["hi"] = hi
            if lo < cur["lo"]:
                cur["lo"] = lo
            cur["hi_last"] = hi
    if cur:
        segs_out.append(cur)
    for k in range(len(segs_out) - 1):
        mid = (segs_out[k]["t1"] + segs_out[k + 1]["t0"]) / 2.0
        segs_out[k]["t1"] = mid
        segs_out[k + 1]["t0"] = mid
    return segs_out


def profile_from_hatch(g, view, axis_pos, kind, bin_pt=1.0, step_tol=6.0):
    """**剖面线层** → 材料截面轮廓 `[(轴向, 径向), ...]`（闭合）。认不出返回 None。

    ## 为什么用剖面线，而不是走环

    剖面线（`剖面线层`）是设计师亲手画的"**这里剖到了材料**"标记 ——
    **孔、空腔、外面都没有剖面线**。所以它比走环更本质：它直接给出"材料在哪"。

    实测 sj-009 底部垫片（轴 x=280，孔应在 x[236.6, 323.3]）：

        y=404  剖面线 x ∈ 201~235 | 326~360     ← 中间 235~326 空的 = 孔
        y=427  剖面线 x ∈ 230~237 | 323~330     ← 只剩凸台壁那一薄圈

    孔的位置**一点剖面线都没有** ⇒ 扫描出来天然带孔。

    ## 做法（**必须求交点，不能取端点**）

    ★ 这一步踩过一次坑：剖面线是 **45° 斜线**，若只收集"落在该轴向 bin 内的**端点**"，
    则某个 y 处往往只有稀疏几个点（一条斜线在该 y 只贡献一个点），
    `r_in` 会被当成 `r_out` ⇒ 轮廓退化、体积算成 −95%（sj-009 实测）。

    正确做法是**扫描线求交**：对每个轴向位置 t，求所有剖面线**段**与 `t=const` 直线的
    **交点**，这样该处材料被覆盖的径向范围才会完整出现。

    取**轴的一侧**（kind='v' 取 x≥轴，kind='h' 取 y≥轴）：轴剖视图关于轴对称，
    只算一侧即可，且 `径向 = |坐标 − 轴|` 无需取绝对值。

    轮廓 = **外缘正序 + 内缘逆序**（闭合成环），回转/拉伸都能直接用。

    ## 相对走环的优势

    1. **孔自动被排除** —— 走环只走"最外那个环"，孔被跳过
       （sj-009 走环解差的 115.9mm³ 正好 = Ø6.5 通孔 π×3.25²×3.5=116.1，误差 0.2%）；
    2. **不需要闭合** —— 走环在 82 点/4 点的复杂轮廓上退化为面积 0
       （sj-003/006/008 实测退化到 bbox，体积 +1739%/+349%/+411%）；
    3. **容错** —— 剖面线是密集平行线，个别线段丢失不影响整体。

    ## 已知偏差

    剖面线有间距（通常 2-3mm），扫描出的 `r_in`/`r_out` 有零点几毫米偏差。
    调用方应把结果**吸附到标注**（`snap_to`）后再建体。
    """
    hatch = segs_in_view(g, view, "剖面线层")
    if not hatch:
        return None, "无剖面线"

    segs = [(s["p1"], s["p2"]) for s in hatch]
    if kind == "v":
        t_all = [p[1] for sg in segs for p in sg]
    else:
        t_all = [p[0] for sg in segs for p in sg]
    t0, t1 = min(t_all), max(t_all)
    if t1 - t0 < 1e-6:
        return None, "剖面线轴向跨度为 0"
    nb = max(4, int((t1 - t0) / bin_pt))

    prof = []
    for i in range(nb):
        t = t0 + (i + 0.5) * (t1 - t0) / nb
        rs = []
        for (a, b) in segs:
            if kind == "v":                      # 轴竖直：扫水平线 y=t，径向=x−轴
                lo, hi = (a[1], b[1]) if a[1] <= b[1] else (b[1], a[1])
                if not (lo - 1e-9 <= t <= hi + 1e-9):
                    continue
                x = a[0] if abs(b[1] - a[1]) < 1e-9 else a[0] + (t - a[1]) / (b[1] - a[1]) * (b[0] - a[0])
                if x >= axis_pos - 1e-9:
                    rs.append(x - axis_pos)
            else:                                # 轴水平：扫竖直线 x=t，径向=y−轴
                lo, hi = (a[0], b[0]) if a[0] <= b[0] else (b[0], a[0])
                if not (lo - 1e-9 <= t <= hi + 1e-9):
                    continue
                y = a[1] if abs(b[0] - a[0]) < 1e-9 else a[1] + (t - a[0]) / (b[0] - a[0]) * (b[1] - a[1])
                if y >= axis_pos - 1e-9:
                    rs.append(y - axis_pos)
        if len(rs) < 2:
            continue
        prof.append((t - t0, min(rs), max(rs)))

    if len(prof) < 2:
        return None, "有效扫描 bin 不足 2 个"

    # 分段取极值压掉锯齿（剖面线有间距 ⇒ 逐 bin 的 r_in/r_out 会来回跳，见 _step_segments）
    segs_out = _step_segments(prof, step_tol)
    if not segs_out:
        return None, "分段失败"

    pts = []
    for sg in segs_out:                       # 外缘，轴向正序
        pts.append((sg["t0"], sg["hi"]))
        pts.append((sg["t1"], sg["hi"]))
    for sg in reversed(segs_out):             # 内缘，逆序 → 闭合成环
        pts.append((sg["t1"], sg["lo"]))
        pts.append((sg["t0"], sg["lo"]))

    # 去掉连续重复点（段边界会重复）
    ded = []
    for p in pts:
        if not ded or abs(p[0] - ded[-1][0]) > 1e-9 or abs(p[1] - ded[-1][1]) > 1e-9:
            ded.append(p)
    return ded, None


def section_outer_of_hatch(g, view, bin_pt=1.0, step_tol=6.0):
    """剖面线 → 截面**外轮廓**（正交多边形，闭合，页面坐标）。认不出返回 None。

    与 `profile_from_hatch` **同一套扫描 + 分段逻辑**，区别只在结果的维度：

    | 用途 | 结果 |
    |---|---|
    | 回转（`profile_from_hatch`） | `(轴向, 径向)` 一维轮廓 —— 因为回转体轴对称 |
    | 拉伸（本算子） | `(x, y)` 二维外轮廓 —— 截面是任意形状 |

    ## 什么时候该用它

    只在**当前剖面视图自己带剖面线**时用（判据见 `route_extrude`）：
    剖面线是设计师画的"这里剖到材料"标记，扫描出来天然避开空腔。

    ## 已知限制（如实）

    1. **只取外轮廓，孔暂不处理** —— 剖面线的"空洞"（实测 sj-008 视图0 有
       `467~479 | 488~496`）说明截面中心有挖空，转成内环需要额外一步，本轮未做；
    2. 结果边界是**阶梯状正交多边形**（每段 2 个点），点数比走环多；
    3. 剖面线间距会让外缘略微内缩，调用方宜**吸附到标注**。
    """
    hatch = segs_in_view(g, view, "剖面线层")
    if not hatch:
        return None, "无剖面线"
    segs = [(s["p1"], s["p2"]) for s in hatch]
    ys = [p[1] for sg in segs for p in sg]
    y0, y1 = min(ys), max(ys)
    if y1 - y0 < 1e-6:
        return None, "剖面线纵向跨度为 0"
    nb = max(4, int((y1 - y0) / bin_pt))
    prof = []
    for i in range(nb):
        y = y0 + (i + 0.5) * (y1 - y0) / nb
        xs = []
        for (a, b) in segs:
            lo, hi = (a[1], b[1]) if a[1] <= b[1] else (b[1], a[1])
            if not (lo - 1e-9 <= y <= hi + 1e-9):
                continue
            x = a[0] if abs(b[1] - a[1]) < 1e-9 else a[0] + (y - a[1]) / (b[1] - a[1]) * (b[0] - a[0])
            xs.append(x)
        if len(xs) < 2:
            continue
        prof.append((y, min(xs), max(xs)))
    if len(prof) < 2:
        return None, "有效扫描 bin 不足 2 个"

    segs_out = _step_segments(prof, step_tol)
    if not segs_out:
        return None, "分段失败"

    poly = []
    for sg in segs_out:                        # 左边界，自下而上
        poly.append((sg["lo"], sg["t0"]))
        poly.append((sg["lo"], sg["t1"]))
    for sg in reversed(segs_out):              # 右边界，自上而下 → 闭合成环
        poly.append((sg["hi"], sg["t1"]))
        poly.append((sg["hi"], sg["t0"]))
    ded = []
    for p in poly:
        if not ded or abs(p[0] - ded[-1][0]) > 1e-9 or abs(p[1] - ded[-1][1]) > 1e-9:
            ded.append(p)
    return ded, None


def components(segs, tol=1.5):
    """按**端点连通**把线段分组。返回 `[[seg,...], ...]`。

    一个被离散成 32 段弧线的圆 = 同一组；方形的 4 条边 = 另一组。
    这是 `circles_in_view` 的前置步骤（不同心的多个圆必须分开检测）。
    """
    n = len(segs)
    if n == 0:
        return []
    par = list(range(n))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb

    cell = max(tol, 1e-6)
    grid = {}

    def key(p):
        return (int(p[0] // cell), int(p[1] // cell))

    for i, s in enumerate(segs):
        for p in (s["p1"], s["p2"]):
            k = key(p)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in grid.get((k[0] + dx, k[1] + dy), ()):
                        for q in (segs[j]["p1"], segs[j]["p2"]):
                            if abs(q[0] - p[0]) <= tol and abs(q[1] - p[1]) <= tol:
                                uni(i, j)
        for p in (s["p1"], s["p2"]):
            grid.setdefault(key(p), []).append(i)

    buckets = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)
    return [[segs[i] for i in idx] for idx in buckets.values()]


def circles_in_view(g, view, layer="粗实线层", tol=1.5):
    """视图内**多个独立圆** → `[(cx, cy, r), ...]`（页面坐标，半径降序）。

    ## 与 `circle_of` 的分工（**不是重复**）

    | 算子 | 前提 | 用在 |
    |---|---|---|
    | `circle_of` | 假设**所有圆同心**（按到质心的距离聚类） | 轴剖视图（回转体的台阶圆） |
    | `circles_in_view` | 先按**端点连通**分组，再逐组检测 | 俯视图（**孔阵列，不同心**） |

    ★ 为什么必须分开：`circle_of` 拿整张俯视图去算"到质心的距离"，
    4 个分布孔会被聚成 1 个假簇或被角度覆盖校验否掉。
    实测 sj-002 俯视图分组后读出 **4×Ø3.5 + 4×Ø2.6 + Ø6.5**，与真值孔完全对上；
    而同一视图直接喂 `circle_of` 只能得到形心处的假圆。

    方形/多边形组会被 `circle_of` 的角度覆盖判据自动否掉（返回 None），不产生假圆。
    """
    out = []
    for gp in components(segs_in_view(g, view, layer), tol=tol):
        c, rs = circle_of(gp)
        if c and rs:
            out.append((c[0], c[1], max(rs)))
    out.sort(key=lambda t: -t[2])
    return out


def arrow_count_of(g, view, thr=8.0):
    """该视图内的**箭头个数** ≈ 标注条数（尺寸线层的"极短线段"就是箭头）。

    ## 依据（机械制图）

    主视图应当"最能反映零件形状特征"（`projection-rules.md §7`）——
    而尺寸按 `dimension-placement.md`「**特征集中**」原则，**都往表达最清楚的那个视图上标**。
    所以"该视图里的标注条数"是"形状特征充分度"的**可执行代理指标**（用户 2026-10-16 补充：
    「面积最大不一定是主视图，**主视图一般是标注尺寸最多的那个视图**」）。

    ## 为什么不数"尺寸数字"（踩坑记录）

    试过用带坐标的文字来数 —— **不可行**：这批 PDF 内容流有全局 `/cm` 缩放，
    pypdf 的 `visitor_text` 累积的 cm 与 `pdf_geom` 的 CTM **不同源**，
    文字坐标与线段坐标差约 16.7 倍（=1/0.06）；自动标定又因"线段范围含图框、文字范围由标题栏主导"而偏移，
    实测每视图只能数到 0~2 个。⇒ 改用**同空间**的尺寸线层短段（箭头）。

    ## 边界（如实）

    实测 5 件可判的里 **3 件与三等关系判据一致、1 件并列、1 件不一致**
    （那件把孔的定位尺寸标在俯视图上 —— 常见做法）。
    ⇒ **不能拿它单独定主视图**，只作**交叉验证**：两者冲突时标记出来，让人复核。
    """
    import math as _m
    ss = segs_in_view(g, view, "尺寸线层")
    return sum(1 for s in ss
               if _m.hypot(s["p2"][0] - s["p1"][0], s["p2"][1] - s["p1"][1]) <= thr)

def circle_inside(cx, cy, r, poly, n=8):
    """整圆是否**完全落在轮廓内**（按 n 等分采样圆周，逐点用射线法判）。

    ## 为什么要它（制图原则）

    `dimension-mapping.md` §56：「**圆孔** φ 标在反映圆实形的视图；
    非圆视图表现为两条虚线（或剖视中的两条实线），间距 = φ」——
    孔是**内部特征**，一定被外形**完整包围**，它的整条圆周都不可能越出外轮廓。

    只判"圆心在轮廓内"是不够的：**贴着外形的圆**圆心在里、圆周在外，
    会被误当孔。实测 sj-008 底座：主视图里的 Ø48pt 圆（对应真值 48mm 那道线性尺寸
    所在的外形）被当成 Ø48 孔减掉 ⇒ 截面被挖空 ⇒ 建出的体 volume=0 ⇒
    整条 extrude 路线被判失败、退回 revolve（−17.8%）。
    """
    import math as _m
    for i in range(n):
        a = 2 * _m.pi * i / n
        if not point_in_polygon((cx + r * _m.cos(a), cy + r * _m.sin(a)), poly):
            return False
    return True

def pick_holes(circles, outline_circle=False, rel_tol=0.15):
    """从检测到的圆里挑出**孔**。同心组的处理分两种情形。

    ## 两类"同心圆组"，几何上必须分开对待

    | 情形 | 材料在哪 | 例（实测） | 该怎么减 |
    |---|---|---|---|
    | **凸台 / 中心结构** | 在**圆内** | sj-007：外轮廓是 70×45 **矩形**，组内 Ø30/Ø28/Ø20.53/Ø17.62/Ø6.5 | **只减最内层**（Ø28 经 census 确认是 `boss`） |
    | **阶梯孔 / 内腔** | 在**圆外** | sj-003：外轮廓是 **Ø42.8 圆**，组内 Ø24(腔)/Ø3.53/Ø3.09 | **整组都减** |

    ## 判据：`outline_circle`

    **外轮廓本身就是圆** ⇒ 与它同心的圆组是"阶梯孔/腔"（材料在圆外）⇒ 整组都减；
    否则（外轮廓是矩形/异形）⇒ 组内是凸台 ⇒ 只减最内层。

    踩过的坑：早期一律"只取最内层"，导致 sj-003 的 **Ø24 内腔被丢掉**
    （组内最内是 Ø3.09），于是模型成了实心柱 —— 体积 **+735%**
    （真值 3984.1 是薄壁罩，我建出 33281.7）。
    """
    groups = []
    for (cx, cy, r) in circles:
        placed = False
        for gp in groups:
            ax, ay, ar = gp[0]
            tol = rel_tol * max(r, ar)
            if abs(cx - ax) <= tol and abs(cy - ay) <= tol:
                gp.append((cx, cy, r))
                placed = True
                break
        if not placed:
            groups.append([(cx, cy, r)])
    out = []
    for gp in groups:
        gp.sort(key=lambda t: t[2])
        if outline_circle and len(gp) > 1:
            out.extend(gp)              # 阶梯孔/腔：整组都算孔
        else:
            out.append(gp[0])           # 凸台：只取最内层
    return out


def point_in_polygon(pt, poly):
    """射线法：判断点是否在多边形内（poly 为闭合点列，无需首尾重复）。"""
    x, y = pt[0], pt[1]
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i][0], poly[i][1]
        x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if xi > x:
                inside = not inside
    return inside


def stepped_profile(g, view, axis_pos, kind, nb=120, layer="粗实线层", tol_r=0.8):
    """轴剖视图 → **阶梯半剖轮廓** `[(轴向, 径向), ...]`（外缘正序 + 内缘逆序，闭合）。
    认不出返回 `(None, 原因)`。

    ## 制图依据（这是本轮的转折点）

    剖视图上的粗实线只有两类：
      · **平行于轴的线**（素线）⇒ 给出**该段的半径**；
      · **垂直于轴的线**（台阶线）⇒ 给出**台阶的轴向位置**。
    所以"某个轴向位置处的径向范围" = **跨越该位置的所有素线的 r 的 [min, max]**。
    按轴向分 bin 扫一遍，就得到完整的阶梯轮廓。

    ## 为什么比 `profile_from_hatch` 更适合薄壁多台阶件（sj-003 实测）

    sj-003 顶部保护罩是**阶梯薄壁套（9 级半径）**，图上只画了**局部剖**
    （剖面线仅覆盖轴向两端 15/75 个 bin）。

    ⇒ 剖面线扫描只采到两端，中间 30mm 采空 ⇒ 轮廓退化 ⇒ 建出实心柱（+613%）。
    而**素线是贯穿全长的**（实测 r=11.16 那条长 29.76mm），
    按轴向分 bin 能逐段还原：实测输出

        轴向 0.17 → 半径 21.40 (Ø42.80)      顶法兰
        轴向 2.21 → 半径 13.26 (Ø26.52)      台阶
        轴向 5.60 → 半径 11.25 (Ø22.50)      长筒（到 35.8）
        轴向 40.76→ 半径 13.26 (Ø26.52)      底
        内缘       → Ø24.45 / Ø13.0 / Ø3.05  腔 + 中央孔

    与真值 census（Ø42 len=2 / Ø26 腔 / Ø24 腔 / Ø3 孔）**逐条对上**。

    ## 参数与压缩

    相邻 bin 的 r 会因离散化抖动 ⇒ `tol_r`（pt）内视为同值、压掉中间点，
    否则会带入几十个锯齿点。
    """
    segs = segs_in_view(g, view, layer)
    if not segs:
        return None, "无粗实线"

    par = []                                   # (半径, 轴向起, 轴向止)
    for s in segs:
        (x1, y1), (x2, y2) = s["p1"], s["p2"]
        if kind == "v" and abs(x1 - x2) < 0.5:                 # 竖线 = 平行于轴
            par.append((abs(x1 - axis_pos), min(y1, y2), max(y1, y2)))
        elif kind == "h" and abs(y1 - y2) < 0.5:
            par.append((abs(y1 - axis_pos), min(x1, x2), max(x1, x2)))
    if not par:
        return None, "没有平行于轴的素线"

    ts = [v for _, lo, hi in par for v in (lo, hi)]
    t0, t1 = min(ts), max(ts)
    if t1 - t0 < 1e-6:
        return None, "轴向跨度为 0"

    prof = []
    for i in range(nb):
        tc = t0 + (i + 0.5) * (t1 - t0) / nb
        rs = [r for r, lo, hi in par if lo - 1e-6 <= tc <= hi + 1e-6]
        if rs:
            prof.append((tc - t0, min(rs), max(rs)))
    if len(prof) < 2:
        return None, "有效轴向 bin 不足 2 个"

    def compress(seq):
        out = [seq[0]]
        for p in seq[1:]:
            if abs(p[1] - out[-1][1]) > tol_r:
                out.append(p)
        if seq[-1] != out[-1]:
            out.append(seq[-1])
        return out

    outer = compress([(t, ro) for t, _ri, ro in prof] + [(t1 - t0, prof[-1][2])])
    inner = compress([(t, ri) for t, ri, _ro in reversed(prof)] + [(0.0, prof[0][1])])
    return outer + inner, None


def pick_profile(g, view, axis_pos, kind, multi_view=False):
    """取回转用的**半剖轮廓**。返回 `(pts, 来源)`，都失败返回 `(None, None)`。

    ## 两条路的取舍（制图规范驱动）

    | 路 | 依据 | 强项 |
    |---|---|---|
    | `hatch`（剖面线） | 设计师点的"这里剖到材料"，孔/腔处天然没有 | **实心/简单件**（单视图轴剖垫片） |
    | `stepped`（素线） | 平行于轴的粗实线给半径、台阶线给轴向位置 | **多台阶薄壁件** |

    ## 判据：**多视图件的"局部剖"用素线，其余用剖面线**

    · **多视图 + 局部剖**（`hatch_fill_ratio < 0.5`）⇒ 剖面线只画了局部，
      拿去扫描会**漏掉中间段**（实测 sj-003 中间 30mm 采空 ⇒ 实心柱 +613%）
      ⇒ **改用素线**（素线贯穿全长，能逐段还原）；
    · **单视图**（如 sj-009/011）⇒ 设计师只画一张图，必然是完整剖
      ⇒ **剖面线扫描**最准（−1.9% / −9.1%；换素线法反而 −39% / −99.8%）。
    """
    fill = hatch_fill_ratio(g, view)
    use_stepped_first = multi_view and fill < 0.5
    order = ["stepped", "hatch"] if use_stepped_first else ["hatch", "stepped"]
    for name in order:
        if name == "stepped":
            pts, _e = stepped_profile(g, view, axis_pos, kind)
        else:
            pts, _e = profile_from_hatch(g, view, axis_pos, kind)
        if pts is not None:
            return pts, name
    return None, None


def half_profile_of(poly, axis_pos, kind, tol=1e-6):
    """外轮廓 + 轴线位置 → **半剖轮廓**（局部坐标 `(轴向, 径向)`）。认不出返回 None。

    ## 为什么必须"补轴上的端点"

    这是本轮挖到的最隐蔽的一个根因，实测损失 **-94.3%**：

      · 外轮廓走的是**【粗实线层】**，而**轴线属于【中心线层】** —— 两者不同层；
      · 所以外轮廓**根本不经过轴线**，它只描述"零件实体"的边界；
      · 直接取半侧（x≥轴 的点）再用 `Polyline(close=True)` 闭合，
        会把**首尾两点斜着直连** —— 得到一条穿过零件内部的斜边。

    实测 sj-009 底部垫片：半侧只剩 4 点 `(纵0,径80)(20,80)(20,50)(47,50)`，
    闭合后是四边形，面积只有真值的 ~1/5 ⇒ 回转体积差 **-94.3%**。
    补上轴上的两个端点 `(0,轴)` `(47,轴)` 变成六边形后，
    体积 = π(底盘) + π(凸台) − π(通孔) = 169.6+88.4−116.1 = 141.9，与真值一致。

    ## 参数

    kind='v' 竖中心线（轴竖直）⇒ 取 x≥轴的**右半**，轴向=y、径向=x−轴
    kind='h' 横中心线（轴水平）⇒ 取 y≥轴的**上半**，轴向=x、径向=y−轴

    返回的 `(轴向, 径向)` 已经是**回转用的局部坐标**（轴向→X、径向→Y）。
    半侧点保持**原环序**（不排序）：环与轴线相交两次，同侧的点在环序上是连续的，
    排序反而会打乱环序、造成自交。
    """
    if kind == "v":
        half = [p for p in poly if p[0] >= axis_pos - tol]
        if len(half) < 2:
            return None
        head = (axis_pos, half[0][1])
        tail = (axis_pos, half[-1][1])
        loop = [head] + half + [tail]
        y0 = min(p[1] for p in loop)
        return [(abs(p[1] - y0), abs(p[0] - axis_pos)) for p in loop]
    else:
        half = [p for p in poly if p[1] >= axis_pos - tol]
        if len(half) < 2:
            return None
        head = (half[0][0], axis_pos)
        tail = (half[-1][0], axis_pos)
        loop = [head] + half + [tail]
        x0 = min(p[0] for p in loop)
        return [(abs(p[0] - x0), abs(p[1] - axis_pos)) for p in loop]


def _covered(ranges):
    """把若干区间合并后返回总覆盖长度（用于"共线段的累计覆盖"）。"""
    if not ranges:
        return 0.0
    rs = sorted(ranges)
    tot, cur = 0.0, [rs[0][0], rs[0][1]]
    for a, b in rs[1:]:
        if a <= cur[1] + 1e-6:
            cur[1] = max(cur[1], b)
        else:
            tot += cur[1] - cur[0]
            cur = [a, b]
    tot += cur[1] - cur[0]
    return tot


def axis_view_of(g, views, min_frac=0.6):
    """视图集合 → 带回转轴的视图。返回 `(view, 轴位置, kind)` 或 None。

    ## 判据（制图规范）

    中心线（**细点画线**）穿过回转体的轴线。所以"视图内有一条**贯穿**该视图的
    中心线层直线"⇒ 该视图是轴向剖视 ⇒ 那条线就是回转轴。
    `kind='v'` = 竖中心线（⇒ 轴水平），`'h'` = 横中心线。

    ## ★ 必须按"共线段的累计覆盖"判，不能看单段长度

    制图规范里中心线是**点画线**，PDF 里它被**离散成很多短段**
    （实测 sj-003 轴线 x=280 上有 5 段：4/23/4/12/8 pt）。
    早期实现要求**单段**长度 > 0.6×视图边长 ⇒ **真轴线被判成"短"而错过**
    ⇒ sj-003/006 被 extrude 抢先接管，建出实心柱（+379%/+162%）。

    ⇒ 改为：同 x（或同 y）的中心线段**先合并成区间**再算总覆盖长度。
    实测 sj-003 合并后覆盖 62/75 = **83%** ✓ 能正确识别。

    ## 多个候选

    取**覆盖比例最高**者（原实现取"面积最大的视图"—— 面积大不代表那是主轴线，
    俯视图上一堆孔的中心线也很密）。比例相同再比覆盖的绝对长度。
    """
    best = None
    for v in views:
        b = v["bbox"]
        vert, horiz = {}, {}
        for s in segs_in_view(g, v, "中心线层"):
            (x1, y1), (x2, y2) = s["p1"], s["p2"]
            if abs(x1 - x2) < 1e-6:
                vert.setdefault(round(x1, 1), []).append((min(y1, y2), max(y1, y2)))
            elif abs(y1 - y2) < 1e-6:
                horiz.setdefault(round(y1, 1), []).append((min(x1, x2), max(x1, x2)))
        h, w = b[3] - b[1], b[2] - b[0]
        for x, rs in vert.items():
            L = _covered(rs)
            if h > 1e-6 and L > min_frac * h:
                key = (L / h, L)
                if best is None or key > best[3]:
                    best = (v, x, "v", key)
        for y, rs in horiz.items():
            L = _covered(rs)
            if w > 1e-6 and L > min_frac * w:
                key = (L / w, L)
                if best is None or key > best[3]:
                    best = (v, y, "h", key)
    return None if best is None else (best[0], best[1], best[2])


def concentric_groups(circles, rel_tol=0.10):
    """圆列表 → **同心圆组**（只返回组内 ≥2 个圆的）。

    制图意义：一个中心处叠着多个圆 ⇒ 该处有**台阶 / 多级孔 / 凸台**。
    端视图上出现同心圆组，往往就是回转体的特征。
    """
    groups = []
    for (cx, cy, r) in circles:
        for gp in groups:
            ax, ay, ar = gp[0]
            tol = rel_tol * max(r, ar)
            if abs(cx - ax) <= tol and abs(cy - ay) <= tol:
                gp.append((cx, cy, r))
                break
        else:
            groups.append([(cx, cy, r)])
    return [gp for gp in groups if len(gp) >= 2]


def hatch_coverage(g, view, layer="剖面线层"):
    """某视图里**剖面线铺开的程度**（剖面线端点 bbox 面积 / 视图 bbox 面积）。

    制图意义：**全剖视图**上剖面线铺满剖面区域；**局部剖**只覆盖一小块
    （实测 sj-001 只有 3%）；非剖视图为 0。
    """
    hs = segs_in_view(g, view, layer)
    if not hs:
        return 0.0
    xs = [q[0] for s in hs for q in (s["p1"], s["p2"])]
    ys = [q[1] for s in hs for q in (s["p1"], s["p2"])]
    return ((max(xs) - min(xs)) * (max(ys) - min(ys))) / max(view["w"] * view["h"], 1e-9)


def full_section_view_of(g, views, cov=0.5, center_tol=0.08):
    """视图集合 → **全剖视图 + 它的回转轴**。返回 `(view, 轴位置, kind)` 或 None。

    ## 为什么不用 `axis_view_of`

    两个原因（都是实测换来的）：

    1. **实心体件的俯视图上每个孔都画一小段中心线**，按坐标聚起来也能凑出很长的"贯穿"
       （实测 sj-003 俯视图 v0 有 161 段中心线）⇒ `axis_view_of` 误把**俯视图**
       当轴向剖视 ⇒ 回转而剖面线扫描失败、退回走环 ⇒ 得到**实心柱**（sj-003 +864%）。
    2. **中心线是点画线**，PDF 里被离散成**带间隙**的段
       （实测 sj-003 轴线 x=279.96 上 4 段，段间固定间隔 3.78pt）。
       靠"累计覆盖长度"判会因间隙而不达标（42.4/75.4 = 56% < 60%）。

    ## 判据（制图规范）：**回转轴的投影就是视图的对称中心线**

    所以不必纠结长度，直接找"**位置落在视图对称中心附近**"的中心线段：
    `|x − 视图x中心| ≤ center_tol × 视图宽`（竖线）或同式对 y（横线）。
    这条判据天然排除俯视图 —— 俯视图的孔中心线**不在视图对称中心**上。

    再叠加"该视图是全剖视图"（剖面线 ≥ `cov`，`hatch_coverage`），
    两个制图特征同时满足才认定。多候选取剖面线覆盖率最高的视图。
    """
    cands = [v for v in views if hatch_coverage(g, v) >= cov]
    cands.sort(key=lambda v: -hatch_coverage(g, v))
    for v in cands:
        b = v["bbox"]
        cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
        cw, ch = b[2] - b[0], b[3] - b[1]
        best = None
        for s in segs_in_view(g, v, "中心线层"):
            (x1, y1), (x2, y2) = s["p1"], s["p2"]
            if abs(x1 - x2) < 1e-6 and abs(x1 - cx) <= center_tol * cw:
                L = abs(y2 - y1)
                if best is None or L > best[3]:
                    best = (v, x1, "v", L)
            elif abs(y1 - y2) < 1e-6 and abs(y1 - cy) <= center_tol * ch:
                L = abs(x2 - x1)
                if best is None or L > best[3]:
                    best = (v, y1, "h", L)
        if best is not None:
            return (best[0], best[1], best[2])
    return None


def hatch_fill_ratio(g, view, nb=40, layer="剖面线层"):
    """剖面线在视图内的**填充连续性**（非空 bin 比例，x/y 两方向取小）。

    ## 区分【全剖视图】与【局部剖视图】（制图规范）

    · **全剖**：剖面线沿剖切方向**连续铺开** ⇒ 比例高；
    · **局部剖**：只在局部剖开（用波浪线分界）⇒ 比例低。
      实测 sj-003 顶部保护罩的剖视图只在**轴向两端**有剖面线（15/75 bin = 22%），
      因为它是"两端局部剖"。

    ★ 为什么不能只看 `hatch_coverage`（剖面线端点 bbox 面积 / 视图面积）：
      两端各一撮剖面线，其 bbox 照样覆盖整张视图 ⇒ sj-003 被判成 100% 全剖，
      进而用剖面线扫描 ⇒ 中间 30mm 采空 ⇒ 建出实心柱（实测 +613%）。
    """
    hs = segs_in_view(g, view, layer)
    if not hs:
        return 0.0
    ps = [p for s in hs for p in (s["p1"], s["p2"])]

    def fill(vals):
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-9:
            return 1.0
        return len({min(nb - 1, int((v - lo) / (hi - lo) * nb)) for v in vals}) / nb

    return min(fill([p[0] for p in ps]), fill([p[1] for p in ps]))


def centered_axis_of(g, view, tol=0.08, layer="中心线层"):
    """视图内**落在对称中心附近的中心线** —— 制图规范里，回转轴的投影就是它。

    返回 `(位置, 'v'|'h')` 或 None。取最长的一段（点画线会被离散成多段）。

    为什么加"居中"这一条：实心件的俯视图上**每个孔都画一小段中心线**，
    只看"有没有中心线"会把俯视图也认成轴向剖视。而孔的定位中心线**不在视图对称中心**。
    """
    b = view["bbox"]
    cx, cy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
    cw, ch = b[2] - b[0], b[3] - b[1]
    best = None
    for s in segs_in_view(g, view, layer):
        (x1, y1), (x2, y2) = s["p1"], s["p2"]
        if abs(x1 - x2) < 1e-6 and abs(x1 - cx) <= tol * cw:
            L = abs(y2 - y1)
            if best is None or L > best[2]:
                best = (x1, "v", L)
        elif abs(y1 - y2) < 1e-6 and abs(y1 - cy) <= tol * ch:
            L = abs(x2 - x1)
            if best is None or L > best[2]:
                best = (y1, "h", L)
    return None if best is None else (best[0], best[1])


def hatch_axial_span(g, view, kind):
    """剖面线**沿轴向的跨度比**（剖面线轴向范围 / 视图轴向边长）。

    区分两种"局部剖"：
      · **贯穿式局部剖**（如 sj-003）：剖面线在轴向**两端**都有（跨度比 1.0），
        中间不画是因为那里**真的没有材料**（空腔）；
      · **单侧局部剖**（如 sj-001）：剖面线只在轴向一小段（跨度比 **0.08**），
        只是为显示某个局部细节（槽/孔），**不能代表零件的完整轴向轮廓**。

    ⇒ 只有前者能用来推"整个零件的回转轮廓"。
    """
    hs = segs_in_view(g, view, "剖面线层")
    if not hs:
        return 0.0
    b = view["bbox"]
    if kind == "v":                                   # 轴竖直 ⇒ 轴向是 y
        vs = [p[1] for s in hs for p in (s["p1"], s["p2"])]
        return (max(vs) - min(vs)) / max(b[3] - b[1], 1e-9)
    vs = [p[0] for s in hs for p in (s["p1"], s["p2"])]  # 轴水平 ⇒ 轴向是 x
    return (max(vs) - min(vs)) / max(b[2] - b[0], 1e-9)


def axisymmetric_section_of(g, views, fill_lo=0.05, fill_hi=0.5, span_min=0.8,
                            slender_ratio=3.0):
    """**回转体的局部剖视图**。返回 `(view, 轴位置, kind)` 或 None。

    ## 判据（机械制图，两条同时满足）

    1. 该视图是**局部剖视图**（`fill_lo < hatch_fill_ratio < fill_hi`）；
    2. 该视图内有**居中中心线**（`centered_axis_of`，即回转轴的投影）。

    ## 为什么这两条能分开回转体与棱柱件（实测全池验证）

    | 件 | 有局部剖视图 | 该视图有居中轴线 | 结论 |
    |---|---|---|---|
    | sj-003 顶部保护罩 | v1 22% | **有**（x=280.0，正是视图中心） | **回转体** ✓ |
    | sj-001 切槽螺栓 | v2 32% | **有**（x=371.7） | **回转体** ✓ |
    | sj-007 抗剪块 | v1 35% | **无** | 矩形块 ✗ 正确排除 |
    | sj-006 / sj-008 / sj-009 / sj-011 | —— | —— | fill 不在区间内 |

    ★ 关键在**"居中"**：抗剪块的剖视图也有局部剖面线，但它没有轴线；
    而回转体的局部剖视图上**必画点画线轴线**（制图规范）。

    ## 已知边界（调用方需自行加条件）

    **单视图轴剖件**（sj-009 底部垫片、sj-011 定心垫片）也满足上述判据
    （它们只有一张图，那必然是全剖/局部剖，且轴线居中）。
    但它们用**剖面线扫描**效果很好（−1.9% / −9.1%），换到素线法反而差
    （实测 −39% / −99.8%）⇒ **调用方应额外要求"视图数 ≥ 2"**，
    把单视图件让给剖面线扫描。
    """
    # ---- 情形 1：**局部剖视图 + 居中轴线 + 剖面线沿轴向贯穿**（罩/套类回转体）----
    for v in views:
        ax = centered_axis_of(g, v)
        if ax is None:
            continue
        f = hatch_fill_ratio(g, v)
        if not (fill_lo < f < fill_hi):
            continue
        # 剖面线必须**沿轴向贯穿**（两端都有）。否则是"单侧局部剖"，
        # 只表达局部细节（sj-001 切槽螺栓的剖面线只占轴向 8%，跨度比 0.079）。
        if hatch_axial_span(g, v, ax[1]) < span_min:
            continue
        return (v, ax[0], ax[1])

    # ---- 情形 2：**细长视图 + 居中轴线**（轴类零件）----
    #
    # 制图规范：轴类（细长回转体）零件的主视图是**细长的阶梯轴**，
    # 轴线（点画线）贯穿全长，轮廓是"两端封口的阶梯形"。
    #
    # ★ 为什么必须单独加这一条：sj-001 切槽螺栓**是回转体**（Ø6 柱 len52 + Ø11.5 头），
    #   但它的剖面线只在轴向 8%（单侧局部剖，为显示切槽）⇒ 情形 1 被 span 判据排除
    #   ⇒ 落到 `route_extrude`，把"Ø5.8 柱"当成"5.8mm 宽的**矩形**棱柱"建，
    #   截面积差 π/4 ≈ 2.2 倍（实测 +106%）。
    #   用素线法（`stepped_profile`）读它的主视图则完全正确：
    #     竖线 x=364 → Ø5.80（长 85mm 主体）｜竖线 x=387 → Ø11.5（长 5mm 头）
    #   ⇒ 体积 2763 vs 真值 2713（**−1.8%**）。
    #
    # 判据取"长宽比 ≥ 3"：实测全池只有 sj-001 满足（240/31 = 7.7）；
    # sj-002 的 189×15、sj-007 的 186×16 虽然也细长，但它们**没有居中轴线**
    # （实测 "无居中轴"）⇒ 被正确排除。
    for v in views:
        ax = centered_axis_of(g, v)
        if ax is None:
            continue
        w, h = v["w"], v["h"]
        pos, kind = ax
        # (a) 轴线必须**沿视图的长边** —— 轴类零件的主视图里，轴就是零件的**最长方向**。
        if kind == "v":
            if not (w > 1e-9 and h >= slender_ratio * w):
                continue
        else:
            if not (h > 1e-9 and w >= slender_ratio * h):
                continue
        # (b) 轴线必须**真的贯穿**视图（覆盖 ≥ 30% 长边）。
        #     只靠"存在一条居中的中心线"会被**短中心线**骗过：sj-006 的俯视图 v0
        #     在对称中心处有一段 13pt 的横向中心线（孔的中心线），
        #     而视图宽 106.6pt ⇒ 覆盖仅 12% ⇒ 不是轴线。实测若不加这条，
        #     sj-006 被误当轴类零件（revolve，−95% → +281%）。
        b = v["bbox"]
        if kind == "v":
            rs = [(min(s["p1"][1], s["p2"][1]), max(s["p1"][1], s["p2"][1]))
                  for s in segs_in_view(g, v, "中心线层")
                  if abs(s["p1"][0] - s["p2"][0]) < 1e-6
                  and abs(s["p1"][0] - pos) < 1e-6]
            cover = _covered(rs) / max(b[3] - b[1], 1e-9)
        else:
            rs = [(min(s["p1"][0], s["p2"][0]), max(s["p1"][0], s["p2"][0]))
                  for s in segs_in_view(g, v, "中心线层")
                  if abs(s["p1"][1] - s["p2"][1]) < 1e-6
                  and abs(s["p1"][1] - pos) < 1e-6]
            cover = _covered(rs) / max(b[2] - b[0], 1e-9)
        if cover >= 0.30:
            return (v, pos, kind)
    return None


def three_views(g, views, tol=0.03, min_edge_frac=0.2):
    """按**投影原则**识别 主视图(V) / 俯视图(H) / 左视图(W)。返回 `(V, H, W, wide_ok)` 或 None。

    ## 依据（`projection-rules.md` §2 + §3）

    §2 展开后的轴映射 —— **这是判读尺寸关联的基石**：

    | 视图 | 图纸横轴 | 图纸纵轴 | 能读出的尺寸 |
    |---|---|---|---|
    | **主视图** | X（长） | Z（高） | 长、高 |
    | **俯视图** | X（长） | Y（宽） | 长、宽 |
    | **左视图** | Y（宽） | Z（高） | 宽、高 |

    §3 三等关系：
      · **长对正** —— 主视图 ↔ 俯视图，共享 **X**（两者宽度相等）；
      · **高平齐** —— 主视图 ↔ 左视图，共享 **Z**（两者高度相等）；
      · **宽相等** —— 俯视图 ↔ 左视图，共享 **Y**（俯视图的高 == 左视图的宽）。

    ## 为什么这样定主视图（而不是"面积最大"）

    主视图的定义是"**最能反映形状特征**"的那个方向，但那句话**不可直接执行** ——
    实测用"面积最大"判会被证伪（sj-005 的最大视图是俯视图，用了它厚度算成 7.5mm、真值 10mm）。

    可直接执行的等价判据是 §3 的**结构唯一性**：

        主视图 ⟺ **同时**「与某视图长对正」**且**「与另一视图高平齐」的那个视图

    因为只有 V 面同时与 H 面共享 X、与 W 面共享 Z。这条判据是**结构性**的，不依赖尺寸猜测。
    实测 4 件多视图件（sj-004/005/006/008）全部一次命中，且 X/Y/Z 三方向各有两路交叉验证通过、
    与真值 STEP 的 bbox 一致。

    ## 两个工程约束（都是实测补的）

    · `min_edge_frac`：先滤掉**局部放大图 / 螺纹孔大样**这类小视图。
      sj-002 顶部垫片的 4 个 13×13pt 视图就是放大图，不过滤会被它们凑出"3.5×3.5×3.5"的假三视图。
    ·  `wide_ok`（宽相等）作**加分项而非硬条件**：实测 sj-007 抗剪块的左视图缺失
      （它的 v3 是 11×120 的断面），宽相等不成立；此时 Y 取**俯视图**给出的值（真值 ✓）。
    """
    def same(a, b):
        return abs(a - b) <= tol * max(a, b, 1.0)

    vs = [v for v in views if v["n_seg"] >= 4]
    if len(vs) < 2:
        return None
    mx = max(max(v["w"], v["h"]) for v in vs)
    vs = [v for v in vs if max(v["w"], v["h"]) >= min_edge_frac * mx]
    if len(vs) < 2:
        return None

    best = None
    for i, V in enumerate(vs):
        for j, H in enumerate(vs):
            if j == i or not same(H["w"], V["w"]):       # 长对正：主 ↔ 俯 共享 X
                continue
            for k, W in enumerate(vs):
                if k in (i, j) or not same(W["h"], V["h"]):   # 高平齐：主 ↔ 左 共享 Z
                    continue
                wide_ok = same(H["h"], W["w"])           # 宽相等：俯 ↔ 左 共享 Y
                score = (2 if wide_ok else 1, V["w"] * V["h"])
                if best is None or score > best[0]:
                    best = (score, V, H, W, wide_ok)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]

def pair_of(views, tol=0.03):
    """视图集合 → **投影相关的一对**。返回 `(A, B, axis)` 或 None。

    判据（机械制图的投影关系）：
      · **长对正**：两视图「宽」相等 ⇒ 同一 x 方向尺寸 ⇒ axis='x'
      · **高平齐**：两视图「高」相等 ⇒ 同一 y 方向尺寸 ⇒ axis='y'

    取第一对命中的（调用方按段数过滤过，先命中的通常就是主视图对）。
    容差 3%：图纸比例与离散化带来偏差，实测各件配对偏差都远小于 3%。

    ★ 这是把「投影原则」变成可执行判据的最小形式 —— 原先是散在 route_extrude 里的
      一个局部函数 `same()`，现在提成算子，`route_revolve` 也可复用同一套判据。
    """
    def same(a, b):
        return abs(a - b) <= tol * max(a, b, 1.0)

    for i in range(len(views)):
        for j in range(i + 1, len(views)):
            A, B = views[i], views[j]
            if same(A["w"], B["w"]):
                return A, B, "x"
            if same(A["h"], B["h"]):
                return A, B, "y"
    return None


# ================================================================ 数值标定
def annos_of(anno):
    """标注 → 候选值集合（升序）。并三类来源：Ø 的 d、R 的 2r、裸数字。

    这一条被抄过 **2 份逐字相同**的代码（route_extrude 与 route_revolve 各一份），
    是本轮消重的直接对象。
    """
    vals = ({d["d"] for d in anno["diameter"]}
            | {2 * r["r"] for r in anno["radius"]})
    for x in anno["linear_bare"]:
        try:
            vals.add(float(x))
        except ValueError:
            pass
    return sorted(vals)


def scale_of(measured, annos, tol_frac=0.012):
    """实测跨度 + 标注 → 比例 pt/mm。规则：**最大实测跨度 ↔ 最大标注**。

    依据投影原则里的「总体尺寸」：每个方向只有一个总体尺寸，且它是最大的。

    踩坑记录（五版）：
      · "逐对投票、谁命中多谁赢" —— **错**，大比例会撞小标注刷票
        （188.6pt / 2.0 = 94.3 pt/mm，厚度算成 0.16mm、体积 0.6）。
      · "最大跨度配任意标注" —— **也错**（会配到 2.0 这种极小值）。
      · 两端都取最大才对，实测五件全中：
        合金管垫片 160/12=13.33；顶部垫片 188.6/50=3.77；抗剪块 186.7/70=2.667；
        保护罩 79.1/42.8=1.848；底座 87.5/60=1.458。

    score = 有多少个实测跨度能落在某条标注上（仅作诊断，不参与决策）。
    """
    if not measured or not annos:
        return None, 0
    m_max = max(measured)
    a_max = max(a for a in annos if a > 0)
    sc = m_max / a_max
    score = 0
    for m2 in measured:
        v = m2 / sc
        if any(abs(v - a2) <= max(tol_frac * abs(a2), 0.06) for a2 in annos):
            score += 1
    return sc, score


def snap_to(val, annos, tol_frac=0.02):
    """实测值 → 吸附到容差内**最接近**的标注。返回 `(值, 是否吸附)`。

    「标注优先」的依据：图纸数字是**设计意图**，几何只用来确定"哪个数字放哪"。
    吸附掉的是弦缩/离散化带来的 0.3% 级偏差（合金管垫片实测厚 0.997 → 吸附到 1）。
    """
    best = None
    for a in annos:
        if a and abs(val - a) <= max(tol_frac * abs(a), 0.05):
            if best is None or abs(val - a) < abs(val - best):
                best = a
    return (best if best is not None else val), best is not None
