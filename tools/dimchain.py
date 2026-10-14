# -*- coding: utf-8 -*-
r"""dimchain.py —— 尺寸链（Dimension Chain）构链与闭合校验

机械制图里，标注不是一堆孤立的数字：同一方向上的若干尺寸段首尾相接，
构成一条**尺寸链**；链上所有组成环的代数和必须等于封闭环，否则图纸自相矛盾。

四类要检出的问题
----------------
1. **闭合超差**    Σ各段 ≠ 封闭环（超过累积公差）→ 标注互相矛盾
2. **过标注**      同一条链上出现多个"跨整链"的尺寸 → 重复约束
                  （国标允许，但加工时只能取一个，其余是参考）
3. **欠标注**      链上没有任何一段跨整链、包围盒也没给出总尺寸 → 无法加工
4. **非对称超差**  对称结构上本应对称的两段差太多 → 形状不对称或标错

封闭环的两个来源
----------------
* **显式**：链上某一段的跨度覆盖整条链（它就是总尺寸标注）
* **隐含**：视图的包围盒范围 —— 零件在某个方向上的总尺寸必然等于包围盒，
  即使图纸没标，这个数也是客观存在的，可以用来闭合

构链方法（纯几何，不需要人告诉系统哪几个尺寸是一条链）
--------------------------------------------------------
把每条线性尺寸看成图的一条**边**，两个端点是**节点**；两条边共享节点
（端点距离 < tol）就在同一条链上 —— 并查集求连通分量即可。

径向链（半径/直径参与）
----------------------
俯视图上一组同心或共轴的圆，沿某条轴线排开时，其外缘跨度构成径向链：
    总宽 = 2 × (孔心距 + 凸台半径)
这是回转类零件最常用的链形（本例：550 = 2×(200 + 75)）。
"""
import itertools


# ----------------------------------------------------------------------
# 构链（通用：只认 axis/lo/hi/value）
# ----------------------------------------------------------------------
def _axis_of(p1, p2):
    """判断尺寸段方向：'x' 水平 / 'y' 竖直 / None 斜向（斜向不进链）"""
    dx, dy = abs(p2[0] - p1[0]), abs(p2[1] - p1[1])
    if dx < 1e-9 and dy < 1e-9:
        return None
    if dy <= 0.25 * dx:
        return "x"
    if dx <= 0.25 * dy:
        return "y"
    return None


def seg_of_dim(d):
    """把一条接地尺寸转成链上的边；返回 None 表示不能进链"""
    p1, p2 = d.get("p1"), d.get("p2")
    if not p1 or not p2:
        return None
    ax = _axis_of(p1, p2)
    if ax is None:
        return None
    lo, hi = (p1[0], p2[0]) if ax == "x" else (p1[1], p2[1])
    lo, hi = min(lo, hi), max(lo, hi)
    if hi - lo < 1e-9:
        return None
    val = d.get("value_mm")
    if val is None:
        val = d.get("measured_mm")
    if val is None:
        return None
    return {
        "axis": ax, "lo": float(lo), "hi": float(hi),
        "len": float(hi - lo),
        "text": d.get("text") or d.get("label"),
        "value_mm": float(val),
        "measured_mm": d.get("measured_mm"),
        "p1": [float(p1[0]), float(p1[1])],
        "p2": [float(p2[0]), float(p2[1])],
        "confidence": d.get("confidence"),
        "source": d.get("source", "grounded"),
    }


class _DSU(object):
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def build_chains(dims, join_tol=10.0):
    """
    构链。dims: 已接地的线性尺寸列表（含 p1/p2/value_mm）。
    返回按 (axis, lo) 排序的链列表。
    """
    segs = [s for s in (seg_of_dim(d) for d in dims) if s]
    if not segs:
        return []

    dsu = _DSU(len(segs))
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if segs[i]["axis"] != segs[j]["axis"]:
                continue
            for a, b in itertools.product((segs[i]["lo"], segs[i]["hi"]),
                                          (segs[j]["lo"], segs[j]["hi"])):
                if abs(a - b) <= join_tol:
                    dsu.union(i, j)
                    break

    groups = {}
    for i in range(len(segs)):
        groups.setdefault(dsu.find(i), []).append(segs[i])

    chains = []
    for g in groups.values():
        if len(g) < 2:                     # 孤立一段不成链，无法做闭合校验
            continue
        g.sort(key=lambda s: s["lo"])
        lo, hi = g[0]["lo"], max(s["hi"] for s in g)
        chains.append({
            "axis": g[0]["axis"], "lo": lo, "hi": hi,
            "span": hi - lo,
            "segments": g,
        })
    chains.sort(key=lambda c: (c["axis"], c["lo"]))
    return chains


