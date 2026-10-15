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
sys.path.insert(0, os.path.join(ROOT, "tools"))

from msgio import run_stage, ref_path, ref_data, exec_module
from facelevels import check_face_levels
from lib.pdf_marks import check_draw_spec, check_pdf_marks


def _marks_kind(in_msg, S):
    """标注 label → kind。优先用 s5 新增的 `marks_kind`，否则读 `_drawing.json`。

    两种情况拿不到（非线框渲染时 `_drawing.json` 可能不存在、s5 是老版本）：
    返回 None，调用方据此跳过 PDF 校验而不是报错。
    """
    k = S.get("marks_kind")
    if k:
        return k
    try:
        p = ref_path(in_msg, "drawing_json_file")
    except Exception:
        return None                      # 可选 ref 缺失时不报错，只放弃这项校验
    if not p or not os.path.exists(p):
        return None
    try:
        import json
        d = json.load(open(p, encoding="utf-8"))
        return {x["label"]: x.get("kind") for x in d.get("dims", [])}
    except Exception:
        return None


def _rp(in_msg, role):
    """取 ref 路径；缺失的可选 ref 会抛异常，这里一律当"没有"（返回 None）。"""
    try:
        return ref_path(in_msg, role)
    except Exception:
        return None


def _check_pdf(in_msg, S, add):
    """图上印的字 vs 模型实测值（遗留 §二-2 修的检测缺口）。两道检查：

    ① 硬编码扫描：draw_spec 里带字面量 `label=` 的标注（不用读 PDF）
    ② PDF 文字核对：把 draw_spec 声明要画的标注到交付 PDF 里逐条核对
    """
    import os as _os
    ds = _rp(in_msg, "draw_spec") or _os.path.join(
        _os.environ.get("MPIPE_HERE", "."), "draw_spec.py")
    meas, hard = check_draw_spec(ds, add)
    if _os.path.exists(ds):
        print("[s6_compare] draw_spec 硬编码扫描：%d 条标注写死了字面量%s"
              % (hard, "" if not hard else "（问题已报）"))

    only = meas if meas else None      # 没有声明就退回「查全部线性尺寸」
    n, bad, state = check_pdf_marks(_rp(in_msg, "drawing_pdf"), S["marks"],
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

    # ---- 端面标高（系统性）：补「geom 只测圆+包围盒、不测面到面距离」的盲区 ----
    check_face_levels(R, ref_path(in_msg, "model_step"), TOL, add)

    # ---- 图上印的字（遗留 §二-2 修的检测缺口）----
    # ① 扫 draw_spec 里有没有硬编码的标注值
    # ② 把 draw_spec 声明要画的标注，到**交付 PDF 的文字层**逐条核对实测值在不在
    #    （之前这里只看 _drawing.json 的值，bracket 的硬编码标注因此一路 pass）
    pdf_state, pdf_n = _check_pdf(in_msg, S, add)

    n_geom = sum(1 for x in iss if x["kind"] == "geom")
    return [], {"issues": iss, "n_geom": n_geom, "n_mark": len(iss) - n_geom,
                "calib": R.CALIB_NOTE, "tol": TOL,
                "pdf_check": pdf_state, "pdf_checked": pdf_n}


if __name__ == "__main__":
    run_stage("s6_compare", handler)
