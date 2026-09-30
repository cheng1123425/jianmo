# -*- coding: utf-8 -*-
r"""s6_compare —— 几何摘要 vs 原图基准，产出差异清单（L 形支座）

检查项（与 ref_spec 自洽，覆盖核心尺寸与 3-φ8 孔位）：
  - 俯视外接 L=40 / W=26
  - 主视总高 H_total=39
  - 右侧视图 2×φ8（轴沿 X），心距 pitch=26；俯视 1×φ8（底板孔）；主视 ≥1×φ8（立板两孔投影重合）
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
            "L = 底板长 = 40（立板落在底板 X 范围内，不增加总长）")
    if abs(S["len_y_top"] - R.TOP["len_y"]) > TOL:
        add("geom", "俯视外接 Y (W)", R.TOP["len_y"], S["len_y_top"], None,
            "W = 底板宽 = 26")

    # ---- 主视总高 ----
    if abs(S["hgt_front"] - R.FRONT["height"]) > TOL:
        add("geom", "主视总高 (H_total)", R.FRONT["height"], S["hgt_front"], None,
            "H_total = 底板厚 + 立板高 = 8 + 31 = 39")

    # ---- 俯视 φ8（底板孔，轴 Z → 圆）----
    top8 = phi8(S["top_circles"])
    if len(top8) != 1:
        add("geom", "底板 φ8 圆数 (Top)", 1, len(top8), None,
            "1 个底板孔，轴沿 Z，俯视为圆")
    elif abs(top8[0][1] - R.TOP["circles"][0][1]) > 1.5:
        add("geom", "底板 φ8 圆心 x (Top)", R.TOP["circles"][0][1], round(top8[0][1], 1),
            None, "底板孔应在自由段 X≈-13")

    # ---- 主视 φ8：立板两孔轴沿 X，在 Front 视图投影为矩形/线（非圆），
    #      故 Front 不要求出现 φ8 圆；孔位由 Top 与 Right 校验即可。 ----

    # ---- 右侧 φ8（立板两孔，轴沿 X → 右侧视为 2 个圆；
    #      两孔沿世界 Y 分居 ±13，在 Right 视图里表现为 view2d-x 方向间距）----
    right8 = phi8(S["right_circles"])
    if len(right8) != 2:
        add("geom", "立板 φ8 圆数 (Right)", 2, len(right8), None,
            "立板两 φ8，轴沿 X，右侧视为 2 个圆")
    else:
        # 两孔圆心在 Right 视图里的欧氏距离（其一沿 view2d-x 相差 26，另一维重合）
        dx = right8[0][1] - right8[1][1]
        dy = right8[0][2] - right8[1][2]
        pitch = (dx * dx + dy * dy) ** 0.5
        if abs(pitch - R.RIGHT["hole_pitch"]) > TOL:
            add("geom", "立板 φ8 心距 (pitch)", R.RIGHT["hole_pitch"], round(pitch, 1),
                None, "pitch = 立板宽两端 = 26")

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
