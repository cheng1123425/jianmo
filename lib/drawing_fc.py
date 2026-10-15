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
  * 标注工具（见下「两套标注方式」）
  * 收尾取值（`finalize()`：recompute 后从标注对象读 FreeCAD 实算值）
  * 导出（`_drawing.json` + `.FCStd`）

两套标注方式（2026-10-15 起并存，遗留 §1.4 的收敛对象）
---------------------------------------------------------
| 方式 | 方法 | 尺寸值来源 | 谁在用 |
|---|---|---|---|
| **绑边**（项目目标） | `add_dia` / `add_rad` / `dia_by_center` / `rad_by_center` / `disty_by_edge` / `distx_by_edge` | FreeCAD 从投影边**实测** | gasket（全线）；另三个零件正在迁移 |
| 两点距离（过渡态） | `add_distx` / `add_disty` | 传两个坐标点，**算出来** | bracket / lbracket / ybracket |

README 承诺的是绑边。收敛顺序：① 两种并存（本文档）→ ② 逐零件迁移 + 像素对比
→ ③ `arch_impact.py --strict` 报 0 依赖后删掉两点距离那套。
**在 ③ 完成前不要删 `add_distx` / `add_disty`。**

为什么标注布置用「回调」而不是「数据清单」
------------------------------------
`s3_render` 那边的标注可以完全数据化（现已下沉为共享层的 `steps/s3_render.py` +
零件的 `draw_spec.py`），但 s2 的标注牵涉「按半径找投影边」「按坐标找水平边」
「找不到就跳过」这类逻辑，硬塞进数据表反而失真。所以这里用一个
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

    # ==================================================================
    # 绑边标注（2026-10-15 新增，遗留 §1.4 第①步）
    #
    # 为什么要加：`add_distx` / `add_disty` 走 `TechDraw.makeDistanceDim(view, type, v1, v2)`，
    #   传的是**两个坐标点** —— 尺寸值是"算出来的"，改三维后不一定跟着变。
    #   而 gasket 那套（`find_hline` 找边 + `d.References2D = [(view,"EdgeN"), ...]`）
    #   是**把尺寸绑到投影边上**，值由 FreeCAD 从边实测 —— 这才是 README 承诺的做法：
    #   "每个尺寸都是 DrawViewDimension，用 References2D 引用投影边，改三维自动跟随"。
    #
    # 为什么**新增方法而不是改 add_disty 的签名**（MSG.md §〇 纪律 1「只增不改」）：
    #   三个零件（bracket/lbracket/ybracket）正在用 add_distx/add_disty，改签名会
    #   让它们同时断线。两种方式先在 lib 里并存，逐个零件迁移完再收敛（§1.4 第③步）。
    #
    # 下游注意：`d.References2D` 的边号是 **0-based 的可见边下标**
    #   （对应 `enumerate(view.getVisibleEdges())`），不是 TechDraw 内部 1-based 编号。
    # ==================================================================

    def find_hline(self, view, y, tol=0.5):
        """找**水平边**（两端 y 相同），返回最长的那条。

        返回 (下标, (x_lo, x_hi))；找不到返回 (None, None)。
        同名的多条水平边时取最长的一条 —— 尺寸线引出的那条通常就是主轮廓边。
        """
        best = None
        for k, e in enumerate(self.visible(view)):
            c = e.Curve
            if "Circle" in c.__class__.__name__:
                continue                       # 圆不是"线"
            a = e.valueAt(e.FirstParameter)
            b = e.valueAt(e.LastParameter)
            if abs(a.y - y) > tol or abs(b.y - y) > tol:
                continue
            ln = abs(a.x - b.x)
            if best is None or ln > best[2]:
                best = (k, (min(a.x, b.x), max(a.x, b.x)), ln)
        return (best[0], best[1]) if best else (None, None)

    def find_vline(self, view, x, tol=0.5):
        """找**竖直边**（两端 x 相同），返回最长的那条。返回 (下标, (y_lo, y_hi))。"""
        best = None
        for k, e in enumerate(self.visible(view)):
            c = e.Curve
            if "Circle" in c.__class__.__name__:
                continue
            a = e.valueAt(e.FirstParameter)
            b = e.valueAt(e.LastParameter)
            if abs(a.x - x) > tol or abs(b.x - x) > tol:
                continue
            ln = abs(a.y - b.y)
            if best is None or ln > best[2]:
                best = (k, (min(a.y, b.y), max(a.y, b.y)), ln)
        return (best[0], best[1]) if best else (None, None)

    def _bound_dim(self, view, type_str, edge_ks, X, Y, kind, label, extra=None):
        """建一个**绑边**尺寸：`References2D` 指向给定的可见边下标。

        公共收口 —— `disty_by_edge` / `distx_by_edge` / `dia_by_center` / `rad_by_center`
        都走这里，保证 `_rec` 记出来的结构一致（下游 s5/s6 只认结构不认来源）。
        """
        d = self.doc.addObject("TechDraw::DrawViewDimension",
                               "Dim%d" % len(self.dims))
        d.Type = type_str
        d.References2D = [(view, "Edge%d" % k) for k in edge_ks]
        self.page.addView(d)
        d.X, d.Y = X, Y
        rec = {"label": label, "_d": d}
        if len(edge_ks) == 2:
            rec["_e1"], rec["_e2"] = edge_ks
        else:
            rec["_edge"] = edge_ks[0]
        rec.update(extra or {})
        return self._rec(view, kind, X, Y, 0, rec)

    def disty_by_edge(self, view, y1, y2, X, Y, label):
        """竖直距离尺寸 —— **绑到两条水平边**（gasket `disty` 的通用化）。

        替代 `add_disty`（两点距离）。用法：`y1`/`y2` 是**视图 2D 坐标**里的 y
        （不是模型 z —— 视图可能翻转，gasket 那边用 YMAP 先换算过一次；
        本方法直接吃 2D 坐标，零件自己负责换算）。
        """
        k1, r1 = self.find_hline(view, y1)
        k2, r2 = self.find_hline(view, y2)
        if k1 is None or k2 is None:
            raise RuntimeError("找不到水平边 y=%.2f / y=%.2f -> %s" % (y1, y2, label))
        return self._bound_dim(view, "DistanceY", [k1, k2], X, Y, "distY", label,
                               {"y1": float(y1), "y2": float(y2)})

    def distx_by_edge(self, view, x1, x2, X, Y, label):
        """水平距离尺寸 —— **绑到两条竖直边**。替代 `add_distx`（两点距离）。"""
        k1, r1 = self.find_vline(view, x1)
        k2, r2 = self.find_vline(view, x2)
        if k1 is None or k2 is None:
            raise RuntimeError("找不到竖直边 x=%.2f / x=%.2f -> %s" % (x1, x2, label))
        return self._bound_dim(view, "DistanceX", [k1, k2], X, Y, "distX", label,
                               {"x1": float(x1), "x2": float(x2)})

    def dia_by_center(self, view, r, cx, cy, X, Y, label, optional=False):
        """直径尺寸 —— 按**半径 + 圆心**找圆并绑边。

        与 `add_dia` 的区别：后者只按半径找（`first_circle_r`），同半径的孔有多个时
        会拿到第一个；本方法多一个圆心约束，能精确选中目标孔。
        绑定方式与 `add_dia` 相同（`References2D` 单边），**不是新增能力而是更精确的定位**。
        """
        k, c = self.first_circle_r(view, r, tol=0.5)
        if k is not None and cx is not None and abs(c.Center.x - cx) > 0.5:
            k, c = self._circle_at(view, r, cx, cy)
        if k is None:
            if optional:
                return None
            raise RuntimeError("找不到 r=%.2f @ (%.2f,%.2f) -> %s" % (r, cx, cy, label))
        d = self.doc.addObject("TechDraw::DrawViewDimension",
                               "Dim%d" % len(self.dims))
        d.Type = "Diameter"
        d.References2D = [(view, "Edge%d" % k)]
        self.page.addView(d)
        d.X, d.Y = X, Y
        return self._rec(view, "dia", X, Y, 0,
                         {"r": _y(c.Radius), "cx": _y(c.Center.x), "cy": _y(c.Center.y),
                          "label": label, "_d": d, "_edge": k})

    def rad_by_center(self, view, r, cx, cy, X, Y, label, optional=False):
        """半径尺寸 —— 按半径 + 圆心找圆并绑边（`add_rad` 的精确版）。"""
        k, c = self.first_circle_r(view, r, tol=0.5)
        if k is not None and cx is not None and abs(c.Center.x - cx) > 0.5:
            k, c = self._circle_at(view, r, cx, cy)
        if k is None:
            if optional:
                return None
            raise RuntimeError("找不到 r=%.2f @ (%.2f,%.2f) -> %s" % (r, cx, cy, label))
        d = self.doc.addObject("TechDraw::DrawViewDimension",
                               "Dim%d" % len(self.dims))
        d.Type = "Radius"
        d.References2D = [(view, "Edge%d" % k)]
        self.page.addView(d)
        d.X, d.Y = X, Y
        return self._rec(view, "rad", X, Y, 0,
                         {"r": _y(c.Radius), "cx": _y(c.Center.x), "cy": _y(c.Center.y),
                          "label": label, "_d": d, "_edge": k})

    def _circle_at(self, view, r, cx, cy, tol=0.5):
        """按半径 + 圆心找圆边，返回 (下标, 曲线)；找不到 (None, None)。"""
        for k, e in enumerate(self.visible(view)):
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

    # ---------------- 锚点驱动（G 阶段：2D↔3D 语义绑定）----------------
    def add_anchor_dim(self, anchor, X, Y):
        """按 `ir_anchors.json` 的一个锚点生成标注——**几何谓词驱动**，不写死边号。

        谓词 → 生成方式：
          * ``circle``   → 按半径找投影圆，`References2D` 绑边做直径标注（真·绑边）。
          * ``extent``   → 整体范围标注（长/宽/高）。
          * ``level_pair``→ 两个同径圆的圆心间距标注（两点距离）。

        返回带锚点元数据（fid / semantic / expected）的标注记录，供下游 s6 追链路。
        无锚点声明的标注不经过这里——各零件 `place_marks` 保留原行为（向后兼容）。
        """
        label = anchor.get("label")
        geom = anchor.get("geom") or {}
        kind = geom.get("kind")
        expected = anchor.get("expected")
        meta = {"anchor_fid": anchor.get("fid"), "semantic": anchor.get("semantic"),
                "expected": expected, "geom": geom}

        if anchor.get("view") not in self.views:
            return self._rec(None, "anchor_missing_view", X, Y, 0,
                             dict(meta, label=label, note="视图不存在"))
        view = self.views[anchor["view"]]

        if kind == "circle":
            r = float(geom.get("r"))
            k, c = self.first_circle_r(view, r)
            if k is None:
                return self._rec(view, "dia", X, Y, 0,
                                 dict(meta, label=label, note="未找到 r=%.2f 的圆" % r,
                                      found=False))
            d = self.doc.addObject("TechDraw::DrawViewDimension", "Dim%d" % len(self.dims))
            d.Type = "Diameter"
            d.References2D = [(view, "Edge%d" % k)]      # 绑边
            self.page.addView(d)
            d.X, d.Y = X, Y
            return self._rec(view, "dia", X, Y, 0,
                             dict(meta, label=label, r=_y(c.Radius),
                                  cx=_y(c.Center.x), cy=_y(c.Center.y),
                                  found=True, _d=d, _edge=k))

        if kind == "extent":
            direction = 0 if anchor.get("dim_kind") == "extentH" else 1
            d = self.TechDraw.makeExtentDim(view, [], direction)
            d.FormatSpec = "%.0f"
            self.page.addView(d)
            d.X, d.Y = X, Y
            return self._rec(view, "extentH" if direction == 0 else "extentV", X, Y, 0,
                             dict(meta, label=label, found=True, _d=d))

        if kind == "level_pair":
            r = float(geom.get("r"))
            axis = geom.get("axis", "x")
            hits = [e.Curve for e in self.visible(view)
                    if "Circle" in e.Curve.__class__.__name__
                    and abs(_y(e.Curve.Radius) - r) < 0.3]
            if len(hits) < 2:
                return self._rec(view, "distX", X, Y, 0,
                                 dict(meta, label=label, found=False,
                                      note="同径圆不足 2 个(找到%d)" % len(hits)))
            a = sorted(_y(c.Center.x) if axis == "x" else _y(c.Center.y) for c in hits)
            v1, v2 = a[0], a[-1]
            AppV = self.App.Vector
            if axis == "x":
                p1, p2 = AppV(v1, 0, 0), AppV(v2, 0, 0)
                dk = "DistanceX"
            else:
                p1, p2 = AppV(0, v1, 0), AppV(0, v2, 0)
                dk = "DistanceY"
            d = self.TechDraw.makeDistanceDim(view, dk, p1, p2)
            d.FormatSpec = "%.0f"
            self.page.addView(d)
            d.X, d.Y = X, Y
            return self._rec(view, "distX", X, Y, 0,
                             dict(meta, label=label, coords=[round(v1, 3), round(v2, 3)],
                                  found=True, _d=d))

        # 未知谓词：诚实留痕，不静默
        return self._rec(view, "anchor_unknown", X, Y, 0,
                         dict(meta, label=label, note="未知谓词 %r" % kind, found=False))

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
