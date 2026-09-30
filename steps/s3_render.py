# -*- coding: utf-8 -*-
r"""
【第 3 段 / 渲染 A3 矢量 PDF】
读 _td_data.json：
  - 视图几何：FreeCAD TechDraw HLR 投影出来的可见边
  - 尺寸：位置 + **FreeCAD 算出的真实值**（value 字段，段 2 用 getRawValue() 读的）
本段只负责排版落盘，不再自己计算任何尺寸数字。
"""
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # 项目根，用于引用 msgio

from msgio import boot, finish, ref_path, ref_data    # noqa: E402

# ---- 输入只来自消息 ----
IN = boot("s3_render")
OUT_DIR = ref_data(IN, "out_dir")
data = json.load(open(ref_path(IN, "drawing_json"), encoding="utf-8"))

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

A3W, A3H = 420.0, 297.0
fig = plt.figure(figsize=(A3W / 25.4, A3H / 25.4))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, A3W); ax.set_ylim(0, A3H)
ax.set_aspect("equal"); ax.axis("off")
LW, AR = 0.35, 3.0


def ln(x0, y0, x1, y1, w=LW, c="k", z=2):
    ax.plot([x0, x1], [y0, y1], color=c, lw=w, solid_capstyle="butt", zorder=z)


def arrow(tip, deg, size=AR):
    a = math.radians(deg); s = math.sin(a); co = math.cos(a)
    bx, by = tip[0] - size * co, tip[1] - size * s
    px, py = -s * size * 0.33, co * size * 0.33
    ax.add_patch(Polygon([tip, (bx + px, by + py), (bx - px, by - py)], closed=True,
                         facecolor="k", edgecolor="none", zorder=3))


def txt(x, y, s, size=9, c="k", ha="center", va="center", rot=0):
    ax.text(x, y, s, fontsize=size, color=c, ha=ha, va=va, rotation=rot, zorder=4)


# ---------- 视图几何 ----------
V = {v["name"]: v for v in data["views"]}


def draw_view(name):
    v = V[name]
    for e in v["edges"]:
        ax.plot([v["X"] + q[0] * v["plot_scale"] for q in e],
                [v["Y"] + q[1] * v["plot_scale"] for q in e], color="k", lw=0.45, zorder=2)
    xs = [q[0] for e in v["edges"] for q in e]
    ys = [q[1] for e in v["edges"] for q in e]
    return min(xs), max(xs), min(ys), max(ys)


bb = {n: draw_view(n) for n in ("Front", "Top", "Iso")}
mt = V["Top"]
LEN = bb["Top"][1] - bb["Top"][0]      # 总长
WID = bb["Top"][3] - bb["Top"][2]      # 总宽
HGT = bb["Front"][3] - bb["Front"][2]  # 总高


# ---------- 图框 + 标题栏 ----------
M = 8.0
ax.add_patch(Polygon([(M, M), (A3W - M, M), (A3W - M, A3H - M), (M, A3H - M)], closed=True,
                     fill=False, edgecolor="k", lw=0.9, zorder=1))
tx0, ty0, TBW, TBH = A3W - M - 180, M, 180.0, 46.0
ax.add_patch(Polygon([(tx0, ty0), (tx0 + TBW, ty0), (tx0 + TBW, ty0 + TBH), (tx0, ty0 + TBH)],
                     closed=True, fill=False, edgecolor="k", lw=0.7, zorder=1))
for i in range(1, 4):
    ln(tx0, ty0 + i * TBH / 4, tx0 + TBW, ty0 + i * TBH / 4, 0.5)
ln(tx0 + 120, ty0, tx0 + 120, ty0 + TBH, 0.5)
txt(tx0 + 3, ty0 + 37, "零件名称：加工垫片（图 1-19）", 11, ha="left")
txt(tx0 + 3, ty0 + 29, "比例 1:4    单位 mm    第一角投影", 9, ha="left")
txt(tx0 + 3, ty0 + 21, "材料 未标注        数量 1", 9, ha="left")
txt(tx0 + 3, ty0 + 13, "外接 %.0f × %.0f × %.0f" % (LEN, WID, HGT), 9, ha="left")
txt(tx0 + 3, ty0 + 5, "视图/尺寸：FreeCAD TechDraw 1.1.0（参数化关联）", 8, ha="left")
txt(tx0 + 123, ty0 + 37, "2026-09-29", 9, ha="left")
txt(tx0 + 123, ty0 + 29, "未注公差", 9, ha="left")
txt(tx0 + 123, ty0 + 21, "去毛刺", 9, ha="left")

