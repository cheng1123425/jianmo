# -*- coding: utf-8 -*-
r"""
【第 2 段 / FreeCAD TechDraw 出图（无界面）】
=============================================
- 三视图 DrawViewPart：主视 / 俯视 / 轴测（对 STEP 实体做 HLR 投影）
- **所有尺寸都用 References2D 关联到视图边**（"EdgeN" 用 0-based 可见边下标！）
  改三维 → recompute → 尺寸自动跟随
- 圆心距（200）无法用边引用表达，改用「从实体派生的坐标」——同样随模型刷新
- 每个尺寸的显示值取 FreeCAD 的 getRawValue()，写入 _td_data.json
- 存 gasket_fixture.FCStd
"""
import json
import math
import os
import sys

import FreeCAD as App
import Part
import TechDraw

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import params as P

STEP = os.path.join(P.STEP_DIR, P.TAG + ".step")
TD = "D:/3d/\u65b0\u5efa\u6587\u4ef6\u5939/FreeCAD 1.1/data/Mod/TechDraw/Templates/ISO/A3_Landscape_TD.svg"
PLOT = {"Front": 0.25, "Top": 0.25, "Iso": 0.20}


try:                       # freecadcmd 默认按 GBK 输出，中文会乱码
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def p(*a):
    print(*a); sys.stdout.flush()


# ================= 建模文档 =================
doc = App.newDocument("GasketFixture")
shape = Part.Shape(); shape.read(STEP)
obj = doc.addObject("Part::Feature", P.TAG); obj.Shape = shape

page = doc.addObject("TechDraw::DrawPage", "Page")
tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
tpl.Template = TD
page.Template = tpl

views = {}
for nm, dd, xd, X, Y in [
    ("Front", (0, -1, 0), None,       115, 228),
    ("Top",   (0, 0, 1),  None,       115, 100),
    ("Iso",   (1, -1, 1), (1, 1, 0),  315, 150),
]:
    v = doc.addObject("TechDraw::DrawViewPart", "View" + nm)
    v.Source = [obj]; v.Direction = dd
    if xd is not None:
        v.XDirection = xd          # 只给轴测图指定，主/俯视用默认（否则 Z 轴会翻转）
    page.addView(v)
    v.X = X; v.Y = Y               # addView 之后设位置，否则被页面居中覆盖
    views[nm] = v
doc.recompute()

vt, vf = views["Top"], views["Front"]


# ================= 边查找（返回 0-based 下标 = "EdgeN"） =================
def visible(view):
    return view.getVisibleEdges()


def find_circle(view, r, cx=None, cy=None, tol=0.5):
    """按半径/圆心找可见圆边"""
    for k, e in enumerate(visible(view)):
        c = e.Curve
        if "Circle" not in c.__class__.__name__:
            continue
        if abs(c.Radius - r) > tol:
            continue
        if cx is not None and abs(c.Center.x - cx) > tol:
            continue
        if cy is not None and abs(c.Center.y - cy) > tol:
            continue
        return k, c
    return None, None


def find_hline(view, y, tol=0.5):
    """找水平线（两端 y 相同），返回最长的那条：(下标, (x_lo, x_hi))"""
    best = None
    for k, e in enumerate(visible(view)):
        c = e.Curve
        if "Circle" in c.__class__.__name__:
            continue
        a = e.valueAt(e.FirstParameter); b = e.valueAt(e.LastParameter)
        if abs(a.y - y) > tol or abs(b.y - y) > tol:
            continue
        ln = abs(a.x - b.x)
        if best is None or ln > best[2]:
            best = (k, (min(a.x, b.x), max(a.x, b.x)), ln)
    if best is None:
        p("[dbg] find_hline y=%.2f 失败；Front 可见边端点：")
        for k, e in enumerate(visible(view)):
            a = e.valueAt(e.FirstParameter); b = e.valueAt(e.LastParameter)
            p("   [%2d] (%8.2f,%8.2f) -> (%8.2f,%8.2f)" % (k, a.x, a.y, b.x, b.y))
    return (best[0], best[1]) if best else (None, None)


def view_bb(view, n=16):
    """视图可见边的包围盒（2D）"""
    xs, ys = [], []
    for e in visible(view):
        f0, f1 = e.FirstParameter, e.LastParameter
        for i in range(n + 1):
            q = e.valueAt(f0 + (f1 - f0) * i / n)
            xs.append(q.x); ys.append(q.y)
    return min(xs), max(xs), min(ys), max(ys)


def boss_top_y(view):
    """中心凸台顶面投影线（水平、长度≈2*R_BOSS、x 居中）的 y"""
    best = None
    for e in visible(view):
        a = e.valueAt(e.FirstParameter); b = e.valueAt(e.LastParameter)
        if abs(a.y - b.y) > 0.5:
            continue
        if abs((a.x + b.x) / 2) > 1.0:
            continue
        sc = abs(abs(a.x - b.x) - 2 * P.R_BOSS)
        if best is None or sc < best[0]:
            best = (sc, a.y)
    if best is None or best[0] > 0.5:
        raise RuntimeError("找不到中心凸台顶线（水平、长约 %.0f、居中）" % (2 * P.R_BOSS))
    return best[1]


