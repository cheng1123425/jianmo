# -*- coding: utf-8 -*-
r"""lib/drawing_render.py —— A3 工程图渲染的**通用骨架**（零件无关）

被各零件的 `steps/s3_render.py` 调用。零件只提供三样东西：

| 提供 | 内容 |
|---|---|
| `place` | 视图布局：哪个视图放纸面什么位置、是否上下翻转 |
| `title` | 标题栏文字（零件名 / 比例 / 材料 / 外接 / 日期） |
| `dims`  | 标注清单（声明式，见下） |

本模块负责（四个零件原本一字不差、各复制一份的那部分）：
  * A3 画布 / 图框 / 标题栏
  * 绘制工具（线、折线、箭头、文字）
  * **自动适配**：保证所有内容（视图 + 标注 + 文字）不越图框 —— 见 `_fit_shift()`

坐标约定（重要）
--------------
所有位置一律用「**逻辑坐标**」= 不含 DX/DY 的纸面坐标；
DX/DY 只在最底层的绘制函数（ln / poly / arrow / txt）里加**一次**。
在别处再加一次就会双重平移 —— 标注会飞出纸面。

标注清单 `dims` 的条目格式
-------------------------
```python
{"kind": "extent", "view": "Front", "axis": 0, "at": ("BB", 3, +5), "label": "28"}
{"kind": "h",      "view": "Front", "ua": -11, "ub": 11, "at": ("BB", 3, +13), "label": "16"}
{"kind": "v",      "view": "Front", "wa": 27, "wb": 35, "at": ("BB", 0, -8),  "label": "8"}
{"kind": "extent_y","view": "Right", "wa": 0, "wb": 37, "at": ("BB", 0, -8),  "label": "27"}
{"kind": "leader", "view": "Front", "uw": (-11, 8.5), "off": (-25, 16),       "label": "2-φ6"}
```
`at = (source, index, offset)`：`("BB", 3, +5)` 即 `BB[view][3] + 5`（BB = 该视图的纸面包围盒）。
"""
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.text as mtext
from matplotlib.patches import Polygon

A3W, A3H = 420.0, 297.0
M_FRAME = 8.0          # 图框距纸边
PAD = 6.0              # 内容与图框之间的最小间隙
TXT_PAD = 18.0         # 文字半宽的保守估计（防止文字压到线框上）
TITLE_W, TITLE_H = 170.0, 44.0


