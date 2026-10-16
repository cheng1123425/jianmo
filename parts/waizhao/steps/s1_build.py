# -*- coding: utf-8 -*-
r"""waizhao（外罩 sj-012）—— 三维建模 → STEP / STL

构造（坐标系：z=0 为底面，回转轴 = Z，中心在原点）：
  1) 回转外形：底法兰 Ø48×3 → **圆柱本体 Ø28**（z=3 → 48.5）
     → 台阶 Ø28→Ø20.53 → 40° 锥帽 → 顶面 z=52
  2) 内腔：Ø22 直腔到 z=44 ∪ R7 球冠（球心 z=41）∪ Ø6.5 顶孔（贯穿顶面）
  3) 壁上长圆孔 Ø6×21（正面 +Y，径向贯穿壁），孔心 z=25.52
  4) 底法兰 4×Ø4.5 通孔，BCD Ø38（N/S/E/W）
  5) 4 条径向加强筋（等宽 6 的平行侧板，45°+90k）

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

    r_flange = P.FLANGE_D / 2.0        # 24
    r_body = P.BODY_D / 2.0            # 14
    r_cap_bot = P.CAP_D_BOT / 2.0      # 10.265
    r_cap_top = P.CAP_D_TOP / 2.0      # 8.99
    r_bore = P.BORE_D / 2.0            # 11
    r_hole = P.TOP_HOLE_D / 2.0        # 3.25

    with BuildPart() as bp:
        # ---- 1. 回转外形（法兰 + 圆柱本体 + 台阶 + 40° 锥帽）----
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Polyline(
                    (0, 0),
                    (r_flange, 0.0),
                    (r_flange, P.FLANGE_T),
                    (r_body, P.Z_BODY_BOT),
                    (r_body, P.Z_SHOULDER),
                    (r_cap_bot, P.Z_SHOULDER),
                    (r_cap_top, P.Z_TOP),
                    (0, P.Z_TOP),
                    (0, 0),
                )
            make_face()
        revolve(axis=Axis.Z)

        # ---- 2a. 内腔 Ø22 到 z=44 ----
        with BuildSketch(Plane.XY.offset(-1.0)):
            Circle(r_bore)
        extrude(amount=P.Z_BORE_TOP + 1.0, mode=Mode.SUBTRACT)

        # ---- 2b. 顶部球冠 R7（球心 z=41）----
        with Locations((0, 0, P.DOME_ZC)):
            Sphere(P.DOME_R, mode=Mode.SUBTRACT)

        # ---- 2c. 顶孔 Ø6.5（贯穿顶面）----
        with BuildSketch(Plane.XY.offset(P.Z_BORE_TOP)):
            Circle(r_hole)
        extrude(amount=(P.Z_TOP - P.Z_BORE_TOP) + 1.0, mode=Mode.SUBTRACT)

        # ---- 3. 底法兰 4×Ø4.5（BCD Ø38，N/S/E/W）----
        with BuildSketch(Plane.XY.offset(P.FLANGE_T + 1.0)):
            with PolarLocations(P.BASE_HOLE_BCD / 2.0, 4, start_angle=90):
                Circle(P.BASE_HOLE_D / 2.0)
        extrude(amount=-(P.FLANGE_T + 2.0), mode=Mode.SUBTRACT)

    part = bp.part

    # ---- 4. 4 条径向加强筋（等宽 4.0 平行侧板）----
    with BuildPart() as rp:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Polyline((P.RIB_R_IN, P.Z_BODY_BOT),
                         (P.RIB_R_OUT, P.Z_BODY_BOT),
                         (P.RIB_R_OUT, P.RIB_Z_KNEE),
                         (P.RIB_FACE_END_R, P.RIB_FACE_END_Z),
                         (P.RIB_R_IN, P.RIB_Z_TOP),
                         (P.RIB_R_IN, P.Z_BODY_BOT))
            make_face()
        extrude(amount=P.RIB_W / 2.0, both=True)
    rib = rp.part
    for _a in P.RIB_ANGLES:
        part = part + Rot(0, 0, _a) * rib

    # ---- 5. 壁上长圆孔（正面 +Y，径向贯穿壁）----
    with BuildPart() as sp:
        with BuildSketch(Plane.XZ):
            with BuildLine():
                Polyline((P.SLOT_W / 2.0, P.SLOT_ZC - P.SLOT_STRAIGHT / 2.0),
                         (P.SLOT_W / 2.0, P.SLOT_ZC + P.SLOT_STRAIGHT / 2.0))
                CenterArc((0, P.SLOT_ZC + P.SLOT_STRAIGHT / 2.0), P.SLOT_W / 2.0, 0, 180)
                Polyline((-P.SLOT_W / 2.0, P.SLOT_ZC + P.SLOT_STRAIGHT / 2.0),
                         (-P.SLOT_W / 2.0, P.SLOT_ZC - P.SLOT_STRAIGHT / 2.0))
                CenterArc((0, P.SLOT_ZC - P.SLOT_STRAIGHT / 2.0), P.SLOT_W / 2.0, 180, 180)
            make_face()
        extrude(amount=-40.0)          # Plane.XZ 法向 = -Y ⇒ 往 +Y 拉，只切正面壁
    part = part - sp.part

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
