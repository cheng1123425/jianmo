# -*- coding: utf-8 -*-
r"""views_to_3d.py —— 矢量 PDF → 视图 → 尺寸 → 三维（方案④ 的落地端）

链路
    矢量 PDF
      → pdf_geom：带图层的线段（粗实线层 = 可见轮廓）
      → 视图分区（粗实线连通聚类 + 嵌套同心合并 + 剥边框）
      → readops：从图元里量出几何量（圆 / 轮廓 / 轴 / 配对 / 定标 / 吸附）
      → pdf_anno：标注值（Ø/R/裸数字）
      → 按「最大实测 ↔ 最大标注」定标
      → 尺寸（外径/内孔/厚度 或 剖面+厚度 或 半剖回转）→ build123d 建体 → STEP
      → 与真值 census 对拍

本文件只做**三件事**：路线调度、建体、收尾对拍。
所有"从图元里量出数"的活都在 `readops.py`（读图算子库）——
本轮 12 件循环的教训是：反复重写的一直是那一层，而不是建体。

三条路线（**专用优先，通用回退**，顺序不能反）
    annular  环形件：外圆 + 同心内孔 + 厚度        约束最强，先试
    extrude  通用件：长对正/高平齐的一对视图 → 剖面 + 厚度
    revolve  回转件：单视图 + 中心线 → 绕轴回转 360°

定位：打通链路的最小验证，不是通用解图器。

用法
    python views_to_3d.py <文件.pdf> --truth <真值.step> [--out <目录>]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# ---------------------------------------------------------------- 收尾
def _finalize(out, solid, truth_path, out_dir, part):
    """统一收尾：写模型信息、导出 STEP、与真值对拍。"""
    if solid is not None and solid.volume > 1e-6:
        out["model"] = {"volume": round(solid.volume, 3),
                        "bbox": [round(v, 3) for v in
                                 (solid.bounding_box().size.X,
                                  solid.bounding_box().size.Y,
                                  solid.bounding_box().size.Z)]}
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            from build123d import export_step
            sp = os.path.join(out_dir, part + ".step")
            export_step(solid, sp)
            out["step"] = sp
    if truth_path and os.path.exists(truth_path):
        import census as _c
        t = _c.census(truth_path)
        out["truth"] = {"volume": t["volume"], "bbox": t["bbox"], "faces": t["faces"]}
        if t["volume"] and solid is not None:
            out["diff"] = {"volume_pct": round(
                (solid.volume - t["volume"]) / t["volume"] * 100, 3)}
    return out


# ---------------------------------------------------------------- 路线 1：环形件
def route_annular(g, views, anno):
    """环形件：外圆 + 同心内孔 + 厚度。**优先**，约束最强。

    定标用「最大圆直径 ↔ 最大 Ø」——与 `readops.scale_of` 是同一条规则
    （最大实测 ↔ 最大标注），只是这里的"实测"取圆直径而非视图跨度。
    """
    import readops as R

    dias = sorted({d["d"] for d in anno["diameter"]}, reverse=True)
    bare = []
    for x in anno["linear_bare"]:
        try:
            bare.append(float(x))
        except ValueError:
            pass

    circle_views = []
    for i, segs in R.by_view(g, views).items():
        v = views[i]
        c, rs = R.circle_of(segs)
        if rs and abs(v["w"] - v["h"]) < 0.20 * max(v["w"], v["h"]):
            circle_views.append({"view": i, "center": c, "radii": rs, "bbox": v["bbox"]})
    if not circle_views:
        return None, "无圆视图"
    cv = max(circle_views, key=lambda d: d["bbox"][2] - d["bbox"][0])
    if not dias:
        return None, "无 Ø 标注，无法定标"
    scale = 2 * max(cv["radii"]) / dias[0]
    measured = [round(2 * r / scale, 3) for r in sorted(cv["radii"], reverse=True)]

    # 与圆视图**高平齐**（y 范围相同）且更窄的那个视图 = 厚度
    cy0, cy1 = cv["bbox"][1], cv["bbox"][3]
    thick = None
    for i, v in enumerate(views):
        if i == cv["view"]:
            continue
        b = v["bbox"]
        if (abs(b[1] - cy0) < 0.05 * (cy1 - cy0)
                and abs(b[3] - cy1) < 0.05 * (cy1 - cy0)
                and b[2] - b[0] < 0.5 * (cy1 - cy0)):
            thick = round((b[2] - b[0]) / scale, 3)
            break
    if len(measured) < 2:
        return None, "圆不足 2 个（外径+内孔）"
    if thick is None:
        return None, "找不到与圆视图高平齐的薄视图（厚度）"

    od_r, s1 = R.snap_to(measured[0], dias)
    id_r, s2 = R.snap_to(measured[1], dias)
    th_r, s3 = R.snap_to(thick, bare + dias)

    from build123d import Cylinder
    solid = Cylinder(od_r / 2.0, th_r) - Cylinder(id_r / 2.0, th_r)
    return {"route": "annular", "scale_pt_per_mm": round(scale, 4),
            "measured_diameters_mm": measured,
            "annotated_diameters": dias,
            "thickness_mm": thick,
            "snap": {"od": s1, "id": s2, "thickness": s3},
            "final": {"od": od_r, "id": id_r, "thickness": th_r},
            "_solid": solid}, None


# ---------------------------------------------------------------- 路线 2：通用拉伸
def _build_layered(base_face, layers, axis="x"):
    """**分层建体**：每层取"主视图轮廓 ∩ 该层的宽度条带" → 拉伸该层厚度 → 按 z 堆叠求并。

    制图依据：`section-analysis.md` §3.3「台阶突变处 ⇒ 回到**邻接视图**上量出转折坐标」、
    §4「台阶状突变（多级高度）⇒ **复杂轮廓一次成型**，不要分段建多个体」。
    这里的分层不是"分段建多个零件"，而是**同一零件的多层截面堆叠**（一次成型）。
    """
    from build123d import Rectangle, Pos, extrude as _ex
    bb = base_face.bounding_box()
    W = bb.max.X - bb.min.X
    H = bb.max.Y - bb.min.Y
    cx = (bb.max.X + bb.min.X) / 2.0
    cy = (bb.max.Y + bb.min.Y) / 2.0
    # `axis` 是"长对正/高平齐"的共同方向 ⇒ 层的区间就落在该方向上：
    #   axis="x" ⇒ 条带是"x ∈ [a,b]、y 全取"；axis="y" ⇒ 反过来。
    solid = None
    for (z0, z1, ivs) in layers:
        f = base_face
        for (a, b) in ivs:
            if axis == "x":
                bar = Pos((a + b) / 2.0, cy, 0) * Rectangle(max(b - a, 1e-6), H * 3.0)
            else:
                bar = Pos(cx, (a + b) / 2.0, 0) * Rectangle(W * 3.0, max(b - a, 1e-6))
            f = f & bar
        try:
            piece = _ex(f, amount=z1 - z0)
        except Exception:
            continue
        if piece.volume < 1e-9:
            continue
        piece = Pos(0, 0, z0) * piece
        solid = piece if solid is None else (solid + piece)
    return solid


def route_extrude(g, views, anno):
    """通用件：一对投影相关的视图（长对正/高平齐）→ 大的是剖面、小的给厚度 → 拉伸。"""
    import readops as R

    big = [v for v in views if v["n_seg"] >= 8]
    if len(big) < 2:
        big = [v for v in views if v["n_seg"] >= 4]      # 薄件主视图可能只有 6 段
    if len(big) < 2:
        return None, "≥4 段的视图不足 2 个"

    annos = R.annos_of(anno)
    if not annos:
        return None, "无标注可用作标定"
    dias_h = sorted({d["d"] for d in anno["diameter"]}
                    | {2 * r["r"] for r in anno["radius"]})
    extents = R.extents_of(big)
    if not extents:
        return None, "无实测跨度"
    sc, score = R.scale_of(extents, annos)
    if not sc:
        return None, "标定失败"

    # ⚠️ 试过"先定主视图（面积最大者）再配对"（制图规范：主视图 = 形状特征最充分的方向）。
    #   **实测净负，已回退**：sj-004 的厚度从 13mm 修正为 10mm（+581→+547），
    #   但 sj-005 从 +60% 崩到 **+441%**（它的最大视图 v2 是俯视图 15×10，
    #   被当成主视图后厚度算成 7.5mm，真值 10mm）。
    #   ⇒ "面积最大即主视图"这条**不成立**；主视图要按"形状特征"判，
    #   而"轮廓取到外框"这个更上游的问题没解决前，换 pair 只是把误差搬来搬去。
    # ★★ 视图分配（第14轮）：**先用投影原则的三等关系定 主/俯/左**（`projection-rules.md` §2/§3），
    # 失败再回退 `pair_of`。
    #
    # 为什么必须换：`pair_of` 只是在遍历顺序里"先命中哪一对就用哪一对"，**不区分哪个是主视图**。
    # 实测 sj-008 底座：它选出 (v1 88×70, v0 70×70)，厚度算成 47.9mm（真值 40mm）；
    # 而按三等关系，主视图 = v1（同时与 v2 高平齐、与 v3 长对正），俯视图 = v3，厚度 = 40mm ✓。
    # 4 件多视图件（sj-004/005/006/008）用三等关系全部一次命中，
    # X/Y/Z 三方向各有两路交叉验证通过、与真值 STEP 的 bbox 一致。
    #
    # §2 轴映射：主视图读(长,高)、俯视图读(长,宽) ⇒
    #   **剖面取主视图**（它反映"长×高"的形状特征），**宽度取自俯视图**（长对正 ⇒ 共享 X）。
    tv = R.three_views(g, views)
    if tv is not None:
        V, H, W, wide_ok = tv
        A, B, axis = V, H, "x"        # 主视图 ↔ 俯视图，长对正 ⇒ 共同方向 x
        view_src = "three_views%s" % ("" if wide_ok else "(宽不相等,左视图缺)")
    else:
        pair = R.pair_of(big)
        if not pair:
            return None, "找不到长对正/高平齐的一对视图"
        A, B, axis = pair
        view_src = "pair_of"

    # ★ 选哪个当剖面 —— **按机械制图原则**：
    #   「主视图应选**最能反映零件形状特征**的方向」（投影原则）；
    #   「台阶状突变（多级高度）⇒ 复杂轮廓一次成型，不要分段建多个体」、
    #   「台阶突变处 ⇒ 回到**邻接视图**上量出转折坐标」（section-analysis.md §3.3 / §4）。
    #
    #   可执行化：**轮廓实占率（轮廓面积 / 视图 bbox 面积）更低**的那个视图，
    #   说明它的轮廓更有凹凸、表达了更多形状特征（台阶就在那里）。
    #   实测：sj-007 大视图(70×45)实占 100%（就是个矩形），小视图(70×6)实占 80%
    #   ⇒ 厚度方向的台阶画在小视图上，该用它当剖面。
    #   保护：两者实占率差不到 10% 时**不切换**（避免把本来对的件改坏，如 sj-002 两边都是 100%）。
    import profile as _P

    def _occ(v):
        pl, _d = R.loop_of(R.segs_in_view(g, v), v["bbox"], degrade=True)
        if not pl:
            return None
        return _P.poly_area(pl) / max(v["w"] * v["h"], 1e-9)

    if view_src.startswith("three_views"):
        prof, thin = A, B                          # 固定：剖面=主视图，薄视图=俯视图
    else:
        prof, thin = (A, B) if A["w"] * A["h"] >= B["w"] * B["h"] else (B, A)
    big, small = prof, thin
    o_big, o_small = _occ(big), _occ(small)    # 仅作记录，不再用于切换

    # ⚠️ 试过加"会切过去的视图必须检测得到圆"这条附加约束（制图原则：孔的实形
    #   画在能反映实形的视图上），**实测有害已回退** —— 它把上轮靠切换拿到的改善
    #   全部撤销（sj-004 −41.4→+581.3、sj-007 +16.3→+47.8、sj-008 −8.0→+2.6）。
    #   正确的解法是"轮廓取一个视图、孔取另一个视图"（多视图联合），但那需要
    #   视图间的坐标映射（长对正/高平齐），是更大的工程，不由这一条约束解决。
    # ★ 收窄后的判据：**大视图"铺满自己的 bbox"（填充率 ≥0.95）且小视图没铺满** ⇒ 用小的。
    #   理由：大视图的轮廓**恰好等于它的外接矩形** ⇒ 走环很可能只抓到"视图外框"、
    #   没抓到真轮廓（实测 sj-007 抗剪块：大视图 70×45 实占 1.00，而真值截面只有 65%）。
    #   反例保护：实心件两边都铺满（sj-002 顶部垫片 1.00 / 1.00）⇒ **不切换**。
    #   原判据是"实占率差 >0.10"，它把 sj-001/sj-006 也切到 small
    #   （sj-001 差 0.30、sj-006 差 0.57），而这两件用小视图会**丢掉主轴轮廓**
    #   （sj-006 的 Ø96 内腔圆被当成剖面 ⇒ 厚度算成 21mm）。
    # ★★ 重设（2026-10-16 第13轮）：**剖面恒取"面积大的那个视图"（主视图）**。
    #
    # 原来这里是"轮廓实占率差 > 0.10 ⇒ 改用小视图"。该判据**已被证伪**：
    # 实测三个件的需求互相冲突，而它给出同一个方向 ——
    #   sj-001 需要 big（差 0.30）、sj-006 需要 big（差 0.57）、sj-007 需要 small（差 0.20）。
    # 更糟的是它把"哪个视图当剖面"和"厚度取哪条边"绑在一起：一旦切到 small，
    # `thin` 就变成主视图，厚度取到主视图的**长边**（sj-006 的厚度被算成 21mm，真值 5mm）。
    #
    # 制图规范的正确表述是两句**独立**的话：
    #   · 「主视图应选**最能反映零件形状特征**的方向」⇒ 表达面积最大的那个视图；
    #   · 「厚度是**垂直于主视图**的尺寸」⇒ 从**另一个视图**的"非共同方向"上取。
    # 实测三件在"恒用 big"下**厚度全部正确**：
    #   sj-001 big 31×240 / thin 31×27（axis=x）⇒ 厚 27pt = 10mm ✓
    #   sj-006 big 107×112 / thin 107×27（axis=x）⇒ 厚 27pt = 5mm  ✓
    #   sj-007 big 187×120 / thin 187×16（axis=x）⇒ 厚 16pt = 6mm  ✓
    #
    # ⚠️ 代价（如实记账）：sj-007 抗剪块的"厚度方向台阶"画在**侧视图**上
    #   （实测 side 轮廓 9 点含凸台、俯视是完整圆角矩形），恒用 big 后它从 +16.3% 变 +55%。
    #   但那是**"多段建模"该解决的问题**（section-analysis.md §3.3「台阶突变处 ⇒
    #   回到邻接视图上量出转折坐标」），不该由 pick 用"碰巧接近"来掩盖。
    prof, thin = big, small
    profile_pick = "big(主视图=面积大者)"
    # 厚度取"薄视图"垂直于投影方向的尺寸（`thin` 就是薄的那个视图）。
    thick_pt = thin["h"] if axis == "x" else thin["w"]
    thick_mm = thick_pt / sc

    # 剖面轮廓：**剖面视图自带剖面线**且**剖面线覆盖视图大部分**时，才用剖面线扫描。
    #
    # ★ 覆盖率判据不是可选的。实测（8 件 extrude 全测）：
    #     · prof 视图根本没有剖面线的：7 件（剖面线都在**别的**视图上）；
    #     · sj-001 是唯一 prof 带剖面线的，但覆盖率只有 **3%**
    #       —— 那是局部剖/断面的线，不是"截面填充"，扫描出来截面残缺
    #       ⇒ 体积从 +106% 变成 **-91.6%**（更难看、也是错的）。
    #   所以必须要求剖面线**铺满视图**（≥50%）才认为它是真剖视图的截面填充。
    src = None
    poly, degraded = None, None
    hatch_segs = R.segs_in_view(g, prof, "剖面线层")
    if hatch_segs:
        hx = [p[0] for s in hatch_segs for p in (s["p1"], s["p2"])]
        hy = [p[1] for s in hatch_segs for p in (s["p1"], s["p2"])]
        cov = ((max(hx) - min(hx)) * (max(hy) - min(hy))) / max(prof["w"] * prof["h"], 1e-9)
        if cov >= 0.5:
            poly, _herr = R.section_outer_of_hatch(g, prof)
            if poly is not None:
                src = "hatch"
    if poly is None:
        poly, degraded = R.loop_of(R.segs_in_view(g, prof), prof["bbox"], degrade=True)
        src = "loop"

    snap_th = thick_mm
    for a in annos:
        if abs(thick_mm - a) <= max(0.02 * a, 0.06):
            snap_th = a
            break

    from build123d import Polyline, make_face, extrude, Pos, Cylinder
    x0 = min(p[0] for p in poly)
    y0 = min(p[1] for p in poly)
    # ⚠️ 这里**必须平移**（减轮廓自身的 min）：下面的**减孔**用的是
    # `(cx - x0)/sc` 这套坐标 —— 一旦这里不平移、孔还按旧式换算，
    # 两者就错位、孔减不到（实测 sj-002 体积从 9720 涨到 10007、sj-006 从 380 涨到 1652）。
    # 分层用的 `layers` 则在下面单独对齐到本坐标系（见 `_align_layers`）。
    pts = [((p[0] - x0) / sc, (p[1] - y0) / sc) for p in poly]
    base = make_face(Polyline(*pts, close=True))

    # ★ **分层拉伸**（厚度方向有台阶时）。
    #   制图依据：`section-analysis.md` §3.3「台阶突变处 ⇒ 回到**邻接视图**上量出转折坐标」。
    #   判据：薄视图轮廓里存在**"中间高度的水平段"**（`profile.has_step`）——
    #   那是厚度方向台阶的投影。实测 sj-007 抗剪块（厚度向 4 个平面）有 3 条中间水平段，
    #   而 sj-002 顶部垫片（薄视图是 4 点矩形）没有 ⇒ 走普通拉伸，不受影响。
    thin_poly, _thd = R.loop_of(R.segs_in_view(g, thin), thin["bbox"])
    solid = None
    layered = None
    if thin_poly is not None and _P.has_step(thin_poly, axis=axis):
        layers = _P.layers_of(thin_poly, sc, axis=axis)
        # ★ **对齐坐标原点**：`base` 用"轮廓自身 min"为原点，而 `layers` 的区间是
        #   图纸 pt/sc。三等关系（长对正/高平齐）保证两视图**共享同一图纸坐标轴**，
        #   所以只要把薄视图的区间平移到主视图轮廓的原点即可。
        #   不改这一步的后果：条带与剖面错开 ⇒ 交集空 ⇒ 建出 volume=0 的空体
        #   （sj-008 底座因此一直落到 revolve 兜底）。
        if layers:
            base_o = x0 if axis == "x" else y0
            off = base_o / sc
            layers = [(z0, z1, [(a - off, b - off) for (a, b) in ivs])
                      for (z0, z1, ivs) in layers]
        if len(layers) >= 2:
            solid = _build_layered(base, layers, axis=axis)
            if solid is not None and solid.volume > 1e-6:
                layered = len(layers)
            else:
                solid = None
    if solid is None:
        try:
            solid = extrude(base, amount=snap_th)
        except Exception as e:
            return None, "拉伸失败：%s" % str(e)[:40]

    # ★ 减孔：**剖面视图内部**的圆就是孔（俯视图里孔表现为圆，且被剖到的孔天然标 Ø）。
    #   实测 sj-002 分组后读出 4×d13.2 + 4×d9.9 + d24.7，按定标换算是 4×Ø3.5 + 4×Ø2.6 + Ø6.5
    #   —— **与真值孔完全对上**，且这些孔本来就画在 prof 视图里，不需要跨视图映射。
    #
    #   三道过滤（第二、三道是加严后补的，都有实测依据）：
    #     ① 太大 ⇒ 是外轮廓/中心大凸台，不当孔；
    #     ② 不在轮廓内 ⇒ 不属于这个截面；
    #     ③ ★ 先 `pick_holes` 做**同心组只取最内层**（否则中心凸台的多层同心圆会被整组挖穿
    #        —— 实测 sj-007 误减 Ø30/Ø28/Ø20.53/Ø17.62，真值里根本没这些孔），
    #        再要求直径**能在 Ø 标注里对上**（孔一定标直径，便于加工）。
    cs_all = R.circles_in_view(g, prof)
    # ★ **外轮廓本身是不是圆** —— 决定同心圆组是"阶梯孔/腔"还是"凸台"：
    #   轮廓是圆（如 sj-003 的 Ø42.8）⇒ 与它同心的整组都减；
    #   轮廓是矩形/异形（如 sj-007 的 70×45）⇒ 组内是凸台，只减最内层。
    outline_circle = bool(cs_all) and 2 * cs_all[0][2] >= 0.9 * min(prof["w"], prof["h"])
    # ★ 阈值 0.8 → 0.95：实测 sj-006 的 Ø18 内腔是 96pt、视图 107×112，
    #   96 > 0.8×112 = 89.6 ⇒ **被当成"外轮廓"排掉** ⇒ 内腔没减、体积偏小（−95%）。
    #   放宽到 0.95 后 Ø96 < 106.4 通过；仍在轮廓内的判据（point_in_polygon）兜住误减。
    cand = [(cx, cy, r) for (cx, cy, r) in cs_all
            if 2 * r < 0.95 * max(prof["w"], prof["h"])
            and R.point_in_polygon((cx, cy), poly)
            # ★★ 孔必须**整圈**落在轮廓内（制图原则：孔是内部特征，被外形完整包围）。
            #   只判"圆心在内"会漏掉**贴着外形的圆** —— 实测 sj-008 底座的 Ø48pt 圆
            #   圆心在内、圆周越界，被当孔减掉 ⇒ 截面挖空 ⇒ volume=0 ⇒ extrude 整条失败。
            and R.circle_inside(cx, cy, r, poly)]
    holes = []
    for (cx, cy, r) in R.pick_holes(cand, outline_circle=outline_circle):
        if not dias_h:
            continue
        hv, hit = R.snap_to(r * 2 / sc, dias_h, tol_frac=0.04)
        if not hit:
            continue
        holes.append((cx, cy, hv / 2.0))
    body_before_holes = solid
    for (cx, cy, rr) in holes:
        try:
            solid -= (Pos((cx - x0) / sc, (cy - y0) / sc, snap_th / 2.0)
                      * Cylinder(rr, snap_th * 1.2))
        except Exception:
            pass
    # ★ 保底：**宁可不减孔，也不出空体**。实测 sj-008 曾因误减一个大"孔"把截面挖空
    #   ⇒ volume=0 ⇒ 整条 extrude 路线被判失败、退回 revolve（−17.8%）。
    #   减孔后若体为空/退化，退回减孔前的体，让偏差可见、而不是退化成 0。
    if solid is None or solid.volume <= 1e-6:
        solid = body_before_holes
    # ★ **交叉验证（只报告、不影响建体）**：用户 2026-10-16 补充的判据 ——
    #   「面积最大不一定是主视图，**主视图一般是标注尺寸最多的那个视图**」。
    #   理由正当：`projection-rules.md §7`「主视图最能反映形状特征」不可直接执行，
    #   而 `dimension-placement.md`「特征集中」⇒ 尺寸都往表达最清楚的那个视图上标。
    #   实测（`arrow_count_of`，尺寸线层的箭头数）：5 件可判里 3 件与三等关系一致、1 件并列、
    #   1 件冲突（那件把孔的定位尺寸标在俯视图上，是常见做法）。
    #   ⇒ **不作主判据**（三等关系是 structural 的、且有尺寸语义验证），只留痕供人工复核。
    dim_agree = None
    if view_src.startswith("three_views"):
        n_self = R.arrow_count_of(g, prof)
        n_max = max(R.arrow_count_of(g, v) for v in views) if views else 0
        dim_agree = "ok" if n_self >= n_max else "conflict(%d<max%d)" % (n_self, n_max)

    return {"route": "extrude", "profile_degraded": degraded, "profile_src": src,
            "dim_agree": dim_agree,
            "profile_pick": profile_pick, "layered": layered, "view_src": view_src, "scale_pt_per_mm": round(sc, 4),
            "profile_view": [prof["w"], prof["h"]],
            "thin_view": [thin["w"], thin["h"]],
            "poly_pts": len(poly), "thickness_mm": round(snap_th, 3),
            "poly_mm": [[round(a, 2), round(b, 2)] for a, b in pts],
            "holes": [round(h[2] * 2, 2) for h in holes],
            "scale_votes": score, "axis": axis, "_solid": solid}, None


# ---------------------------------------------------------------- 路线 3：回转
def route_revolve(g, views, anno):
    """回转件：**单视图 + 中心线 → 绕轴回转 360°**。

    什么时候需要：有的图只有一张轴剖侧视图（如底部垫片、定心垫片），
    锥面/台阶全在这一张轮廓里，没有俯视图可配对 —— 拉伸路线无从下手。
    """
    import readops as R

    annos = R.annos_of(anno)
    extents = R.extents_of(views)
    if not annos or not extents:
        return None, "缺标注或跨度，无法定标"
    sc, score = R.scale_of(extents, annos)

    # ★ **优先选"全剖视图"**（制图原则：轴向剖视 = 贯穿的中心线 + 铺满的剖面线）。
    #   只用 `axis_view_of`（只看中心线）会误选俯视图（每孔一小段中心线也能凑成"贯穿"）
    #   ⇒ 回转而剖面线扫描失败、退回走环 ⇒ 得到**实心柱**（实到 sj-003 +864%）。
    # ★ 三选一，按"判据强度"排序：回转体判据认定的视图 > 全剖视图 > 有中心线的视图。
    #   必须把 `axisymmetric_section_of` 放最前：它是**判据本身挑出来的那个视图**
    #   （实测 sj-001 的轴在主视图 v2 上，而 `axis_view_of` 会选到别的视图 ⇒ 建出 −98% 的小body）。
    best = (R.axisymmetric_section_of(g, views)
            or R.full_section_view_of(g, views) or R.axis_view_of(g, views))
    if best is None:
        return None, "没有带中心线的视图"
    v, axis_pos, kind = best

    # ★ 三级取轮廓，按"离制图本质由近到远"排序：
    #   stepped —— **剖视图的素线**（平行于轴的粗实线）给半径、台阶线给轴向位置。
    #              制图上这才是"剖面轮廓"的正解，且**贯穿全长**
    #              （实测 sj-003 是阶梯薄壁套 9 级半径、图上只有局部剖，
    #               剖面线只在两端；素线 r=11.16 那条却长 29.76mm ⇒ 能逐段还原）
    #   hatch   —— 剖面线扫描（"这里剖到材料"）。适合实心/简单件，
    #              实测 sj-009 走环解差 115.9mm³ 正好是 Ø6.5 通孔 π×3.25²×3.5=116.1
    #   loop    —— 走环法，最后的回退
    pts, src = R.pick_profile(g, v, axis_pos, kind, multi_view=len(views) >= 2)
    if pts is None:
        poly, _deg = R.loop_of(R.segs_in_view(g, v), v["bbox"], degrade=False)
        if poly is None:
            return None, "回转：素线/剖面线/走环三条路都失败"
        pts = R.half_profile_of(poly, axis_pos, kind)
        src = "loop"
    if pts is None or len(pts) < 3:
        return None, "半剖面点不足"
    pts = [(a / sc, b / sc) for a, b in pts]

    # ★ 径向吸附到 Ø 标注：剖面线有间距 ⇒ 扫描出的半径有零点几毫米偏差
    #   （sj-009 实测 79.4pt→5.955mm、43.5pt→3.26mm，吸附后分别是 Ø12 的一半、Ø6.5 的一半）。
    #   图纸数字是设计意图，几何只用来确认"哪个数字放哪"。
    dias = sorted({d["d"] for d in anno["diameter"]}
                  | {2 * r["r"] for r in anno["radius"]})
    snapped = 0
    if dias:
        out = []
        for a, b in pts:
            vb, hit = R.snap_to(b * 2.0, dias, tol_frac=0.03)
            snapped += 1 if hit else 0
            out.append((a, vb / 2.0))
        pts = out

    # ★ 吸附后去掉**完全重合**的相邻点。
    #   相邻段的内缘 r 在吸附后会落到同一个标注值（如两段都 →Ø6.5 的一半），
    #   于是出现零长边 —— OCCT 直接拒绝："BRep_API: command not done"（sj-009 实测）。
    ded = []
    for p in pts:
        if not ded or abs(p[0] - ded[-1][0]) > 1e-6 or abs(p[1] - ded[-1][1]) > 1e-6:
            ded.append(p)
    pts = ded

    from build123d import Polyline, make_face, revolve, Axis
    try:
        solid = revolve(make_face(Polyline(*pts, close=True)), Axis.X, 360)
    except Exception as e:
        return None, "回转失败：%s" % str(e)[:40]
    return {"route": "revolve", "profile_src": src, "scale_pt_per_mm": round(sc, 4),
            "axis": kind, "profile_pts": len(pts),
            "profile_view": [v["w"], v["h"]],
            "_solid": solid}, None


# ---------------------------------------------------------------- 调度
ROUTES = [("annular", route_annular), ("extrude", route_extrude),
          ("revolve", route_revolve)]


def routes_for(g, views):
    """路线分派：**专用优先、通用回退**；**回转体把 revolve 提到 extrude 之前**。

    ## 为什么需要"提前"

    早期顺序是 `annular → extrude → revolve`。而 `route_extrude` 只要**能建出非空体**
    就算成功 ⇒ 回转体被它抢先接管，建出实心柱：

    | 件 | 真值 | extrude 建的 | 偏差 |
    |---|---|---|---|
    | sj-003 顶部保护罩 | Ø42 薄壁罩，vol 3984 | 实心柱，19088 | +379% |
    | sj-006 上层限位口 | Ø20 盘，vol 468 | 小异形块，21 | −95% |

    ⇒ 用**制图原则的回转体判据**（`readops.is_axisymmetric`：
    有全剖视图 + 有同心圆组）决定要不要提前。

    ## 为什么还要保留最后的 `revolve`

    单视图轴剖件（sj-009 底部垫片、sj-011 定心垫片）只有一张视图，
    不满足"另有视图含同心圆组"，判据为 False ⇒ 它们仍走
    `annular(失败) → extrude(失败) → revolve`，行为不变（实测逐位一致）。
    """
    import readops as R
    base = [("annular", route_annular)]
    # ★ 判据（制图规范）：**局部剖视图 + 居中轴线** ⇒ 是回转体，
    #   且**视图数 ≥ 2**（单视图轴剖件留给剖面线扫描，见 axisymmetric_section_of 的边界说明）。
    # ★ 但若**能配成完整的三等关系三视图**，就不是回转体 ——
    #   制图规范 `projection-rules.md §7.4`：「能用两个视图表达清楚的不用三个」；
    #   反过来，一个零件被画了**三个成三等关系的视图**，说明它的形体是**块/棱柱类**，
    #   而不是回转体（回转体只需一个轴向剖视 + 一个端视图）。
    #   缺这条的后果：sj-008 底座被 `axisymmetric_section_of` 抢走（v0 的 70×70 视图
    #   恰有居中轴线 + 满铺剖面线）⇒ 走 revolve、厚度取不到 ⇒ 停在 −17.8%。
    if (len(views) >= 2 and R.three_views(g, views) is None
            and R.axisymmetric_section_of(g, views) is not None):
        base.append(("revolve", route_revolve))
    base += [("extrude", route_extrude), ("revolve", route_revolve)]
    return base


def run(pdf_path, truth_path=None, out_dir=None):
    import pdf_geom as G
    g = G.geometry_of(pdf_path)
    views = [v for v in G.cluster_views(g["segments"]) if v["n_seg"] >= 3]

    import pdf_anno
    anno = pdf_anno.anno_of(pdf_path)

    # ★ 顺序不能反。踩过的坑：把通用拉伸路线放在最前（"or True"），
    #   结果把合金管垫片的精确解挤掉，全体变成 +40% 的粗解。
    errs = []
    for name, fn in routes_for(g, views):
        r, err = fn(g, views, anno)
        if r is None:
            errs.append("%s: %s" % (name, err))
            continue
        solid = r.pop("_solid", None)
        if solid is None or solid.volume <= 1e-6:
            errs.append("%s: 建体为空" % name)
            continue
        out = {"ok": True, "part": g["part"], "view_route": name, "views": len(views)}
        out.update(r)
        return _finalize(out, solid, truth_path, out_dir, g["part"])

    return {"ok": False, "part": g["part"], "why": "；".join(errs) or "所有路线都失败"}


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    pdf, truth, out = None, None, None
    i = 0
    while i < len(argv):
        if argv[i] == "--truth":
            truth = argv[i + 1]; i += 2; continue
        if argv[i] == "--out":
            out = argv[i + 1]; i += 2; continue
        pdf = argv[i]; i += 1
    r = run(pdf, truth, out)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
