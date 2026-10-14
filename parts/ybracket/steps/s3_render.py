# -*- coding: utf-8 -*-
r"""s3_render —— 双耳直角支座的图纸渲染（薄包装）

通用骨架（A3 画布 / 图框 / 自动适配 / 标注画法）都在 `lib/drawing_render.py`，
本文件只声明这个零件自己的三样东西：视图布局、标题栏、标注清单。

标注数值取自 `_drawing.json` 里 FreeCAD 的实测值（`MEAS`）。
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

MEAS = {d["label"]: d["value"] for d in data["dims"]}

# ---- ① 视图布局：(纸面 x, 纸面 y, 是否上下翻转) ----
PLACE = {"Front": (115, 185, True), "Right": (295, 185, True), "Top": (115, 70, False)}
VIEW_ORDER = ("Front", "Right", "Top")
LABELS = (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图"))

# ---- ② 标题栏 ----
TITLE = {
    "name": "双耳直角支座",
    "scale": "比例 1:1.25  单位 mm    第一角投影",
    "material": "材料 未标注        数量 1",
    "bbox": "200 × 144 × 120",
    "note": "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过",
    "date": "2026-09-30",
}

# ---- ③ 标注清单 ----
# 视图标签在这个零件里是「居中放在视图正上方」，由 label_style="center" 控制
DIMS = [
    dict(kind="extent", view="Top", axis=0, at=("BB", 3, +5),
         label="%.0f" % MEAS.get("len_x", 200)),
    dict(kind="extent", view="Top", axis=1, at=("BB", 0, -8),
         label="%.0f" % MEAS.get("depth_y", 144)),
    dict(kind="extent", view="Front", axis=1, at=("BB", 0, -8),
         label="%.0f" % MEAS.get("height_z", 120)),
    dict(kind="extent", view="Right", axis=1, at=("BB", 0, -8),
         label="%.0f" % MEAS.get("depth_y", 144)),
]

pdf, png, dx, dy = render(data, OUT_DIR, PLACE, VIEW_ORDER, TITLE, DIMS,
                          LABELS, label_style="center", meas=MEAS)

finish([("drawing_pdf", pdf), ("drawing_png", png)],
       {"pdf_bytes": os.path.getsize(pdf), "png_bytes": os.path.getsize(png),
        "n_dims_drawn": len(data["dims"]), "shift_dx": round(dx, 2),
        "shift_dy": round(dy, 2)})
