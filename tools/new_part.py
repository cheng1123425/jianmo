# -*- coding: utf-8 -*-
r"""tools/new_part.py —— 一键生成「纯数据零件」骨架（阶段 1 的验收工具）

**它证明的事**：新增一个零件，只需要交**数据文件**，不需要写任何 `.py`。

    python tools/new_part.py --name acc_plate
    → parts/acc_plate/
        params.py          # 尺寸真值（数值）
        ref_spec.py        # 闭环基准（几何期望）
        dims_spec.py       # 尺寸表条目
        draw_spec.py       # 出图声明（视图/标注/标题栏）
        ir.json            # 特征图（构造真值）
        ir_anchors.json    # 2D↔3D 标注锚点
        notes/plan_src.md  # 规划输入
      ✗ 不生成 steps/*.py —— 这正是「不写 Python」的意思

数据仍用 `.py` 扩展名，是因为项目既有约定（`exec_module` 加载），
但内容**全是字面量赋值**，没有逻辑 —— 等价于 JSON/YAML。

隔离：算法层（tools/），只写零件目录，不参与 mpipe/1 消息协议。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PARAMS = '''# -*- coding: utf-8 -*-
r"""{name} —— 尺寸参数（唯一数值真值源）

只写**具名尺寸**，不写任何逻辑。建模/标注/校验都读这里。
命名参考 docs/v3-命名规范与逻辑分层.md：<部位>_[<修饰>_]<量型>[_<方向>]
"""

TAG = "{name}"

# ---- 主体（示例：矩形板 + 两孔；按实际零件改）----
BASE_L_X = 60.0          # X 全长
BASE_W_Y = 40.0          # Y 宽
BASE_T_Z = 10.0          # Z 厚
HOLE_D = 8.0             # 孔径
HOLE_PITCH_X = 40.0      # 两孔心距
'''

REF_SPEC = '''# -*- coding: utf-8 -*-
r"""{name} —— 闭环基准（几何期望 + 标注清单）

`s6_compare` 用它逐项核对模型；`s5b_dimchain` 用它校验尺寸链自洽。
数值应与 params.py / 图纸一致。
"""

CALIB_NOTE = "待填：从原图量得的 px/mm 标定说明"
TOL = 0.5                                        # 判定容差 (mm)

TOP = {{
    "len_x": 60.0,                               # 俯视外接 X
    "len_y": 40.0,                               # 俯视外接 Y
}}

FRONT = {{
    "height": 10.0,                              # 主视总高
}}

RIGHT = {{}}

#: 平面端面标高（子集语义：声明的每个标高必须真实存在）。键必须小写 x/y/z。
FACE_LEVELS = {{
    "z": [0.0, 10.0],
}}

#: 图上必须出现的标注（闭环核对其数值）
MARKS = {{
    "L": 60.0,
    "W": 40.0,
    "H_total": 10.0,
    "D8": 8.0,
}}
'''

DIMS_SPEC = '''# -*- coding: utf-8 -*-
r"""{name} —— 尺寸命名 + 三维↔二维推导关系（s4_table 用）

`cat` 要与 notes/plan_src.md 的「构造」段对得上；`label` 要与 s2 实际产出的标注一致。
`expr` 是**参数推出的期望值**，`got` 是 FreeCAD 实测值 —— s4 并列两者核对。
"""

DIMS = [
    dict(key="BASE_L_X", cat="外形", label="L",
         solid="X 全长", rel="标注 = L", style="lin",
         expr=lambda P: P.BASE_L_X),
    dict(key="BASE_W_Y", cat="外形", label="W",
         solid="Y 宽", rel="标注 = W", style="lin",
         expr=lambda P: P.BASE_W_Y),
    dict(key="BASE_T_Z", cat="外形", label="H_total",
         solid="Z 厚", rel="标注 = T", style="lin",
         expr=lambda P: P.BASE_T_Z),
    dict(key="HOLE_D", cat="孔", label="D8",
         solid="孔径", rel="标注 = D", style="dia",
         expr=lambda P: P.HOLE_D),
]


def notes(P):
    """尺寸表附注（s4_table 用）。纯文本，(标题, 说明) 列表。"""
    return [
        ("尺寸是怎么来的",
         "待填：从图纸量出的推导说明（尺寸链闭合关系）。"),
        ("标注值从哪来",
         "全部由 FreeCAD 从当前三维实体实测（getRawValue）；参数列是 params.py 的输入值，"
         "两列一致即说明建模与图纸没有跑偏。"),
    ]
'''

DRAW_SPEC = '''# -*- coding: utf-8 -*-
r"""{name} —— 出图声明（s2_drawing / s3_render 共用）

