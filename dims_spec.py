# -*- coding: utf-8 -*-
r"""
尺寸命名与推导对照表（单一清单 / single source of naming）
===========================================================
这张表是「三维建模参数  ↔  二维图纸标注」的唯一说明来源。
make_table.py 会读它 + params.py + _td_data.json，自动生成对照表文件。

命名约定
--------
    R_xxx      半径                    Radius
    D_xxx      直径 / 中心距            Diameter / Distance
    H_xxx      高出底板的高度           Height（自底板顶面 z = BASE_T 起算）
    BASE_T     底板厚度                 Base Thickness

三维 → 二维的推导（三类）
------------------------
    ① 直读型 ：图纸标注 = 某参数（或 2 × 参数）
    ② 派生型 ：图纸标注 = 多个参数算出来（总长、总宽）
    ③ 构造型 ：只影响图形、不直接成标注（凹颈圆心位置由 R_NECK 与两圆外切定出）

字段说明
--------
    key    params.py 里的参数名（派生量为 None）
    cat    分类
    solid  在三维模型里是什么
    label  freecad_drawing.py 里该尺寸的 label（用于从 _td_data.json 取实测值）
    rel    参数 → 标注 的关系式（人读）
    style  标注形式：dia(φ) / rad(R) / lin(线性)
    expr   期望值计算函数，入参是 params 模块
"""
import math


def neck_center(P):
    """凹颈弧圆心到零件中心的 x 分量 fx（R_NECK 同时与中心弧、侧弧外切）"""
    return (P.D_SIDE ** 2 + (P.R_NECK + P.R_OUT_CEN) ** 2
            - (P.R_NECK + P.R_SIDE) ** 2) / (2 * P.D_SIDE)


DIMS = [
    # ---------------- 俯视轮廓 ----------------
    dict(key="R_OUT_CEN", cat="俯视轮廓", label="OD_center_arc",
         solid="中心外圆弧半径（俯视轮廓在零件中心处的圆弧）",
         rel="标注 = 2 × R_OUT_CEN", style="dia", expr=lambda P: 2 * P.R_OUT_CEN),
    dict(key="R_SIDE", cat="俯视轮廓", label="OD_wing",
         solid="两侧圆弧半径 = 侧凸台外半径（同一尺寸控制两者）",
         rel="标注 = 2 × R_SIDE", style="dia", expr=lambda P: 2 * P.R_SIDE),
    dict(key="D_SIDE", cat="俯视轮廓", label="hole_pitch",
         solid="侧凸台中心到零件中心的距离（同时决定侧孔位置）",
         rel="标注 = D_SIDE（圆心距，非边缘距离）", style="lin", expr=lambda P: P.D_SIDE),
    dict(key="R_NECK", cat="俯视轮廓", label="R_neck",
         solid="凹颈过渡圆弧半径（同时与中心圆弧、侧圆弧外切）",
         rel="标注 = R_NECK", style="rad", expr=lambda P: P.R_NECK),

    # ---------------- 高度 ----------------
    dict(key="BASE_T", cat="高度", label="T_base",
         solid="底板厚度（z = 0 → BASE_T）",
         rel="标注 = BASE_T", style="lin", expr=lambda P: P.BASE_T),
    dict(key="H_CEN", cat="高度", label="H_boss",
         solid="中心凸台高出底板的高度（z = BASE_T → BASE_T+H_CEN）",
         rel="标注 = H_CEN", style="lin", expr=lambda P: P.H_CEN),
    dict(key="H_WING", cat="高度", label="H_step",
         solid="侧凸台高出底板的高度（z = BASE_T → BASE_T+H_WING）",
         rel="标注 = H_WING", style="lin", expr=lambda P: P.H_WING),

    # ---------------- 凸台与孔 ----------------
    dict(key="R_BOSS", cat="凸台", label="OD_boss",
         solid="中心凸台外半径（圆柱，从底板顶面往上）",
         rel="标注 = 2 × R_BOSS", style="dia", expr=lambda P: 2 * P.R_BOSS),
    dict(key="D_HOLE_CEN", cat="孔", label="ID_center",
         solid="中心通孔直径（贯通全高 z = 0 → BASE_T+H_CEN）",
         rel="标注 = D_HOLE_CEN", style="dia", expr=lambda P: P.D_HOLE_CEN),
    dict(key="D_HOLE_SIDE", cat="孔", label="ID_side",
         solid="两侧通孔直径（贯通 z = 0 → BASE_T+H_WING）",
         rel="标注 = D_HOLE_SIDE", style="dia", expr=lambda P: P.D_HOLE_SIDE),

    # ---------------- 派生量（无独立参数） ----------------
    dict(key=None, cat="派生量", label="L",
         solid="零件总长（X 方向外接）= 两侧圆弧外缘之间的距离",
         rel="2 × (D_SIDE + R_SIDE)", style="lin",
         expr=lambda P: 2 * (P.D_SIDE + P.R_SIDE)),
    dict(key=None, cat="派生量", label="W",
         solid="零件总宽（Y 方向外接）= 中心外圆弧的直径",
         rel="2 × R_OUT_CEN", style="lin", expr=lambda P: 2 * P.R_OUT_CEN),
]


def notes(P):
    """推导说明（依赖当前参数，所以做成函数）"""
    return [
        ("轮廓是怎么拼出来的",
         "俯视轮廓 = 中心圆弧(R_OUT_CEN, 圆心在原点) + 左右两条圆弧(R_SIDE, 圆心在 x=±D_SIDE) "
         "+ 四条凹颈弧(R_NECK) 外切连接。凹颈弧与中心弧、侧弧都是「外切」关系。"),
        ("凹颈圆心位置（构造型，不成标注）",
         "凹颈弧圆心 F 满足：|F − 原点| = R_NECK + R_OUT_CEN，|F − 侧圆心| = R_NECK + R_SIDE。"
         "两圆交点即 F，x 分量 fx = [D_SIDE² + (R_NECK+R_OUT_CEN)² − (R_NECK+R_SIDE)²] / (2·D_SIDE)，"
         "当前 fx = %.2f。它只决定图形长什么样，图纸上不直接标注。" % neck_center(P)),
        ("高度链",
         "0（底面）→ BASE_T（底板顶面）→ BASE_T+H_WING（侧凸台顶）／BASE_T+H_CEN（中心凸台顶）。"
         "图上标的 50 / 50 / 20 都是「相邻两级之差」，不是绝对高度。"),
        ("为什么中心孔是贯通孔而不是沉孔",
         "图纸中心是一圈套一圈的同心圆，按惯例（以及实体的实际构造）作贯通孔处理。"),
        ("标注值从哪来",
         "全部由 FreeCAD 从当前三维实体实测（getRawValue）；参数列是 params.py 的输入值，"
         "两列一致即说明建模与图纸没有跑偏。"),
    ]