class Renderer(object):
    """一张 A3 工程图的渲染器。所有绘制都经由它，DX/DY 只在底层加一次。"""

    def __init__(self, view_lw=0.42, lw=0.32, ar=2.6):
        self.fig = plt.figure(figsize=(A3W / 25.4, A3H / 25.4))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self._setup()
        self.dx = self.dy = 0.0
        self.view_lw = view_lw
        self.lw = lw
        self.ar = ar

    def _setup(self):
        self.ax.set_xlim(0, A3W)
        self.ax.set_ylim(0, A3H)
        self.ax.set_aspect("equal")
        self.ax.axis("off")

    # ---------------- 底层绘制（唯一施加 DX/DY 的地方）----------------
    def ln(self, x0, y0, x1, y1, w=None, c="k", z=2, shift=True, gid=None):
        w = self.lw if w is None else w
        d = self.dx if shift else 0.0
        e = self.dy if shift else 0.0
        line, = self.ax.plot([x0 + d, x1 + d], [y0 + e, y1 + e], color=c, lw=w,
                             solid_capstyle="butt", zorder=z)
        if gid:
            line.set_gid(gid)

    def poly(self, xs, ys, color="k", lw=None, z=2):
        lw = self.view_lw if lw is None else lw
        self.ax.plot([x + self.dx for x in xs], [y + self.dy for y in ys],
                     color=color, lw=lw, zorder=z)

    def arrow(self, tip, deg, size=None):
        size = self.ar if size is None else size
        tx, ty = tip[0] + self.dx, tip[1] + self.dy
        a = math.radians(deg)
        s, co = math.sin(a), math.cos(a)
        bx, by = tx - size * co, ty - size * s
        px, py = -s * size * 0.32, co * size * 0.32
        self.ax.add_patch(Polygon([(tx, ty), (bx + px, by + py), (bx - px, by - py)],
                                  closed=True, facecolor="k", edgecolor="k", zorder=3))

    def txt(self, x, y, s, size=9, c="k", ha="center", va="center", rot=0,
            shift=True, gid=None):
        d = self.dx if shift else 0.0
        e = self.dy if shift else 0.0
        t = self.ax.text(x + d, y + e, s, fontsize=size, color=c, ha=ha, va=va,
                         rotation=rot, zorder=4)
        if gid:
            t.set_gid(gid)

    # ---------------- 图框 / 标题栏（纸面固定件）----------------
    def draw_frame(self, title):
        """图框 + 标题栏。gid="frame" → 不参与自动适配的包围盒。"""
        g = "frame"
        _fr = Polygon([(M_FRAME, M_FRAME), (A3W - M_FRAME, M_FRAME),
                       (A3W - M_FRAME, A3H - M_FRAME), (M_FRAME, A3H - M_FRAME)],
                      closed=True, fill=False, edgecolor="k", lw=0.9, zorder=1)
        _fr.set_gid(g)
        self.ax.add_patch(_fr)

        tx0, ty0 = A3W - M_FRAME - TITLE_W, M_FRAME
        _tb = Polygon([(tx0, ty0), (tx0 + TITLE_W, ty0),
                       (tx0 + TITLE_W, ty0 + TITLE_H), (tx0, ty0 + TITLE_H)],
                      closed=True, fill=False, edgecolor="k", lw=0.7, zorder=1)
        _tb.set_gid(g)
        self.ax.add_patch(_tb)
        for i in range(1, 4):
            self.ln(tx0, ty0 + i * TITLE_H / 4, tx0 + TITLE_W, ty0 + i * TITLE_H / 4,
                    0.45, shift=False, gid=g)
        self.ln(tx0 + 112, ty0, tx0 + 112, ty0 + TITLE_H, 0.45, shift=False, gid=g)

        rows_l = [("零件名称：%s" % title.get("name", ""), 11, 35),
                  (title.get("scale", ""), 8.6, 27),
                  (title.get("material", "材料 未标注        数量 1"), 8.6, 19),
                  ("外接 %s" % title.get("bbox", ""), 8.6, 11),
                  (title.get("note", ""), 7.2, 4)]
        for s, sz, dy in rows_l:
            self.txt(tx0 + 3, ty0 + dy, s, sz, ha="left", shift=False, gid=g)
        rows_r = [(title.get("date", ""), 35), ("未注公差", 27), ("去毛刺", 19)]
        for s, dy in rows_r:
            self.txt(tx0 + 115, ty0 + dy, s, 8.6, ha="left", shift=False, gid=g)

    # ---------------- 自动适配 ----------------
    def content_bbox(self):
        """扫描画布上所有线条 / 多边形 / 文字，返回真实包围盒（不含 gid=frame）"""
        xlo = ylo = float("inf")
        xhi = yhi = float("-inf")
        for a in self.ax.get_children():
            if a.get_gid() == "frame":
                continue
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
                if a.get_text().strip():
                    x, y = a.get_position()
                    ha = a.get_ha()
                    x0 = x - TXT_PAD if ha in ("center", "right") else x
                    x1 = x + TXT_PAD if ha in ("center", "left") else x
                    xlo = min(xlo, x0); xhi = max(xhi, x1)
                    ylo = min(ylo, y - 2.5); yhi = max(yhi, y + 2.5)
        return xlo, xhi, ylo, yhi

    def fit_shift(self):
        """把所有内容推进图框所需的最小整体平移 (dx, dy)"""
        xlo, xhi, ylo, yhi = self.content_bbox()
        if xlo == float("inf"):
            return 0.0, 0.0
        lo = M_FRAME + PAD
        hix, hiy = A3W - M_FRAME - PAD, A3H - M_FRAME - PAD
        dx = (lo - xlo) if xlo < lo else ((hix - xhi) if xhi > hix else 0.0)
        dy = (lo - ylo) if ylo < lo else ((hiy - yhi) if yhi > hiy else 0.0)
        return dx, dy

    def reset(self):
        self.ax.clear()
        self._setup()

    def save(self, out_dir):
        pdf = os.path.join(out_dir, "drawing.pdf")
        png = os.path.join(out_dir, "drawing.png")
        self.fig.savefig(pdf)
        self.fig.savefig(png, dpi=300)
        return pdf, png


