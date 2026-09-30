# -*- coding: utf-8 -*-
r"""
L 形支座 —— 尺寸命名 + 三维↔二维推导关系（第 2 版）
====================================================
cat 必须与 notes/plan_src.md 的「构造」段对得上，s0_plan 才能定位失误步骤。
label 必须与 s2_drawing 实际产出的标注标签一致（s4 据 label 查实测值）。
"""
DIMS = [
    # ---- 底板 ----
    dict(key="BASE_L", cat="底板", label="L",
         solid="底板 X 方向全长（含左端 R9 圆头）",
         rel="标注 = 9 + 17 + 22 + 8（尺寸链闭合）", style="lin", expr=lambda P: P.BASE_L),
    dict(key="BASE_W", cat="底板", label="W",
         solid="底板 Y 方向最大宽",
         rel="标注 = W", style="lin", expr=lambda P: P.BASE_W),
    dict(key="BASE_T", cat="底板", label="T_base",
         solid="底板厚",
         rel="标注 = T", style="lin", expr=lambda P: P.BASE_T),
    dict(key="BASE_R_END", cat="底板", label="R_end",
         solid="底板左端 R9 圆头半径（圆心 = 左孔心）",
         rel="标注 = R9", style="rad", expr=lambda P: P.BASE_R_END),

    # ---- 立板 ----
    dict(key="WALL_H", cat="立板", label="H_total",
         solid="立板自身高（不含底板）；总高 = BASE_T + WALL_H",
         rel="总高标注 = T + WALL_H", style="lin",
         expr=lambda P: P.BASE_T + P.WALL_H),
    dict(key="WALL_L", cat="立板", label="W_wall",
         solid="立板 Y 方向宽（= 底板最大宽）",
         rel="标注 = WALL_L（与底板宽同）", style="lin", expr=lambda P: P.WALL_L),

    # ---- 孔 ----
    dict(key="D_HOLE", cat="孔", label="D",
         solid="所有 φ8 孔直径",
         rel="标注 = D", style="dia", expr=lambda P: P.D_HOLE),
    dict(key=None, cat="孔", label="pitch",
         solid="立板顶 2×φ8 孔心距（Y 方向）",
         rel="标注 = 2 × WALL_HOLE_Y", style="lin",
         expr=lambda P: 2.0 * P.WALL_HOLE_Y),

    # ---- 窗口 ----
    dict(key="WIN_H", cat="窗口", label="win_h",
         solid="中央矩形窗口 Z 高",
         rel="标注 = WIN_H", style="lin", expr=lambda P: P.WIN_H),

    # ---- 派生 ----
    dict(key=None, cat="派生", label="wall_h",
         solid="立板自身高（不含底板）",
         rel="标注 = H_total − T_base", style="lin", expr=lambda P: P.WALL_H),
]


def notes(P):
    return [
        ("底板长 56 是怎么来的",
         "图上没有总体 X 标注，只有定位链 17 / 22 / 30。用尺寸链闭合：左端 R9 圆心=左孔心，"
         "底板长 = R9(9) + 17 + 22 + 立板厚(8) = 56。校核：30 = 22 + 8；主视「长对正」实测 56。"),
        ("底板形状（叶形）",
         "不是矩形+R9：左端是 R9 半圆头（圆心在左孔心 X=9），上/下为直斜边向右渐宽，"
         "到 X=26（右孔处）达全宽 Y=±20，再直边到 X=56。"),
        ("立板顶部「双耳」怎么建",
         "两个 R7 圆耳各罩一个 φ8（圆心 Y=±13、Z=32，耳顶 Z=39），中间用 R6,5 凹弧相连"
         "（凹弧两端落在两耳内缘 Y=±6）。整条轮廓在 YZ 平面画好再沿 X 拉伸 8。"),
        ("轴沿 X 的孔只在右视图显圆",
         "立板 2×φ8 轴沿 X：主视（沿 Y 看）中两孔投影重合为 1 个圆，右视（沿 X 看）中显 2 个圆、"
         "心距 26。俯视里它们是矩形/线，不是圆。"),
        ("标注值从哪来",
         "全部由 FreeCAD 从当前三维实体实测（getRawValue）；参数列是 params.py 的输入值，"
         "两列一致即说明建模与图纸没有跑偏。"),
    ]
