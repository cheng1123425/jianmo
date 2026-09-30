# -*- coding: utf-8 -*-
r"""s6_compare —— 当前投影 vs 原图基准，产出差异清单（只判定，不修改任何东西）

入参 refs: ref_spec（原图基准，人的输入）
入参 data: s5 的几何摘要
产出 data: issues（每项含 kind/name/base/cur/dev/action/note）
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msgio import run_stage, ref_path, ref_data, exec_module    # noqa: E402


def group(circles):
    """按圆心是否在轴上，分成中心组 / 侧组"""
    cen = sorted([c for c in circles if abs(c[1]) < 1.0], key=lambda c: -c[0])
    side = sorted([c for c in circles if abs(c[1]) >= 1.0], key=lambda c: -c[0])
    return cen, side


def roles_for(bases, cen=True):
    """按半径降序给组内每个圆定角色"""
    names = ["OD_center_arc", "OD_boss", "ID_center"] if cen else ["OD_wing", "ID_side"]
    order = sorted(range(len(bases)), key=lambda i: -bases[i][0])
    out = [None] * len(bases)
    for rank, i in enumerate(order):
        out[i] = names[rank] if rank < len(names) else None
    return out


def best_match(bases, curs):
    """组内一对一最优配对（数量少，暴力枚举；避免半径接近时贪心误配）"""
    n = min(len(bases), len(curs))
    if n == 0:
        return [], len(bases), len(curs)
    best, bc = None, None
    for perm in itertools.permutations(range(len(curs)), n):
        cost = sum(abs(curs[perm[i]][0] - bases[i][0])
                   + abs(curs[perm[i]][1] - bases[i][1])
                   + abs(curs[perm[i]][2] - bases[i][2]) for i in range(n))
        if bc is None or cost < bc:
            bc, best = cost, perm
    return [(bases[i], curs[best[i]]) for i in range(n)], len(bases) - n, len(curs) - n


ROLE2PARAM = {
    "OD_center_arc": ("R_OUT_CEN",   1, "中心外弧"),
    "OD_boss":       ("R_BOSS",      1, "中心凸台"),
    "ID_center":     ("D_HOLE_CEN",  2, "中心通孔"),
    "OD_wing":       ("R_SIDE",      1, "侧凸台"),
    "ID_side":       ("D_HOLE_SIDE", 2, "侧通孔"),
}


def handler(in_msg):
    R = exec_module(ref_path(in_msg, "ref_spec"), "ref_spec")
    S = ref_data(in_msg)

    # ---- 基准反推出的参数值（修正建议直接用这些，不从当前值反解）----
    _cen, _side = group(R.TOP["circles"])
    _z = R.FRONT["z_levels"]
    BP = {
        "R_OUT_CEN":   _cen[0][0],
        "R_BOSS":      _cen[1][0],
        "D_HOLE_CEN":  2 * _cen[2][0],
        "R_SIDE":      _side[0][0],
        "D_HOLE_SIDE": 2 * _side[-1][0],
        "D_SIDE":      abs(_side[0][1]),
        "R_NECK":      R.TOP["neck_R"],
        "BASE_T":      _z[1] - _z[0],
        "H_WING":      _z[2] - _z[1],
        "H_CEN":       _z[3] - _z[1],
    }
    blx, bly, bh = R.TOP["len_x"], R.TOP["len_y"], R.FRONT["height"]

    iss = []

    def add(kind, name, base, now, action=None, note=""):
        iss.append({"kind": kind, "name": name, "base": base, "cur": now,
                    "dev": None if (base is None or now is None) else now - base,
                    "action": action, "note": note})

    # ---- 俯视外接 ----
    if abs(S["len_x"] - blx) > R.TOL:
        add("geom", "外接总长", blx, S["len_x"],
            ("D_SIDE", blx / 2.0 - BP["R_SIDE"]), "总长 = 2×(D_SIDE + R_SIDE)")
    if abs(S["len_y"] - bly) > R.TOL:
        add("geom", "外接总宽", bly, S["len_y"], ("R_OUT_CEN", BP["R_OUT_CEN"]),
            "总宽 = 2×R_OUT_CEN")

    # ---- 俯视各组圆（凹颈弧不参与配对）----
    cur_circ = [c for c in S["top_circles"] if abs(c[0] - R.TOP["neck_R"]) > 1.0]
    b_cen, b_side = group(R.TOP["circles"])
    c_cen, c_side = group(cur_circ)
    for bases, curs, is_cen in ((b_cen, c_cen, True), (b_side, c_side, False)):
        pairs, miss_b, miss_c = best_match(bases, curs)
        names = roles_for(bases, is_cen)
        if miss_b or miss_c:
            add("geom", "%s组圆数量" % ("中心" if is_cen else "侧"), len(bases), len(curs), None,
                "圆数不符 → 配对不可靠，跳过该组半径比对（特征缺失/多余，或两个特征尺寸刚好重合）")
            continue
        for i, (b, c) in enumerate(pairs):
            role = names[i]
            if role is None:
                continue
            pname, k, label = ROLE2PARAM[role]
            if abs(c[0] - b[0]) > R.TOL:
                add("geom", "%s 半径" % label, b[0], c[0], (pname, BP[pname]),
                    "直径标注 %.0f，应为 φ%.0f" % (2 * b[0], 2 * BP[pname] / k))
            if abs(c[1] - b[1]) > R.TOL:
                add("geom", "%s 圆心 x" % label, b[1], c[1], ("D_SIDE", BP["D_SIDE"]),
                    "特征中心位置 = D_SIDE")

    # ---- 凹颈 ----
    neck = [r for r in S["all_radii"] if abs(r - R.TOP["neck_R"]) < 1.0]
    if not neck:
        add("geom", "凹颈 R", R.TOP["neck_R"], None, ("R_NECK", BP["R_NECK"]),
            "投影里没有该半径的弧")
    elif abs(neck[0] - R.TOP["neck_R"]) > R.TOL:
        add("geom", "凹颈 R", R.TOP["neck_R"], neck[0], ("R_NECK", BP["R_NECK"]))

    # ---- 前视高度 ----
    if abs(S["height"] - bh) > R.TOL:
        add("geom", "总高", bh, S["height"], ("H_CEN", BP["H_CEN"]), "总高 = BASE_T + H_CEN")
    if len(S["steps"]) == 3:
        rule = [("BASE_T", "底板厚"), ("H_WING", "侧凸台高出底板"), ("H_CEN", "中心凸台高出底板")]
        base_steps = [_z[1] - _z[0], _z[2] - _z[1], _z[3] - _z[2]]
        for i, (bs, cs) in enumerate(zip(base_steps, S["steps"])):
            if abs(cs - bs) > R.TOL:
                pn, cn = rule[i]
                add("geom", cn, bs, cs, (pn, BP[pn]), "相邻高度层之差")
    elif S["steps"]:
        add("geom", "高度层数量", 3, len(S["steps"]), None, "投影里的水平层数与基准不符")

    if S["boss_w"] is not None and abs(S["boss_w"] - R.FRONT["boss_width"]) > R.TOL:
        add("geom", "中心凸起宽度", R.FRONT["boss_width"], S["boss_w"],
            ("R_BOSS", BP["R_BOSS"]), "中心凸台直径 = 该宽度")

    # ---- 图纸标注值 ----
    for label, bv in R.MARKS.items():
        cv = S["marks"].get(label)
        if cv is None:
            add("mark", label, bv, None, None, "图纸上缺少这个标注")
        elif abs(cv - bv) > R.TOL:
            add("mark", label, bv, cv, None, "标注值与原图不符（形状对但标注错？）")

    n_geom = sum(1 for x in iss if x["kind"] == "geom")
    return [], {"issues": iss, "n_geom": n_geom, "n_mark": len(iss) - n_geom,
                "calib": R.CALIB_NOTE, "tol": R.TOL}


if __name__ == "__main__":
    run_stage("s6_compare", handler)
