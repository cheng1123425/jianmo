# -*- coding: utf-8 -*-
r"""铰链支座 —— 出 A3 工程图（三视图 + 尺寸标注）→ PNG + 矢量 PDF

视图几何来自 `_bracket_data.json`（FreeCAD TechDraw 对 STEP 实体的 HLR 投影，真投影非描图）。
尺寸值取自图纸标注，且已由 bracket_verify.py 闭环校核通过。
坐标一律用 TechDraw 的 `view2d` 坐标（脚本末尾附各视图的实测范围）。
"""
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(HERE, "_bracket_data.json"), encoding="utf-8"))
V = {v["name"]: v for v in data["views"]}

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

A3W, A3H = 420.0, 297.0
SC, LW, AR = 2.0, 0.32, 2.6                 # 比例 2:1 / 线宽 / 箭头长(mm)
#   第三项 = 是否翻转 y。FreeCAD 各视图的 view2d y 朝向不一致（实测）：
#   Front/Right 的 w 随 Z 增大而减小 → 画到纸上要翻转；Top 的 w 已朝上 → 不翻转
PLACE = {"Front": (34, 172, True), "Right": (214, 172, True), "Top": (34, 45, False)}

fig = plt.figure(figsize=(A3W / 25.4, A3H / 25.4))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, A3W); ax.set_ylim(0, A3H)
ax.set_aspect("equal"); ax.axis("off")


def ln(x0, y0, x1, y1, w=LW, c="k", z=2):
    ax.plot([x0, x1], [y0, y1], color=c, lw=w, solid_capstyle="butt", zorder=z)


def arrow(tip, deg, size=AR):
    a = math.radians(deg); s, co = math.sin(a), math.cos(a)
    bx, by = tip[0] - size * co, tip[1] - size * s
    px, py = -s * size * 0.32, co * size * 0.32
    ax.add_patch(Polygon([tip, (bx + px, by + py), (bx - px, by - py)], closed=True,
                         facecolor="k", edgecolor="none", zorder=3))


def txt(x, y, s, size=8.6, ha="center", va="center", c="k"):
    ax.text(x, y, s, fontsize=size, ha=ha, va=va, color=c, zorder=5)


# ---------- 各视图 view2d 范围 & → 纸面映射（统一翻转 y：view2d 的 y 向上为正，直接映射） ----------
BB = {}
for nm, v in V.items():
    xs = [p[0] for e in v["edges"] for p in e]
    ys = [p[1] for e in v["edges"] for p in e]
    BB[nm] = (min(xs), max(xs), min(ys), max(ys))


def M(nm, u, w):
    """view2d (u,w) → 纸面 (x,y)（按 PLACE 的翻转设置）"""
    x0, x1, y0, y1 = BB[nm]
    px, py, flip = PLACE[nm]
    return (px + (u - x0) * SC, py + ((y1 - w) if flip else (w - y0)) * SC)


def RECT(nm):
    """视图在纸面的矩形 (x0,y0,x1,y1)"""
    px, py, _ = PLACE[nm]
    return px, py, px + (BB[nm][1] - BB[nm][0]) * SC, py + (BB[nm][3] - BB[nm][2]) * SC


# ---------- 图框 + 标题栏 ----------
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
txt(tx0 + 3, ty0 + 4,  "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过", 7.2, ha="left")
txt(tx0 + 115, ty0 + 35, "2026-09-29", 8.6, ha="left")
txt(tx0 + 115, ty0 + 27, "未注公差", 8.6, ha="left")
txt(tx0 + 115, ty0 + 19, "去毛刺", 8.6, ha="left")

# ---------- 画三视图 ----------
for nm, v in V.items():
    for e in v["edges"]:
        pts = [M(nm, p[0], p[1]) for p in e]
        ax.plot([q[0] for q in pts], [q[1] for q in pts], color="k", lw=0.42, zorder=2)