# ================= 主视图 z → view2d y 映射（动态求，自动适配 y 轴朝向） =================
zs_model = sorted(set([0.0, P.BASE_T, P.BASE_T + P.H_WING, P.BASE_T + P.H_CEN]))
_z0, _z1 = zs_model[0], zs_model[-1]
_, _, _y0, _y1 = view_bb(vf)
if abs((_y1 - _y0) - (_z1 - _z0)) > 0.5:
    raise RuntimeError("主视图 y 范围 %.1f 与模型 z 范围 %.1f 不匹配" % (_y1 - _y0, _z1 - _z0))
_yboss = boss_top_y(vf)        # 凸台顶面对应 z=_z1
_flip = abs(_yboss - _y0) < abs(_yboss - _y1)     # y 轴朝下？
YMAP = ({z: _y1 - (z - _z0) for z in zs_model} if _flip
        else {z: _y0 + (z - _z0) for z in zs_model})
p("[map] 主视图 y 轴%s  ->  %s" % ("朝下(已适配)" if _flip else "朝上",
                                    {k: round(v, 1) for k, v in YMAP.items()}))

Z_BASE = YMAP[0.0]
Z_BT = YMAP[P.BASE_T]
Z_WING = YMAP[P.BASE_T + P.H_WING]
Z_BOSS = YMAP[P.BASE_T + P.H_CEN]


# ================= 尺寸 =================
dims = []


def _rec(view, kind, X, Y, value, extra):
    d = {"kind": kind, "view": view.Name.replace("View", ""),
         "X": float(X), "Y": float(Y), "value": round(float(value), 4)}
    d.update(extra)
    dims.append(d)
    return d


def dia(view, r, cx, cy, X, Y, label):
    """直径尺寸，关联引用圆边"""
    k, c = find_circle(view, r, cx, cy)
    if k is None:
        raise RuntimeError("找不到圆 r=%.2f c=(%s,%s) -> %s" % (r, cx, cy, label))
    d = doc.addObject("TechDraw::DrawViewDimension", "Dim%d" % len(dims))
    d.Type = "Diameter"; d.References2D = [(view, "Edge%d" % k)]
    page.addView(d); d.X, d.Y = X, Y
    _rec(view, "dia", X, Y, 0, {"r": float(c.Radius), "cx": float(c.Center.x),
                                "cy": float(c.Center.y), "label": label, "_d": d, "_edge": k})


def rad_neck(view, X, Y, label):
    """R_NECK 凹颈弧：模型里有 4 条同半径弧，取「左上」那条（圆心 x<0, y>0）。
    不写死圆心坐标 —— 改孔心距/凸台后颈弧会挪位，写死就会找不到。"""
    for k, e in enumerate(visible(view)):
        c = e.Curve
        if "Circle" not in c.__class__.__name__:
            continue
        if abs(c.Radius - P.R_NECK) > 0.5:
            continue
        if c.Center.x < -1.0 and c.Center.y > 1.0:
            d = doc.addObject("TechDraw::DrawViewDimension", "Dim%d" % len(dims))
            d.Type = "Radius"; d.References2D = [(view, "Edge%d" % k)]
            page.addView(d); d.X, d.Y = X, Y
            _rec(view, "rad", X, Y, 0, {"r": float(c.Radius), "cx": float(c.Center.x),
                                        "cy": float(c.Center.y), "label": label,
                                        "_d": d, "_edge": k})
            return
    raise RuntimeError("找不到 R%.0f 凹颈弧（左上）" % P.R_NECK)


def disty(view, z1, z2, X, Y, label):
    """竖直距离尺寸：引用两条水平边（用模型 z 值定位）"""
    y1, y2 = YMAP[z1], YMAP[z2]
    k1, r1 = find_hline(view, y1)
    k2, r2 = find_hline(view, y2)
    if k1 is None or k2 is None:
        raise RuntimeError("找不到水平边 y=%.1f / y=%.1f -> %s" % (y1, y2, label))
    d = doc.addObject("TechDraw::DrawViewDimension", "Dim%d" % len(dims))
    d.Type = "DistanceY"; d.References2D = [(view, "Edge%d" % k1), (view, "Edge%d" % k2)]
    page.addView(d); d.X, d.Y = X, Y
    _rec(view, "distY", X, Y, 0, {"y1": y1, "y2": y2, "label": label,
                                  "_d": d, "_e1": k1, "_e2": k2})


def distx_pts(view, p1, p2, X, Y, label):
    """水平距离尺寸（用派生坐标；用于圆心距这类无法用边表达的量）"""
    d = TechDraw.makeDistanceDim(view, "DistanceX",
                                 App.Vector(p1[0], p1[1], 0), App.Vector(p2[0], p2[1], 0))
    d.FormatSpec = "%.0f"
    page.addView(d); d.X, d.Y = X, Y
    _rec(view, "distX", X, Y, 0, {"p1": list(p1), "p2": list(p2), "label": label, "_d": d})


