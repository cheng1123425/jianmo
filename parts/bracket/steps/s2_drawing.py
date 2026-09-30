# -*- coding: utf-8 -*-
r"""s2_drawing —— STEP → 工程图（铰链支座，三视图 + 尺寸标注）

视图布局：Top / Front / Right。
标注：12 个尺寸，全部用边关联（getVisibleEdges 的 0-based 下标）或两点距离。
"""
import json
import os
import sys

import FreeCAD as App                          # noqa: F401
import Part                                    # noqa: F401
import TechDraw                                # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))

from msgio import boot, finish, ref_path, ref_data, exec_module   # noqa: E402

IN = boot("s2_drawing")
P = exec_module(ref_path(IN, "params"), "bracket_params")
STEP = ref_path(IN, "model_step")
OUT_DIR = ref_data(IN, "out_dir")
TD = ref_data(IN, "template")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def p(*a):
    print(*a); sys.stdout.flush()


def _y(v):
    """FreeCAD Quantity → float"""
    return float(v)


# ================= 文档 =================
doc = App.newDocument("Bracket")
shape = Part.Shape(); shape.read(STEP)
obj = doc.addObject("Part::Feature", P.TAG); obj.Shape = shape

page = doc.addObject("TechDraw::DrawPage", "Page")
tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
tpl.Template = TD
page.Template = tpl

PLOT = {"Front": 2.0, "Top": 2.0, "Right": 2.0}
views = {}
for nm, d, xd, X, Y in [
    ("Top",   (0, 0, 1),  None,       34, 45),
    ("Front", (0, -1, 0), None,       34, 172),
    ("Right", (1, 0, 0),  (0, 1, 0),  214, 172),
]:
    v = doc.addObject("TechDraw::DrawViewPart", "View" + nm)
    v.Source = [obj]; v.Direction = d
    if xd is not None:
        v.XDirection = xd
    page.addView(v)
    v.X = X; v.Y = Y
    views[nm] = v
doc.recompute()

vt, vf, vr = views["Top"], views["Front"], views["Right"]


# ================= 工具 =================
def visible(view):
    return view.getVisibleEdges()


def first_circle_r(view, r, tol=0.5):
    for k, e in enumerate(visible(view)):
        c = e.Curve
        if "Circle" in c.__class__.__name__ and abs(_y(c.Radius) - r) < tol:
            return k, c
    return None, None


# ================= 标注 =================
dims = []


def _rec(view, kind, X, Y, value, extra):
    d = {"kind": kind, "view": view.Name.replace("View", ""),
         "X": float(X), "Y": float(Y), "value": round(float(value), 4)}
    d.update(extra)
    dims.append(d)


def add_dia(view, r, X, Y, label):
    k, c = first_circle_r(view, r)
    if k is None:
        raise RuntimeError("找不到 r=%.2f -> %s" % (r, label))
    d = doc.addObject("TechDraw::DrawViewDimension", "Dim%d" % len(dims))
    d.Type = "Diameter"; d.References2D = [(view, "Edge%d" % k)]
    page.addView(d); d.X, d.Y = X, Y
    _rec(view, "dia", X, Y, 0, {"r": _y(c.Radius), "cx": _y(c.Center.x),
                                "cy": _y(c.Center.y), "label": label, "_d": d, "_edge": k})


def add_rad(view, r, X, Y, label):
    k, c = first_circle_r(view, r)
    if k is None:
        raise RuntimeError("找不到 r=%.2f -> %s" % (r, label))
    d = doc.addObject("TechDraw::DrawViewDimension", "Dim%d" % len(dims))
    d.Type = "Radius"; d.References2D = [(view, "Edge%d" % k)]
    page.addView(d); d.X, d.Y = X, Y
    _rec(view, "rad", X, Y, 0, {"r": _y(c.Radius), "cx": _y(c.Center.x),
                                "cy": _y(c.Center.y), "label": label, "_d": d, "_edge": k})


def add_distx(view, x1, x2, X, Y, label):
    """用两点做水平距离"""
    v1 = App.Vector(_y(x1), 0, 0); v2 = App.Vector(_y(x2), 0, 0)
    d = TechDraw.makeDistanceDim(view, "DistanceX", v1, v2)
    d.FormatSpec = "%.0f"
    page.addView(d); d.X, d.Y = X, Y
    _rec(view, "distX", X, Y, 0, {"x1": float(x1), "x2": float(x2),
                                  "label": label, "_d": d})


def add_disty(view, y1, y2, X, Y, label):
    """用两点做竖直距离"""
    v1 = App.Vector(0, _y(y1), 0); v2 = App.Vector(0, _y(y2), 0)
    d = TechDraw.makeDistanceDim(view, "DistanceY", v1, v2)
    d.FormatSpec = "%.0f"
    page.addView(d); d.X, d.Y = X, Y
    _rec(view, "distY", X, Y, 0, {"y1": float(y1), "y2": float(y2),
                                  "label": label, "_d": d})


def add_extent(view, direction, X, Y, label):
    d = TechDraw.makeExtentDim(view, [], direction)
    d.FormatSpec = "%.0f"
    page.addView(d); d.X, d.Y = X, Y
    _rec(view, "extentH" if direction == 0 else "extentV", X, Y, 0,
         {"label": label, "_d": d})


