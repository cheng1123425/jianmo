# -*- coding: utf-8 -*-
r"""s6_compare —— 几何摘要 vs 原图基准，产出差异清单（铰链支座）"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容

from msgio import run_stage, ref_path, ref_data, exec_module


def handler(in_msg):
    R = exec_module(ref_path(in_msg, "ref_spec"), "ref_spec")
    S = ref_data(in_msg)

    iss = []

    def add(kind, name, base, now, action=None, note=""):
        iss.append({"kind": kind, "name": name, "base": base, "cur": now,
                    "dev": None if (base is None or now is None) else now - base,
                    "action": action, "note": note})

    TOL = R.TOL

    # ---- 俯视外接 ----
    if abs(S["len_x_top"] - R.TOP["len_x"]) > TOL:
        add("geom", "俯视外接 X (底板长)", R.TOP["len_x"], S["len_x_top"],
            None, "底板长 = L（参数）")
    if abs(S["len_y_top"] - R.TOP["len_y"]) > TOL:
        add("geom", "俯视外接 Y (含圆头)", R.TOP["len_y"], S["len_y_top"],
            None, "外接 = -HEAD_Y + END_Y = 12 + 24 = 36…不对，是 46")

    # ---- 主视总高 ----
    if abs(S["hgt_front"] - R.FRONT["height"]) > TOL:
        add("geom", "主视总高 (=HEAD_Z+R_HEAD)", R.FRONT["height"], S["hgt_front"],
            None, "总高 = HEAD_Z + R_HEAD")

    # ---- 侧视外接 ----
    if abs(S["len_x_right"] - R.RIGHT["len_x"]) > TOL:
        add("geom", "侧视外接 X", R.RIGHT["len_x"], S["len_x_right"],
            None, "侧视 X = 圆头最左 + 底板右")

    # ---- 各视图圆 ----
    # Top：期望 2 个 φ9（半径 4.5），每个圆心 x=±22.5, y=12
    cnt9 = sum(1 for c in S["top_circles"] if abs(c[0] - 4.5) < 0.1)
    if cnt9 != 2:
        add("geom", "底板孔 φ9 圆数 (Top)", 2, cnt9, None, "2 个 φ9 孔，轴沿 Z")

    # Front：期望 2 个 φ6 + 2 个 φ3
    cnt6 = sum(1 for c in S["front_circles"] if abs(c[0] - 3.0) < 0.1)
    cnt3 = sum(1 for c in S["front_circles"] if abs(c[0] - 1.5) < 0.1)
    if cnt6 != 2:
        add("geom", "台阶孔 φ6 圆数 (Front)", 2, cnt6, None, "2 个 φ6 沉孔，轴沿 Y")
    if cnt3 != 2:
        add("geom", "台阶孔 φ3 圆数 (Front)", 2, cnt3, None, "2 个 φ3 通孔，轴沿 Y")

    # Right：期望 1 个 R10 + 1 个 φ8
    cntR = sum(1 for c in S["right_circles"] if abs(c[0] - 10.0) < 0.1)
    cnt8 = sum(1 for c in S["right_circles"] if abs(c[0] - 4.0) < 0.1)
    if cntR != 1:
        add("geom", "圆头 R10 圆数 (Right)", 1, cntR, None, "圆头，2 臂重合显示 1")
    if cnt8 != 1:
        add("geom", "销孔 φ8 圆数 (Right)", 1, cnt8, None, "销孔，2 臂重合显示 1")

    # ---- 图纸标注 ----
    for label, bv in R.MARKS.items():
        cv = S["marks"].get(label)
        if cv is None:
            add("issue", label, bv, None, None, "图纸上缺少该标注")
        elif abs(cv - bv) > TOL:
            add("issue", label, bv, cv, None, "标注值与原图不符")

    n_geom = sum(1 for x in iss if x["kind"] == "geom")
    return [], {"issues": iss, "n_geom": n_geom, "n_mark": len(iss) - n_geom,
                "calib": R.CALIB_NOTE, "tol": R.TOL}


if __name__ == "__main__":
    run_stage("s6_compare", handler)