# -*- coding: utf-8 -*-
r"""acc_plate —— 尺寸命名 + 三维↔二维推导关系（s4_table 用）

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
