# -*- coding: utf-8 -*-
r"""s6_compare —— 几何摘要 vs 原图基准，产出差异清单（L 形支座 · 第 2 版）

检查项（与 ref_spec 自洽）：
  - 俯视外接 L=56 / W=40
  - 主视总高 H_total=39
  - 俯视 3×φ8（底板孔，轴 Z → 圆）；右视 2×φ8（立板销孔，轴 X → 圆，心距 26）
  - 图纸标注 L / W / H_total / pitch
"""
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
    TOL = R.TOL

    iss = []

    def add(kind, name, base, now, action=None, note=""):
        iss.append({"kind": kind, "name": name, "base": base, "cur": now,
                    "dev": None if (base is None or now is None) else now - base,
                    "action": action, "note": note})

    def phi8(circles):
        return [c for c in circles if abs(c[0] - 4.0) < 0.3]

    # ---- 俯视外接 ----
    if abs(S["len_x_top"] - R.TOP["len_x"]) > TOL:
        add("geom", "俯视外接 X (L)", R.TOP["len_x"], S["len_x_top"], None,
            "L = 底板长 = 56")
    if abs(S["len_y_top"] - R.TOP["len_y"]) > TOL:
        add("geom", "俯视外接 Y (W)", R.TOP["len_y"], S["len_y_top"], None,
            "W = 底板最大宽 = 40")

    # ---- 主视总高 ----
    if abs(S["hgt_front"] - R.FRONT["height"]) > TOL:
        add("geom", "主视总高 (H_total)", R.FRONT["height"], S["hgt_front"], None,
            "H_total = 底板厚 + 立板高 = 8 + 31 = 39")

    # ---- 俯视 φ8（底板孔，轴 Z → 圆）----
    # 注：立板为曲面顶（双耳），其销孔在 TechDraw 俯视里也会投出圆/弧，
    #     故此处只校验"底板 3 孔存在"（>=3），不要求恰好等于 3。
    top8 = phi8(S["top_circles"])
    if len(top8) < 3:
        add("geom", "底板 φ8 圆数 (Top)", 3, len(top8), None,
            "底板应有 3 个 φ8 孔（轴沿 Z，俯视为圆）")

    # ---- 右视 φ8（立板销孔，轴 X → 2 个圆，心距 = pitch）----
    right8 = phi8(S["right_circles"])
    if len(right8) != 2:
        add("geom", "立板 φ8 圆数 (Right)", 2, len(right8), None,
            "立板两 φ8，轴沿 X，右视显 2 个圆")
    else:
        dx = right8[0][1] - right8[1][1]
        dy = right8[0][2] - right8[1][2]
        pitch = (dx * dx + dy * dy) ** 0.5
        if abs(pitch - R.RIGHT["hole_pitch"]) > TOL:
            add("geom", "立板 φ8 心距 (pitch)", R.RIGHT["hole_pitch"], round(pitch, 1),
                None, "pitch = 26")

    # ---- 图纸标注 ----
    for label, bv in R.MARKS.items():
        cv = S["marks"].get(label)
        if cv is None:
            add("issue", label, bv, None, None, "图纸上缺少该标注")
        elif abs(cv - bv) > TOL:
            add("issue", label, bv, cv, None, "标注值与原图不符")

    n_geom = sum(1 for x in iss if x["kind"] == "geom")
    return [], {"issues": iss, "n_geom": n_geom, "n_mark": len(iss) - n_geom,
                "calib": R.CALIB_NOTE, "tol": TOL}


if __name__ == "__main__":
    run_stage("s6_compare", handler)
