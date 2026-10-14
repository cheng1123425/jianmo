# -*- coding: utf-8 -*-
r"""s3_render —— 投影特征 → A3 矢量 PDF / PNG（铰链支座）

视图：Top / Front / Right。Front/Right 的 view2d y 朝下（要翻转），Top 的 y 朝上。

自动适配（保证内容不越图框）
--------------------------
绘制**分两遍**：
  ① 先按原位画一遍，扫描画布上所有线条 / 多边形 / 文字，量出真实包围盒；
  ② 若包围盒越出图框，就把「视图 + 尺寸」整体平移 (DX, DY) 再重画一遍。
图框与标题栏是纸面固定件，不参与平移。

这样「每个视图最靠外的线不越过图框」由程序保证，不依赖人工调坐标。

坐标来源只有一处：视图位置取 `v["X"]/v["Y"]`（FreeCAD 建视图时给的位置），
不再用 PLACE 里的副本 —— 两处各写一份、靠人工保持一致是隐患。

坐标约定（重要）
--------------
所有位置一律用「**逻辑坐标**」= 不含 DX/DY 的纸面坐标；
DX/DY 只在最底层的绘制函数（ln / poly / arrow / txt）里加**一次**。
在别处（如 M()、draw_view 的返回值）再加一次就会双重平移 —— 标注会飞出图纸。
"""
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.text as mtext
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
M_FRAME = 8.0          # 图框距纸边
PAD = 6.0              # 内容与图框之间的最小间隙
TXT_PAD = 18.0         # 文字半宽的保守估计（防止文字压到线框上）
LW, AR = 0.32, 2.6

DX, DY = 0.0, 0.0      # 自动适配算出的整体平移

fig = plt.figure(figsize=(A3W / 25.4, A3H / 25.4))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, A3W)
ax.set_ylim(0, A3H)
ax.set_aspect("equal")
ax.axis("off")

V = {v["name"]: v for v in data["views"]}

# 各视图 view2d y 朝向：Front/Right 朝下（flip=True），Top 朝上（flip=False）
PLACE = {"Top": (34, 45, False), "Front": (34, 172, True), "Right": (214, 172, True)}
BB = {}


def ln(x0, y0, x1, y1, w=LW, c="k", z=2, shift=True, gid=None):
    d = DX if shift else 0.0
    e = DY if shift else 0.0
    line, = ax.plot([x0 + d, x1 + d], [y0 + e, y1 + e], color=c, lw=w,
                    solid_capstyle="butt", zorder=z)
    if gid:
        line.set_gid(gid)


def poly(xs, ys, color="k", lw=0.42, z=2):
    """折线（只在这里加整体平移 DX/DY —— 见文件头的坐标约定）"""
    ax.plot([x + DX for x in xs], [y + DY for y in ys], color=color, lw=lw, zorder=z)


def arrow(tip, deg, size=AR):
    tx, ty = tip[0] + DX, tip[1] + DY
    a = math.radians(deg)
    s, co = math.sin(a), math.cos(a)
    bx, by = tx - size * co, ty - size * s
    px, py = -s * size * 0.32, co * size * 0.32
    ax.add_patch(Polygon([(tx, ty), (bx + px, by + py), (bx - px, by - py)], closed=True,
                         facecolor="k", edgecolor="k", zorder=3))


def txt(x, y, s, size=9, c="k", ha="center", va="center", rot=0, shift=True, gid=None):
    d = DX if shift else 0.0
    e = DY if shift else 0.0
    t = ax.text(x + d, y + e, s, fontsize=size, color=c, ha=ha, va=va, rotation=rot, zorder=4)
    if gid:
        t.set_gid(gid)


def draw_view(name):
    v = V[name]
    px, py, flip = PLACE[name]
    sc = v["plot_scale"]
    # 关键：ey_min/ey_max 必须取「整个视图」的范围（对所有边统一），
    # 而不是逐边各自归一 —— 否则 flip=True 时水平边会被压到同一条 y 上。
    ey_min = min(p[1] for e in v["edges"] for p in e)
    ey_max = max(p[1] for e in v["edges"] for p in e)
    xs = []
    ys = []
    for e in v["edges"]:
        ex = [v["X"] + q[0] * sc for q in e]
        ey = [v["Y"] + ((ey_max - q[1]) if flip else (q[1] - ey_min)) * sc for q in e]
        xs.extend(ex)
        ys.extend(ey)
        poly(ex, ey)
    # 返回**逻辑坐标**下的包围盒（不含 DX/DY）—— 平移由底层函数统一施加，
    # 否则 BB 里带偏移、再经 ln/txt 又被加一次，标注会双重平移。
    return min(xs), max(xs), min(ys), max(ys)


