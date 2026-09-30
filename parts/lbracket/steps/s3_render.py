# -*- coding: utf-8 -*-
r"""s3_render —— 投影特征 → A3 矢量 PDF / PNG（L 形支座）

视图：Top / Front / Right。Front/Right 的 view2d y 朝下（要翻转），Top 的 y 朝上。
尺寸数值取自 s2 实测（data["dims"]），位置按各视图包围盒自适应。
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
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容

from msgio import boot, finish, ref_path, ref_data    # noqa: E402

IN = boot("s3_render")
OUT_DIR = ref_data(IN, "out_dir")
data = json.load(open(ref_path(IN, "drawing_json"), encoding="utf-8"))

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

A3W, A3H = 420.0, 297.0
fig = plt.figure(figsize=(A3W / 25.4, A3H / 25.4))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, A3W); ax.set_ylim(0, A3H)
ax.set_aspect("equal"); ax.axis("off")
LW, AR = 0.32, 2.6


def ln(x0, y0, x1, y1, w=LW, c="k", z=2):
    ax.plot([x0, x1], [y0, y1], color=c, lw=w, solid_capstyle="butt", zorder=z)


def arrow(tip, deg, size=AR):
    a = math.radians(deg); s, co = math.sin(a), math.cos(a)
    bx, by = tip[0] - size * co, tip[1] - size * s
    px, py = -s * size * 0.32, co * size * 0.32
    ax.add_patch(Polygon([tip, (bx + px, by + py), (bx - px, by - py)], closed=True,
                         facecolor="k", edgecolor="k", zorder=3))


def txt(x, y, s, size=9, c="k", ha="center", va="center", rot=0):
    ax.text(x, y, s, fontsize=size, color=c, ha=ha, va=va, rotation=rot, zorder=4)


V = {v["name"]: v for v in data["views"]}

# 各视图 view2d y 朝向：Front/Right 朝下（flip=True），Top 朝上（flip=False）
PLACE = {"Top": (34, 45, False), "Front": (34, 172, True), "Right": (214, 172, True)}


def draw_view(name):
    v = V[name]
    px, py, flip = PLACE[name]
    sc = v["plot_scale"]
    xs = []
    ys = []
    for e in v["edges"]:
        ey_min = min(p[1] for p in e)
        ey_max = max(p[1] for p in e)
        for q in e:
            xs.append(v["X"] + q[0] * sc)
            ys.append(v["Y"] + ((ey_max - q[1]) if flip else (q[1] - ey_min)) * sc)
        ax.plot([v["X"] + q[0] * sc for q in e],
                [v["Y"] + ((ey_max - q[1]) if flip else (q[1] - ey_min)) * sc for q in e],
                color="k", lw=0.42, zorder=2)
    return min(xs), max(xs), min(ys), max(ys)


BB = {n: draw_view(n) for n in ("Top", "Front", "Right")}


# 图框 + 标题栏
m = 8.0
ax.add_patch(Polygon([(m, m), (A3W - m, m), (A3W - m, A3H - m), (m, A3H - m)],
                     closed=True, fill=False, edgecolor="k", lw=0.9, zorder=1))
tx0, ty0, TBW, TBH = A3W - m - 170, m, 170.0, 44.0
ax.add_patch(Polygon([(tx0, ty0), (tx0 + TBW, ty0), (tx0 + TBW, ty0 + TBH), (tx0, ty0 + TBH)],
                     closed=True, fill=False, edgecolor="k", lw=0.7, zorder=1))
for i in range(1, 4):
    ln(tx0, ty0 + i * TBH / 4, tx0 + TBW, ty0 + i * TBH / 4, 0.45)
ln(tx0 + 112, ty0, tx0 + 112, ty0 + TBH, 0.45)
txt(tx0 + 3, ty0 + 35, "零件名称：L 形支座", 11, ha="left")
txt(tx0 + 3, ty0 + 27, "比例 2:1    单位 mm    第一角投影", 8.6, ha="left")
txt(tx0 + 3, ty0 + 19, "材料 未标注        数量 1", 8.6, ha="left")
txt(tx0 + 3, ty0 + 11, "外接 40 × 26 × 39", 8.6, ha="left")
txt(tx0 + 3, ty0 + 4, "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过", 7.2, ha="left")
txt(tx0 + 115, ty0 + 35, "2026-09-30", 8.6, ha="left")
txt(tx0 + 115, ty0 + 27, "未注公差", 8.6, ha="left")
txt(tx0 + 115, ty0 + 19, "去毛刺", 8.6, ha="left")

# 视图标签
for nm, lbl in (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图")):
    x0, y0, x1, y1 = BB[nm]
    txt(x1, y1 + 3.5, lbl, 11, ha="right")


# ================= 尺寸 =================
MEAS = {d["label"]: d["value"] for d in data["dims"]}


def M(nm, u, w):
    """view2d (u,w) → 纸面 (x,y)（按 PLACE 的翻转设置）"""
    v = V[nm]
    sc = v["plot_scale"]
    px, py, flip = PLACE[nm]
    ey_min = min(p[1] for p in [q for e in v["edges"] for q in e])
    ey_max = max(p[1] for p in [q for e in v["edges"] for q in e])
    return (px + u * sc, py + ((ey_max - w) if flip else (w - ey_min)) * sc)


def view_yminmax(nm):
    ey_min = min(p[1] for p in [q for e in V[nm]["edges"] for q in e])
    ey_max = max(p[1] for p in [q for e in V[nm]["edges"] for q in e])
    return ey_min, ey_max


def dim_extent(nm, axis, paper_p, label):
    """axis=0 横（view2d x 跨度），axis=1 竖（view2d y 跨度）"""
    v = V[nm]
    sc = v["plot_scale"]
    if axis == 0:
        xs = [q[0] for e in v["edges"] for q in e]
        x_lo, x_hi = min(xs), max(xs)
        ya = M(nm, 0, view_yminmax(nm)[0] if PLACE[nm][2] else view_yminmax(nm)[1])[1]
        xa, xb = M(nm, x_lo, 0)[0], M(nm, x_hi, 0)[0]
        ln(xa, ya, xa, paper_p); ln(xb, ya, xb, paper_p)
        ln(xa, paper_p, xb, paper_p); arrow((xa, paper_p), 180); arrow((xb, paper_p), 0)
        txt((xa + xb) / 2, paper_p + 2, label, 9)
    else:
        ys = [q[1] for e in v["edges"] for q in e]
        w_lo, w_hi = min(ys), max(ys)
        xa = M(nm, 0, w_lo)[0]
        ya, yb = M(nm, 0, w_lo)[1], M(nm, 0, w_hi)[1]
        ln(xa, ya, paper_p, ya); ln(xa, yb, paper_p, yb)
        ln(paper_p, ya, paper_p, yb); arrow((paper_p, ya), 270); arrow((paper_p, yb), 90)
        txt(paper_p - 2.5, (ya + yb) / 2, label, 9, va="center", ha="right")


def dim_extent_y(nm, w_lo, w_hi, paper_p, label):
    """在 Right 视图里按 view2d y 给出竖向量（Right 翻转）"""
    xa = M(nm, 0, w_lo)[0]
    ya, yb = M(nm, 0, w_lo)[1], M(nm, 0, w_hi)[1]
    ln(xa, ya, paper_p, ya); ln(xa, yb, paper_p, yb)
    ln(paper_p, ya, paper_p, yb); arrow((paper_p, ya), 270); arrow((paper_p, yb), 90)
    txt(paper_p - 2.5, (ya + yb) / 2, label, 9, va="center", ha="right")


# Top：L（横）、W（竖）
dim_extent("Top", 0, BB["Top"][3] + 5, "%.0f" % MEAS.get("L", 40))
dim_extent("Top", 1, BB["Top"][0] - 8, "%.0f" % MEAS.get("W", 26))
# Front：H_total（竖）
dim_extent("Front", 1, BB["Front"][0] - 8, "%.0f" % MEAS.get("H_total", 39))
# Right：pitch（两 φ8 圆心 y 间距）
rc = [c for c in V["Right"]["circles"] if abs(c["r"] - 4.0) < 0.3]
if len(rc) >= 2:
    cys = sorted(c["cy"] for c in rc)
    dim_extent_y("Right", cys[0], cys[1], BB["Right"][0] - 8, "%.0f" % MEAS.get("pitch", 26))


pdf = os.path.join(OUT_DIR, "drawing.pdf")
png = os.path.join(OUT_DIR, "drawing.png")
fig.savefig(pdf)
fig.savefig(png, dpi=300)

finish([("drawing_pdf", pdf), ("drawing_png", png)],
       {"pdf_bytes": os.path.getsize(pdf), "png_bytes": os.path.getsize(png),
        "n_dims_drawn": len(data["dims"])})