def extent(view, direction, X, Y, label):
    d = TechDraw.makeExtentDim(view, [], direction)
    d.FormatSpec = "%.0f"
    page.addView(d); d.X, d.Y = X, Y
    _rec(view, "extentH" if direction == 0 else "extentV", X, Y, 0,
         {"label": label, "_d": d})


# ---- 从实体派生：侧孔柱面轴线 x（供圆心距标注） ----
def side_hole_axis_x(sh):
    for f in sh.Faces:
        s = f.Surface
        if "Cylinder" not in s.__class__.__name__:
            continue
        if abs(s.Radius - P.D_HOLE_SIDE / 2.0) > 0.3:
            continue
        if abs(s.Axis.z) < 0.99:
            continue
        if abs(s.Center.x) < 1e-6:
            continue
        return float(s.Center.x)
    return None


# ================= 俯视图标注（位置照原图） =================
# label 用固定语义名（不含数值）；数值一律由后面的 getRawValue() 现场读
rad_neck(vt, 66.7, 140.0, "R_neck")
dia(vt, P.R_OUT_CEN, 0.0, 0.0, 117.5, 150.8, "OD_center_arc")
dia(vt, P.R_BOSS, 0.0, 0.0, 156.7, 60.8, "OD_boss")
dia(vt, P.D_HOLE_CEN / 2, 0.0, 0.0, 163.3, 153.3, "ID_center")
dia(vt, P.R_SIDE, -P.D_SIDE, 0.0, 40.8, 83.3, "OD_wing")
dia(vt, P.D_HOLE_SIDE / 2, -P.D_SIDE, 0.0, 43.3, 119.2, "ID_side")

hx = side_hole_axis_x(shape)
if hx is None:
    raise RuntimeError("实体里找不到侧孔圆柱面，无法标注孔心距")
distx_pts(vt, (hx, 0.0), (0.0, 0.0), 90, 64, "hole_pitch")
extent(vt, 0, 115, 44, "L")
extent(vt, 1, 196, 100, "W")

# ================= 主视图标注（位置照原图） =================
disty(vf, P.BASE_T, P.BASE_T + P.H_CEN, 198, 245, "H_boss")
disty(vf, 0.0, P.BASE_T, 198, 202, "T_base")
disty(vf, P.BASE_T, P.BASE_T + P.H_WING, 38.5, 212, "H_step")

doc.recompute()

# ---- 统一读 FreeCAD 算出的值 ----
p("[dims] FreeCAD 计算值：")
for rec in dims:
    dv = rec.pop("_d")
    rec["value"] = round(float(dv.getRawValue()), 4)
    p("   %-6s Edge%-4s -> %8.2f      %s"
      % (rec["kind"], rec.get("_edge", rec.get("_e1", "-")), rec["value"], rec["label"]))
for rec in dims:
    for k in ("_edge", "_e1", "_e2"):
        rec.pop(k, None)


# ================= 导出 JSON =================
def edges_json(view, n=64):
    out = []
    for e in view.getVisibleEdges():
        f0, f1 = e.FirstParameter, e.LastParameter
        out.append([[round(e.valueAt(f0 + (f1 - f0) * i / n).x, 3),
                     round(e.valueAt(f0 + (f1 - f0) * i / n).y, 3)] for i in range(n + 1)])
    return out


def circles_json(view):
    """圆特征（半径/圆心）—— 供闭环校核直接比对，不必从采样点反推曲线"""
    out = []
    for k, e in enumerate(view.getVisibleEdges()):
        c = e.Curve
        if "Circle" in c.__class__.__name__:
            out.append({"i": k, "r": round(c.Radius, 3),
                        "cx": round(c.Center.x, 3), "cy": round(c.Center.y, 3)})
    return out


def hlines_json(view):
    """水平线特征（y 值 + x 范围）—— 供校核主视图高度层。
    额外验中点，避免把「首尾同高、中间是曲线」的边误判成水平线。"""
    out = []
    for k, e in enumerate(view.getVisibleEdges()):
        if "Circle" in e.Curve.__class__.__name__:
            continue
        f0, f1 = e.FirstParameter, e.LastParameter
        a = e.valueAt(f0); b = e.valueAt(f1); m = e.valueAt((f0 + f1) / 2.0)
        if abs(a.y - b.y) < 1e-6 and abs(m.y - a.y) < 1e-6:
            out.append({"i": k, "y": round(a.y, 3),
                        "x0": round(min(a.x, b.x), 3), "x1": round(max(a.x, b.x), 3)})
    return out


data = {
    "views": [{"name": nm, "X": float(v.X), "Y": float(v.Y), "plot_scale": PLOT[nm],
               "edges": edges_json(v), "circles": circles_json(v), "hlines": hlines_json(v)}
              for nm, v in views.items()],
    "dims": dims,
}
jf = os.path.join(HERE, "_td_data.json")
json.dump(data, open(jf, "w", encoding="utf-8"), ensure_ascii=False)
p("[out] JSON:", jf, os.path.getsize(jf), "bytes")

fc = os.path.join(HERE, P.TAG + ".FCStd")
doc.saveAs(fc)
p("[out] FCStd:", fc)
p("@@STAGE2_OK@@")
