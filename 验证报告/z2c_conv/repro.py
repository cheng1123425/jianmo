# -*- coding: utf-8 -*-
"""转化实验（分阶段）：Zero-to-CAD 样本 uuid 13d78484 → build123d。"""
from build123d import *

W, D, H = 70.0, 20.0, 10.0
FL, FT = 30.0, 5.0
RW, RT, RH = 15.0, 4.0, 5.0
CH = 1.0
HD, CBD, CBDEP = 4.0, 6.5, 3.0


def stat(tag, p):
    bb = p.bounding_box()
    print("%-14s vol=%.3f bbox=%.2f×%.2f×%.2f X[%.1f,%.1f] Y[%.1f,%.1f] Z[%.1f,%.1f]"
          % (tag, p.volume, bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z,
             bb.min.X, bb.max.X, bb.min.Y, bb.max.Y, bb.min.Z, bb.max.Z))


# base: rect(70,20).extrude(10)
base = Pos(0, 0, H / 2) * Box(W, D, H)
stat("1 base", base)
# flange: rect(30,5).translate((50,0)).extrude(10)
flange = Pos(W / 2 + FL / 2, 0, H / 2) * Box(FL, FT, H)
stat("2 flange", flange)
part = base + flange
stat("3 union", part)
# rib on top face
rib = Pos(0, 0, H + RH / 2) * Box(RW, RT, RH)
part = part + rib
stat("4 +rib", part)

# cbore hole：样本 = faces(">X").workplane().pushPoints([(FT/2,0)]).cboreHole(4,6.5,3)
# +X 面在 X=max；孔沿 -X 钻入；局部 (FT/2,0)
xmax = part.bounding_box().max.X
part = part - (Pos(xmax, FT / 2, H / 2) * Rot(0, 90, 0)
               * CounterBoreHole(radius=HD / 2, counter_bore_radius=CBD / 2,
                                 counter_bore_depth=CBDEP, depth=FL))
stat("5 -cbore", part)
print("ORIG volume=13328.504 bbox=70.00×20.00×15.00")
