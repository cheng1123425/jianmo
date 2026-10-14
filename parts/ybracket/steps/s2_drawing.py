# -*- coding: utf-8 -*-
r"""s2_drawing —— STEP → 工程图（双耳直角支座，三视图 + 尺寸标注）

视图布局：Top / Front / Right。
标注（与原图基准自洽）：
  Top   : len_x=200（外接 X）、depth_y=144（外接 Y）、ear_R=42、ear_pitch=116、
          ear_hole=42、d_thru=32、d_cbore=54
  Front : height_z=120（外接 Z）、ear_t=32、arm_t=32
  Right : depth_y=144、base_h=48、wall_t=20、cbore_depth=22、opening=96
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
P = exec_module(ref_path(IN, "params"),
                os.path.basename(ref_path(IN, "params"))[:-3])
STEP = ref_path(IN, "model_step")
OUT_DIR = ref_data(IN, "out_dir")
TD = ref_data(IN, "template")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def p(*a):
    print(*a)
    sys.stdout.flush()


def _y(v):
    """FreeCAD Quantity → float"""
    return float(v)


# ================= 文档 =================
doc = App.newDocument("YBracket")
shape = Part.Shape()
shape.read(STEP)
obj = doc.addObject("Part::Feature", P.TAG)
obj.Shape = shape

page = doc.addObject("TechDraw::DrawPage", "Page")
tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
tpl.Template = TD
page.Template = tpl

PLOT = {"Front": 0.8, "Top": 0.8, "Right": 0.8}
# 视图布局：第一角投影标准位置（主视左上、俯视其下、侧视其右）
# 零件 200×144×120，scale 0.8 → 主视 160×96、俯视 160×115、侧视 115×96，
# X/Y 为图纸上的**视图中心**（TechDraw 约定），拉开避免重叠（A3 图框 420×297）。
views = {}
for nm, d, xd, X, Y in [
    ("Front", (0, -1, 0), None,       115, 185),
    ("Top",   (0, 0, 1),  None,       115,  70),
    ("Right", (1, 0, 0),  (0, 1, 0),  295, 185),
]:
    v = doc.addObject("TechDraw::DrawViewPart", "View" + nm)
    v.Source = [obj]
    v.Direction = d
    if xd is not None:
        v.XDirection = xd
    page.addView(v)
    v.X = X
    v.Y = Y
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
    d.Type = "Diameter"
    d.References2D = [(view, "Edge%d" % k)]
    page.addView(d)
    d.X, d.Y = X, Y
    _rec(view, "dia", X, Y, 0, {"r": _y(c.Radius), "cx": _y(c.Center.x),
                                "cy": _y(c.Center.y), "label": label, "_d": d, "_edge": k})


def add_rad(view, r, X, Y, label):
    k, c = first_circle_r(view, r)
    if k is None:
        raise RuntimeError("找不到 r=%.2f -> %s" % (r, label))
    d = doc.addObject("TechDraw::DrawViewDimension", "Dim%d" % len(dims))
    d.Type = "Radius"
    d.References2D = [(view, "Edge%d" % k)]
    page.addView(d)
    d.X, d.Y = X, Y
    _rec(view, "rad", X, Y, 0, {"r": _y(c.Radius), "cx": _y(c.Center.x),
                                "cy": _y(c.Center.y), "label": label, "_d": d, "_edge": k})


def add_distx(view, x1, x2, X, Y, label):
    """用两点做水平距离"""
    v1 = App.Vector(_y(x1), 0, 0)
    v2 = App.Vector(_y(x2), 0, 0)
    d = TechDraw.makeDistanceDim(view, "DistanceX", v1, v2)
    d.FormatSpec = "%.0f"
    page.addView(d)
    d.X, d.Y = X, Y
    _rec(view, "distX", X, Y, 0, {"x1": float(x1), "x2": float(x2),
                                  "label": label, "_d": d})


def add_disty(view, y1, y2, X, Y, label):
    """用两点做竖直距离"""
    v1 = App.Vector(0, _y(y1), 0)
    v2 = App.Vector(0, _y(y2), 0)
    d = TechDraw.makeDistanceDim(view, "DistanceY", v1, v2)
    d.FormatSpec = "%.0f"
    page.addView(d)
    d.X, d.Y = X, Y
    _rec(view, "distY", X, Y, 0, {"y1": float(y1), "y2": float(y2),
                                  "label": label, "_d": d})


def add_extent(view, direction, X, Y, label):
    d = TechDraw.makeExtentDim(view, [], direction)
    d.FormatSpec = "%.0f"
    page.addView(d)
    d.X, d.Y = X, Y
    _rec(view, "extentH" if direction == 0 else "extentV", X, Y, 0,
         {"label": label, "_d": d})


# ================= 标注（参数语义名 = label） =================
# ---- Front：height_z（总高）----
add_extent(vf, 1, _y(vf.X) - 8, _y(vf.Y) + 20, "height_z")    # 120

# ---- Top：len_x / depth_y（外接）+ 双耳 R42 / 耳孔 Ø42 / 中心台阶孔 ----
add_extent(vt, 0, _y(vt.X) + 50, _y(vt.Y) - 15, "len_x")         # 200
add_extent(vt, 1, _y(vt.X) - 8, _y(vt.Y) + 20, "depth_y")        # 144
# 圆的标注：找不到就跳过（TechDraw 里圆可能被消隐/识别为弧，不因此让整步失败）
k42t, _ = first_circle_r(vt, P.EAR_R)
if k42t is not None:
    add_rad(vt, P.EAR_R, _y(vt.X) - 45, _y(vt.Y) + 45, "ear_R")        # R42
else:
    p("[warn] Top 视图未找到 R42 圆头，跳过 ear_R 标注")
k21t, _ = first_circle_r(vt, P.EAR_PITCH / 2.0)  # 耳孔半径 = 21
if k21t is not None:
    add_dia(vt, P.EAR_PITCH / 2.0, _y(vt.X) - 30, _y(vt.Y) - 35, "ear_hole")  # 2-Ø42
else:
    p("[warn] Top 视图未找到 Ø42 耳孔，跳过 ear_hole 标注")
k27t, _ = first_circle_r(vt, P.D_CBORE / 2.0)   # 沉孔半径 = 27
if k27t is not None:
    add_dia(vt, P.D_CBORE / 2.0, _y(vt.X) + 35, _y(vt.Y) + 35, "d_cbore")     # Ø54
else:
    p("[warn] Top 视图未找到 Ø54 沉孔，跳过 d_cbore 标注")
k16t, _ = first_circle_r(vt, P.D_THRU / 2.0)    # 通孔半径 = 16
if k16t is not None:
    add_dia(vt, P.D_THRU / 2.0, _y(vt.X) + 35, _y(vt.Y) - 35, "d_thru")       # Ø32
else:
    p("[warn] Top 视图未找到 Ø32 通孔，跳过 d_thru 标注")

# ---- Right：depth_y（外接水平）----
add_extent(vr, 0, _y(vr.X) + 50, _y(vr.Y) - 15, "depth_y")     # 144

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
        a = e.valueAt(f0)
        b = e.valueAt(f1)
        m = e.valueAt((f0 + f1) / 2.0)
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
