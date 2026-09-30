# -*- coding: utf-8 -*-
r"""s1_build —— 三维建模 → STEP / STL（铰链支座）

入参消息
    refs: params      (params.py，人的输入)
    data: out_dir     (产物目录)
产出
    model_step / model_stl
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))          # 兼容 import dims_spec/ref_spec

from build123d import *                       # noqa: F401,F403
from msgio import run_stage, ref_path, ref_data, exec_module


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"), "bracket_params")
    out_dir = ref_data(in_msg, "out_dir")

    # ---- 切点 + 弧角 ----
    T_UP = P.tangent_point((P.END_Y, P.END_Z), (P.HEAD_Y, P.HEAD_Z), P.R_HEAD, upper=True)
    T_DN = P.tangent_point((0.0, P.T), (P.HEAD_Y, P.HEAD_Z), P.R_HEAD, upper=False)
    A_UP = math.degrees(math.atan2(T_UP[1] - P.HEAD_Z, T_UP[0] - P.HEAD_Y))
    A_DN = math.degrees(math.atan2(T_DN[1] - P.HEAD_Z, T_DN[0] - P.HEAD_Y))

    # ---- 建模 ----
    with BuildPart() as p:                                          # noqa: F405
        # 底板
        with BuildSketch(Plane.XY):                                 # noqa: F405
            Rectangle(P.L, P.W, align=(Align.CENTER, Align.MIN))    # noqa: F405
        extrude(amount=P.T)                                         # noqa: F405

        # 臂：YZ 平面画侧轮廓（圆+切线）
        for x0 in (P.ARM_XI, -P.ARM_XO):
            with BuildSketch(Plane.YZ.offset(x0)):                  # noqa: F405
                with BuildLine():                                   # noqa: F405
                    CenterArc((P.HEAD_Y, P.HEAD_Z), P.R_HEAD, A_DN, (A_UP - A_DN) - 360.0)  # noqa: F405
                    Line(T_UP, (P.END_Y, P.END_Z))                 # noqa: F405
                    Line((P.END_Y, P.END_Z), (P.END_Y, P.T))       # noqa: F405
                    Line((P.END_Y, P.T), (0.0, P.T))               # noqa: F405
                    Line((0.0, P.T), T_DN)                         # noqa: F405
                make_face()                                         # noqa: F405
            extrude(amount=P.ARM_T)                                 # noqa: F405

        # 底板 2×φ9（移到 Y = W/2 = 12，匹配底板 Y∈[0, W]）
        with BuildSketch(Plane.XY):                                 # noqa: F405
            with Locations((P.PITCH9 / 2, P.W / 2), (-P.PITCH9 / 2, P.W / 2)):  # noqa: F405
                Circle(P.D_9 / 2)                                   # noqa: F405
        extrude(amount=P.T, mode=Mode.SUBTRACT)                     # noqa: F405

    part = p.part

    # 所有孔都用 part - tool（技巧 9 最终结论）
    TOOLS = []
    for sgn in (-1, 1):
        xc = sgn * (P.ARM_XI + P.ARM_T / 2)
        TOOLS.append(Pos(xc, P.HEAD_Y, P.HEAD_Z)                    # 2-φ8 横向销孔（轴沿 X，贯穿两臂）
                     * Cylinder(P.D_PIN / 2, P.ARM_T + 12, rotation=(0, 90, 0)))  # noqa: F405
        TOOLS.append(Pos(xc, P.HEAD_Y - 4, P.HEAD_Z)                # 2-φ3 通孔（轴沿 Y）
                     * Cylinder(P.D_CS / 2, 36, rotation=(90, 0, 0)))             # noqa: F405
        TOOLS.append(Pos(xc, P.HEAD_Y - P.R_HEAD + P.CS_DEPTH / 2, P.HEAD_Z)  # 2-φ6 沉孔（深 3）
                     * Cylinder(P.D_CB / 2, P.CS_DEPTH, rotation=(90, 0, 0)))    # noqa: F405
    for t in TOOLS:
        part = part - t

    bb = part.bounding_box()
    os.makedirs(out_dir, exist_ok=True)
    step = os.path.join(out_dir, P.TAG + ".step")
    stl = os.path.join(out_dir, P.TAG + ".stl")
    export_step(part, step)                                         # noqa: F405
    export_stl(part, stl)                                           # noqa: F405

    return [("model_step", step), ("model_stl", stl)], {
        "bounding_box": [round(bb.max.X - bb.min.X, 2),
                         round(bb.max.Y - bb.min.Y, 2),
                         round(bb.max.Z - bb.min.Z, 2)],
        "volume": round(part.volume, 1),
        "solids": len(part.solids()),
        "bbox_xyz_min": [round(bb.min.X, 2), round(bb.min.Y, 2), round(bb.min.Z, 2)],
        "bbox_xyz_max": [round(bb.max.X, 2), round(bb.max.Y, 2), round(bb.max.Z, 2)],
    }


if __name__ == "__main__":
    run_stage("s1_build", handler)