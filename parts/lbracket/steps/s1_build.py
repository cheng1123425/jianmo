# -*- coding: utf-8 -*-
r"""s1_build —— 三维建模 → STEP / STL（L 形支座 · 第 2 版，按原图重修）

构造（坐标系：原点 = 底板左端·底面中心）：
  1) 底板（叶形）：左端 R9 圆头（圆心=左孔心 X=9），斜边向右渐宽到 Y=±20，
     直边到 X=56；Z∈[0,8]
  2) 立板：X∈[48,56]，Y∈[-20,20]，Z∈[8,39]；顶部"双耳"：
     两个 R7 圆耳（各罩一个 φ8）+ 中间 R6,5 凹弧
  3) 三角筋：立板背面 X=48 与底板顶面 Z=8 之间的直角三角形，沿 Y 贯穿
  4) 孔（后段切除）：底板 3×φ8（轴 Z）+ 立板 2×φ8（轴 X）
  5) 中央矩形窗口：8(Y)×14(Z) 贯穿立板厚度

入参消息  refs: params；data: out_dir
产出      model_step / model_stl
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))

from build123d import *                       # noqa: F401,F403
from msgio import run_stage, ref_path, ref_data, exec_module


def _arc(cx, cz, r, a0, a1, n=12):
    """在 (u,v)=(Y,Z) 平面采样圆弧，返回点列"""
    out = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        out.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    return out


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"),
                    os.path.basename(ref_path(in_msg, "params"))[:-3])
    out_dir = ref_data(in_msg, "out_dir")

    hw = P.BASE_W / 2.0                 # 20
    rn = P.BASE_R_END                   # 9（R9 圆头）
    ncx = P.BASE_NOSE_CX                # 9（R9 圆心 = 左孔心）
    tap = P.BASE_TAPER_X                # 26（渐宽收束 X = 右孔 X）

    with BuildPart() as p:                       # noqa: F405
        # ============== 1. 底板（叶形） ==============
        pts = []
        # 左端 R9 半圆：从 (ncx, +rn) 经 (ncx-rn, 0) 到 (ncx, -rn)（逆时针穿 180°）
        pts += _arc(ncx, 0.0, rn, 90, 270, n=16)
        # 斜边渐宽 → 全宽矩形 → 右端
        pts += [(tap, -hw), (P.BASE_L, -hw), (P.BASE_L, hw), (tap, hw)]
        with BuildSketch(Plane.XY) as s_base:    # noqa: F405
            Polygon(*pts, align=None)            # noqa: F405
        extrude(amount=P.BASE_T)                 # noqa: F405

        # ============== 2. 立板（顶部双耳） ==============
        wy = P.WALL_L / 2.0                 # 20
        eh = P.WALL_HOLE_Y                  # 13（耳心 Y）
        hr = P.WALL_TOP_R                   # 7（耳 R7）
        ir = P.WALL_INNER_R                 # 6.5（中凹 R6,5）
        zc = P.WALL_HOLE_Z                  # 32（耳心 Z）
        ztop = P.BASE_T + P.WALL_H          # 39（耳顶）
        zbot = P.BASE_T                     # 8（立板底）
        prof = []
        prof.append((-wy, zbot))
        prof.append((wy, zbot))
        prof.append((wy, zc))
        # 右耳 R7：0° → 180°（(wy,zc) → (eh,ztop) → (wy-hr,zc)）
        prof += _arc(eh, zc, hr, 0, 180, n=10)
        # 中间 R6,5 凹弧：(eh-hr,zc) → 下凹 → (-(eh-hr),zc)
        x_dip = eh - hr                     # 6
        half = math.sqrt(max(ir * ir - x_dip * x_dip, 0.0))   # 2.5
        c_dip = zc + half                   # 34.5
        a0 = math.degrees(math.atan2(zc - c_dip, x_dip))
        a1 = math.degrees(math.atan2(zc - c_dip, -x_dip))
        prof += _arc(0.0, c_dip, ir, a0, a1, n=10)
        # 左耳 R7：0° → 180°（(-x_dip,zc) → (-eh,ztop) → (-wy,zc)）
        prof += _arc(-eh, zc, hr, 0, 180, n=10)
        with BuildSketch(Plane.YZ.offset(P.WALL_X0)) as s_wall:   # noqa: F405
            Polygon(*prof, align=None)           # noqa: F405
        extrude(amount=P.WALL_T)                 # noqa: F405（沿 +X）

        # ============== 3. 三角筋（XZ 平面，沿 Y 贯穿立板全长） ==============
        rib_h = 22.0
        rib_l = 20.0
        with BuildSketch(Plane.XZ.offset(-wy)) as s_rib:   # noqa: F405
            with BuildLine() as rib_line:                  # noqa: F405
                Line((P.WALL_X0, zbot), (P.WALL_X0, zbot + rib_h))       # noqa: F405
                Line((P.WALL_X0, zbot + rib_h), (P.WALL_X0 - rib_l, zbot))  # noqa: F405
                Line((P.WALL_X0 - rib_l, zbot), (P.WALL_X0, zbot))       # noqa: F405
            make_face()                                    # noqa: F405
        extrude(amount=P.WALL_L)                           # noqa: F405

    part = p.part

    # ============== 4. 孔（后段切除） ==============
    tools = []
    # 底板 3×φ8（轴 Z）
    for hx, hy in [(P.BASE_HOLE_X, P.BASE_HOLE_Y),
                   (P.BASE_HOLE2_X, P.BASE_HOLE2_Y),
                   (P.BASE_HOLE2_X, -P.BASE_HOLE2_Y)]:
        tools.append(Pos(hx, hy, P.BASE_T / 2.0)
                     * Cylinder(P.D_HOLE / 2.0, P.BASE_T + 2.0))       # noqa: F405
    # 立板 2×φ8（轴 X）
    for hy in (P.WALL_HOLE_Y, -P.WALL_HOLE_Y):
        tools.append(Pos(P.WALL_HOLE_X, hy, P.WALL_HOLE_Z)
                     * Cylinder(P.D_HOLE / 2.0, P.WALL_T + 4.0,          # noqa: F405
                                rotation=(0, 90, 0)))
    # 中央矩形窗口（贯穿立板厚 X）
    tools.append(Pos(P.WALL_HOLE_X, 0.0, P.WIN_Z0 + P.WIN_H / 2.0)
                 * Box(P.WALL_T + 4.0, P.WIN_W, P.WIN_H))                # noqa: F405
    for t in tools:
        part = part - t

    bb = part.bounding_box()
    os.makedirs(out_dir, exist_ok=True)
    step = os.path.join(out_dir, P.TAG + ".step")
    stl = os.path.join(out_dir, P.TAG + ".stl")
    export_step(part, step)                                    # noqa: F405
    export_stl(part, stl)                                      # noqa: F405

    return [("model_step", step), ("model_stl", stl)], {
        "bounding_box": [round(bb.max.X - bb.min.X, 2),
                         round(bb.max.Y - bb.min.Y, 2),
                         round(bb.max.Z - bb.min.Z, 2)],
        "volume": round(part.volume, 1),
        "solids": len(part.solids()),
        "bbox_min": [round(bb.min.X, 2), round(bb.min.Y, 2), round(bb.min.Z, 2)],
        "bbox_max": [round(bb.max.X, 2), round(bb.max.Y, 2), round(bb.max.Z, 2)],
    }


if __name__ == "__main__":
    run_stage("s1_build", handler)