# ================= 标注（参数语义名 = label） =================
# ---- Front ----
# 28（两臂外宽 = ARM_XO × 2）
add_distx(vf, -P.ARM_XO, P.ARM_XO, _y(vf.X) + 50, _y(vf.Y) + 5, "arm_outer")
# 16（内距 = ARM_GAP）
add_distx(vf, -P.ARM_XI, P.ARM_XI, _y(vf.X) + 50, _y(vf.Y) + 20, "arm_inner")
# 8（底板厚 = T）
add_disty(vf, 0, P.T, _y(vf.X) - 5, _y(vf.Y) + 15, "T_base")
# 45（底板 2-φ9 孔心距）—— 用底板两 φ9 圆心
add_distx(vf, -P.PITCH9 / 2, P.PITCH9 / 2, _y(vf.X) + 50, _y(vf.Y) - 10, "P9")
# 62（底板总长 = L）
add_extent(vf, 0, _y(vf.X) + 50, _y(vf.Y) - 25, "L")
# 2-φ6 引出（Front 视图里 φ6 沉孔是圆）
k6, _ = first_circle_r(vf, P.D_CB / 2)
if k6 is not None:
    e = visible(vf)[k6]
    c = e.Curve
    add_dia(vf, P.D_CB / 2, _y(vf.X) - 25, _y(vf.Y) - 30, "dia_cbore")
# 2-φ3 引出
k3, _ = first_circle_r(vf, P.D_CS / 2)
if k3 is not None:
    add_dia(vf, P.D_CS / 2, _y(vf.X) + 25, _y(vf.Y) + 30, "dia_thru")

# ---- Right ----
# 27（圆心高）
add_disty(vr, 0, P.HEAD_Z, _y(vr.X) - 5, _y(vr.Y) + 5, "head_h")
# 14（右端总高 = END_Z）
add_disty(vr, 0, P.END_Z, _y(vr.X) - 5, _y(vr.Y) - 5, "arm_h")
# 36（臂水平总长 = END_Y − HEAD_Y = 24 − (−12) = 36）
add_distx(vr, P.HEAD_Y, P.END_Y, _y(vr.X) + 50, _y(vr.Y) - 8, "arm_len")
# 46（侧视外接 = END_Y − HEAD_Y + R_HEAD = 36 + 10 = 46；用 extent 取更稳）
add_extent(vr, 0, _y(vr.X) + 50, _y(vr.Y) - 25, "W")
# R10 圆头
add_rad(vr, P.R_HEAD, _y(vr.X) - 50, _y(vr.Y) + 5, "R_head")
# 2-φ8 销孔
add_dia(vr, P.D_PIN / 2, _y(vr.X) + 30, _y(vr.Y) - 30, "dia_pin")

# ---- Top ----
# 2-φ9 引出（Top 视图里 φ9 孔是圆）
add_dia(vt, P.D_9 / 2, _y(vt.X) + 35, _y(vt.Y) + 10, "D9")

doc.recompute()

p("[dims] FreeCAD 计算值：")
for rec in dims:
    dv = rec.pop("_d")
    rec["value"] = round(float(dv.getRawValue()), 4)
    p("   %-6s Edge%-4s -> %8.2f      %s"
      % (rec["kind"], rec.get("_edge", "-"), rec["value"], rec["label"]))
for rec in dims:
    for k in ("_edge", "_e1", "_e2"):
        rec.pop(k, None)


# ================= 导出 =================
def edges_json(view, n=64):
    out = []
    for e in view.getVisibleEdges():
        f0, f1 = e.FirstParameter, e.LastParameter
        out.append([[_y(e.valueAt(f0 + (f1 - f0) * i / n).x),
                     _y(e.valueAt(f0 + (f1 - f0) * i / n).y)] for i in range(n + 1)])
    return out


def circles_json(view):
    out = []
    for k, e in enumerate(view.getVisibleEdges()):
        c = e.Curve
        if "Circle" in c.__class__.__name__:
            out.append({"i": k, "r": round(_y(c.Radius), 3),
                        "cx": round(_y(c.Center.x), 3), "cy": round(_y(c.Center.y), 3)})
    return out


def hlines_json(view):
    out = []
    for k, e in enumerate(view.getVisibleEdges()):
        if "Circle" in e.Curve.__class__.__name__:
            continue
        f0, f1 = e.FirstParameter, e.LastParameter
        a = e.valueAt(f0); b = e.valueAt(f1); m = e.valueAt((f0 + f1) / 2.0)
        if abs(_y(a.y) - _y(b.y)) < 1e-6 and abs(_y(m.y) - _y(a.y)) < 1e-6:
            out.append({"i": k, "y": round(_y(a.y), 3),
                        "x0": round(min(_y(a.x), _y(b.x)), 3), "x1": round(max(_y(a.x), _y(b.x)), 3)})
    return out


data = {
    "views": [{"name": nm, "X": float(v.X), "Y": float(v.Y), "plot_scale": PLOT[nm],
               "edges": edges_json(v), "circles": circles_json(v), "hlines": hlines_json(v)}
              for nm, v in views.items()],
    "dims": dims,
}
jf = os.path.join(OUT_DIR, "_drawing.json")
json.dump(data, open(jf, "w", encoding="utf-8"), ensure_ascii=False)

fc = os.path.join(OUT_DIR, P.TAG + ".FCStd")
doc.saveAs(fc)

finish([("drawing_json", jf), ("fcstd", fc)], {
    "views": [v["name"] for v in data["views"]],
    "n_edges": sum(len(v["edges"]) for v in data["views"]),
    "n_circles": sum(len(v["circles"]) for v in data["views"]),
    "n_dims": len(data["dims"]),
    "dim_values": {d["label"]: d["value"] for d in data["dims"]},
})