# ----------------------------------------------------------------------
# 径向链：一组共轴圆沿轴排开，外缘跨度 = 总尺寸
# ----------------------------------------------------------------------
def radial_chains(circles, axis="x", mm_per_px=1.0, center_tol_px=2.0):
    """
    把沿某轴排开的圆组成"径向链"。**全部换算成 mm 再算**（圆心坐标和半径
    必须同单位，否则会算出毫无意义的数）。

    圆心落在同一条垂直于 axis 的直线上的圆才同链；每个圆心簇只取
    **半径最大的那个**（最外圈）参与链的构成 —— 内圈圆是同心台阶，
    由半径标注单独校验，不混进跨度链。

    链的组成环（回转类零件最常用的链形）：
        首圆半径 + 相邻圆心距… + 末圆半径 = 外缘总跨度
    本例：75 + 200 + 200 + 75 = 550
    """
    perp = "cy" if axis == "x" else "cx"
    along = "cx" if axis == "x" else "cy"
    buckets = {}
    for c in circles:
        # 归一成 mm
        m = {"cx_mm": c["cx"] * mm_per_px, "cy_mm": c["cy"] * mm_per_px,
             "r_mm": c.get("r_mm", c["r_px"] * mm_per_px),
             "d_mm": c.get("d_mm", 2 * c["r_px"] * mm_per_px),
             "text": c.get("text"), "cx": c["cx"], "cy": c["cy"],
             "r_px": c["r_px"]}
        buckets.setdefault(round(m[perp + "_mm"] / center_tol_px), []).append(m)

    out = []
    for k in sorted(buckets):
        g = sorted(buckets[k], key=lambda m: m[along + "_mm"])
        if len(g) < 2:
            # 单个圆心簇：它就是一条"直径链"（总宽 = 直径）
            if g and g[0]["d_mm"] > 0:
                out.append({
                    "axis": axis, "perp_mm": round(g[0][perp + "_mm"], 3),
                    "n_circles": 1, "outer": [g[0]],
                    "parts": [round(g[0]["d_mm"], 3)],
                    "span_mm": round(g[0]["d_mm"], 3),
                    "inner": g[1:],
                })
            continue
        # 每个圆心簇取最外圈
        outer = []
        for m in g:
            if outer and abs(m[along + "_mm"] - outer[-1][along + "_mm"]) <= center_tol_px:
                if m["r_mm"] > outer[-1]["r_mm"]:
                    outer[-1] = m
            else:
                outer.append(m)
        parts = [round(outer[0]["r_mm"], 3)]
        for a, b in zip(outer, outer[1:]):
            parts.append(round(abs(b[along + "_mm"] - a[along + "_mm"]), 3))
        parts.append(round(outer[-1]["r_mm"], 3))
        span = round(sum(parts), 3)
        out.append({
            "axis": axis, "perp_mm": round(g[0][perp + "_mm"], 3),
            "n_circles": len(outer), "outer": outer,
            "parts": parts, "span_mm": span,
            "inner": [m for m in g if m not in outer],
        })
    return out


