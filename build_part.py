# -*- coding: utf-8 -*-
r"""
【第 1 段 / 三维建模】读 params.py → 建实体 → 导出 STEP / STL
"""
import math
import os
import sys

from build123d import *

import params as P

# ---------------- 凹颈圆弧（R_NECK 与中心圆弧 / 侧圆弧外切） ----------------
fx = (P.D_SIDE ** 2 + (P.R_NECK + P.R_OUT_CEN) ** 2 - (P.R_NECK + P.R_SIDE) ** 2) / (2 * P.D_SIDE)
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
A_br = Vector(A_tr.X, -A_tr.Y)
A_bl = Vector(A_tl.X, -A_tl.Y)
B_rt = tang(F_tr, B_R, P.R_SIDE)
B_rb = Vector(B_rt.X, -B_rt.Y)
B_lt = tang(F_tl, B_L, P.R_SIDE)
B_lb = Vector(B_lt.X, -B_lt.Y)

a_c_tr = math.degrees(math.atan2(A_tr.Y, A_tr.X))
a_c_tl = math.degrees(math.atan2(A_tl.Y, A_tl.X))
a_b = math.degrees(math.atan2(B_rt.Y - B_R.Y, B_rt.X - B_R.X))
NECK = angF(F_tr, B_rt) - angF(F_tr, A_tr)

# ---------------- 建模 ----------------
with BuildPart() as p:
    with BuildSketch(Plane.XY):
        with BuildLine():
            CenterArc(A, P.R_OUT_CEN, a_c_tl, a_c_tr - a_c_tl)                    # 中心圆弧(上)
            CenterArc(F_tr, P.R_NECK, angF(F_tr, A_tr), NECK)                    # 右上凹颈
            CenterArc(B_R, P.R_SIDE, a_b, -2 * a_b)                              # 右侧圆弧
            CenterArc(F_br, P.R_NECK, angF(F_br, B_rb), angF(F_br, A_br) - angF(F_br, B_rb))
            CenterArc(A, P.R_OUT_CEN, -a_c_tr, -(a_c_tl - a_c_tr))               # 中心圆弧(下)
            CenterArc(F_bl, P.R_NECK, angF(F_bl, A_bl), angF(F_bl, B_lb) - angF(F_bl, A_bl))
            CenterArc(B_L, P.R_SIDE, a_b - 180, -2 * a_b)                        # 左侧圆弧
            CenterArc(F_tl, P.R_NECK, angF(F_tl, B_lt), angF(F_tl, A_tl) - angF(F_tl, B_lt))
        make_face()
    extrude(amount=P.BASE_T)

    # 中心凸台
    with BuildSketch(Plane.XY * Pos(0, 0, P.BASE_T)):
        Circle(P.R_BOSS)
    extrude(amount=P.H_CEN)

    # 侧凸台
    with BuildSketch(Plane.XY * Pos(0, 0, P.BASE_T)):
        with Locations((P.D_SIDE, 0), (-P.D_SIDE, 0)):
            Circle(P.R_SIDE)
    extrude(amount=P.H_WING)

    # 中心通孔（贯通全高）
    with BuildSketch(Plane.XY):
        Circle(P.D_HOLE_CEN / 2)
    extrude(amount=P.BASE_T + P.H_CEN, mode=Mode.SUBTRACT)

    # 两侧通孔
    with BuildSketch(Plane.XY):
        with Locations((P.D_SIDE, 0), (-P.D_SIDE, 0)):
            Circle(P.D_HOLE_SIDE / 2)
    extrude(amount=P.BASE_T + P.H_WING, mode=Mode.SUBTRACT)

part = p.part
bb = part.bounding_box()
print("[3D] 包围盒 X[%.1f,%.1f] Y[%.1f,%.1f] Z[%.1f,%.1f]"
      % (bb.min.X, bb.max.X, bb.min.Y, bb.max.Y, bb.min.Z, bb.max.Z))
print("[3D] 体积 = %.1f mm^3" % part.volume)

os.makedirs(P.STEP_DIR, exist_ok=True)
step = os.path.join(P.STEP_DIR, P.TAG + ".step")
stl = os.path.join(P.STEP_DIR, P.TAG + ".stl")
export_step(part, step)
export_stl(part, stl)
print("[3D] 已导出:", step)