# ---------------- 视图与标注 ----------------
def _view_yminmax(v):
    ys = [p[1] for e in v["edges"] for p in e]
    return min(ys), max(ys)


def draw_views(r, views, place, view_order):
    """画所有视图的边，返回各视图的**逻辑坐标**包围盒"""
    bb = {}
    for name in view_order:
        v = views[name]
        px, py, flip = place[name]
        sc = v["plot_scale"]
        # 关键：ey_min/ey_max 取「整个视图」的范围（对所有边统一），
        # 而不是逐边各自归一 —— 否则 flip=True 时水平边会被压到同一条 y 上。
        ey_min, ey_max = _view_yminmax(v)
        xs, ys = [], []
        for e in v["edges"]:
            ex = [v["X"] + q[0] * sc for q in e]
            ey = [v["Y"] + ((ey_max - q[1]) if flip else (q[1] - ey_min)) * sc for q in e]
            xs.extend(ex)
            ys.extend(ey)
            r.poly(ex, ey)
        bb[name] = (min(xs), max(xs), min(ys), max(ys))
    return bb


def _paper_at(bb, view, at):
    """at = (source, index, offset) → 纸面逻辑坐标"""
    src, idx, off = at
    if src == "BB":
        return bb[view][idx] + off
    raise ValueError("未知 at 来源：%s" % src)


def _M(r, views, place, nm, u, w):
    """view2d (u,w) → 纸面**逻辑坐标**（位置统一取 v["X"]/v["Y"]）"""
    v = views[nm]
    sc = v["plot_scale"]
    px, py, flip = place[nm]
    ey_min, ey_max = _view_yminmax(v)
    return (v["X"] + u * sc,
            v["Y"] + ((ey_max - w) if flip else (w - ey_min)) * sc)


def draw_dims(r, views, place, bb, dims, meas=None):
    """按声明清单画标注"""
    for d in dims:
        kind = d["kind"]
        nm = d["view"]
        label = d["label"]
        if kind == "extent":
            v = views[nm]
            axis = d["axis"]
            paper_p = _paper_at(bb, nm, d["at"])
            if axis == 0:
                xs = [q[0] for e in v["edges"] for q in e]
                x_lo, x_hi = min(xs), max(xs)
                ymn, ymx = _view_yminmax(v)
                ya = _M(r, views, place, nm, 0, ymn if place[nm][2] else ymx)[1]
                xa, xb = _M(r, views, place, nm, x_lo, 0)[0], _M(r, views, place, nm, x_hi, 0)[0]
                r.ln(xa, ya, xa, paper_p); r.ln(xb, ya, xb, paper_p)
                r.ln(xa, paper_p, xb, paper_p)
                r.arrow((xa, paper_p), 180); r.arrow((xb, paper_p), 0)
                r.txt((xa + xb) / 2, paper_p + 2, label, 9)
            else:
                ymn, ymx = _view_yminmax(v)
                xa = _M(r, views, place, nm, 0, ymn)[0]
                ya, yb = _M(r, views, place, nm, 0, ymn)[1], _M(r, views, place, nm, 0, ymx)[1]
                r.ln(xa, ya, paper_p, ya); r.ln(xa, yb, paper_p, yb)
                r.ln(paper_p, ya, paper_p, yb)
                r.arrow((paper_p, ya), 270); r.arrow((paper_p, yb), 90)
                r.txt(paper_p - 2.5, (ya + yb) / 2, label, 9, va="center", ha="right")
        elif kind in ("h", "v"):
            paper_p = _paper_at(bb, nm, d["at"])
            if kind == "h":
                xa, xb = _M(r, views, place, nm, d["ua"], 0)[0], _M(r, views, place, nm, d["ub"], 0)[0]
                r.ln(xa, paper_p, xa, paper_p - 2); r.ln(xb, paper_p, xb, paper_p - 2)
                r.ln(xa, paper_p, xb, paper_p)
                r.arrow((xa, paper_p), 180); r.arrow((xb, paper_p), 0)
                r.txt((xa + xb) / 2, paper_p + 2, label, 9, va="bottom")
            else:
                ya, yb = _M(r, views, place, nm, 0, d["wa"])[1], _M(r, views, place, nm, 0, d["wb"])[1]
                r.ln(paper_p, ya, paper_p - 2, ya); r.ln(paper_p, yb, paper_p - 2, yb)
                r.ln(paper_p, ya, paper_p, yb)
                r.arrow((paper_p, ya), 270); r.arrow((paper_p, yb), 90)
                r.txt(paper_p - 2.5, (ya + yb) / 2, label, 9, va="center", ha="right")
        elif kind in ("extent_y",):
            paper_p = _paper_at(bb, nm, d["at"])
            xa = _M(r, views, place, nm, 0, d["wa"])[0]
            ya, yb = _M(r, views, place, nm, 0, d["wa"])[1], _M(r, views, place, nm, 0, d["wb"])[1]
            r.ln(xa, ya, paper_p, ya); r.ln(xa, yb, paper_p, yb)
            r.ln(paper_p, ya, paper_p, yb)
            r.arrow((paper_p, ya), 270); r.arrow((paper_p, yb), 90)
            r.txt(paper_p - 2.5, (ya + yb) / 2, label, 9, va="center", ha="right")
        elif kind == "leader":
            x_view, y_view = _M(r, views, place, nm, d["uw"][0], d["uw"][1])
            lx, ly = x_view + d["off"][0], y_view + d["off"][1]
            r.ln(lx, ly, x_view, y_view)
            r.arrow((x_view, y_view),
                    math.degrees(math.atan2(y_view - ly, x_view - lx)) + 180)
            r.txt(lx + 1.5, ly + 1.5, label, 9, ha="left", va="bottom")
        else:
            raise ValueError("未知标注类型：%s" % kind)


