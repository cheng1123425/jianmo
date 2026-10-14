# -*- coding: utf-8 -*-
r"""ybracket_preview —— 双耳支座三视图预览（纯 build123d，绕开 FreeCAD）

沙箱无 FreeCAD，s2_drawing（TechDraw 出图）跑不通。这里用简单正交投影
（丢掉视线方向分量）把 STEP 实体投影成三视图：
  俯视 Top（丢 Z → X×Y）、主视 Front（丢 Y → X×Z）、侧视 Right（丢 X → Y×Z）
再合成一张带标题栏的 A3 预览图，供用户确认零件外形是否符合图纸。

用途：仅作「外形确认」可视化，不产出 s2 的 drawing_json（那需要 FreeCAD）。
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))

from build123d import import_step


def ortho(edges, drop):
    """简单正交投影：把每条边离散，丢掉 drop 分量，返回 (x,y) 点列列表"""
    out = []
    for e in edges:
        pts = []
        for i in range(65):
            v = e @ (i / 64)
            if drop == "Z":
                pts.append((float(v.X), float(v.Y)))
            elif drop == "Y":
                pts.append((float(v.X), float(v.Z)))
            else:  # drop X
                pts.append((float(v.Y), float(v.Z)))
        out.append(pts)
    return out


def main():
    step = os.path.join(ROOT, "parts", "ybracket", "models", "ybracket.step")
    out_dir = os.path.join(ROOT, "parts", "ybracket", "models")
    shape = import_step(step)
    edges = shape.edges()

    top = ortho(edges, "Z")      # 俯视 X×Y
    front = ortho(edges, "Y")    # 主视 X×Z
    right = ortho(edges, "X")    # 侧视 Y×Z

    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    A3W, A3H = 420.0, 297.0
    fig = plt.figure(figsize=(A3W / 25.4, A3H / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, A3W); ax.set_ylim(0, A3H)
    ax.set_aspect("equal"); ax.axis("off")

    def bounds(edges):
        xs = [p[0] for e in edges for p in e]
        ys = [p[1] for e in edges for p in e]
        return min(xs), max(xs), min(ys), max(ys)

    # 统一 scale：取所有视图最大跨度，映射到 160mm 格宽
    all_edges = top + front + right
    xs = [p[0] for e in all_edges for p in e]
    ys = [p[1] for e in all_edges for p in e]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    scale = 160.0 / span

    layout = [
        ("俯视 Top",   top,   34, 45,  False),
        ("主视 Front", front, 34, 172, True),
        ("侧视 Right", right, 214, 172, True),
    ]
    for title, edges2, px, py, flip in layout:
        x0, x1, y0, y1 = bounds(edges2)
        def tx(x):
            return px + (x - x0) * scale
        def ty(y):
            return py + ((y1 - y) if flip else (y - y0)) * scale
        for e in edges2:
            ex = [tx(p[0]) for p in e]
            ey = [ty(p[1]) for p in e]
            ax.plot(ex, ey, color="k", lw=0.5, solid_capstyle="butt", zorder=2)
        bx = tx(x1)
        by = ty(y0)
        ax.text(bx, by + 4, title, fontsize=11, ha="right", va="bottom", zorder=4)

    # 图框 + 标题栏
    m = 8.0
    ax.add_patch(Polygon([(m, m), (A3W - m, m), (A3W - m, A3H - m), (m, A3H - m)],
                         closed=True, fill=False, edgecolor="k", lw=0.9, zorder=1))
    tx0, ty0, TBW, TBH = A3W - m - 170, m, 170.0, 44.0
    ax.add_patch(Polygon([(tx0, ty0), (tx0 + TBW, ty0), (tx0 + TBW, ty0 + TBH), (tx0, ty0 + TBH)],
                         closed=True, fill=False, edgecolor="k", lw=0.7, zorder=1))
    for i in range(1, 4):
        ax.plot([tx0, tx0 + TBW], [ty0 + i * TBH / 4, ty0 + i * TBH / 4], color="k", lw=0.45)
    ax.plot([tx0 + 112, tx0 + 112], [ty0, ty0 + TBH], color="k", lw=0.45)
    ax.text(tx0 + 3, ty0 + 35, "零件名称：双耳直角支座", fontsize=11, ha="left")
    ax.text(tx0 + 3, ty0 + 27, "比例 1:2    单位 mm    第一角投影", fontsize=8.6, ha="left")
    ax.text(tx0 + 3, ty0 + 19, "材料 未标注        数量 1", fontsize=8.6, ha="left")
    ax.text(tx0 + 3, ty0 + 11, "外接 200 × 144 × 120", fontsize=8.6, ha="left")
    ax.text(tx0 + 3, ty0 + 4, "预览图（build123d 正交投影，非 FreeCAD 出图）", fontsize=7.0, ha="left")

    png = os.path.join(out_dir, "preview.png")
    fig.savefig(png, dpi=160)
    print("saved:", png)


if __name__ == "__main__":
    main()
