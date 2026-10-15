# -*- coding: utf-8 -*-
r"""转化实验（独立验证）：挖出的惯用法 → build123d 算子 → 建件验证几何。

挖掘来源（样本 13d78484 的 CadQuery）：
    result.faces(">X").workplane().pushPoints([(2.5,0)]).cboreHole(4, 6.5, 3)
即 "在面上、于若干点处钻沉头孔"。数据化形式（拟入 IR 词表）：
    {"op":"cbore_hole", "face":"+Z", "at":[[u,v],...], "d":4.0, "cbore_d":6.5, "cbore_depth":3.0}

注：Zero-to-CAD 的 step 是"目标模型"、code 是"agent 复现"，二者不匹配，
故不拿样本 step 做基准，改为独立验证算子几何（孔半径/沉孔深/体积）。
"""
import math
from build123d import *


def build_with_cbore(block_len, block_w, block_h, op):
    """按算子数据建件：块 + 在指定面若干点钻沉头孔。"""
    d, cd, cdep = op["d"], op["cbore_d"], op["cbore_depth"]
    with BuildPart() as bp:
        Box(block_len, block_w, block_h)
        for (u, v) in op["at"]:
            with Locations(Pos(u, v, block_h / 2)):      # +Z 面中心
                CounterBoreHole(radius=d / 2, counter_bore_radius=cd / 2,
                                counter_bore_depth=cdep)
    return bp.part


op = {"op": "cbore_hole", "face": "+Z", "at": [(0.0, 0.0)],
      "d": 4.0, "cbore_d": 6.5, "cbore_depth": 3.0}

block = Pos(0, 0, 5) * Box(20, 20, 10)
part = build_with_cbore(20, 20, 10, op)
print("基块 vol=%.3f" % block.volume)
print("钻后 vol=%.3f" % part.volume)

expect_remove = math.pi * 2**2 * 10 + math.pi * (3.25**2 - 2**2) * 3
print("期望去除=%.3f → 期望 vol=%.3f" % (expect_remove, block.volume - expect_remove))

cs = sorted({round(float(f.radius), 3) for f in part.faces() if "CYLINDER" in str(f.geom_type)})
print("圆柱面半径:", cs, "（应含 2.0=Ø4通孔 与 3.25=Ø6.5沉孔）")
ok = (2.0 in cs and 3.25 in cs
      and abs(part.volume - (block.volume - expect_remove)) < 0.5)
print("判定:", "PASS ✅" if ok else "FAIL ❌")