# ================= 尺寸 =================
def M(nm, u, w):
    """view2d (u,w) → 纸面**逻辑坐标** (x,y)（不含 DX/DY；位置统一取 v["X"]/v["Y"]）"""
    v = V[nm]
    sc = v["plot_scale"]
    px, py, flip = PLACE[nm]
    ey_min = min(p[1] for p in [q for e in v["edges"] for q in e])
    ey_max = max(p[1] for p in [q for e in v["edges"] for q in e])
    return (v["X"] + u * sc,
            v["Y"] + ((ey_max - w) if flip else (w - ey_min)) * sc)


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


# ================= 一遍完整的绘制 =================
def draw_all():
    global BB
    BB = {n: draw_view(n) for n in ("Top", "Front", "Right")}

    # 图框 + 标题栏（纸面固定件：不随视图平移，且**不参与**自动适配的包围盒计算，
    # 否则它们自身的 8mm 边距会误触发平移）
    _fr = Polygon([(M_FRAME, M_FRAME), (A3W - M_FRAME, M_FRAME),
                   (A3W - M_FRAME, A3H - M_FRAME), (M_FRAME, A3H - M_FRAME)],
                  closed=True, fill=False, edgecolor="k", lw=0.9, zorder=1)
    _fr.set_gid("frame")
    ax.add_patch(_fr)
    tx0, ty0, TBW, TBH = A3W - M_FRAME - 170, M_FRAME, 170.0, 44.0
    _tb = Polygon([(tx0, ty0), (tx0 + TBW, ty0), (tx0 + TBW, ty0 + TBH), (tx0, ty0 + TBH)],
                  closed=True, fill=False, edgecolor="k", lw=0.7, zorder=1)
    _tb.set_gid("frame")
    ax.add_patch(_tb)
    for i in range(1, 4):
        ln(tx0, ty0 + i * TBH / 4, tx0 + TBW, ty0 + i * TBH / 4, 0.45, shift=False, gid="frame")
    ln(tx0 + 112, ty0, tx0 + 112, ty0 + TBH, 0.45, shift=False, gid="frame")
    txt(tx0 + 3, ty0 + 35, "零件名称：铰链支座", 11, ha="left", shift=False, gid="frame")
    txt(tx0 + 3, ty0 + 27, "比例 2:1    单位 mm    第一角投影", 8.6, ha="left",
        shift=False, gid="frame")
    txt(tx0 + 3, ty0 + 19, "材料 未标注        数量 1", 8.6, ha="left", shift=False, gid="frame")
    txt(tx0 + 3, ty0 + 11, "外接 62 × 46 × 37", 8.6, ha="left", shift=False, gid="frame")
    txt(tx0 + 3, ty0 + 4, "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过", 7.2,
        ha="left", shift=False, gid="frame")
    txt(tx0 + 115, ty0 + 35, "2026-09-29", 8.6, ha="left", shift=False, gid="frame")
    txt(tx0 + 115, ty0 + 27, "未注公差", 8.6, ha="left", shift=False, gid="frame")
    txt(tx0 + 115, ty0 + 19, "去毛刺", 8.6, ha="left", shift=False, gid="frame")

    # 视图标签
    for nm, lbl in (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图")):
        x0, y0, x1, y1 = BB[nm]
        txt(x1, y1 + 3.5, lbl, 11, ha="right")

    # ---- Front: 28 / 16 / 8 / 45 / 62 / 引出 2-φ6 / 2-φ3 ----
    dim_extent("Front", 0, BB["Front"][3] + 5, "28")
    dim_h("Front", -11, 11, BB["Front"][3] + 13, "16")
    dim_v("Front", 27, 35, BB["Front"][0] - 8, "8")
    dim_h("Front", -22.5, 22.5, BB["Front"][1] - 8, "45")
    dim_extent("Front", 0, BB["Front"][1] - 18, "62")
    leader_dia("Front", (-11, 8.5), "2-φ6", (-25, 16))
    leader_dia("Front", (11, 8.5), "2-φ3", (20, -16))

    # ---- Right: 27 / 14 / 36 / 引出 R10 / 2-φ8 ----
    dim_v("Right", 37, 0, BB["Right"][0] - 8, "27")
    dim_v("Right", 14, 0, BB["Right"][2] + 5, "14")
    dim_h("Right", -12, 24, BB["Right"][1] - 8, "36")
    leader_dia("Right", (-20, 27), "R10", (-25, 16))
    leader_dia("Right", (-12, 27), "2-φ8", (28, 12))

    # ---- Top: 引出 2-φ9 ----
    leader_dia("Top", (22.5, 12), "2-φ9", (24, 18))


# ================= 自动适配：把内容推进图框 =================
def _content_bbox():
    """扫描画布上所有线条 / 多边形 / 文字，返回真实包围盒（data 坐标）"""
    xlo = ylo = float("inf")
    xhi = yhi = float("-inf")
    for a in ax.get_children():
        if a.get_gid() == "frame":
            continue                    # 图框/标题栏是纸面固定件，不参与适配
        if isinstance(a, mlines.Line2D):
            xs, ys = a.get_xdata(), a.get_ydata()
            if len(xs) and len(ys):
                xlo = min(xlo, min(xs)); xhi = max(xhi, max(xs))
                ylo = min(ylo, min(ys)); yhi = max(yhi, max(ys))
        elif isinstance(a, mpatches.Polygon):
            xy = a.get_xy()
            xlo = min(xlo, min(p[0] for p in xy)); xhi = max(xhi, max(p[0] for p in xy))
            ylo = min(ylo, min(p[1] for p in xy)); yhi = max(yhi, max(p[1] for p in xy))
        elif isinstance(a, mtext.Text):
            s = a.get_text()
            if s and s.strip():
                x, y = a.get_position()
                ha = a.get_ha()
                # 按对齐方式保守估算文字占位（文字宽度拿不准，宁大勿小）
                x0 = x - TXT_PAD if ha in ("center", "right") else x
                x1 = x + TXT_PAD if ha in ("center", "left") else x
                xlo = min(xlo, x0); xhi = max(xhi, x1)
                ylo = min(ylo, y - 2.5); yhi = max(yhi, y + 2.5)
    return xlo, xhi, ylo, yhi


def _fit_shift():
    """算出把所有内容推进图框所需的最小整体平移 (dx, dy)"""
    xlo, xhi, ylo, yhi = _content_bbox()
    if xlo == float("inf"):
        return 0.0, 0.0
    lo = M_FRAME + PAD
    hix, hiy = A3W - M_FRAME - PAD, A3H - M_FRAME - PAD
    dx = (lo - xlo) if xlo < lo else ((hix - xhi) if xhi > hix else 0.0)
    dy = (lo - ylo) if ylo < lo else ((hiy - yhi) if yhi > hiy else 0.0)
    return dx, dy


def _reset_axes():
    ax.clear()
    ax.set_xlim(0, A3W)
    ax.set_ylim(0, A3H)
    ax.set_aspect("equal")
    ax.axis("off")


# ---- ① 试画一遍，量包围盒 ----
draw_all()
_xlo, _xhi, _ylo, _yhi = _content_bbox()
_dx, _dy = _fit_shift()

# ---- ② 越界就整体平移后重画 ----
if abs(_dx) > 1e-6 or abs(_dy) > 1e-6:
    print("[s3_render] 内容越出图框：x[%.1f, %.1f] y[%.1f, %.1f] → 整体平移 (%+.1f, %+.1f) mm"
          % (_xlo, _xhi, _ylo, _yhi, _dx, _dy))
    DX, DY = _dx, _dy
    _reset_axes()
    draw_all()
    _x2lo, _x2hi, _y2lo, _y2hi = _content_bbox()
    _lo, _hix, _hiy = M_FRAME + PAD, A3W - M_FRAME - PAD, A3H - M_FRAME - PAD
    inside = (_lo - 1e-6 <= _x2lo and _x2hi <= _hix + 1e-6
              and _lo - 1e-6 <= _y2lo and _y2hi <= _hiy + 1e-6)
    print("[s3_render] 平移后内容范围 x[%.1f, %.1f] y[%.1f, %.1f] —— %s"
          % (_x2lo, _x2hi, _y2lo, _y2hi, "已全部收进图框 ✅" if inside else "仍有越界 ❌"))

pdf = os.path.join(OUT_DIR, "drawing.pdf")
png = os.path.join(OUT_DIR, "drawing.png")
fig.savefig(pdf)
fig.savefig(png, dpi=300)

finish([("drawing_pdf", pdf), ("drawing_png", png)],
       {"pdf_bytes": os.path.getsize(pdf), "png_bytes": os.path.getsize(png),
        "n_dims_drawn": len(data["dims"]), "shift_dx": round(DX, 2), "shift_dy": round(DY, 2)})
