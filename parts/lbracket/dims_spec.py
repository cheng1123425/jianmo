# -*- coding: utf-8 -*-
r"""
L 形支座 —— 尺寸命名 + 三维↔二维推导关系

cat 必须与 notes/plan_src.md 的「构造」段对得上，s0_plan 才能定位失误步骤。

注意：本零件参数较多，仅先实现核心 cat（底板/立板/三角筋/孔），派生量折叠到现有 cat。
"""
# ---------------- DIMS 列表 ----------------
# expr 必须能用参数命名空间里的名字计算（用 P.XXX）
DIMS = [
    # ---- 底板 ----
    dict(key="BASE_L", cat="底板", label="L",
         solid="底板 X 方向长（含 R9 圆角起点）",
         rel="标注 = L", style="lin", expr=lambda P: P.BASE_L),
    dict(key="BASE_W", cat="底板", label="W",
         solid="底板 Y 方向宽",
         rel="标注 = W", style="lin", expr=lambda P: P.BASE_W),
    dict(key="BASE_T", cat="底板", label="T_base",
         solid="底板厚",
         rel="标注 = T", style="lin", expr=lambda P: P.BASE_T),
    dict(key="BASE_R_END", cat="底板", label="R_end",
         solid="底板左端 R9 圆角半径",
         rel="标注 = R9", style="rad", expr=lambda P: P.BASE_R_END),

    # ---- 立板 ----
    dict(key="WALL_H", cat="立板", label="H_total",
         solid="立板自身高（不含底板）；总高 = BASE_T + WALL_H",
         rel="总高标注 = T + WALL_H", style="lin",
         expr=lambda P: P.BASE_T + P.WALL_H),
    dict(key="WALL_L", cat="立板", label="W",
         solid="立板 Y 方向长（= 底板宽）",
         rel="标注 = WALL_L（与底板宽同）", style="lin",
         expr=lambda P: P.WALL_L),

    # ---- 孔 ----
    dict(key="D_HOLE", cat="孔", label="D",
         solid="所有 3 个 φ8 孔的直径",
         rel="标注 = D", style="dia", expr=lambda P: P.D_HOLE),
    dict(key=None, cat="孔", label="pitch",
         solid="立板顶 2×φ8 孔心距（Y 方向）",
         rel="标注 = WALL_HOLE_Y2 - WALL_HOLE_Y1", style="lin",
         expr=lambda P: P.WALL_HOLE_Y2 - P.WALL_HOLE_Y1),

    # ---- 派生 ----
    dict(key=None, cat="派生", label="wall_h",
         solid="立板自身高（不含底板）",
         rel="标注 = H_total - T_base", style="lin",
         expr=lambda P: P.WALL_H),
]


def notes(P):
    return [
        ("底板左端 R9 怎么画才不出错",
         "build123d 0.13 里用 CenterArc+Line 手画轮廓再 make_face 经常收不了口"
         "（报 Face can only be created with closed wires）。稳妥做法：先 Rectangle(40,26)"
         "再 fillet 最左两个顶点 radius=9，右端保持方角。"),
        ("立板为什么要落在底板 X 范围内",
         "若 WALL_X0=22（立板 X∈[22,30]）会探出底板右端，俯视总长变成 50 而非 40；"
         "把 WALL_X0 收到 12（X∈[12,20] ⊂ [-20,20]），俯视外接 X 才是底板长 40，"
         "L 标注才对得上。"),
        ("3-φ8 在三视图里的出现方式不同",
         "底板孔轴沿 Z → 俯视为圆（1 个）；立板两孔轴沿 X → 主视投影重合为 1 个圆、"
         "右视各显 1 个圆（共 2 个，心距 = 立板宽 26）。所以三视图圆数 1/1/2，"
         "不能按「每张图都该有 3 个圆」去数。"),
        ("标注值从哪来",
         "全部由 FreeCAD 从当前三维实体实测（getRawValue）；参数列是 params.py 的输入值，"
         "两列一致即说明建模与图纸没有跑偏。"),
    ]