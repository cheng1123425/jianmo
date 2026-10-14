# -*- coding: utf-8 -*-
r"""s1_build —— 三维建模 → STEP / STL

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
sys.path.insert(0, ROOT)                              # 项目根（msgio / lib 所在）
sys.path.insert(0, os.path.dirname(HERE))             # 零部件目录（dims_spec / ref_spec）

from build123d import *                       # noqa: F401,F403
from msgio import run_stage, ref_path, ref_data, exec_module


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"), "gasket_params")
    out_dir = ref_data(in_msg, "out_dir")

    # ---------------- 凹颈圆弧（R_NECK 与中心圆弧 / 侧圆弧外切） ----------------
    fx = (P.SIDE_BOSS_P ** 2 + (P.NECK_R + P.CEN_ARC_R) ** 2
          - (P.NECK_R + P.SIDE_BOSS_R) ** 2) / (2 * P.SIDE_BOSS_P)
    fy = math.sqrt((P.NECK_R + P.CEN_ARC_R) ** 2 - fx ** 2)

    def tang(F, C, r):
        d = F - C
        return C + (d / d.length) * r

    def angF(F, Pt):
        return math.degrees(math.atan2(Pt.Y - F.Y, Pt.X - F.X))

    F_tr, F_tl = Vector(fx, fy), Vector(-fx, fy)
    F_br, F_bl = Vector(fx, -fy), Vector(-fx, -fy)
    A, B_R, B_L = Vector(0, 0), Vector(P.SIDE_BOSS_P, 0), Vector(-P.SIDE_BOSS_P, 0)

    A_tr = tang(F_tr, A, P.CEN_ARC_R)
    A_tl = tang(F_tl, A, P.CEN_ARC_R)
    A_br, A_bl = Vector(A_tr.X, -A_tr.Y), Vector(A_tl.X, -A_tl.Y)
    B_rt = tang(F_tr, B_R, P.SIDE_BOSS_R)
    B_rb = Vector(B_rt.X, -B_rt.Y)
    B_lt = tang(F_tl, B_L, P.SIDE_BOSS_R)
    B_lb = Vector(B_lt.X, -B_lt.Y)

    a_c_tr = math.degrees(math.atan2(A_tr.Y, A_tr.X))
    a_c_tl = math.degrees(math.atan2(A_tl.Y, A_tl.X))
    a_b = math.degrees(math.atan2(B_rt.Y - B_R.Y, B_rt.X - B_R.X))
    NECK = angF(F_tr, B_rt) - angF(F_tr, A_tr)

    # ---------------- 建模 ----------------
    with BuildPart() as p:                                          # noqa: F405
        with BuildSketch(Plane.XY):                                 # noqa: F405
            with BuildLine():                                       # noqa: F405
                CenterArc(A, P.CEN_ARC_R, a_c_tl, a_c_tr - a_c_tl)                  # noqa: F405
                CenterArc(F_tr, P.NECK_R, angF(F_tr, A_tr), NECK)                    # noqa: F405
                CenterArc(B_R, P.SIDE_BOSS_R, a_b, -2 * a_b)                              # noqa: F405
                CenterArc(F_br, P.NECK_R, angF(F_br, B_rb),                          # noqa: F405
                          angF(F_br, A_br) - angF(F_br, B_rb))
                CenterArc(A, P.CEN_ARC_R, -a_c_tr, -(a_c_tl - a_c_tr))               # noqa: F405
                CenterArc(F_bl, P.NECK_R, angF(F_bl, A_bl),                          # noqa: F405
                          angF(F_bl, B_lb) - angF(F_bl, A_bl))
                CenterArc(B_L, P.SIDE_BOSS_R, a_b - 180, -2 * a_b)                        # noqa: F405
                CenterArc(F_tl, P.NECK_R, angF(F_tl, B_lt),                          # noqa: F405
                          angF(F_tl, A_tl) - angF(F_tl, B_lt))
            make_face()                                             # noqa: F405
        extrude(amount=P.BASE_T_Z)                                    # noqa: F405

        with BuildSketch(Plane.XY * Pos(0, 0, P.BASE_T_Z)):           # noqa: F405
            Circle(P.CEN_BOSS_R)                                        # noqa: F405
        extrude(amount=P.CEN_BOSS_H_Z)                                     # noqa: F405

        with BuildSketch(Plane.XY * Pos(0, 0, P.BASE_T_Z)):           # noqa: F405
            with Locations((P.SIDE_BOSS_P, 0), (-P.SIDE_BOSS_P, 0)):          # noqa: F405
                Circle(P.SIDE_BOSS_R)                                    # noqa: F405
        extrude(amount=P.SIDE_BOSS_H_Z)                                    # noqa: F405

        with BuildSketch(Plane.XY):                                 # noqa: F405
            Circle(P.CEN_HOLE_D / 2)                                # noqa: F405
        extrude(amount=P.BASE_T_Z + P.CEN_BOSS_H_Z, mode=Mode.SUBTRACT)      # noqa: F405

        with BuildSketch(Plane.XY):                                 # noqa: F405
            with Locations((P.SIDE_BOSS_P, 0), (-P.SIDE_BOSS_P, 0)):          # noqa: F405
                Circle(P.SIDE_HOLE_D / 2)                           # noqa: F405
        extrude(amount=P.BASE_T_Z + P.SIDE_BOSS_H_Z, mode=Mode.SUBTRACT)     # noqa: F405

    part = p.part
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
    }


if __name__ == "__main__":
    run_stage("s1_build", handler)