视图落位 + 视图标签 + 标题栏 + 标注清单。全是字面量，无逻辑。
`label_from="meas:<label>"` = 标注取 FreeCAD 实测值（禁止写死数字，见 lib/pdf_marks.py）。
"""

SCHEMA_VERSION = 1

# ---- ① 视图落位（A3 纸面坐标 mm）: (x, y, 是否翻转Y) ----
PLACE = {{
    "Top":   (34, 45, False),
    "Front": (34, 172, True),
    "Right": (214, 172, True),
    "SecA":  (330, 45, True),
}}

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
    {{"name": "Top",   "dir": (0, 0, 1),  "xdir": None,      "scale": 2.0}},
    {{"name": "Front", "dir": (0, -1, 0), "xdir": None,      "scale": 2.0}},
    {{"name": "Right", "dir": (1, 0, 0),  "xdir": (0, 1, 0), "scale": 2.0}},
    {{"name": "SecA",  "type": "section",
      "dir": (0, -1, 0),        # 看的方向
      "base": "Front",          # 挂在哪个基点视图上（FreeCAD 强制）
      "normal": (0, 1, 0),      # 剖切面法向 —— 切 XZ 面
      "origin": (0, 0, 0),      # 剖切面过原点（YZ 面上 Y=0）
      "section_dir": (0, 1, 0),
      "symbol": "A", "hatch": True, "scale": 2.0}},
]

# ---- ④ 标题栏 ----
TITLE = {{
    "name": "{name}",
    "scale": "比例 2:1    单位 mm    第一角投影",
    "material": "材料 未标注        数量 1",
    "bbox": "",
    "note": "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过",
    "date": "",
}}

# ---- ⑤ 标注清单（s3_render 渲染用；语义绑定见 ir_anchors.json）----
DIMS = [
    dict(kind="extent", view="Top", axis=0, at=("BB", 3, +5), label_from="meas:L"),
    dict(kind="extent", view="Top", axis=1, at=("BB", 0, -8), label_from="meas:W"),
    dict(kind="extent", view="Front", axis=1, at=("BB", 0, -8), label_from="meas:H_total"),
]

# ---- ⑥ 标注在 TechDraw 图面上的摆放（label → [X, Y]；s2 共享实现用）----
DIM_POS = {{
    "L": [80.0, 250.0],
    "W": [10.0, 180.0],
    "H_total": [10.0, 90.0],
    "D8": [180.0, 90.0],
}}
'''

IR_JSON = {
    "ir_version": 1,
    "part": None,
    "source": {"from": "人工标注（纯数据零件）", "script": None, "tool": "tools/new_part.py"},
    "meta": {},
    "features": [
        {
            "id": "F1",
            "semantic": {"type": "主体", "role": "加法"},
            "structural": {"kind": "加法", "target": None},
            "params": {"amount": 10.0},
            "impl": [
                ["sketch", {"plane": {"plane": "Plane.XY", "offset": None, "resolved": True},
                            "ops": [{"op": "sketch_rect",
                                     "params": {"pts": [60.0, 40.0], "align": None}}]}],
                ["extrude", {"amount": 10.0}],
            ],
            "tree": [["Pad", {"length": 10.0}]],
            "deps": [],
            "drawing": None,
            "note": "示例：矩形底板。按实际零件改 ops。",
        },
        {
            "id": "F2",
            "semantic": {"type": "孔", "role": "减法"},
            "structural": {"kind": "减法", "target": "F1"},
            "params": {"pos": {"args": [-20.0, 0.0, 5.0]}, "args": [4.0, 12.0], "rotation": None},
            "impl": [["tool", "tool_cylinder"]],
            "tree": [["Pocket", {"type": "ThroughAll", "reversed": True}]],
            "deps": ["F1"],
            "drawing": None,
            "note": "示例：左孔。",
        },
        {
            "id": "F3",
            "semantic": {"type": "孔", "role": "减法"},
            "structural": {"kind": "减法", "target": "F1"},
            "params": {"pos": {"args": [20.0, 0.0, 5.0]}, "args": [4.0, 12.0], "rotation": None},
            "impl": [["tool", "tool_cylinder"]],
            "tree": [["Pocket", {"type": "ThroughAll", "reversed": True}]],
            "deps": ["F1"],
            "drawing": None,
            "note": "示例：右孔。",
        },
    ],
}

IR_ANCHORS = {
    "_note": ("2D↔3D 语义锚点（正向标注）。每个锚点把一个图纸标注绑到 IR 特征 + "
              "一个可重放的几何谓词（不存 Edge#N）。geom.kind ∈ extent/circle/level_pair。"),
    "part": None,
    "anchors": [
        {"label": "L", "fid": "F1", "semantic": "底板长", "view": "Top",
         "dim_kind": "extentH", "geom": {"kind": "extent", "axis": "x"}, "expected": 60.0},
        {"label": "W", "fid": "F1", "semantic": "底板宽", "view": "Top",
         "dim_kind": "extentV", "geom": {"kind": "extent", "axis": "y"}, "expected": 40.0},
        {"label": "H_total", "fid": "F1", "semantic": "总厚", "view": "Front",
         "dim_kind": "extentV", "geom": {"kind": "extent", "axis": "z"}, "expected": 10.0},
        {"label": "D8", "fid": "F2", "semantic": "孔径", "view": "Top",
         "dim_kind": "dia", "geom": {"kind": "circle", "r": 4.0}, "expected": 8.0},
    ],
}

PLAN_SRC = """# {name} —— 规划输入（s0_plan）

