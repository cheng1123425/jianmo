# -*- coding: utf-8 -*-
r"""lib/drawing_fc.py —— FreeCAD 出图的**通用骨架**（零件无关）

跑在 `freecadcmd` 里（Python 3.11，与项目 venv 3.13 不同），所以本模块只用**通用语法**，
不 import 任何项目其他模块（除 msgio 这类纯 Python 的）。

被各零件的 `steps/s2_drawing.py` 调用。零件只提供两样东西：

| 提供 | 内容 |
|---|---|
| `VIEW_SPECS`  | 建哪些视图：投影方向、XDirection、纸面位置、缩放 |
| `place_marks(b, P)` | 标注布置（哪些尺寸、标在视图的什么位置、用什么语义名） |

本模块负责：
  * 建 FreeCAD 文档 / 载入 STEP / 建视图 / 套 A3 模板
  * 标注工具（`add_dia` / `add_rad` / `add_distx` / `add_disty` / `add_extent`）
  * 收尾取值（`finalize()`：recompute 后从标注对象读 FreeCAD 实算值）
  * 导出（`_drawing.json` + `.FCStd`）

为什么标注布置用「回调」而不是「数据清单」
------------------------------------
`s3_render` 那边的标注可以完全数据化（DIMS 列表），但 s2 的标注牵涉
「按半径找投影边」「找不到就跳过」这类逻辑，硬塞进数据表反而失真。所以这里用一个
`place_marks(builder, P)` 回调 —— 分层目标照样达到：
**lib 管「怎么建图」，零件管「画什么」**。
"""
import json
import os


def _y(v):
    """FreeCAD Quantity → float"""
    return float(v)


