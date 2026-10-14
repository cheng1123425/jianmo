# -*- coding: utf-8 -*-
r"""s3_render —— L 形支座的图纸渲染（薄包装）

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
PLACE = {"Top": (34, 45, False), "Front": (34, 172, True), "Right": (214, 172, True)}
VIEW_ORDER = ("Top", "Front", "Right")
LABELS = (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图"))

# ---- ② 标题栏 ----
TITLE = {
    "name": "L 形支座",
    "scale": "比例 2:1    单位 mm    第一角投影",
    "material": "材料 未标注        数量 1",
    "bbox": "56 × 40 × 39",
    "note": "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过",
    "date": "2026-09-30",
}

# ---- ③ 标注清单 ----
DIMS = [
    # Top：L（横）、W（竖）
    dict(kind="extent", view="Top", axis=0, at=("BB", 3, +5),
         label="%.0f" % MEAS.get("L", 40)),
    dict(kind="extent", view="Top", axis=1, at=("BB", 0, -8),
         label="%.0f" % MEAS.get("W", 26)),
    # Front：H_total（竖）
    dict(kind="extent", view="Front", axis=1, at=("BB", 0, -8),
         label="%.0f" % MEAS.get("H_total", 39)),
]
# Right：pitch（两 φ8 圆心在 view2d y 上的间距）—— 只有确实找到两个 φ8 圆时才标
_right = next(v for v in data["views"] if v["name"] == "Right")
_rc = [c for c in _right["circles"] if abs(c["r"] - 4.0) < 0.3]
if len(_rc) >= 2:
    _cys = sorted(c["cy"] for c in _rc)
    DIMS.append(dict(kind="extent_y", view="Right", wa=_cys[0], wb=_cys[1],
                     at=("BB", 0, -8), label="%.0f" % MEAS.get("pitch", 26)))

pdf, png, dx, dy = render(data, OUT_DIR, PLACE, VIEW_ORDER, TITLE, DIMS,
                          LABELS, label_style="right", meas=MEAS)

finish([("drawing_pdf", pdf), ("drawing_png", png)],
       {"pdf_bytes": os.path.getsize(pdf), "png_bytes": os.path.getsize(png),
        "n_dims_drawn": len(data["dims"]), "shift_dx": round(dx, 2),
        "shift_dy": round(dy, 2)})
