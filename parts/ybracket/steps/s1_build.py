# -*- coding: utf-8 -*-
r"""s1_build —— 三维建模 → STEP / STL（双耳直角支座 · C 形夹持支架）

构造（坐标系：原点 = 背面·底面·对称中心）：
  1) 背板：X∈[-58,58]，Y∈[0,20]，Z∈[0,120]；顶部背面 30 高斜切
  2) 顶臂：X∈[-58,58]，Y∈[0,116]，Z∈[88,120]（与背板间开口 96）
  3) 底座：X∈[-58,58]，Y∈[0,144]，Z∈[0,48]；前部 Y∈[102,144] 斜削（半宽 58→33）
  4) 双耳：R42 圆头（心 = ±58,72），厚 32（Z∈[0,32]），与底座融合
  5) 孔：顶臂中央台阶孔（Ø54 深 22 + Ø32 通）+ 双耳 2-Ø42（轴 Z，贯穿）

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


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"),
                    os.path.basename(ref_path(in_msg, "params"))[:-3])
    out_dir = ref_data(in_msg, "out_dir")

    hw = P.WALL_W / 2.0            # 58（中央块半宽）
    z_arm0 = P.HEIGHT_Z - P.ARM_T  # 88（顶臂底）

    with BuildPart() as p:                       # noqa: F405
        # ============== 1. 背板 ==============
        with BuildSketch(Plane.YZ) as s_wall:    # noqa: F405（YZ 平面，法向 +X）
            with BuildLine() as wl:              # noqa: F405
                Polyline((0, 0), (P.WALL_T, 0), (P.WALL_T, P.HEIGHT_Z),
                         (0, P.HEIGHT_Z - P.WALL_CHAMF_Z), (0, 0))   # noqa: F405
            make_face()                          # noqa: F405
        extrude(amount=hw, both=True)            # noqa: F405（沿 ±X 各 58）

        # ============== 2. 顶臂 ==============
        with BuildSketch(Plane.YZ.offset(-hw)) as s_arm:   # noqa: F405
            with BuildLine() as al:              # noqa: F405
                Polyline((0, z_arm0), (P.ARM_LEN, z_arm0), (P.ARM_LEN, P.HEIGHT_Z),
                         (0, P.HEIGHT_Z), (0, z_arm0))               # noqa: F405
            make_face()                          # noqa: F405
        extrude(amount=P.WALL_W)                 # noqa: F405（沿 +X 116）

        # ============== 3. 底座（带前部斜削） ==============
        taper_y1 = P.DEPTH_Y                     # 144
        hw_f = P.BASE_FRONT_W / 2.0              # 33（前端半宽）
        with BuildSketch(Plane.YZ.offset(-hw)) as s_base:   # noqa: F405
            with BuildLine() as bl:              # noqa: F405
                Polyline((0, 0), (taper_y1, 0), (taper_y1, hw_f),
                         (P.BASE_TAPER_Y0, hw), (0, hw), (0, 0))     # noqa: F405
            make_face()                          # noqa: F405
        extrude(amount=P.WALL_W)                 # noqa: F405

        # ============== 4. 双耳（R42 圆头，厚 32） ==============
        # 耳圆头圆心 X=±58（中央块边缘）、Y=72（总深一半），半径 42：
        #   向外到 X=±100（总宽 200 = 116 + 2×42 ✓），Y∈[30,114]。
        # 圆头与中央块在 X=±58 相切，直接作为 R42 圆盘拉伸即可自然融合。
        for sx in (+1, -1):
            with BuildSketch(Plane.XY) as s_ear:  # noqa: F405
                with Locations((sx * P.EAR_PITCH / 2.0, P.EAR_CY)):   # noqa: F405
                    Circle(P.EAR_R)              # noqa: F405
            extrude(amount=P.EAR_T)              # noqa: F405

    part = p.part

    # ============== 5. 孔（后段切除） ==============
    tools = []
    # 顶臂中央台阶孔（轴 Z，心 (0, 72)）
    cy = P.EAR_CY
    tools.append(Pos(0, cy, P.HEIGHT_Z - P.CBORE_DEPTH / 2.0)
                 * Cylinder(P.D_CBORE / 2.0, P.CBORE_DEPTH + 2.0))       # noqa: F405
    tools.append(Pos(0, cy, z_arm0 + P.ARM_T / 2.0)
                 * Cylinder(P.D_THRU / 2.0, P.ARM_T + 4.0))              # noqa: F405
    # 双耳 2-Ø42（轴 Z，贯穿耳厚）
    for sx in (+1, -1):
        tools.append(Pos(sx * P.EAR_PITCH / 2.0, cy, P.EAR_T / 2.0)
                     * Cylinder(42.0 / 2.0, P.EAR_T + 4.0))              # noqa: F405
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