class DrawingBuilder(object):
    """一张 FreeCAD 工程图的构建器。"""

    def __init__(self, doc_name, step_path, tag, template, view_specs):
        import FreeCAD as App
        import Part
        import TechDraw                                    # noqa: F401 (makeDistanceDim 等)
        self.App = App
        self.TechDraw = TechDraw
        self.doc = App.newDocument(doc_name)
        shape = Part.Shape()
        shape.read(step_path)
        self.obj = self.doc.addObject("Part::Feature", tag)
        self.obj.Shape = shape

        self.page = self.doc.addObject("TechDraw::DrawPage", "Page")
        tpl = self.doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        tpl.Template = template
        self.page.Template = tpl

        self.views = {}
        self.plot = {}
        for spec in view_specs:
            v = self.doc.addObject("TechDraw::DrawViewPart", "View" + spec["name"])
            v.Source = [self.obj]
            v.Direction = spec["dir"]
            if spec.get("xdir") is not None:
                v.XDirection = spec["xdir"]
            self.page.addView(v)
            v.X = spec["X"]
            v.Y = spec["Y"]
            self.views[spec["name"]] = v
            self.plot[spec["name"]] = spec.get("scale", 1.0)
        self.doc.recompute()
        self.dims = []

    # ---------------- 工具 ----------------
    def visible(self, view):
        return view.getVisibleEdges()

    def first_circle_r(self, view, r, tol=0.5):
        """按半径找第一条圆边，返回 (下标, 曲线)；找不到返回 (None, None)"""
        for k, e in enumerate(self.visible(view)):
            c = e.Curve
            if "Circle" in c.__class__.__name__ and abs(_y(c.Radius) - r) < tol:
                return k, c
        return None, None

    def _rec(self, view, kind, X, Y, value, extra):
        d = {"kind": kind, "view": view.Name.replace("View", ""),
             "X": float(X), "Y": float(Y), "value": round(float(value), 4)}
        d.update(extra)
        self.dims.append(d)
        return d

    # ---------------- 标注 ----------------
    def add_dia(self, view, r, X, Y, label, optional=False):
        k, c = self.first_circle_r(view, r)
        if k is None:
            if optional:
                return None
            raise RuntimeError("找不到 r=%.2f -> %s" % (r, label))
        d = self.doc.addObject("TechDraw::DrawViewDimension", "Dim%d" % len(self.dims))
        d.Type = "Diameter"
        d.References2D = [(view, "Edge%d" % k)]
        self.page.addView(d)
        d.X, d.Y = X, Y
        return self._rec(view, "dia", X, Y, 0,
                         {"r": _y(c.Radius), "cx": _y(c.Center.x), "cy": _y(c.Center.y),
                          "label": label, "_d": d, "_edge": k})

    def add_rad(self, view, r, X, Y, label, optional=False):
        k, c = self.first_circle_r(view, r)
        if k is None:
            if optional:
                return None
            raise RuntimeError("找不到 r=%.2f -> %s" % (r, label))
        d = self.doc.addObject("TechDraw::DrawViewDimension", "Dim%d" % len(self.dims))
        d.Type = "Radius"
        d.References2D = [(view, "Edge%d" % k)]
        self.page.addView(d)
        d.X, d.Y = X, Y
        return self._rec(view, "rad", X, Y, 0,
                         {"r": _y(c.Radius), "cx": _y(c.Center.x), "cy": _y(c.Center.y),
                          "label": label, "_d": d, "_edge": k})

    def add_distx(self, view, x1, x2, X, Y, label):
        """用两点做水平距离"""
        App = self.App
        v1 = App.Vector(_y(x1), 0, 0)
        v2 = App.Vector(_y(x2), 0, 0)
        d = self.TechDraw.makeDistanceDim(view, "DistanceX", v1, v2)
        d.FormatSpec = "%.0f"
        self.page.addView(d)
        d.X, d.Y = X, Y
        return self._rec(view, "distX", X, Y, 0,
                         {"x1": float(x1), "x2": float(x2), "label": label, "_d": d})

    def add_disty(self, view, y1, y2, X, Y, label):
        """用两点做竖直距离"""
        App = self.App
        v1 = App.Vector(0, _y(y1), 0)
        v2 = App.Vector(0, _y(y2), 0)
        d = self.TechDraw.makeDistanceDim(view, "DistanceY", v1, v2)
        d.FormatSpec = "%.0f"
        self.page.addView(d)
        d.X, d.Y = X, Y
        return self._rec(view, "distY", X, Y, 0,
                         {"y1": float(y1), "y2": float(y2), "label": label, "_d": d})

    def add_extent(self, view, direction, X, Y, label):
        d = self.TechDraw.makeExtentDim(view, [], direction)
        d.FormatSpec = "%.0f"
        self.page.addView(d)
        d.X, d.Y = X, Y
        return self._rec(view, "extentH" if direction == 0 else "extentV", X, Y, 0,
                         {"label": label, "_d": d})

    # ---------------- 收尾：recompute 后取 FreeCAD 实算值 ----------------
    def finalize(self, verbose=True):
        self.doc.recompute()
        for rec in self.dims:
            dv = rec.pop("_d")
            rec["value"] = round(float(dv.getRawValue()), 4)
        if verbose:
            print("[dims] FreeCAD 计算值：")
            for rec in self.dims:
                print("   %-6s Edge%-4s -> %8.2f      %s"
                      % (rec["kind"], rec.get("_edge", "-"), rec["value"], rec["label"]))
        for rec in self.dims:
            for k in ("_edge", "_e1", "_e2"):
                rec.pop(k, None)
        return self.dims

    # ---------------- 导出 ----------------
    def edges_json(self, view, n=64):
        out = []
        for e in view.getVisibleEdges():
            f0, f1 = e.FirstParameter, e.LastParameter
            out.append([[_y(e.valueAt(f0 + (f1 - f0) * i / n).x),
                         _y(e.valueAt(f0 + (f1 - f0) * i / n).y)] for i in range(n + 1)])
        return out

    def circles_json(self, view):
        out = []
        for k, e in enumerate(view.getVisibleEdges()):
            c = e.Curve
            if "Circle" in c.__class__.__name__:
                out.append({"i": k, "r": round(_y(c.Radius), 3),
                            "cx": round(_y(c.Center.x), 3), "cy": round(_y(c.Center.y), 3)})
        return out

    def hlines_json(self, view):
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
                            "x0": round(min(_y(a.x), _y(b.x)), 3),
                            "x1": round(max(_y(a.x), _y(b.x)), 3)})
        return out

    def export(self, out_dir, tag):
        data = {
            "views": [{"name": nm, "X": float(v.X), "Y": float(v.Y),
                       "plot_scale": self.plot[nm],
                       "edges": self.edges_json(v), "circles": self.circles_json(v),
                       "hlines": self.hlines_json(v)}
                      for nm, v in self.views.items()],
            "dims": self.dims,
        }
        jf = os.path.join(out_dir, "_drawing.json")
        json.dump(data, open(jf, "w", encoding="utf-8"), ensure_ascii=False)
        fc = os.path.join(out_dir, tag + ".FCStd")
        self.doc.saveAs(fc)
        return jf, fc, data