## 零件是什么
待填：一句话描述（示例：一块带两孔的矩形底板）

## 关键尺寸（与 params.py 对应）
- 长 60 / 宽 40 / 厚 10
- 孔径 φ8 ×2，心距 40

## 待确认
- 待填：原图上还没核准的尺寸
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成纯数据零件骨架（不写 Python）")
    ap.add_argument("--name", required=True, help="零件名，如 acc_plate")
    ap.add_argument("--out", default=None, help="输出目录（默认 parts/<name>）")
    ap.add_argument("--force", action="store_true", help="目录已存在时也覆盖")
    a = ap.parse_args(argv)

    out = os.path.abspath(a.out or os.path.join(ROOT, "parts", a.name))
    if os.path.exists(out) and not a.force:
        print("目录已存在：%s（加 --force 覆盖）" % out)
        return 2

    os.makedirs(os.path.join(out, "notes"), exist_ok=True)

    kw = {"name": a.name}
    files = {
        "params.py": PARAMS.format(**kw),
        "ref_spec.py": REF_SPEC.format(**kw),
        "dims_spec.py": DIMS_SPEC.format(**kw),
        "draw_spec.py": DRAW_SPEC.format(**kw),
        "notes/plan_src.md": PLAN_SRC.format(**kw),
    }
    for rel, txt in files.items():
        p = os.path.join(out, rel.replace("/", os.sep))
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt)

    ir = dict(IR_JSON)
    ir["part"] = a.name
    with open(os.path.join(out, "ir.json"), "w", encoding="utf-8") as f:
        json.dump(ir, f, ensure_ascii=False, indent=2)

    anc = dict(IR_ANCHORS)
    anc["part"] = a.name
    with open(os.path.join(out, "ir_anchors.json"), "w", encoding="utf-8") as f:
        json.dump(anc, f, ensure_ascii=False, indent=2)

    made = sorted(list(files) + ["ir.json", "ir_anchors.json"])
    print("[new_part] 已生成 %s" % out)
    for m in made:
        print("   + %s" % m)
    print("   ✗ 未生成 steps/*.py —— 纯数据零件（这就是验收内容）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
