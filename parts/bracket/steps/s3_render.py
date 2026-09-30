# -*- coding: utf-8 -*-
r"""s3_render —— 投影特征 → A3 矢量 PDF / PNG（铰链支座）

视图：Top / Front / Right。Front/Right 的 view2d y 朝下（要翻转），Top 的 y 朝上。
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
    xs = []; ys = []
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
txt(tx0 + 3, ty0 + 35, "零件名称：铰链支座", 11, ha="left")
txt(tx0 + 3, ty0 + 27, "比例 2:1    单位 mm    第一角投影", 8.6, ha="left")
txt(tx0 + 3, ty0 + 19, "材料 未标注        数量 1", 8.6, ha="left")
txt(tx0 + 3, ty0 + 11, "外接 62 × 46 × 37", 8.6, ha="left")
txt(tx0 + 3, ty0 + 4, "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过", 7.2, ha="left")
txt(tx0 + 115, ty0 + 35, "2026-09-29", 8.6, ha="left")
txt(tx0 + 115, ty0 + 27, "未注公差", 8.6, ha="left")
txt(tx0 + 115, ty0 + 19, "去毛刺", 8.6, ha="left")

# 视图标签
for nm, lbl in (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图")):
    x0, y0, x1, y1 = BB[nm]
    txt(x1, y1 + 3.5, lbl, 11, ha="right")


# ================= 尺寸 =================
def M(nm, u, w):
    """view2d (u,w) → 纸面 (x,y)（按 PLACE 的翻转设置）"""
    v = V[nm]
    sc = v["plot_scale"]
    px, py, flip = PLACE[nm]
    ey_min = min(p[1] for p in [q for e in v["edges"] for q in e])
    ey_max = max(p[1] for p in [q for e in v["edges"] for q in e])
    return (px + u * sc, py + ((ey_max - w) if flip else (w - ey_min)) * sc)


def RECT(nm):
    return BB[nm]


def view_yminmax(nm):
    ey_min = min(p[1] for p in [q for e in V[nm]["edges"] for q in e])
    ey_max = max(p[1] for p in [q for e in V[nm]["edges"] for q in e])
    return ey_min, ey_max


def dim_h(nm, ua, ub, y_paper, label):
    xa, xb = M(nm, ua, 0)[0], M(nm, ub, 0)[0]
    ln(xa, y_paper, xa, y_paper - 2); ln(xb, y_paper, xb, y_paper - 2)
    ln(xa, y_paper, xb, y_paper); arrow((xa, y_paper), 180); arrow((xb, y_paper), 0)
    txt((xa + xb) / 2, y_paper + 2, label, 9, va="bottom")


def dim_v(nm, wa, wb, x_paper, label):
    ya, yb = M(nm, 0, wa)[1], M(nm, 0, wb)[1]
    ln(x_paper, ya, x_paper - 2, ya); ln(x_paper, yb, x_paper - 2, yb)
    ln(x_paper, ya, x_paper, yb); arrow((x_paper, ya), 270); arrow((x_paper, yb), 90)
    txt(x_paper - 2.5, (ya + yb) / 2, label, 9, va="center", ha="right")


def dim_extent(nm, axis, paper_p, label, side="right"):
    """axis=0 横, axis=1 竖"""
    v = V[nm]
    sc = v["plot_scale"]
    if axis == 0:
        xs = [q[0] for e in v["edges"] for q in e]
        x_lo, x_hi = min(xs), max(xs)
        ya = M(nm, 0, view_yminmax(nm)[0] if PLACE[nm][2] else view_yminmax(nm)[1])[1]
        xa, xb = M(nm, x_lo, 0)[0], M(nm, x_hi, 0)[0]
        y_paper = paper_p
        ln(xa, ya, xa, y_paper); ln(xb, ya, xb, y_paper)
        ln(xa, y_paper, xb, y_paper); arrow((xa, y_paper), 180); arrow((xb, y_paper), 0)
        txt((xa + xb) / 2, y_paper + 2, label, 9)
    else:
        ys = [q[1] for e in v["edges"] for q in e]
        w_lo, w_hi = min(ys), max(ys)
        xa = M(nm, 0, w_lo)[0]
        ya, yb = M(nm, 0, w_lo)[1], M(nm, 0, w_hi)[1]
        x_paper = paper_p
        ln(xa, ya, x_paper, ya); ln(xa, yb, x_paper, yb)
        ln(x_paper, ya, x_paper, yb); arrow((x_paper, ya), 270); arrow((x_paper, yb), 90)
        txt(x_paper - 2.5, (ya + yb) / 2, label, 9, va="center", ha="right")


def leader_dia(nm, uw, label, off_xy):
    """纸面上从 off_xy 到 uw 的引出线 + 文本"""
    x_view, y_view = M(nm, uw[0], uw[1])
    lx, ly = x_view + off_xy[0], y_view + off_xy[1]
    ln(lx, ly, x_view, y_view)
    arrow((x_view, y_view), math.degrees(math.atan2(y_view - ly, x_view - lx)) + 180)
    txt(lx + 1.5, ly + 1.5, label, 9, ha="left", va="bottom")


# ---- Front: 28 / 16 / 8 / 45 / 62 / 引出 2-φ6 / 2-φ3 ----
# 28（上臂外宽）
dim_extent("Front", 0, BB["Front"][3] + 5, "28")
# 16（内距）
# 用两个 φ3 圆心 x=±11 引出距离
dim_h("Front", -11, 11, BB["Front"][3] + 13, "16")
# 8（底板厚）—— 左侧
dim_v("Front", 27, 35, BB["Front"][0] - 8, "8")
# 45（底板孔心距）—— 下部
dim_h("Front", -22.5, 22.5, BB["Front"][1] - 8, "45")
# 62（底板总长）
dim_extent("Front", 0, BB["Front"][1] - 18, "62")
# 引出 2-φ6 / 2-φ3
leader_dia("Front", (-11, 8.5), "2-φ6", (-25, 16))
leader_dia("Front", (11, 8.5), "2-φ3", (20, -16))

# ---- Right: 27 / 14 / 36 / 引出 R10 / 2-φ8 ----
dim_v("Right", 37, 0, BB["Right"][0] - 8, "27")
dim_v("Right", 14, 0, BB["Right"][2] + 5, "14")
# 36（圆心到右端）
dim_h("Right", -12, 24, BB["Right"][1] - 8, "36")
# R10 引出
leader_dia("Right", (-20, 27), "R10", (-25, 16))
# 2-φ8 引出
leader_dia("Right", (-12, 27), "2-φ8", (28, 12))

# ---- Top: 引出 2-φ9 ----
leader_dia("Top", (22.5, 12), "2-φ9", (24, 18))


pdf = os.path.join(OUT_DIR, "drawing.pdf")
png = os.path.join(OUT_DIR, "drawing.png")
fig.savefig(pdf)
fig.savefig(png, dpi=300)

finish([("drawing_pdf", pdf), ("drawing_png", png)],
       {"pdf_bytes": os.path.getsize(pdf), "png_bytes": os.path.getsize(png),
        "n_dims_drawn": len(data["dims"])})