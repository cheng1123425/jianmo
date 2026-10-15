# -*- coding: utf-8 -*-
r"""waizhao（外罩 sj-012）—— 尺寸命名 + 三维↔二维推导关系（s4_table 用）

`cat` 要与 notes/plan_src.md 的「构造」段对得上；`label` 要与 s2 实际产出的标注一致。
`expr` 是**参数推出的期望值**，`got` 是 FreeCAD 实测值 —— s4 并列两者核对。
"""

DIMS = [
    dict(key="FLANGE_D", cat="外形", label="D_flange",
         solid="底法兰外径", rel="标注 = Ø", style="dia",
         expr=lambda P: P.FLANGE_D),
    dict(key="Z_TOP", cat="外形", label="H_total",
         solid="总高（底面→顶面）", rel="标注 = 总高", style="lin",
         expr=lambda P: P.Z_TOP),
    dict(key="FLANGE_T", cat="外形", label="T_flange",
         solid="底法兰厚", rel="标注 = 法兰厚", style="lin",
         expr=lambda P: P.FLANGE_T),
    dict(key="BASE_HOLE_D", cat="孔", label="D_base_hole",
         solid="底法兰孔径", rel="标注 = 4×Ø", style="dia",
         expr=lambda P: P.BASE_HOLE_D),
    dict(key="TOP_HOLE_D", cat="孔", label="D_top_hole",
         solid="顶部小孔径", rel="标注 = Ø", style="dia",
         expr=lambda P: P.TOP_HOLE_D),
    dict(key="BORE_D", cat="内腔", label="D_bore",
         solid="内腔孔径", rel="标注 = Ø（剖视可见）", style="dia",
         expr=lambda P: P.BORE_D),
]


def notes(P):
    """尺寸表附注（s4_table 用）。纯文本，(标题, 说明) 列表。"""
    return [
        ("尺寸链闭合关系",
         "总高 48.0 = 法兰厚 3.0 + 锥段 33.0 + 上颈 12.0；内腔 Ø22 直段到 z=35，"
         "顶部 R11 半球穹到 z=46，顶孔 Ø6.5 贯穿顶面（z=48）。"),
        ("标注值从哪来",
         "全部由 FreeCAD 从当前三维实体实测（getRawValue）；参数列是 params.py 的输入值，"
         "两列一致即说明建模与图纸没有跑偏。"),
        ("来源与标定",
         "所有尺寸由矢量 PDF 实测（AutoCAD 2024 打印，坐标即物理尺寸）。"
         "比例 k=1.37 由标注反推（尺寸线长度 ≡ 被测量长度），8 条命中、误差<0.6%。"),
    ]
