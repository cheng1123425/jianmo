# -*- coding: utf-8 -*-
r"""s6_compare —— 几何摘要 vs 原图基准，产出差异清单（双耳直角支座）

检查项（与 ref_spec 自洽）：
  - 俯视外接 len_x=200 / len_y=144
  - 主视总高 height_z=120
  - 俯视双耳孔 2-Ø42（r=21，心距 116）+ 中心台阶孔 Ø32(r=16)/Ø54(r=27)
  - 图纸标注 len_x / depth_y / height_z / ear_R / ear_pitch / d_thru / d_cbore ...
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容
sys.path.insert(0, os.path.join(ROOT, "tools"))

from msgio import run_stage, ref_path, ref_data, exec_module
from facelevels import check_face_levels


def handler(in_msg):
    R = exec_module(ref_path(in_msg, "ref_spec"), "ref_spec")
    S = ref_data(in_msg)
    TOL = R.TOL

    iss = []

    def add(kind, name, base, now, action=None, note=""):
        iss.append({"kind": kind, "name": name, "base": base, "cur": now,
                    "dev": None if (base is None or now is None) else now - base,
                    "action": action, "note": note})

    def phi(circles, r):
        return [c for c in circles if abs(c[0] - r) < 0.5]

    # ---- 俯视外接 ----
    if abs(S["len_x_top"] - R.TOP["len_x"]) > TOL:
        add("geom", "俯视外接 X (len_x)", R.TOP["len_x"], S["len_x_top"], None,
            "len_x = 总宽 = 200（= 耳心距 116 + 2×R42）")
    if abs(S["len_y_top"] - R.TOP["len_y"]) > TOL:
        add("geom", "俯视外接 Y (depth_y)", R.TOP["len_y"], S["len_y_top"], None,
            "depth_y = 总深 = 144")

    # ---- 主视总高 ----
    if abs(S["hgt_front"] - R.FRONT["height"]) > TOL:
        add("geom", "主视总高 (height_z)", R.FRONT["height"], S["hgt_front"], None,
            "height_z = 总高 = 120")

    # ---- 俯视耳孔 Ø42（r=21，轴 Z → 2 个圆，心距 = ear_pitch 116）----
    top21 = phi(S["top_circles"], 21.0)
    if len(top21) != 2:
        add("geom", "耳孔 Ø42 圆数 (Top)", 2, len(top21), None,
            "双耳 2-Ø42（轴 Z，俯视显 2 个圆）")
    else:
        dx = top21[0][1] - top21[1][1]
        dy = top21[0][2] - top21[1][2]
        pitch = (dx * dx + dy * dy) ** 0.5
        if abs(pitch - R.TOP["ear_pitch"]) > TOL:
            add("geom", "耳孔心距 (ear_pitch)", R.TOP["ear_pitch"], round(pitch, 1),
                None, "ear_pitch = 116")

    # ---- 俯视中心台阶孔 Ø32(r=16)/Ø54(r=27) ----
    top16 = phi(S["top_circles"], 16.0)
    if len(top16) < 1:
        add("geom", "中心通孔 Ø32 圆数 (Top)", 1, len(top16), None,
            "中心通孔 Φ32（轴 Z，俯视显 1 个圆）")
    top27 = phi(S["top_circles"], 27.0)
    if len(top27) < 1:
        add("geom", "中心沉孔 Ø54 圆数 (Top)", 1, len(top27), None,
            "中心沉孔 Φ54（轴 Z，俯视显 1 个圆）")

    # ---- 图纸标注 ----
    for label, bv in R.MARKS.items():
        cv = S["marks"].get(label)
        if cv is None:
            add("issue", label, bv, None, None, "图纸上缺少该标注")
        elif abs(cv - bv) > TOL:
            add("issue", label, bv, cv, None, "标注值与原图不符")

    # ---- 端面标高（系统性）：补「geom 只测圆+包围盒、不测面到面距离」的盲区 ----
    check_face_levels(R, ref_path(in_msg, "model_step"), TOL, add)

    n_geom = sum(1 for x in iss if x["kind"] == "geom")
    return [], {"issues": iss, "n_geom": n_geom, "n_mark": len(iss) - n_geom,
                "calib": R.CALIB_NOTE, "tol": TOL}


if __name__ == "__main__":
    run_stage("s6_compare", handler)
