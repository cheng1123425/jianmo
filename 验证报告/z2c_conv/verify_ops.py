# -*- coding: utf-8 -*-
r"""转化算子【独立几何验证】驱动。

Zero-to-CAD 的 step_file 是"目标模型"、cadquery_file 是"agent 复现"，二者不匹配，
故不拿样本 step 当基准；改为一律【独立验证】：建已知基体 + 施算子 + 解析算期望 + 比对。

判定口径：
  * 体积：|实测去除量 − 解析去除量| < 0.5（mm³）；
  * 特征：圆柱面半径集合含预期值（如 Ø9 通孔 → r=4.5）。
"""
import math
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build123d import (BuildPart, Box, Cylinder, Mode, Pos, Align,
                       ThreePointArc, Spline, Line, extrude)
from op_lib import apply_ops


def cyl_radii(part):
    return sorted({round(float(f.radius), 3) for f in part.faces()
                   if "CYLINDER" in str(f.geom_type)})


def check(name, base_vol, part, expect_remove, expect_radii=()):
    got_remove = base_vol - part.volume
    dv = abs(got_remove - expect_remove)
    rs = cyl_radii(part)
    radii_ok = all(any(abs(r - e) < 1e-6 for r in rs) for e in expect_radii)
    ok = dv < 0.5 and radii_ok
    print("%-12s base=%9.3f  去除: 实测=%9.3f 期望=%9.3f Δ=%6.3f | 圆柱r=%s 期望%s | %s"
          % (name, base_vol, got_remove, expect_remove, dv, rs,
             list(expect_radii), "PASS ✅" if ok else "FAIL ❌"))
    return ok


results = []

# ----------------------------------------------------------- ① hole_grid 矩形布孔
# 板 80×80×10，3×2 孔，Ø9，边距 10 → x∈{-30,0,30}, y∈{-30,30}
with BuildPart() as bp1:
    Box(80, 80, 10)
    apply_ops(bp1, [{"op": "hole_grid", "d": 9.0, "z": 5.0,
                     "at": [[-30, -30], [0, -30], [30, -30],
                            [-30, 30], [0, 30], [30, 30]]}])
n = 6
results.append(check("hole_grid", 80 * 80 * 10, bp1.part,
                     n * math.pi * 4.5 ** 2 * 10, expect_radii=(4.5,)))

# ----------------------------------------------------------- ② bolt_circle 螺栓圆
# 圆盘 r=30, t=5，6 孔 Ø4.5，BCD r=20
with BuildPart() as bp2:
    Cylinder(radius=30.0, height=5.0)
    apply_ops(bp2, [{"op": "bolt_circle", "n": 6, "d": 4.5, "bcd_r": 20.0, "z": 2.5}])
results.append(check("bolt_circle", math.pi * 30 ** 2 * 5, bp2.part,
                     6 * math.pi * 2.25 ** 2 * 5, expect_radii=(2.25,)))

# ----------------------------------------------------------- ③ cbore_hole 沉头孔
# 块 20×20×10，顶面中心 1 个沉头孔 Ø4 / Ø6.5 / 深 3
with BuildPart() as bp3:
    Box(20, 20, 10)
    apply_ops(bp3, [{"op": "cbore_hole", "d": 4.0, "cbore_d": 6.5,
                     "cbore_depth": 3.0, "z": 5.0, "at": [[0.0, 0.0]]}])
rm = math.pi * 2 ** 2 * 10 + math.pi * (3.25 ** 2 - 2 ** 2) * 3
results.append(check("cbore_hole", 20 * 20 * 10, bp3.part, rm,
                     expect_radii=(2.0, 3.25)))

# ----------------------------------------------------------- ④ fillet 选择性圆角
# 块 40×40×10，倒 4 条竖边（轴Z）R3 → 每条去 r²(1−π/4)·h
with BuildPart() as bp4:
    Box(40, 40, 10)
    apply_ops(bp4, [{"op": "fillet", "dir": "Z", "between": [-1, 11], "r": 3.0}])
