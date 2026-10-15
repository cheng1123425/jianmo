# -*- coding: utf-8 -*-
r"""waizhao（外罩 sj-012）—— 三维建模 → STEP / STL

构造（坐标系：z=0 为底面，回转轴 = Z，中心在原点）：
  1) 回转外形：底法兰 Ø47.8×3 → 外锥 Ø36.4(z=3) → Ø29.4(z=36) → 直颈 Ø29.4 到 z=48（顶面）
  2) 内腔：Ø22 从 z=0.3 起，到 z=35；顶部 R11 半球穹顶（顶到 z=46）
  3) 顶孔 Ø6.5 贯穿顶面
  4) 底法兰 4×Ø4.5 通孔，BCD Ø38（N/S/E/W）
  5) 4 条径向加强筋（45°+90k，宽 6.0，斜靠外锥）

⚠️ 本零件自带 s1_build（不走 IR 算子集）的原因：
   外罩是**回转体（revolve）**，而当前 IR→build123d 生成器把 `revolve`
   当 `extrude` 生成（ops 注册表标 WRONG，见 lib/ops.py / lessons §8.9）。
   走 IR 路会**静默产生错几何**，所以这里用零件自己的构造脚本（项目既有的
   "逃生口"约定：零件自带 s1_build 优先于共享 IR 实现）。

入参消息  refs: params；data: out_dir
产出      model_step / model_stl
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))

from build123d import *                       # noqa: F401,F403
from msgio import run_stage, ref_path, ref_data, exec_module   # noqa: E402


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"),
                    os.path.basename(ref_path(in_msg, "params"))[:-3])
    out_dir = ref_data(in_msg, "out_dir") or os.path.dirname(ref_path(in_msg, "params"))

    with BuildPart() as bp:
        # ---- 1. 回转外形 ----
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Polyline(
                    (0, 0),
                    (P.FLANGE_D / 2, 0),
                    (P.FLANGE_D / 2, P.FLANGE_T),
                    (P.CONE_D_BOT / 2, P.FLANGE_T + 2.4),
                    (P.CONE_D_TOP / 2, P.Z_CONE_TOP),
                    (P.NECK_D / 2, P.Z_TOP),
                    (0, P.Z_TOP),
                    (0, 0),
                )
            make_face()
        revolve(axis=Axis.Z)

        # ---- 2. 内腔 Ø22 ----
        with BuildSketch(Plane.XY.offset(0.3)):
            Circle(P.BORE_D / 2)
        extrude(amount=P.Z_BORE_TOP - 0.3, mode=Mode.SUBTRACT)

        # ---- 2b. 顶部内穹（半球）----
        with Locations((0, 0, P.Z_BORE_TOP)):
            Sphere(P.DOME_R, mode=Mode.SUBTRACT)

        # ---- 3. 顶孔 Ø6.5 ----
        with BuildSketch(Plane.XY.offset(P.Z_TOP + 1)):
            Circle(P.TOP_HOLE_D / 2)
        extrude(amount=-(P.Z_TOP + 1 - (P.Z_BORE_TOP + 6)), mode=Mode.SUBTRACT)

        # ---- 4. 底法兰 4×Ø4.5（BCD Ø38，N/S/E/W）----
        with BuildSketch(Plane.XY.offset(P.FLANGE_T + 1)):
            with PolarLocations(P.BASE_HOLE_BCD / 2, 4, start_angle=90):
                Circle(P.BASE_HOLE_D / 2)
        extrude(amount=-(P.FLANGE_T + 2), mode=Mode.SUBTRACT)

    part = bp.part

    # ---- 5. 4 条径向加强筋 ----
    with BuildPart() as rp:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Polyline((P.CONE_D_BOT / 2, P.FLANGE_T),
                         (P.FLANGE_D / 2, P.FLANGE_T),
                         (P.CONE_D_TOP / 2, P.Z_CONE_TOP),
                         (P.CONE_D_BOT / 2, P.FLANGE_T))
            make_face()
        extrude(amount=P.RIB_W / 2, both=True)
    rib = rp.part
    for _a in (45.0, 135.0, 225.0, 315.0):
        part = part + Rot(0, 0, _a) * rib

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
