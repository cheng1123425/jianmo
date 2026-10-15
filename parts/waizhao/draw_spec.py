# -*- coding: utf-8 -*-
r"""waizhao（外罩 sj-012）—— 出图声明（s2_drawing / s3_render 共用）

视图落位 + 视图标签 + 标题栏 + 标注清单。全是字面量，无逻辑。
`label_from="meas:<label>"` = 标注取 FreeCAD 实测值（禁止写死数字）。
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
          ("Top", "俯视图"), ("SecA", "A-A 剖视（水平剖·过底法兰）"))
LABEL_STYLE = "center"

# ---- 视图投影方向（供 s2 共享实现建 TechDraw 视图；X/Y 取 PLACE）----
#   SecA 建**真剖视图**（剖开露出内腔 Ø22 —— 内腔在三视图里不可见，
#   这正是"内腔不可见特征"用剖视挂标注的正解）。
VIEWS = [
    {"name": "Top",   "dir": (0, 0, 1),  "xdir": None,      "scale": 1.5},
    {"name": "Front", "dir": (0, -1, 0), "xdir": None,      "scale": 1.5},
    {"name": "Right", "dir": (1, 0, 0),  "xdir": (0, 1, 0), "scale": 1.5},
    {"name": "SecA", "type": "section",
      "dir": (0, 0, 1),           # 从上往下看剖切面
      "base": "Top",              # 挂在俯视图上（FreeCAD 强制）
      "normal": (0, 0, 1),        # 剖切面法向 = Z ⇒ **水平剖**，切过底法兰 z=1.5
      "origin": (0, 0, 1.5),
      "section_dir": (1, 0, 0),
      "symbol": "A", "hatch": True, "scale": 1.5},
]

# ---- ④ 标题栏 ----
TITLE = {
    "name": "外罩 sj-012（waizhao）",
    "scale": "比例 1:1    单位 mm    第一角投影",
    "material": "材料 7075        数量 1",
    "bbox": "",
    "note": "尺寸来源：矢量 PDF 实测 · 闭环校核通过",
    "date": "",
}

# ---- ⑤ 标注清单（s3_render 渲染用；语义绑定见 ir_anchors.json）----
DIMS = [
    dict(kind="extent", view="Top", axis=0, at=("BB", 3, +5), label_from="meas:D_flange"),
    dict(kind="extent", view="Front", axis=1, at=("BB", 0, -8), label_from="meas:H_total"),
]

# ---- ⑥ 标注在 TechDraw 图面上的摆放（label → [X, Y]；s2 共享实现用）----
DIM_POS = {
    "D_flange":    [95.0, 95.0],
    "H_total":     [95.0, 175.0],
    "D_base_hole": [60.0, 60.0],
    "D_top_hole":  [130.0, 60.0],
    "D_bore":      [360.0, 95.0],
}
