# -*- coding: utf-8 -*-
r"""s6_compare —— 几何摘要 vs 原图基准，产出差异清单（铰链支座）"""
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

    # ---- 端面标高（系统性）：补「geom 只测圆+包围盒、不测面到面距离」的盲区 ----
    check_face_levels(R, ref_path(in_msg, "model_step"), TOL, add)

    n_geom = sum(1 for x in iss if x["kind"] == "geom")
    pdf_state, pdf_n = _check_pdf(in_msg, S, add)

    return [], {"issues": iss, "n_geom": n_geom, "n_mark": len(iss) - n_geom,
                "pdf_check": pdf_state, "pdf_checked": pdf_n,
                "calib": R.CALIB_NOTE, "tol": R.TOL}


if __name__ == "__main__":
    run_stage("s6_compare", handler)