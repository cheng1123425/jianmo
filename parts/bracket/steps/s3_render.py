# -*- coding: utf-8 -*-
r"""s3_render —— 铰链支座的图纸渲染（薄包装）

通用骨架（A3 画布 / 图框 / 自动适配 / 标注画法）都在 `lib/drawing_render.py`，
本文件只声明这个零件自己的三样东西：视图布局、标题栏、标注清单。

标注数值：目前是「硬编码字符串」（沿袭原实现）。
更理想的做法是取 `_drawing.json` 里的 FreeCAD 实测值，见 lbracket / ybracket 的写法。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容

from msgio import boot, finish, ref_path, ref_data    # noqa: E402
from lib.drawing_render import render                 # noqa: E402

IN = boot("s3_render")
OUT_DIR = ref_data(IN, "out_dir")
data = json.load(open(ref_path(IN, "drawing_json"), encoding="utf-8"))

# ---- ① 视图布局：(纸面 x, 纸面 y, 是否上下翻转) ----
# Front/Right 的 view2d y 朝下（要翻转），Top 朝上
PLACE = {"Top": (34, 45, False), "Front": (34, 172, True), "Right": (214, 172, True)}
# 注意：绘制顺序会影响线条端点的抗锯齿（后画的在上）。这个顺序必须与原实现一致，
# 否则像素对比会出现 ~1% 的「边缘发白」差异（视觉无差，但不是 0 差异）。
VIEW_ORDER = ("Top", "Front", "Right")
LABELS = (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图"))

# ---- ② 标题栏 ----
TITLE = {
    "name": "铰链支座",
    "scale": "比例 2:1    单位 mm    第一角投影",
    "material": "材料 未标注        数量 1",
    "bbox": "62 × 46 × 37",
    "note": "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过",
    "date": "2026-09-29",
}

# ---- ③ 标注清单（at = (BB, 索引, 偏移)：BB 是该视图的纸面包围盒）----
DIMS = [
    dict(kind="extent", view="Front", axis=0, at=("BB", 3, +5), label="28"),
    dict(kind="h", view="Front", ua=-11, ub=11, at=("BB", 3, +13), label="16"),
    dict(kind="v", view="Front", wa=27, wb=35, at=("BB", 0, -8), label="8"),
    dict(kind="h", view="Front", ua=-22.5, ub=22.5, at=("BB", 1, -8), label="45"),
    dict(kind="extent", view="Front", axis=0, at=("BB", 1, -18), label="62"),
    dict(kind="leader", view="Front", uw=(-11, 8.5), off=(-25, 16), label="2-φ6"),
    dict(kind="leader", view="Front", uw=(11, 8.5), off=(20, -16), label="2-φ3"),
    dict(kind="v", view="Right", wa=37, wb=0, at=("BB", 0, -8), label="27"),
    dict(kind="v", view="Right", wa=14, wb=0, at=("BB", 2, +5), label="14"),
    dict(kind="h", view="Right", ua=-12, ub=24, at=("BB", 1, -8), label="36"),
    dict(kind="leader", view="Right", uw=(-20, 27), off=(-25, 16), label="R10"),
    dict(kind="leader", view="Right", uw=(-12, 27), off=(28, 12), label="2-φ8"),
    dict(kind="leader", view="Top", uw=(22.5, 12), off=(24, 18), label="2-φ9"),
]

pdf, png, dx, dy = render(data, OUT_DIR, PLACE, VIEW_ORDER, TITLE, DIMS,
                          LABELS, label_style="right")

finish([("drawing_pdf", pdf), ("drawing_png", png)],
       {"pdf_bytes": os.path.getsize(pdf), "png_bytes": os.path.getsize(png),
        "n_dims_drawn": len(data["dims"]), "shift_dx": round(dx, 2),
        "shift_dy": round(dy, 2)})
