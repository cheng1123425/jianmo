# -*- coding: utf-8 -*-
r"""多耳球铰盖 —— FreeCAD 出投影（俯视 + 主视），导出特征 JSON"""
import json
import os
import sys

import FreeCAD as App
import Part
import TechDraw

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
STEP = r"D:\3d\build123d\socket_cover.step"
TD = "D:/3d/\u65b0\u5efa\u6587\u4ef6\u5939/FreeCAD 1.1/data/Mod/TechDraw/Templates/ISO/A3_Landscape_TD.svg"


def p(*a):
    print(*a); sys.stdout.flush()


doc = App.newDocument("SocketCover")
sh = Part.Shape(); sh.read(STEP)
obj = doc.addObject("Part::Feature", "SocketCover"); obj.Shape = sh

page = doc.addObject("TechDraw::DrawPage", "Page")
tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Tpl"); tpl.Template = TD
page.Template = tpl

views = {}
for nm, d in [("Top", (0, 0, 1)), ("Front", (0, -1, 0))]:
    v = doc.addObject("TechDraw::DrawViewPart", "View" + nm)
    v.Source = [obj]; v.Direction = d
    page.addView(v); v.X = 115; v.Y = 100
    views[nm] = v
doc.recompute()


def circles(view):
    out = []
    for k, e in enumerate(view.getVisibleEdges()):
        c = e.Curve
        if "Circle" in c.__class__.__name__:
            out.append({"i": k, "r": round(c.Radius, 3),
                        "cx": round(c.Center.x, 3), "cy": round(c.Center.y, 3)})
    return out


def hlines(view):
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


def edges(view, n=48):
    out = []
    for e in view.getVisibleEdges():
        f0, f1 = e.FirstParameter, e.LastParameter
        out.append([[round(e.valueAt(f0 + (f1 - f0) * i / n).x, 3),
                     round(e.valueAt(f0 + (f1 - f0) * i / n).y, 3)] for i in range(n + 1)])
    return out


data = {"views": [{"name": nm, "circles": circles(v), "hlines": hlines(v), "edges": edges(v)}
                  for nm, v in views.items()]}
out = os.path.join(HERE, "_socket_data.json")
json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False)

for nm, v in views.items():
    cs = circles(v)
    p("[%s] 可见边 %d，圆 %d 条" % (nm, len(v.getVisibleEdges()), len(cs)))
    for c in cs:
        p("     r=%7.3f  c=(%8.2f,%8.2f)" % (c["r"], c["cx"], c["cy"]))
p("[out]", out, os.path.getsize(out), "bytes")
