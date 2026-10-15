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
from lib.pdf_marks import check_draw_spec, check_pdf_marks


def _marks_kind(in_msg, S):
    """标注 label → kind。优先用 s5 新增的 `marks_kind`，否则读 `_drawing.json`。

    拿不到时返回 None，调用方据此跳过 PDF 核对而不是报错。
    """
    k = S.get("marks_kind")
    if k:
        return k
    try:
        p = ref_path(in_msg, "drawing_json_file")
    except Exception:
        return None
    if not p or not os.path.exists(p):
        return None
    try:
        import json
        d = json.load(open(p, encoding="utf-8"))
        return {x["label"]: x.get("kind") for x in d.get("dims", [])}
    except Exception:
        return None


def _check_pdf(in_msg, S, add):
    """图上印的字 vs 模型实测值（遗留 §二-2 修的检测缺口）。两道检查：

    ① 硬编码扫描：draw_spec 里带字面量 `label=` 的标注（不用读 PDF）
    ② PDF 文字核对：把 draw_spec 声明要画的标注到交付 PDF 里逐条核对
    """
    import os as _os

    def _rp(role):
        """取 ref 路径；缺失的可选 ref 会抛异常，这里一律当"没有"（返回 None）。

        gasket 没有 draw_spec.py（它的出图是独立的老实现），bracket/lbracket/
        ybracket 有 —— 所以这一步必须容错，不能让整个s6 挂掉。
        """
        try:
            return ref_path(in_msg, role)
        except Exception:
            return None

    ds = _rp("draw_spec") or _os.path.join(
        _os.environ.get("MPIPE_HERE", "."), "draw_spec.py")
    meas, hard = check_draw_spec(ds, add)
    if _os.path.exists(ds):
        print("[s6_compare] draw_spec 硬编码扫描：%d 条标注写死了字面量%s"
              % (hard, "" if not hard else "（问题已报）"))

    only = meas if meas else None      # 没有声明就退回「查全部线性尺寸」
    n, bad, state = check_pdf_marks(_rp("drawing_pdf"), S["marks"],
                                    _marks_kind(in_msg, S), add, only=only)
    if state == "skipped":
        print("[s6_compare] PDF 文字核对跳过（pypdf 未安装或 PDF 不可读）")
    else:
        print("[s6_compare] PDF 文字核对：%d 条标注，%s"
              % (n, "全部一致" if state == "ok" else "%d 条对不上" % bad))
    return state, n



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
    pdf_state, pdf_n = _check_pdf(in_msg, S, add)

    return [], {"issues": iss, "n_geom": n_geom, "n_mark": len(iss) - n_geom,
                "pdf_check": pdf_state, "pdf_checked": pdf_n,
                "calib": R.CALIB_NOTE, "tol": TOL}


if __name__ == "__main__":
    run_stage("s6_compare", handler)
