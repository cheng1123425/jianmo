# 建模方案源 —— L 形支座（lbracket）

人工维护。**s0_plan 每轮循环前读这个文件**，把它和 ref_spec、dims_spec、
notes/errors.md 拼成一份本轮方案 notes/plan.md。

## 读图
- 三个投影 + 轴测（左上=主视 X×Z、右上=左视 Y×Z、左下=俯视 X×Y、右下=轴测）
- 底板 40×26×8，左端 R9 圆角
- 立板 8(X)×26(Y)×31(Z)，立底板上方右部，X∈[22, 30]
- 立板顶 2 个 φ8 孔心距 26（Y 方向两端），R7 顶角，R6.5 内凹弧
- 立板中央矩形窗口 14×8（贯穿立板厚度方向）
- 3-φ8 孔：底板 1 个 (X=17, Y=0) + 立板顶 2 个 (X=26, Y=0/26)
- 三角筋：立板背面 X=22 与底板顶面 Z=8 之间的三角形支撑

## 构造
1. 底板 | cat=底板 | params=BASE_L,BASE_W,BASE_T,BASE_R_END | how=Plane.XY 画带 R9 圆角轮廓 → extrude(BASE_T)
2. 立板 | cat=立板 | params=WALL_X0,WALL_T,WALL_L,WALL_H | how=Plane.XY * Pos(0,0,BASE_T) 画 Rectangle(WALL_T, WALL_L) → extrude(WALL_H)
3. 三角筋 | cat=三角筋 | params=WALL_X0,WALL_T,BASE_T,WALL_H,WALL_L | how=Plane.XZ.offset(WALL_X0) 画直角三角形 → extrude(WALL_L) 沿 Y
4. 底板孔 | cat=孔 | params=D_HOLE,BASE_HOLE_X,BASE_HOLE_Y | how=part - Cylinder(D_HOLE/2, BASE_T+1) 沿 Z
5. 立板孔 1 | cat=孔 | params=D_HOLE,WALL_HOLE_X,WALL_HOLE_Y1,WALL_HOLE_Z | how=part - Cylinder(D_HOLE/2, WALL_L+8) 沿 Y
6. 立板孔 2 | cat=孔 | params=D_HOLE,WALL_HOLE_X,WALL_HOLE_Y2,WALL_HOLE_Z | how=part - Cylinder(D_HOLE/2, WALL_L+8) 沿 Y

## 易错
- **底板 R9 圆角画法**：不要先 Rectangle 再 fillet，用 `RadiusArc` 在轮廓线里直接画半圆，避免 fillet 把四条边全倒圆
- **立板坐标**：用 `(WALL_X0 + WALL_T/2, 0)` 作为中心对齐到 Y 中线，让两 φ8 孔在 Y=0 和 Y=26 对称
- **三角筋 plane**：在 `Plane.XZ.offset(WALL_X0)`（立板背面）画三角形 → 三角形的"立板背面顶"在 (0, BASE_T+WALL_H)，"底板顶中心"在 (WALL_T, BASE_T)，"立板背面底"在 (0, BASE_T)。extrude 沿 Y（默认方向）
- **三角筋的 Z 坐标**：建在 XZ 平面里时 Z 方向是 view2d 的 Y，所以三角形顶点用 BASE_T 和 BASE_T + WALL_H 而不是 0 和 WALL_H
- **跳过项**：立板顶 R7 圆角、中央矩形窗口、中央 R6.5 内凹 —— 当前 v1 暂未实现，跑通后逐步补