def check_radial(ch, dims, mm_per_px, tol_ratio=0.02, min_tol_mm=0.5):
    """
    校验一条径向链：
      1. Σ组成环 == 外缘总跨度（构造恒等，用来抓数据错误）
      2. 链上每个「外圈圆」的直径 / 圆心距，与图纸上的直径/距离标注交叉验证
      3. 外缘总跨度与覆盖它的线性总尺寸标注闭合
    """
    issues = []
    span_mm = ch["span_mm"]
    tol = max(min_tol_mm, tol_ratio * span_mm)

    # 1) 组成环自洽
    if abs(sum(ch["parts"]) - span_mm) > 1e-6:
        issues.append({
            "kind": "radial_closure", "axis": ch["axis"],
            "msg": "径向链组成环不自洽：Σ=%.2f ≠ 跨度 %.2f"
                   % (sum(ch["parts"]), span_mm),
            "severity": "error",
        })

    # 2) 与图纸直径/距离标注交叉验证（按"最接近"配对）
    dia_dims = [d for d in dims
                if d.get("type") in ("diameter", "pattern_dia", "radius")
                and d.get("value_mm") is not None]
    lin_dims = [d for d in dims if d.get("value_mm") is not None
                and d.get("type") == "linear"]
    for m in ch["outer"]:
        # 直径标注
        best, berr = None, None
        for d in dia_dims:
            v = d["value_mm"]
            if d["type"] == "radius":
                v = 2 * v
            e = abs(v - m["d_mm"])
            if berr is None or e < berr:
                berr, best = e, (v, d)
        if best is not None and berr <= max(1.0, 0.02 * best[0]):
            continue                                    # 对得上，没事
        if best is not None and berr <= max(3.0, 0.06 * best[0]):
            issues.append({
                "kind": "radial_vs_dia", "axis": ch["axis"],
                "msg": "外圈圆 ⌀%.1fmm 与最近的直径标注 %s=%.1fmm 差 %.1fmm"
                       % (m["d_mm"], best[1].get("text"), best[0], berr),
                "severity": "warn",
                "err_mm": round(berr, 3),
            })

    # 3) 外缘总跨度 vs 总尺寸标注；链上圆心距 vs 距离标注
    for d in lin_dims:
        s = seg_of_dim(d)
        if not s:
            continue
        seg_mm = s["len"] * mm_per_px
        # 3a) 总尺寸标注 ↔ 链跨度
        if abs(seg_mm - span_mm) <= max(tol, 0.02 * span_mm):
            err = d["value_mm"] - span_mm
            if abs(err) > tol:
                issues.append({
                    "kind": "radial_vs_dim", "axis": ch["axis"],
                    "msg": "总尺寸标注 %s=%.2fmm 与径向链跨度 %.2fmm 不符（差 %+.2fmm）"
                           % (d.get("text"), d["value_mm"], span_mm, err),
                    "severity": "error",
                    "dim_mm": d["value_mm"], "span_mm": span_mm,
                    "err_mm": round(err, 3),
                })
        # 3b) 距离标注 ↔ 链上某个圆心距：用链约束反查「接地位」对不对
        #     标注值本身常与链一致（说明没读错），但接地段量出来的长度偏了
        #     （说明箭头/界线吸附错了位置）—— 这时该信链，不该信那一段墨迹
        for p in ch["parts"]:
            if p < 5.0:
                continue                          # 首尾半径段不是圆心距
            if abs(seg_mm - p) > max(20.0, 0.10 * p):
                continue                          # 这段压根不对应这个圆心距
            err_val = d["value_mm"] - p           # 标注值 vs 链值
            err_seg = seg_mm - p                  # 接地段长 vs 链值
            if abs(err_val) <= tol and abs(err_seg) > max(1.5, 0.02 * p):
                issues.append({
                    "kind": "pitch_vs_dim", "axis": ch["axis"],
                    "msg": "距离标注 %s=%.2fmm 与尺寸链一致（链值 %.2fmm），"
                           "但接地段只量到 %.2fmm（差 %+.2fmm）→ 接地位可疑，"
                           "建议按尺寸链取值"
                           % (d.get("text"), d["value_mm"], p, seg_mm, err_seg),
                    "severity": "warn",
                    "text": d.get("text"),
                    "dim_mm": d["value_mm"], "chain_part_mm": p,
                    "seg_mm": round(seg_mm, 2),
                    "err_mm": round(err_seg, 3),
                })
            elif abs(err_val) > tol:
                issues.append({
                    "kind": "pitch_vs_dim", "axis": ch["axis"],
                    "msg": "距离标注 %s=%.2fmm 与链上圆心距 %.2fmm 不符"
                           "（差 %+.2fmm）"
                           % (d.get("text"), d["value_mm"], p, err_val),
                    "severity": "warn",
                    "text": d.get("text"),
                    "dim_mm": d["value_mm"], "chain_part_mm": p,
                    "err_mm": round(err_val, 3),
                })
            break
    return issues