def render(data, out_dir, place, view_order, title, dims, labels,
           label_style="right", meas=None, verbose=True):
    """画一张 A3 工程图并落盘。

    返回 (pdf, png, dx, dy)；dx/dy 是自动适配施加的整体平移（0 表示本来就合规）。
    """
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

    views = {v["name"]: v for v in data["views"]}
    r = Renderer()

    def draw_all():
        bb = draw_views(r, views, place, view_order)
        r.draw_frame(title)
        for nm, lbl in labels:
            x0, y0, x1, y1 = bb[nm]
            if label_style == "center":
                r.txt((x0 + x1) / 2.0, y1 + 5, lbl, 11, ha="center")
            else:
                r.txt(x1, y1 + 3.5, lbl, 11, ha="right")
        draw_dims(r, views, place, bb, dims, meas)
        return bb

    # ① 试画一遍，量包围盒
    draw_all()
    xlo, xhi, ylo, yhi = r.content_bbox()
    dx, dy = r.fit_shift()

    # ② 越界就整体平移后重画
    if abs(dx) > 1e-6 or abs(dy) > 1e-6:
        if verbose:
            print("[s3_render] 内容越出图框：x[%.1f, %.1f] y[%.1f, %.1f] → 平移 (%+.1f, %+.1f) mm"
                  % (xlo, xhi, ylo, yhi, dx, dy))
        r.dx, r.dy = dx, dy
        r.reset()
        draw_all()
        x2lo, x2hi, y2lo, y2hi = r.content_bbox()
        lo, hix, hiy = M_FRAME + PAD, A3W - M_FRAME - PAD, A3H - M_FRAME - PAD
        inside = (lo - 1e-6 <= x2lo and x2hi <= hix + 1e-6
                  and lo - 1e-6 <= y2lo and y2hi <= hiy + 1e-6)
        if verbose:
            print("[s3_render] 平移后 x[%.1f, %.1f] y[%.1f, %.1f] —— %s"
                  % (x2lo, x2hi, y2lo, y2hi, "已全部收进图框" if inside else "仍有越界"))

    pdf, png = r.save(out_dir)
    return pdf, png, r.dx, r.dy
