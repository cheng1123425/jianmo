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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build123d import *                       # noqa: F401,F403
from msgio import run_stage, ref_path, ref_data, exec_module


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"), "gasket_params")
    out_dir = ref_data(in_msg, "out_dir")

    # ---------------- 凹颈圆弧（R_NECK 与中心圆弧 / 侧圆弧外切） ----------------
    fx = (P.D_SIDE ** 2 + (P.R_NECK + P.R_OUT_CEN) ** 2
          - (P.R_NECK + P.R_SIDE) ** 2) / (2 * P.D_SIDE)
    fy = math.sqrt((P.R_NECK + P.R_OUT_CEN) ** 2 - fx ** 2)

    def tang(F, C, r):
        d = F - C
        return C + (d / d.length) * r

    def angF(F, Pt):
        return math.degrees(math.atan2(Pt.Y - F.Y, Pt.X - F.X))

    F_tr, F_tl = Vector(fx, fy), Vector(-fx, fy)
    F_br, F_bl = Vector(fx, -fy), Vector(-fx, -fy)
    A, B_R, B_L = Vector(0, 0), Vector(P.D_SIDE, 0), Vector(-P.D_SIDE, 0)

    A_tr = tang(F_tr, A, P.R_OUT_CEN)
    A_tl = tang(F_tl, A, P.R_OUT_CEN)
    A_br, A_bl = Vector(A_tr.X, -A_tr.Y), Vector(A_tl.X, -A_tl.Y)
    B_rt = tang(F_tr, B_R, P.R_SIDE)
    B_rb = Vector(B_rt.X, -B_rt.Y)
    B_lt = tang(F_tl, B_L, P.R_SIDE)
    B_lb = Vector(B_lt.X, -B_lt.Y)

    a_c_tr = math.degrees(math.atan2(A_tr.Y, A_tr.X))
    a_c_tl = math.degrees(math.atan2(A_tl.Y, A_tl.X))
    a_b = math.degrees(math.atan2(B_rt.Y - B_R.Y, B_rt.X - B_R.X))
    NECK = angF(F_tr, B_rt) - angF(F_tr, A_tr)

    # ---------------- 建模 ----------------
    with BuildPart() as p:                                          # noqa: F405
        with BuildSketch(Plane.XY):                                 # noqa: F405
            with BuildLine():                                       # noqa: F405
                CenterArc(A, P.R_OUT_CEN, a_c_tl, a_c_tr - a_c_tl)                  # noqa: F405
                CenterArc(F_tr, P.R_NECK, angF(F_tr, A_tr), NECK)                    # noqa: F405
                CenterArc(B_R, P.R_SIDE, a_b, -2 * a_b)                              # noqa: F405
                CenterArc(F_br, P.R_NECK, angF(F_br, B_rb),                          # noqa: F405
                          angF(F_br, A_br) - angF(F_br, B_rb))
                CenterArc(A, P.R_OUT_CEN, -a_c_tr, -(a_c_tl - a_c_tr))               # noqa: F405
                CenterArc(F_bl, P.R_NECK, angF(F_bl, A_bl),                          # noqa: F405
                          angF(F_bl, B_lb) - angF(F_bl, A_bl))
                CenterArc(B_L, P.R_SIDE, a_b - 180, -2 * a_b)                        # noqa: F405
                CenterArc(F_tl, P.R_NECK, angF(F_tl, B_lt),                          # noqa: F405
                          angF(F_tl, A_tl) - angF(F_tl, B_lt))
            make_face()                                             # noqa: F405
        extrude(amount=P.BASE_T)                                    # noqa: F405

        with BuildSketch(Plane.XY * Pos(0, 0, P.BASE_T)):           # noqa: F405
            Circle(P.R_BOSS)                                        # noqa: F405
        extrude(amount=P.H_CEN)                                     # noqa: F405

        with BuildSketch(Plane.XY * Pos(0, 0, P.BASE_T)):           # noqa: F405
            with Locations((P.D_SIDE, 0), (-P.D_SIDE, 0)):          # noqa: F405
                Circle(P.R_SIDE)                                    # noqa: F405
        extrude(amount=P.H_WING)                                    # noqa: F405

        with BuildSketch(Plane.XY):                                 # noqa: F405
            Circle(P.D_HOLE_CEN / 2)                                # noqa: F405
        extrude(amount=P.BASE_T + P.H_CEN, mode=Mode.SUBTRACT)      # noqa: F405

        with BuildSketch(Plane.XY):                                 # noqa: F405
            with Locations((P.D_SIDE, 0), (-P.D_SIDE, 0)):          # noqa: F405
                Circle(P.D_HOLE_SIDE / 2)                           # noqa: F405
        extrude(amount=P.BASE_T + P.H_WING, mode=Mode.SUBTRACT)     # noqa: F405

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