rm = 4 * (3.0 ** 2 * (1 - math.pi / 4)) * 10
results.append(check("fillet", 40 * 40 * 10, bp4.part, rm))

# ----------------------------------------------------------- ⑤ chamfer 选择性倒角
# 块 40×40×10（默认居中，z∈[-5,5]），倒 2 条底部长边（方向X、位置Z≈-5）d=2
with BuildPart() as bp5:
    Box(40, 40, 10)
    apply_ops(bp5, [{"op": "chamfer", "dir": "X", "pos_axis": "Z",
                     "between": [-6, -4], "d": 2.0}])
rm = 2 * (2.0 ** 2 / 2) * 40
results.append(check("chamfer", 40 * 40 * 10, bp5.part, rm))

# ----------------------------------------------------------- ⑥ 组合件：法兰盘
# 盘 r=62.5(Ø125) t=10 + 6×Ø6 螺栓圆(BCD Ø105) + 中心孔 Ø90
# 演示"多算子组合成一个真实零件特征集"（阀盖底部法兰形态）
with BuildPart() as bp6:
    Cylinder(radius=62.5, height=10.0)
    apply_ops(bp6, [
        {"op": "bolt_circle", "n": 6, "d": 6.0, "bcd_r": 52.5, "z": 5.0},
        {"op": "hole_grid", "d": 90.0, "z": 5.0, "at": [[0.0, 0.0]]},  # 中心通孔
    ])
rm = 6 * math.pi * 3.0 ** 2 * 10 + math.pi * 45.0 ** 2 * 10
results.append(check("composite", math.pi * 62.5 ** 2 * 10, bp6.part, rm,
                     expect_radii=(3.0, 45.0)))

# ----------------------------------------------------------- ⑦ revolve 回转体（锥台）
# 挖出的惯用法：Polyline 画剖面 + revolve(axis=Z) → 锥台
# 剖面 (0,-5)→(30,-5)→(10,5)→(0,5)，绕 Z 回转 → r 由 30 收到 10
from build123d import (BuildSketch, BuildLine, Polyline, make_face, revolve,
                       Plane, Axis)
with BuildPart() as bp7:
    with BuildSketch(Plane.XZ):
        with BuildLine():
            Polyline((0, -5), (30, -5), (10, 5), (0, 5), (0, -5))
        make_face()
    revolve(axis=Axis.Z)
rm = math.pi * 10 / 3 * (30 ** 2 + 30 * 10 + 10 ** 2)   # 锥台体积公式
vol_ok = abs(bp7.part.volume - rm) < 0.5
print("%-12s 锥台体积: 实测=%.3f 期望=%.3f Δ=%.3f | %s"
      % ("revolve", bp7.part.volume, rm, abs(bp7.part.volume - rm),
         "PASS ✅" if vol_ok else "FAIL ❌"))
results.append(vol_ok)

print("\n总体:", "全部 PASS ✅" if all(results) else "有 FAIL ❌",
      "(%d/%d)" % (sum(results), len(results)))

# ----------------------------------------------------------- ⑧ shell 抽壳
# 块 40×40×10，壁厚 2，顶面敞开 → V = 外包 − 内腔
#   内腔 = (40−2t)×(40−2t)×(10−t) = 36×36×8
with BuildPart() as bp8:
    Box(40, 40, 10)
    apply_ops(bp8, [{"op": "shell", "thickness": 2.0, "open": "+Z"}])
V_shell = 40 * 40 * 10 - (40 - 4) * (40 - 4) * (10 - 2)
ok8 = abs(bp8.part.volume - V_shell) < 0.5
print("%-12s 体积: 实测=%.3f 期望=%.3f Δ=%.3f | %s"
      % ("shell", bp8.part.volume, V_shell, abs(bp8.part.volume - V_shell),
         "PASS ✅" if ok8 else "FAIL ❌"))
