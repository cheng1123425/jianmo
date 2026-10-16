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
         "总高 52.0 = 法兰厚 3.0 + 圆柱本体 45.5（z=3→48.5）+ 40° 锥帽 3.5（z=48.5→52）。"
         "内腔 Ø22 直段到 z=44，顶部 R7 球冠（球心 z=41）收顶，顶孔 Ø6.5 贯穿顶面。"
         "⚠️ 图上 48.5±0.1 是**颈顶台阶**标高，不是总高（曾把 48.5 当总高 ⇒ 整体矮 3.5）。"),
        ("标注值从哪来",
         "全部由 FreeCAD 从当前三维实体实测（getRawValue）；参数列是 params.py 的输入值，"
         "两列一致即说明建模与图纸没有跑偏。"),
        ("来源与标定",
         "所有尺寸由矢量 PDF 实测（AutoCAD 2024 打印，坐标即物理尺寸）；"
         "并用客户真值 `外罩.STEP` 逐点复核（体积差 0.5%、体素一致率 98.1%）。"
         "⚠️ 标定 k 必须做最小二乘细化：只按命中条数拟合会系统性偏小 0.4%。"),
        ("易踩的坑",
         "① 本体是 Ø28 **圆柱**，图纸正视图里那条斜线是 4 条筋在 45° 的投影（×cos45°），"
         "不是外锥；② 俯视图量到的『筋宽 6』是**含 R1 根圆角的轮廓线**，真实筋宽 4.0。"),
    ]
