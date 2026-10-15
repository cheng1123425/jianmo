# -*- coding: utf-8 -*-
r"""s6_compare（共享层 · ref_spec 驱动）—— 几何摘要 vs 基准，产出差异清单

**它让「新增零件不写 Python」成立**：检查项不再写死在零件里，而是**从
`parts/<name>/ref_spec.py` 的数据声明推出来**（`TOP` / `FRONT` / `RIGHT` /
`FACE_LEVELS` / `MARKS`），所以任何零件都用同一份代码。

**回落规则**：零件自带 `steps/s6_compare.py` → 用自带的（老零件/特殊检查）；
没自带 → 落到本共享实现。

检查项（按 ref_spec 声明，缺哪项跳过哪项）：
  - `R.TOP.len_x / len_y`  ↔ `S.len_x_top / len_y_top`
  - `R.FRONT.height`       ↔ `S.hgt_front`
  - `R.RIGHT.hole_pitch`   ↔ `S.right_circles` 两个同径圆的心距（可选 `R.RIGHT.hole_d`）
  - `R.MARKS`              ↔ `S.marks`（图上标注值）
  - `R.FACE_LEVELS`        ↔ 模型平面端面标高（子集语义）
  - PDF 图面文字（遗留 §二-2 修的检测缺口）

入参消息  refs: ref_spec / model_step / draw_spec / drawing_json_file / drawing_pdf
          data: s5_collect 的 S
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from msgio import run_stage, ref_path, ref_data, exec_module            # noqa: E402
from facelevels import check_face_levels                                # noqa: E402
from lib.pdf_marks import check_draw_spec, check_pdf_marks               # noqa: E402


def _rp(in_msg, role):
    try:
        return ref_path(in_msg, role)
    except Exception:
        return None


def _marks_kind(in_msg, S):
    k = S.get("marks_kind")
    if k:
        return k
    p = _rp(in_msg, "drawing_json_file")
    if not p or not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
        return {x["label"]: x.get("kind") for x in d.get("dims", [])}
    except Exception:
        return None


def _check_pdf(in_msg, S, add):
    """图上印的字 vs 模型实测值（遗留 §二-2）。两道：① 硬编码扫描 ② PDF 文字核对。"""
    ds = _rp(in_msg, "draw_spec") or os.path.join(
        os.environ.get("MPIPE_HERE", "."), "draw_spec.py")
    meas, hard = check_draw_spec(ds, add)
    if os.path.exists(ds):
        print("[s6_compare] draw_spec 硬编码扫描：%d 条标注写死了字面量%s"
              % (hard, "" if not hard else "（问题已报）"))
    only = meas if meas else None
    n, bad, state = check_pdf_marks(_rp(in_msg, "drawing_pdf"), S.get("marks", {}),
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
    TOL = getattr(R, "TOL", 0.5)

    iss = []

    def add(kind, name, base, now, action=None, note=""):
        iss.append({"kind": kind, "name": name, "base": base, "cur": now,
                    "dev": None if (base is None or now is None) else now - base,
                    "action": action, "note": note})

    def cmp(name, base, now, note=""):
        if base is None or now is None:
            return
        if abs(now - base) > TOL:
            add("geom", name, base, now, None, note)

    TOP = getattr(R, "TOP", {}) or {}
    FRONT = getattr(R, "FRONT", {}) or {}
    RIGHT = getattr(R, "RIGHT", {}) or {}

    # ---- 俯视外接 / 主视总高（按 ref_spec 声明，缺则跳过）----
    cmp("俯视外接 X (L)", TOP.get("len_x"), S.get("len_x_top"))
    cmp("俯视外接 Y (W)", TOP.get("len_y"), S.get("len_y_top"))
    cmp("主视总高 (H_total)", FRONT.get("height"), S.get("hgt_front"))

    # ---- 同径孔心距（可选声明）----
    r = RIGHT.get("hole_d", 4.0) / 2.0
    if RIGHT.get("hole_pitch") is not None:
        same = [c for c in (S.get("right_circles") or []) if abs(c[0] - r) < 0.3]
        if len(same) != 2:
            add("geom", "右视同径圆数", 2, len(same), None, "声明了 hole_pitch 但右视不是 2 个同径圆")
        else:
            dx = same[0][1] - same[1][1]
            dy = same[0][2] - same[1][2]
            cmp("右视孔心距 (pitch)", RIGHT["hole_pitch"], round((dx * dx + dy * dy) ** 0.5, 1))

    # ---- 图纸标注 ----
    marks_now = S.get("marks") or {}
    for label, bv in (getattr(R, "MARKS", {}) or {}).items():
        cv = marks_now.get(label)
        if cv is None:
            add("issue", label, bv, None, None, "图纸上缺少该标注")
        elif abs(cv - bv) > TOL:
            add("issue", label, bv, cv, None, "标注值与原图不符")

    # ---- 端面标高（补「只测圆+包围盒」的盲区）----
    ms = _rp(in_msg, "model_step")
    if ms and os.path.exists(ms):
        check_face_levels(R, ms, TOL, add)

    # ---- 图上印的字 ----
    pdf_state, pdf_n = _check_pdf(in_msg, S, add)

    n_geom = sum(1 for x in iss if x["kind"] == "geom")
    return [], {"issues": iss, "n_geom": n_geom, "n_mark": len(iss) - n_geom,
                "calib": getattr(R, "CALIB_NOTE", ""), "tol": TOL,
                "pdf_check": pdf_state, "pdf_checked": pdf_n}


if __name__ == "__main__":
    run_stage("s6_compare", handler)