txt(V["Front"]["X"], V["Front"]["Y"] + bb["Front"][2] * V["Front"]["plot_scale"] - 7, "主视图", 13)
txt(V["Top"]["X"], V["Top"]["Y"] + bb["Top"][2] * V["Top"]["plot_scale"] - 6, "俯视图", 13)
txt(V["Iso"]["X"], V["Iso"]["Y"] + bb["Iso"][2] * V["Iso"]["plot_scale"] - 9, "轴测图", 13)

# ---------- 尺寸 ----------
DEG = lambda a: math.degrees(a)
for d in data["dims"]:
    v = V[d["view"]]
    sc, VX, VY = v["plot_scale"], v["X"], v["Y"]
    x0v, x1v, y0v, y1v = bb[v["name"]]
    k = d["kind"]
    val = d["value"]                     # ← FreeCAD 算出的真实值

    if k in ("dia", "rad"):
        lx, ly = d["X"], d["Y"]
        ccx, ccy = VX + d["cx"] * sc, VY + d["cy"] * sc
        rpg = d["r"] * sc
        dx, dy = lx - ccx, ly - ccy
        L = math.hypot(dx, dy) or 1.0
        tx, ty = ccx + rpg * dx / L, ccy + rpg * dy / L
        ln(lx, ly, tx, ty)
        arrow((tx, ty), DEG(math.atan2(ty - ly, tx - lx)))
        s = ("\u03c6%.0f" % val) if k == "dia" else ("R%.0f" % val)
        txt(lx + dx / L * 4.0, ly + dy / L * 4.0, s, 10)

    elif k in ("distY",):
        Xp = d["X"]
        ya, yb = VY + d["y1"] * sc, VY + d["y2"] * sc
        xa = VX + (x1v if Xp > VX else x0v) * sc
        ln(xa, ya, Xp + 1.2, ya); ln(xa, yb, Xp + 1.2, yb)
        ln(Xp, ya, Xp, yb)
        arrow((Xp, ya), 270); arrow((Xp, yb), 90)
        if Xp > VX:
            txt(Xp + 3.4, (ya + yb) / 2, "%.0f" % val, 9, ha="left")
        else:
            txt(Xp - 3.4, (ya + yb) / 2, "%.0f" % val, 9, ha="right")

    elif k == "distX":
        Yp = d["Y"]
        xa, ya = VX + d["p1"][0] * sc, VY + d["p1"][1] * sc
        xb, yb = VX + d["p2"][0] * sc, VY + d["p2"][1] * sc
        ln(xa, ya, xa, Yp + 1.2); ln(xb, yb, xb, Yp + 1.2)
        ln(xa, Yp, xb, Yp)
        arrow((xa, Yp), 180); arrow((xb, Yp), 0)
        txt((xa + xb) / 2, Yp + 3.4, "%.0f" % val, 9)

    elif k == "extentH":
        a = (VX + x0v * sc, VY + y0v * sc); b = (VX + x1v * sc, VY + y0v * sc)
        y = d["Y"]
        ln(a[0], a[1], a[0], y + 1.2); ln(b[0], b[1], b[0], y + 1.2)
        ln(a[0], y, b[0], y); arrow((a[0], y), 180); arrow((b[0], y), 0)
        txt((a[0] + b[0]) / 2, y + 3.4, "%.0f" % val, 9)

    elif k == "extentV":
        a = (VX + x0v * sc, VY + y0v * sc); b = (VX + x0v * sc, VY + y1v * sc)
        x = d["X"]
        ln(a[0], a[1], x + 1.2, a[1]); ln(b[0], b[1], x + 1.2, b[1])
        ln(x, a[1], x, b[1]); arrow((x, a[1]), 270); arrow((x, b[1]), 90)
        txt(x + 3.4, (a[1] + b[1]) / 2, "%.0f" % val, 9, ha="left")

pdf = os.path.join(OUT_DIR, "drawing.pdf")
png = os.path.join(OUT_DIR, "drawing.png")
fig.savefig(pdf)
fig.savefig(png, dpi=300)

finish([("drawing_pdf", pdf), ("drawing_png", png)],
       {"pdf_bytes": os.path.getsize(pdf), "png_bytes": os.path.getsize(png),
        "n_dims_drawn": len(data["dims"])})