# ----------------------------------------------------------------------
# 闭合校验
# ----------------------------------------------------------------------
def check_chain(ch, dims, bbox=None, tol_ratio=0.02, min_tol_mm=0.5):
    """
    校验一条链。

    dims : 全部尺寸（用来判断"组成环"—— 跨整链的段不算组成环）
    bbox : {"x": (lo, hi), "y": (lo, hi)} 视图包围盒（像素），作为**隐含封闭环**
    """
    out = []
    segs = ch["segments"]
    n = len(segs)
    tol_mm = max(min_tol_mm, tol_ratio * sum(s["value_mm"] for s in segs))

    # ---- 封闭环候选 ----
    lo, hi = ch["lo"], ch["hi"]
    explicit = [s for s in segs if s["lo"] <= lo + 1e-6 and s["hi"] >= hi - 1e-6]
    implicit = None
    if bbox and ch["axis"] in bbox:
        blo, bhi = bbox[ch["axis"]]
        # 包围盒必须覆盖整条链，才有资格当封闭环
        if blo <= lo + 1e-6 and bhi >= hi - 1e-6:
            implicit = (blo, bhi)

    if len(explicit) > 1:
        vals = [s["value_mm"] for s in explicit]
        if max(vals) - min(vals) > tol_mm:
            out.append({
                "kind": "closure",
                "axis": ch["axis"],
                "msg": "重复的总尺寸互相矛盾：%s"
                       % " vs ".join("%s=%.2f" % (s["text"], s["value_mm"])
                                     for s in explicit),
                "severity": "error",
                "err_mm": round(max(vals) - min(vals), 3),
            })
        else:
            out.append({
                "kind": "over_dim",
                "axis": ch["axis"],
                "msg": "该链有 %d 个尺寸跨整链（%s）：重复约束，加工时只能取一个"
                       % (len(explicit), ch["axis"]),
                "severity": "info",
                "duplicates": [s["text"] for s in explicit],
            })
    elif len(explicit) == 1:
        total = explicit[0]["value_mm"]
        sum_mm = sum(s["value_mm"] for s in segs if s is not explicit[0])
        err = sum_mm - total
        if abs(err) > tol_mm:
            out.append({
                "kind": "closure",
                "axis": ch["axis"], "n_segments": n,
                "msg": "尺寸链不闭合：Σ各段 %.2fmm ≠ 总尺寸 %s=%.2fmm（差 %+.2fmm）"
                       % (sum_mm, explicit[0]["text"], total, err),
                "severity": "error",
                "sum_mm": round(sum_mm, 3), "total_mm": round(total, 3),
                "err_mm": round(err, 3), "tol_mm": round(tol_mm, 3),
            })
    else:
        # 没有显式总尺寸 → 用包围盒当封闭环；连包围盒都没有才报欠标注
        if implicit is not None:
            span_px = implicit[1] - implicit[0]
            sum_mm = sum(s["value_mm"] for s in segs)
            # 段的长度是像素，需要标定换算；用"段长/链跨度"折算成 mm
            scale = (span_px and sum_mm / max(ch["span"], 1e-9)) or 0.0
            total_mm = span_px * scale if scale else span_px
            # 更直接：Σ各段(按标注值) 与 链跨度按同比例缩放后的值比
            total_mm = ch["span"] * (sum_mm / max(ch["span"], 1e-9))
            err = sum_mm - total_mm
            if abs(err) > tol_mm:
                out.append({
                    "kind": "closure",
                    "axis": ch["axis"], "n_segments": n,
                    "msg": "尺寸链不闭合：Σ各段 %.2fmm ≠ 包围盒总尺寸 %.2fmm"
                           "（差 %+.2fmm，图纸未标总尺寸）"
                           % (sum_mm, total_mm, err),
                    "severity": "error",
                    "sum_mm": round(sum_mm, 3), "total_mm": round(total_mm, 3),
                    "err_mm": round(err, 3), "tol_mm": round(tol_mm, 3),
                })
        else:
            out.append({
                "kind": "under_dim",
                "axis": ch["axis"], "n_segments": n,
                "msg": "该链未标总尺寸（%s 向，%d 段）—— 无法加工"
                       % (ch["axis"], n),
                "severity": "warn",
            })

    # ---- 非对称超差 ----
    ss = sorted(segs, key=lambda s: -s["len"])
    for a, b in zip(ss[0::2], ss[1::2]):
        if a is b:
            continue
        d = abs(a["value_mm"] - b["value_mm"])
        if d <= max(tol_mm, 0.05 * max(a["value_mm"], b["value_mm"])):
            continue
        ratio = min(a["value_mm"], b["value_mm"]) / \
            max(a["value_mm"], b["value_mm"], 1e-9)
        if ratio >= 0.6:
            out.append({
                "kind": "asymmetry",
                "axis": ch["axis"],
                "msg": "疑似不对称：%s=%.2fmm 与 %s=%.2fmm（差 %.2fmm）"
                       % (a["text"], a["value_mm"], b["text"], b["value_mm"], d),
                "severity": "warn",
                "err_mm": round(d, 3),
            })
    return out


def check_all(dims, mm_per_px, join_tol=10.0, tol_ratio=0.02, bbox=None,
              circles=None):
    """
    一键：构链 + 逐链校验 + 径向链校验。

    dims    : 已接地尺寸（含 p1/p2/value_mm）
    circles : [{"cx","cy","r_px","r_mm","d_mm"}]（用于径向链）
    bbox    : {"x":(lo,hi),"y":(lo,hi)} 像素坐标的视图包围盒
    返回 (chains, issues)
    """
    chains = build_chains(dims, join_tol)
    issues = []
    for ch in chains:
        for it in check_chain(ch, dims, bbox, tol_ratio):
            it["chain"] = {
                "axis": ch["axis"],
                "span_px": round(ch["span"], 2),
                "segments": [{"text": s["text"], "value_mm": s["value_mm"],
                              "measured_mm": s.get("measured_mm")}
                             for s in ch["segments"]],
            }
            issues.append(it)

    # 径向链（半径/直径与总尺寸的闭合）
    radial = []
    if circles:
        for axis in ("x", "y"):
            for ch in radial_chains(circles, axis, mm_per_px):
                radial.append(ch)
                for it in check_radial(ch, dims, mm_per_px):
                    it["chain"] = {"axis": ch["axis"],
                                   "span_mm": ch["span_mm"],
                                   "parts": ch["parts"]}
                    issues.append(it)
    return chains, issues, radial
