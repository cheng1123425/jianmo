# -*- coding: utf-8 -*-
r"""s1_build —— 三维建模 → STEP / STL（L 形支座）

读图构造（几何自洽版）：
  1) 底板 40×26×8，左端 R9 圆角（右端方角）
  2) 立板 8(X)×26(Y)×31(Z)，落在底板右端部 X∈[12,20]，Y 与底板同宽居中
  3) 三角筋：立板背面 X=12 与底板顶面 Z=8 之间的直角三角形，沿 Y 贯穿立板全长
  4) 3 个 φ8 孔：底板 1 (X=-13, Y=0, 轴 Z) + 立板沿 Y 两端 2 (X=16, Y=±13, 轴 X)
  5) 立板顶 R7 / 中央矩形窗口 / 中央 R6.5 内凹 —— 当前 v1 暂未实现（plan_src 已注明）

入参消息
    refs: params (params.py)
    data: out_dir
产出
    model_step / model_stl
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))

from build123d import *                       # noqa: F401,F403
from msgio import run_stage, ref_path, ref_data, exec_module


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"),
                    os.path.basename(ref_path(in_msg, "params"))[:-3])
    out_dir = ref_data(in_msg, "out_dir")

    hl, hw = P.BASE_L / 2.0, P.BASE_W / 2.0
    r = P.BASE_R_END

    with BuildPart() as p:                       # noqa: F405
        # ============== 1. 底板：矩形 + 左端两顶点 fillet（R9），右端方角 ==============
        with BuildSketch(Plane.XY) as s_base:    # noqa: F405
            rect = Rectangle(P.BASE_L, P.BASE_W,  # noqa: F405
                            align=(Align.CENTER, Align.CENTER))  # noqa: F403
            left_verts = rect.vertices().sort_by(Axis.X)[:2]    # noqa: F403
            fillet(left_verts, radius=r)                     # noqa: F405
        extrude(amount=P.BASE_T)                          # noqa: F405

        # ============== 2. 立板：落在底板右端部 ==============
        with BuildSketch(Plane.XY * Pos(0, 0, P.BASE_T)) as s_wall:  # noqa: F405
            with Locations((P.WALL_X0 + P.WALL_T / 2.0, 0)):        # noqa: F405
                Rectangle(P.WALL_T, P.WALL_L,                      # noqa: F405
                          align=(Align.CENTER, Align.CENTER))      # noqa: F403
        extrude(amount=P.WALL_H)                             # noqa: F405

        # ============== 3. 三角筋：XZ 平面直角三角形 → 沿 Y 贯穿立板全长 ==============
        with BuildSketch(Plane.XZ.offset(-P.WALL_L / 2.0)) as s_rib:  # noqa: F405
            with BuildLine() as rib_line:                      # noqa: F405
                Line((P.WALL_X0, P.BASE_T), (P.WALL_X0, P.BASE_T + P.WALL_H))   # noqa: F405
                Line((P.WALL_X0, P.BASE_T + P.WALL_H), (P.WALL_X0 + P.WALL_T, P.BASE_T))  # noqa: F405
                Line((P.WALL_X0 + P.WALL_T, P.BASE_T), (P.WALL_X0, P.BASE_T))   # noqa: F405
            make_face()                                      # noqa: F405
        # Plane.XZ 法线 = Y；平面已在 Y=-WALL_L/2，向 +Y 拉伸 WALL_L → Y∈[-13,13]
        extrude(amount=P.WALL_L)                            # noqa: F405

    part = p.part

    # ============== 4. 孔（3-φ8） ==============
    tools = []
    # 底板孔：轴沿 Z，贯穿底板
    tools.append(Pos(P.BASE_HOLE_X, P.BASE_HOLE_Y, P.BASE_T / 2.0)
                 * Cylinder(P.D_HOLE / 2.0, P.BASE_T + 2.0))             # noqa: F405
    # 立板孔：轴沿 X（rotation 把默认 +Z 旋到 +X），贯穿立板厚
    for y in (P.WALL_HOLE_Y1, P.WALL_HOLE_Y2):
        tools.append(Pos(P.WALL_HOLE_X, y, P.WALL_HOLE_Z)
                     * Cylinder(P.D_HOLE / 2.0, P.WALL_T + 4.0,          # noqa: F405
                                rotation=(0, 90, 0)))
    for t in tools:
        part = part - t

    # ============== 5. 立板顶 R7 圆角 / 窗口 / R6.5 —— v1 跳过 ==============

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
