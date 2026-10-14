# -*- coding: utf-8 -*-
r"""
双耳直角支座（C 形夹持支架）—— 尺寸命名 + 三维↔二维推导关系
============================================================
cat 必须与 notes/plan_src.md 的「构造」段对得上，s0_plan 才能定位失误步骤。
label 必须与 s2_drawing 实际产出的标注标签一致（s4 据 label 查实测值）。
"""
DIMS = [
    # ---- 总体 ----
    dict(key="LEN_X", cat="总体", label="len_x",
         solid="X 方向总宽（耳心距 116 + 2×R42 = 200）",
         rel="标注 = 200（= EAR_PITCH + 2×EAR_R）", style="lin", expr=lambda P: P.LEN_X),
    dict(key="DEPTH_Y", cat="总体", label="depth_y",
         solid="Y 方向总深",
         rel="标注 = 144", style="lin", expr=lambda P: P.DEPTH_Y),
    dict(key="HEIGHT_Z", cat="总体", label="height_z",
         solid="Z 方向总高",
         rel="标注 = 120", style="lin", expr=lambda P: P.HEIGHT_Z),

    # ---- 背板 ----
    dict(key="WALL_T", cat="背板", label="wall_t",
         solid="背板厚（Y 方向）",
         rel="标注 = 20", style="lin", expr=lambda P: P.WALL_T),
    dict(key="WALL_CHAMF_Z", cat="背板", label="chamf_z",
         solid="背板顶部背面斜切（竖向 30）",
         rel="标注 = 30", style="lin", expr=lambda P: P.WALL_CHAMF_Z),

    # ---- 顶臂 ----
    dict(key="ARM_T", cat="顶臂", label="arm_t",
         solid="顶臂厚（Z 方向 32）",
         rel="标注 = 32", style="lin", expr=lambda P: P.ARM_T),
    dict(key="OPENING", cat="顶臂", label="opening",
         solid="开口深度（背板前侧面 → 顶臂前端）",
         rel="标注 = 96（= ARM_LEN − WALL_T）", style="lin",
         expr=lambda P: P.OPENING),

    # ---- 底座 ----
    dict(key="BASE_H", cat="底座", label="base_h",
         solid="底座高（Z 方向 48）",
         rel="标注 = 48", style="lin", expr=lambda P: P.BASE_H),
    dict(key="BASE_FRONT_W", cat="底座", label="base_front_w",
         solid="底座前端宽（斜削后 66）",
         rel="标注 = 66", style="lin", expr=lambda P: P.BASE_FRONT_W),

    # ---- 双耳 ----
    dict(key="EAR_R", cat="双耳", label="ear_R",
         solid="耳圆头半径",
         rel="标注 = R42", style="rad", expr=lambda P: P.EAR_R),
    dict(key="EAR_PITCH", cat="双耳", label="ear_pitch",
         solid="2-Ø42 耳孔心距",
         rel="标注 = 116", style="lin", expr=lambda P: P.EAR_PITCH),
    dict(key=None, cat="双耳", label="ear_hole",
         solid="耳孔直径",
         rel="标注 = 2-Ø42", style="dia", expr=lambda P: 42.0),

    # ---- 中央台阶孔 ----
    dict(key="D_THRU", cat="中央孔", label="d_thru",
         solid="顶臂中央通孔直径",
         rel="标注 = Φ32", style="dia", expr=lambda P: P.D_THRU),
    dict(key="D_CBORE", cat="中央孔", label="d_cbore",
         solid="顶臂中央沉孔直径",
         rel="标注 = Φ54", style="dia", expr=lambda P: P.D_CBORE),
    dict(key="CBORE_DEPTH", cat="中央孔", label="cbore_depth",
         solid="沉孔深度",
         rel="标注 = 22", style="lin", expr=lambda P: P.CBORE_DEPTH),
]


def notes(P):
    return [
        ("总宽 200 是怎么来的",
         "图上俯视直接标 200；同时由双耳尺寸链闭合：耳孔心距 116 + 2×耳半径 42 = 200，"
         "两路一致，说明读图自洽。"),
        ("开口 96 与顶臂伸出",
         "顶臂 Y 终点 116 = 背板厚 20 + 开口 96；总深 144 比 116 多 28，"
         "正好是剖视图 42（底前部）− 底座前部斜削起点到前端 42 与 144−116=28 的组合关系。"),
        ("双耳为什么在 Z∈[0,32]",
         "主视图两耳/底沿高均为 32，耳圆头圆心在 Y=72（总深一半），故耳是 R42 圆柱体"
         "（轴 Z，高 32）落在底座前部两侧。"),
        ("中央台阶孔",
         "顶臂中央（0,72）处：上方沉孔 Φ54 深 22（自 Z=120 向下），下方通孔 Φ32 贯穿顶臂 32。"),
        ("底座前部斜削",
         "俯视图底座前端宽 66（半宽 33），中段宽 116（半宽 58），从 Y=102 斜削到 Y=144。"),
        ("标注值从哪来",
         "全部由 FreeCAD 从当前三维实体实测（getRawValue）；参数列是 params.py 的输入值，"
         "两列一致即说明建模与图纸没有跑偏。"),
    ]