results.append(ok8)

# ----------------------------------------------------------- ⑨ cut_blind 盲切
# 块 60×40×10，顶面(z=5)向下切 矩形 20×30 深 4 → 去 20*30*4
with BuildPart() as bp9:
    Box(60, 40, 10)
    apply_ops(bp9, [{"op": "cut_blind", "z": 5.0, "depth": 4.0, "at": [0.0, 0.0],
                     "profile": {"kind": "rect", "w": 20.0, "l": 30.0}}])
results.append(check("cut_blind[rect]", 60 * 40 * 10, bp9.part, 20.0 * 30.0 * 4.0))

# 圆轮廓：块 40×40×10，顶面切 φ10 深 3 → 去 π*25*3
with BuildPart() as bp10:
    Box(40, 40, 10)
    apply_ops(bp10, [{"op": "cut_blind", "z": 5.0, "depth": 3.0, "at": [0.0, 0.0],
                      "profile": {"kind": "circle", "r": 5.0}}])
results.append(check("cut_blind[circle]", 40 * 40 * 10, bp10.part,
                     math.pi * 25.0 * 3.0, expect_radii=(5.0,)))

# ============ ⑩⑪⑫⑬ 同族批量：hole / cutThruAll / cskHole / makeCone ============

# ⑩ hole 标准孔：板 40×40×10，2×Ø8 通孔
with BuildPart() as bp11:
    Box(40, 40, 10)
    apply_ops(bp11, [{"op": "hole", "d": 8.0, "z": 5.0,
                      "at": [[-10.0, 0.0], [10.0, 0.0]]}])
results.append(check("hole", 40 * 40 * 10, bp11.part,
                     2 * math.pi * 16.0 * 10, expect_radii=(4.0,)))

# ⑪ cutThruAll 通切：板 40×40×10，10×10 方孔打通
with BuildPart() as bp12:
    Box(40, 40, 10)
    apply_ops(bp12, [{"op": "cut_thru", "z": 5.0, "at": [0.0, 0.0],
                      "profile": {"kind": "rect", "w": 10.0, "l": 10.0}}])
results.append(check("cut_thru", 40 * 40 * 10, bp12.part, 10.0 * 10.0 * 10.0))

# ⑫ cskHole 沉头孔：板 40×40×10，Ø6 通孔 + Ø12 锥沉
#   注：build123d/OCCT 的 `CounterSinkHole` 沉孔形状是**圆锥**（底半径 cs_r、
#   高 cs_r − r），不是圆锥台 —— 实测坐实（用台体公式会差 π·(cs_r−r)·r²）。
with BuildPart() as bp13:
    Box(40, 40, 10)
    apply_ops(bp13, [{"op": "csk_hole", "d": 6.0, "cs_d": 12.0, "angle": 90.0,
                      "z": 5.0, "at": [[0.0, 0.0]]}])
_through = math.pi * 3.0 ** 2 * 10
_sink = math.pi * 6.0 ** 2 * (6.0 - 3.0) / 3.0
rm_csk = _through + _sink
_res = check("csk_hole", 40 * 40 * 10, bp13.part, rm_csk, expect_radii=(3.0,))
_geom = sorted({str(f.geom_type).split(".")[-1] for f in bp13.part.faces()})
_has_cone = "CONE" in _geom
print("            面类型: %s | 有锥面: %s" % (_geom, _has_cone))
results[-1] = _res and _has_cone

# ⑬ makeCone 圆锥（作减法）：板 40×40×10，底 R5 顶 0 高 6
with BuildPart() as bp14:
    Box(40, 40, 10)
    apply_ops(bp14, [{"op": "cone", "r1": 5.0, "r2": 0.0, "h": 6.0,
                      "at": [0.0, 0.0, 2.0]}])
