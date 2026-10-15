# -*- coding: utf-8 -*-
r"""acc_plate —— 出图声明（s2_drawing / s3_render 共用）

视图落位 + 视图标签 + 标题栏 + 标注清单。全是字面量，无逻辑。
`label_from="meas:<label>"` = 标注取 FreeCAD 实测值（禁止写死数字，见 lib/pdf_marks.py）。
"""

SCHEMA_VERSION = 1

# ---- ① 视图落位（A3 纸面坐标 mm）: (x, y, 是否翻转Y) ----
PLACE = {
    "Top":   (34, 45, False),
    "Front": (34, 172, True),
    "Right": (214, 172, True),
    "SecA":  (330, 45, True),
}

# ---- ② 绘制顺序 ----
VIEW_ORDER = ("Top", "Front", "Right", "SecA")

# ---- ③ 视图标签 ----
LABELS = (("Front", "正视图"), ("Right", "侧视图"),
          ("Top", "俯视图"), ("SecA", "A-A 剖视"))
LABEL_STYLE = "center"

# ---- 视图投影方向（供 s2 共享实现建 TechDraw 视图；X/Y 取 PLACE）----
#   type="section" 的条目会建**【真剖视图】**（TechDraw::DrawViewSection + 剖面线），
#   用于把**内腔不可见特征**剖开露出、从而挂得上标注（IR 纪律第 5 条的正解）。
VIEWS = [
    {"name": "Top",   "dir": (0, 0, 1),  "xdir": None,      "scale": 2.0},
    {"name": "Front", "dir": (0, -1, 0), "xdir": None,      "scale": 2.0},
    {"name": "Right", "dir": (1, 0, 0),  "xdir": (0, 1, 0), "scale": 2.0},
    {"name": "SecA",  "type": "section",
      "dir": (0, -1, 0),        # 看的方向
      "base": "Front",          # 挂在哪个基点视图上（FreeCAD 强制）
      "normal": (0, 1, 0),      # 剖切面法向 —— 切 XZ 面
      "origin": (0, 0, 0),      # 剖切面过原点（YZ 面上 Y=0）
      "section_dir": (0, 1, 0),
      "symbol": "A", "hatch": True, "scale": 2.0},
]

# ---- ④ 标题栏 ----
TITLE = {
    "name": "acc_plate",
    "scale": "比例 2:1    单位 mm    第一角投影",
    "material": "材料 未标注        数量 1",
    "bbox": "",
    "note": "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过",
    "date": "",
}

# ---- ⑤ 标注清单（s3_render 渲染用；语义绑定见 ir_anchors.json）----
DIMS = [
    dict(kind="extent", view="Top", axis=0, at=("BB", 3, +5), label_from="meas:L"),
    dict(kind="extent", view="Top", axis=1, at=("BB", 0, -8), label_from="meas:W"),
    dict(kind="extent", view="Front", axis=1, at=("BB", 0, -8), label_from="meas:H_total"),
]

# ---- ⑥ 标注在 TechDraw 图面上的摆放（label → [X, Y]；s2 共享实现用）----
DIM_POS = {
    "L": [80.0, 250.0],
    "W": [10.0, 180.0],
    "H_total": [10.0, 90.0],
    "D8": [180.0, 90.0],
}
