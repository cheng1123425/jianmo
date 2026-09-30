# -*- coding: utf-8 -*-
r"""s4_table —— 尺寸对照表（L 形支座）"""
import json
import os
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容

from msgio import boot, finish, ref_path, ref_data, exec_module    # noqa: E402

IN = boot("s4_table")
P = exec_module(ref_path(IN, "params"),
                os.path.basename(ref_path(IN, "params"))[:-3])
S = exec_module(ref_path(IN, "dims_spec"), "dims_spec")
OUT_DIR = ref_data(IN, "out_dir")

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

data = json.load(open(ref_path(IN, "drawing_json"), encoding="utf-8"))
MEAS = {d["label"]: d["value"] for d in data["dims"]}


def mark_text(style, v):
    if style == "dia":
        return "\u03c6%.0f" % v
    if style == "rad":
        return "R%.0f" % v
    return "%.0f" % v


# 组装行
rows = []
for i, sp in enumerate(S.DIMS, 1):
    key = sp["key"]
    want = sp["expr"](P)
    got = MEAS.get(sp["label"])
    ok = got is not None and abs(got - want) < 0.01
    rows.append({
        "i": str(i),
        "key": key if key else "（派生）",
        "cat": sp["cat"],
        "solid": sp["solid"],
        "mark": mark_text(sp["style"], want),
        "rel": sp["rel"],
        "param": ("%.1f" % getattr(P, key)) if key else "—",
        "meas": ("%.1f" % got) if got is not None else "缺失",
        "ok": "OK" if ok else "!!",
    })

n_ok = sum(1 for r in rows if r["ok"] == "OK")
stamp = time.strftime("%Y-%m-%d %H:%M")

# Markdown
md = ["# 尺寸命名与推导对照表 · L 形支座", "",
      "- 生成时间：%s" % stamp,
      "- 参数来源：`params.py`　实测来源：FreeCAD 从三维实体实测（`_drawing.json`）",
      "- 校验：%d/%d 全部一致" % (n_ok, len(rows)), "",
      "| # | 参数名 | 分类 | 三维建模含义 | 图纸标注 | 参数 → 标注 的关系 | 参数值 | 图纸实测 | 校验 |",
      "|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    md.append("| %s | `%s` | %s | %s | %s | %s | %s | %s | %s |"
              % (r["i"], r["key"], r["cat"], r["solid"], r["mark"], r["rel"],
                 r["param"], r["meas"], r["ok"]))
md += ["", "## 推导说明", ""]
for t, body in S.notes(P):
    md += ["**%s**" % t, "", body, ""]
md_path = os.path.join(OUT_DIR, "dims_table.md")
open(md_path, "w", encoding="utf-8").write("\n".join(md))

# A3 图
A3W, A3H = 420.0, 297.0


def wrap(s, n):
    out, cur = [], ""
    for ch in s:
        cur += ch
        if len(cur) >= n:
            out.append(cur); cur = ""
    if cur:
        out.append(cur)
    return "\n".join(out)


fig = plt.figure(figsize=(A3W / 25.4, A3H / 25.4))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, A3W); ax.set_ylim(0, A3H)
ax.set_aspect("equal"); ax.axis("off")

COLS = [("#", 12, "center", 0), ("参数名", 44, "left", 0), ("三维建模含义", 120, "left", 44),
        ("图纸标注", 30, "center", 0), ("参数 → 标注 的关系", 76, "left", 27),
        ("参数值", 26, "center", 0), ("图纸实测", 26, "center", 0), ("校验", 14, "center", 0)]
TW = sum(c[1] for c in COLS)
X0 = (A3W - TW) / 2.0
RH, HH = 10.0, 9.0


def cell(x, y, w, h, text, size=7.6, weight="normal", bg=None, align="left"):
    if bg:
        ax.add_patch(Rectangle((x, y), w, h, facecolor=bg, edgecolor="none", zorder=1))
    ax.add_patch(Rectangle((x, y), w, h, fill=False, edgecolor="k", lw=0.5, zorder=2))
    lines = text.split("\n")
    th = size * 0.3528 * 1.45
    y0 = y + h / 2 + (len(lines) - 1) * th / 2
    tx = {"left": x + 1.4, "center": x + w / 2, "right": x + w - 1.4}[align]
    for k, ln in enumerate(lines):
        ax.text(tx, y0 - k * th, ln, fontsize=size, fontweight=weight,
                ha={"left": "left", "center": "center", "right": "right"}[align],
                va="center", zorder=3)


ax.text(X0, A3H - 14, "尺寸命名与推导对照表 · L 形支座", fontsize=15, fontweight="bold", va="center")
ax.text(X0, A3H - 21, "参数：params.py      实测：FreeCAD TechDraw 1.1.0 从三维实体读取"
        "      校验：%d/%d 一致      生成：%s" % (n_ok, len(rows), stamp),
        fontsize=8, color="#444", va="center")

y = A3H - 26 - HH
x = X0
for name, w, al, _ in COLS:
    cell(x, y, w, HH, name, size=8.4, weight="bold", bg="#e8e8e8", align="center")
    x += w

y -= RH
for r in rows:
    x = X0
    vals = [r["i"], r["key"],
            wrap(r["solid"], COLS[2][3]),
            r["mark"], wrap(r["rel"], COLS[4][3]),
            r["param"], r["meas"], r["ok"]]
    for (name, w, al, _), v in zip(COLS, vals):
        bg = None
        if name == "校验":
            bg = "#e6f5e6" if r["ok"] == "OK" else "#ffe0e0"
        cell(x, y, w, RH, v, bg=bg)
        x += w
    y -= RH

y -= 6
ax.text(X0, y, "推导说明", fontsize=10.5, fontweight="bold", va="center")
y -= 5
for title, body in S.notes(P):
    y -= 4.2
    ax.text(X0, y, "▍" + title, fontsize=8.4, fontweight="bold", va="center")
    for ln in wrap(body, 100).split("\n"):
        y -= 4.2
        ax.text(X0 + 4, y, ln, fontsize=7.6, va="center", color="#333")

ax.add_patch(Rectangle((7, 7), A3W - 14, A3H - 14, fill=False, edgecolor="k", lw=0.9))

t_pdf = os.path.join(OUT_DIR, "dims_table.pdf")
t_png = os.path.join(OUT_DIR, "dims_table.png")
fig.savefig(t_pdf)
fig.savefig(t_png, dpi=300)

bad = [r for r in rows if r["ok"] != "OK"]
finish([("dims_table_md", md_path), ("dims_table_png", t_png), ("dims_table_pdf", t_pdf)],
       {"rows": len(rows), "consistent": n_ok, "mismatch": len(bad),
        "mismatch_keys": [r["key"] for r in bad]})
