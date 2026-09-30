# -*- coding: utf-8 -*-
r"""
铰链支座 —— 尺寸命名与推导对照表
=================================

命名约定（同 gasket）：
    R_xxx      半径
    D_xxx      直径
    H_xxx      高度（自底面算）
    T_xxx      厚度
"""
import math


DIMS = [
    # ---------------- 底板 ----------------
    dict(key="L", cat="底板", label="L",
         solid="底板 X 方向长",
         rel="标注 = L", style="lin", expr=lambda P: P.L),
    dict(key=None, cat="派生", label="W",
         solid="俯视 Y 外接 = −HEAD_Y + END_Y + R_HEAD（圆头最左 → 底板右）",
         rel="标注 = END_Y − HEAD_Y + R_HEAD", style="lin",
         expr=lambda P: P.END_Y - P.HEAD_Y + P.R_HEAD),
    dict(key="T", cat="底板", label="T_base",
         solid="底板厚（z = 0 → T）",
         rel="标注 = T", style="lin", expr=lambda P: P.T),

    # ---------------- 臂 ----------------
    dict(key="ARM_GAP", cat="臂", label="arm_inner",
         solid="两臂内侧间距（图纸标 16）",
         rel="标注 = ARM_GAP", style="lin", expr=lambda P: P.ARM_GAP),
    dict(key=None, cat="派生", label="arm_outer",
         solid="两臂外侧间距 = ARM_GAP + 2·ARM_T",
         rel="标注 = ARM_GAP + 2 × ARM_T", style="lin",
         expr=lambda P: P.ARM_GAP + 2 * P.ARM_T),

    # ---------------- 圆头铰接端 ----------------
    dict(key="R_HEAD", cat="圆头", label="R_head",
         solid="圆头半径（YZ 平面里）",
         rel="标注 = R_HEAD", style="rad", expr=lambda P: P.R_HEAD),
    dict(key="HEAD_Z", cat="圆头", label="head_h",
         solid="圆头圆心高度（自底面 z=0 起算）",
         rel="标注 = HEAD_Z", style="lin", expr=lambda P: P.HEAD_Z),
    dict(key="END_Z", cat="圆头", label="arm_h",
         solid="臂右端总高（= T + ARM_T）",
         rel="标注 = END_Z", style="lin", expr=lambda P: P.END_Z),
    dict(key=None, cat="派生", label="arm_len",
         solid="臂水平总长 = END_Y − HEAD_Y",
         rel="标注 = END_Y − HEAD_Y", style="lin",
         expr=lambda P: P.END_Y - P.HEAD_Y),

    # ---------------- 底板孔 ----------------
    dict(key="D_9", cat="底板孔", label="D9",
         solid="底板孔直径",
         rel="标注 = D_9", style="dia", expr=lambda P: P.D_9),
    dict(key="PITCH9", cat="底板孔", label="P9",
         solid="底板孔心距",
         rel="标注 = PITCH9", style="lin", expr=lambda P: P.PITCH9),

    # ---------------- 销孔 ----------------
    dict(key="D_PIN", cat="销孔", label="dia_pin",
         solid="两臂间 2-φ8 横向销孔",
         rel="标注 = D_PIN", style="dia", expr=lambda P: P.D_PIN),

    # ---------------- 台阶孔 ----------------
    dict(key="D_CB", cat="台阶孔", label="dia_cbore",
         solid="臂端面 2-φ6 沉孔",
         rel="标注 = D_CB", style="dia", expr=lambda P: P.D_CB),
    dict(key="D_CS", cat="台阶孔", label="dia_thru",
         solid="臂 2-φ3 通孔",
         rel="标注 = D_CS", style="dia", expr=lambda P: P.D_CS),
]


def notes(P):
    return [
        ("为什么臂要在 YZ 平面画",
         "臂的侧轮廓（圆头 + 切线斜边 + 右端竖直边 + 底面）在 YZ 平面是平面图形；"
         "拉伸方向自动沿 X → 正是臂的厚度方向，省去一次旋转。"),
        ("圆弧方向坑（CenterArc 的 arc_size 必须为负）",
         "两个切点 A_DN ≈ -121.3°、A_UP ≈ 55.0° 之间有两条弧；"
         "逆时针 +176.3° 走的是「经过下方与右方」的短弧（错），"
         "顺时针 −183.7° 才走「经过左方 Y=-22」的正确弧。"
         "走错时圆心被判在实体外部 → 所有以圆心定位的孔切除量 0。"),
        ("孔切除一律用 part - tool",
         "实测：with Locations: Cylinder(mode=SUBTRACT) 切除量为 0；"
         "块外造切除体 + add(...,SUBTRACT) 给负切除量（错的）；"
         "part = part - tool 直白可控。"),
        ("为什么底板 Y∈[0, W] 而不是居中",
         "原图：臂只从底板的一侧伸出（-Y 方向），与底板的 +Y 端齐平。"
         "Rectangle 默认居中 → 臂两侧都伸出 → 改用 align=(Align.CENTER, Align.MIN)。"),
        ("标注值从哪来",
         "全部由 FreeCAD 从当前三维实体实测（getRawValue）；参数列是 params.py 的输入值，"
         "两列一致即说明建模与图纸没有跑偏。"),
    ]