results.append(check("cone", 40 * 40 * 10, bp14.part, math.pi * 25.0 * 6.0 / 3))

# ============ ⑭⑮⑯⑰⑱⑲ 异族批次：loft / sweep / mirror / face_plane / arc / spline ====

def check_vol(name, got, expect, tol=0.5):
    """加法型算子：直接比总体积。"""
    d = abs(got - expect)
    ok = d < tol
    print("%-12s 体积: 实测=%.3f 期望=%.3f Δ=%.3f | %s"
          % (name, got, expect, d, "PASS ✅" if ok else "FAIL ❌"))
    results.append(ok)
    return ok


# ⑭ loft 放样：20×20(z=0) → 10×10(z=10)；棱柱体公式 V=h/6(A1+4Am+A2)
with BuildPart() as bp15:
    apply_ops(bp15, [{"op": "loft", "sections": [
        {"plane": {"plane": "XY", "offset": 0.0}, "profile": {"kind": "rect", "w": 20, "l": 20}},
        {"plane": {"plane": "XY", "offset": 10.0}, "profile": {"kind": "rect", "w": 10, "l": 10}}]}])
check_vol("loft", bp15.part.volume, 10 / 6.0 * (400 + 4 * 225 + 100))

# ⑮ sweep 扫掠：φ4 圆沿 20 长直线 → π·4·20
with BuildPart() as bp16:
    apply_ops(bp16, [{"op": "sweep", "profile": {"kind": "circle", "r": 2.0},
                      "path": [[0.0, 0.0, 0.0], [0.0, 0.0, 20.0]]}])
check_vol("sweep", bp16.part.volume, math.pi * 4.0 * 20, tol=1.0)

# ⑯ mirror 镜像：20×20×10（x∈[0,20]）关于 YZ 镜像 → 体积翻倍
with BuildPart() as bp17:
    Box(20, 20, 10, align=(Align.MIN, Align.CENTER, Align.CENTER))
    apply_ops(bp17, [{"op": "mirror", "plane": "YZ"}])
check_vol("mirror", bp17.part.volume, 2 * 20 * 20 * 10)

# ⑰ face_plane 面上生长（workplaneFromTagged 惯用法）：40×40×10 + 顶面 10×10×5 凸台
with BuildPart() as bp18:
    Box(40, 40, 10)
    apply_ops(bp18, [{"op": "face_plane", "sel": "+Z",
                      "profile": {"kind": "rect", "w": 10.0, "l": 10.0},
                      "height": 5.0}])
check_vol("face_plane", bp18.part.volume, 40 * 40 * 10 + 10 * 10 * 5)

# ⑱ threePointArc 三点弧（草图算子，须词法内联）：半圆盘 r=10 拉伸 5
with BuildPart() as bp19:
    with BuildSketch(Plane.XY):
        with BuildLine():
            Line((10.0, 0.0), (-10.0, 0.0))
            ThreePointArc((10.0, 0.0), (0.0, 10.0), (-10.0, 0.0))
        make_face()
    extrude(amount=5.0)
check_vol("three_pt_arc", bp19.part.volume, math.pi * 100.0 / 2 * 5.0)

# ⑲ spline 样条（草图算子）：过 8 个圆上点闭合，面积≈πr²（近似，放宽容差）
_pts = [(10 * math.cos(2 * math.pi * i / 8), 10 * math.sin(2 * math.pi * i / 8))
        for i in range(8)]
with BuildPart() as bp20:
    with BuildSketch(Plane.XY):
        with BuildLine():
            Spline(*_pts, periodic=True)
        make_face()
    extrude(amount=5.0)
check_vol("spline", bp20.part.volume, math.pi * 100.0 * 5.0,
          tol=math.pi * 100 * 5 * 0.03)

print("\n总体:", "全部 PASS ✅" if all(results) else "有 FAIL ❌",
      "(%d/%d)" % (sum(results), len(results)))