for nm, label in (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图")):
    x0, y0, x1, y1 = RECT(nm)
    txt(x1, y1 + 3.5, label, 11, ha="right")


# ---------- 尺寸工具（位置用纸面 mm，指向点用 view2d） ----------
def dim_h(nm, ua, ub, y, label, size=8.6):
    """水平尺寸线：xa/xb 由 view2d u 映射，y 为纸面高度"""
    xa, xb = M(nm, ua, 0)[0], M(nm, ub, 0)[0]
    _, vy0, _, vy1 = RECT(nm)
    ey = vy0 if y < vy0 else (vy1 if y > vy1 else y)
    ln(xa, ey, xa, y); ln(xb, ey, xb, y)
    ln(xa, y, xb, y); arrow((xa, y), 180); arrow((xb, y), 0)
    txt((xa + xb) / 2, y + 1.8, label, size, va="bottom")


def dim_h_below(nm, ua, ub, off, label, size=8.6):
    x0, y0, x1, y1 = RECT(nm)
    dim_h(nm, ua, ub, y0 - off, label, size)


def dim_h_above(nm, ua, ub, off, label, size=8.6):
    x0, y0, x1, y1 = RECT(nm)
    dim_h(nm, ua, ub, y1 + off, label, size)


def dim_v(nm, wa, wb, x, label, size=8.6, left=True):
    """竖直尺寸线：ya/yb 由 view2d w 映射，x 为纸面横坐标"""
    ya, yb = M(nm, 0, wa)[1], M(nm, 0, wb)[1]
    x0, vy0, x1, vy1 = RECT(nm)
    ex = x0 if x < x0 else (x1 if x > x1 else x)
    ln(ex, ya, x, ya); ln(ex, yb, x, yb)
    ln(x, ya, x, yb); arrow((x, ya), 270); arrow((x, yb), 90)
    txt(x + (-1.8 if left else 1.8), (ya + yb) / 2, label, size, va="center",
        ha="right" if left else "left")


def leader(nm, uw, text, off, size=8.6):
    tx, ty = M(nm, uw[0], uw[1])
    lx, ly = tx + off[0], ty + off[1]
    ln(lx, ly, tx, ty)
    arrow((tx, ty), math.degrees(math.atan2(ty - ly, tx - lx)) + 180)
    txt(lx, ly + 2.6, text, size)


# ---- 正视图：上 28/16，右 8，下 45/62，引出 2-φ6 / 2-φ3 ----
dim_h_above("Front", -14, 14, 8, "28")
dim_h_above("Front", -8, 8, 17, "16")
dim_v("Front", 18.5, 10.5, RECT("Front")[2] + 11, "8", left=False)   # 底板厚
dim_h_below("Front", -22.5, 22.5, 10, "45")
dim_h_below("Front", -31, 31, 20, "62")
leader("Front", (-11, -8.5), "2-φ6", (-30, 13))
leader("Front", (11, -8.5), "2-φ3", (20, -20))

# ---- 侧视图：左 27，右 14，下 36，引出 R10 / 2-φ8 ----
#   view2d w 与 Z 的关系实测：w = 18.5 − Z  → Z0→18.5、Z8→10.5、Z14→4.5、Z27→−8.5
dim_v("Right", 18.5, -8.5, RECT("Right")[0] - 11, "27")            # 圆心高 27
dim_v("Right", 18.5, 4.5, RECT("Right")[2] + 11, "14", left=False)  # 右端总高 14
dim_h_below("Right", -13, 23, 11, "36")        # 圆心(u=−13) → 右端(u=+23)，实测 36
leader("Right", (-20.1, -1.4), "R10", (-27, 26))   # 指向圆头弧上一点（距圆心 10）
leader("Right", (-13, -8.5), "2-φ8", (32, 10))

# ---- 俯视图：引出 2-φ9 ----
leader("Top", (22.5, -11), "2-φ9", (26, 26))

png = os.path.join(HERE, "bracket_drawing.png")
pdf = os.path.join(HERE, "bracket_drawing.pdf")
fig.savefig(png, dpi=300)
fig.savefig(pdf)
for nm in ("Front", "Right", "Top"):
    print("[view2d] %-6s x[%7.2f,%7.2f]  y[%7.2f,%7.2f]" % (nm, *BB[nm]))
print("[out]", png, os.path.getsize(png), "bytes")
print("[out]", pdf, os.path.getsize(pdf), "bytes")
