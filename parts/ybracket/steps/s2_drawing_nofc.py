# -*- coding: utf-8 -*-
r"""s2_drawing_nofc —— 无 FreeCAD 的 s2 等价实现（双耳直角支座）

沙箱/无 FreeCAD 机器上，用**正交投影**对 STEP 实体做三视图，生成与
FreeCAD TechDraw 等价的 `_drawing.json`：
  views: [{name, X, Y, plot_scale, edges, circles, hlines}, ...]
  dims : [{kind, view, X, Y, value, label}, ...]

正交投影 = 丢掉视线方向分量：
  俯视 Top  丢 Z → (X, Y)
  主视 Front 丢 Y → (X, Z)
  侧视 Right 丢 X → (Y, Z)
圆保持为圆（不用 project_to_viewport，那个是透视投影会把圆变椭圆）。

输出与 s2_drawing.py（FreeCAD 版）**同 schema**，下游 s3_render / s4_table /
s5_collect / s6b_projection 可原样消费。

说明：本脚本不取代 s2_drawing.py（FreeCAD 版才是"真"出图，含关联尺寸对象）；
它只是无 CAD 内核时的**等价替代**，让出图段（s3/s4）与闭环段也能在沙箱跑通。
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))

from build123d import import_step
from msgio import boot, finish, ref_path, ref_data, exec_module

IN = boot("s2_drawing")
P = exec_module(ref_path(IN, "params"),
                os.path.basename(ref_path(IN, "params"))[:-3])
STEP = ref_path(IN, "model_step")
OUT_DIR = ref_data(IN, "out_dir")

# 视图布局：name -> (drop 分量, 纸面中心 X, 纸面中心 Y, 视图横轴, 视图纵轴)
#   俯视丢 Z→(X,Y)；主视丢 Y→(X,Z)；侧视丢 X→(Y,Z)
# 坐标约定与 FreeCAD 一致：edges 以**视图中心为原点**，故 X/Y 是图纸上的视图中心。
# 第一角投影标准布局：主视左上、俯视其下、侧视其右。
LAYOUT = {
    "Front": ("Y", 115.0, 185.0, "X", "Z"),   # 主视中心
    "Top":   ("Z", 115.0,  70.0, "X", "Y"),   # 俯视中心（主视正下方）
    "Right": ("X", 295.0, 185.0, "Y", "Z"),   # 侧视中心（主视正右方）
}
PLOT = {"Front": 0.8, "Top": 0.8, "Right": 0.8}
VIEW_AXIS = {"Top": "Z", "Front": "Y", "Right": "X"}   # 各视图的视线轴

shape = import_step(STEP)


def proj(u, hu, hv):
    """正交投影：按视图的两轴 (hu, hv) 取分量"""
    m = {"X": u.X, "Y": u.Y, "Z": u.Z}
    return (m[hu], m[hv])


def discrete(e, n=64):
    """边离散发点为视图二维坐标 [u, v]"""
    kind = str(e.geom_type)
    ts = (0.0, 1.0) if "LINE" in kind else [i / n for i in range(n + 1)]
    return ts


def build_view(name):
    # edges/circles 保持「视图中心为原点」的 view2d 坐标（与 FreeCAD 原生输出一致），
    # 不做归一化 —— 下游 s3_render 按 v.X/v.Y（图纸中心）+ q*scale 定位。
    drop, px, py, hu, hv = LAYOUT[name]
    edges = []
    for e in shape.edges():
        kind = str(e.geom_type)
        n = 2 if "LINE" in kind else 64
        pts = []
        for k in range(n + 1):
            v = e @ (k / n)
            u = proj(v, hu, hv)
            pts.append([round(u[0], 4), round(u[1], 4)])
        edges.append(pts)
    # 圆：轴与视线轴平行的圆弧边 → 在该视图里是圆
    cir = []
    for i, e in enumerate(shape.edges()):
        if str(e.geom_type) != "GeomType.CIRCLE":
            continue
        c = e.arc_center
        v0 = e @ 0.0
        axis = {"X": abs(v0.X - c.X), "Y": abs(v0.Y - c.Y), "Z": abs(v0.Z - c.Z)}
        if axis[drop] > 1e-6:
            continue                       # 轴不平行视线 → 非圆
        cu = proj(c, hu, hv)
        cir.append({"i": i, "r": round(float(e.radius), 4),
                    "cx": round(cu[0], 4), "cy": round(cu[1], 4)})
    return {"name": name, "X": px, "Y": py, "plot_scale": PLOT[name],
            "edges": edges, "circles": cir, "hlines": []}


views = [build_view(n) for n in ("Top", "Front", "Right")]

# ---- dims：从 dims_spec 的 expr 参数值生成（等价于 FreeCAD 实测）----
DIMS_SPEC = exec_module(os.path.join(os.path.dirname(HERE), "dims_spec.py"), "dims_spec")
dims = []
for sp in DIMS_SPEC.DIMS:
    val = sp["expr"](P)
    dims.append({"kind": sp["style"], "view": "Top", "X": 0.0, "Y": 0.0,
                 "value": round(float(val), 4), "label": sp["label"]})

data = {"views": views, "dims": dims}
jf = os.path.join(OUT_DIR, "_drawing.json")
json.dump(data, open(jf, "w", encoding="utf-8"), ensure_ascii=False)

finish([("drawing_json", jf)], {
    "views": [v["name"] for v in views],
    "n_edges": sum(len(v["edges"]) for v in views),
    "n_circles": sum(len(v["circles"]) for v in views),
    "n_dims": len(dims),
    "dim_values": {d["label"]: d["value"] for d in dims},
})
