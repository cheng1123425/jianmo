# -*- coding: utf-8 -*-
r"""draw_spec —— 双耳直角支座的图纸渲染数据（2026-10-15 从 steps/s3_render.py 搬来）

原来这些是 `steps/s3_render.py` 里的 Python 字面量。现在是数据。

**这个零件的视图标签是「居中放在视图正上方」**，由 `LABEL_STYLE = "center"` 控制
（bracket / lbracket 用的是默认的 `"right"`）—— 两者差别在
`lib/drawing_render.render` 的 `label_style` 参数。
"""
SCHEMA_VERSION = 1

# ---- ① 视图落位（A3 纸面坐标 mm）----
PLACE = {"Front": (115, 185, True), "Right": (295, 185, True), "Top": (115, 70, False)}

# ---- ② 绘制顺序 ----
VIEW_ORDER = ("Front", "Right", "Top")

# ---- ③ 视图标签 ----
LABELS = (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图"))

#: 视图标签放在视图**正上方居中**（bracket / lbracket 是默认的靠右）
LABEL_STYLE = "center"

# ---- ④ 标题栏 ----
TITLE = {
    "name": "双耳直角支座",
    "scale": "比例 1:1.25  单位 mm    第一角投影",
    "material": "材料 未标注        数量 1",
    "bbox": "200 × 144 × 120",
    "note": "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过",
    "date": "2026-09-30",
}

# ---- ⑤ 标注清单 ----
# 数值全部取 `_drawing.json` 里 FreeCAD 的实测值（改 params.py 后自动跟随）
DIMS = [
    dict(kind="extent", view="Top", axis=0, at=("BB", 3, +5),
         label_from="meas:len_x"),
    dict(kind="extent", view="Top", axis=1, at=("BB", 0, -8),
         label_from="meas:depth_y"),
    dict(kind="extent", view="Front", axis=1, at=("BB", 0, -8),
         label_from="meas:height_z"),
    dict(kind="extent", view="Right", axis=1, at=("BB", 0, -8),
         label_from="meas:depth_y"),
]