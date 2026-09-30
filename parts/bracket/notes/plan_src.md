# 建模方案源 —— 铰链支座（bracket）

人工维护。**s0_plan 每轮循环前读这个文件**，把它和 ref_spec、dims_spec、
notes/errors.md 拼成一份本轮方案 notes/plan.md。

## 读图
- 三个投影 + 轴测；标定：底板长 62 mm ≈ 423 px
- 俯视：底板 62 × 24；两平行臂各厚 6，内距 16（外宽 28），X 居中 → 占 x ∈ ±[8, 14]
- 主视：总高 37（= 圆头圆心高 27 + R10）；底板厚 8；臂厚 6；底板长 62
- 侧视：圆头 R10 圆心 (y=-12, z=27)；右端 (y=24, z=14)；臂水平总长 36
- 孔：底板 2×φ9（孔心距 45）；圆头处 2×φ8 横向销孔贯穿两臂；臂上 2×φ6 沉 + 2×φ3 通
- 存疑：φ6 / φ3 台阶孔所在端面原图未明确（已在 s1_build 注释中标出）

## 构造
1. 底板 | cat=底板 | params=L,W,T | how=Rectangle(L, W, align=(CENTER, MIN)) → extrude(T)
2. 两平行臂 | cat=臂 | params=ARM_T,ARM_GAP,END_Y,END_Z | how=Plane.YZ.offset(±x0) 画侧轮廓（圆 + 切线 + 3 段直线）→ extrude(ARM_T)
3. 圆头铰接端 | cat=圆头 | params=R_HEAD,HEAD_Y,HEAD_Z | how=CenterArc((HEAD_Y,HEAD_Z), R_HEAD, A_DN, (A_UP-A_DN)-360) —— arc_size 必须是负的（顺时针）
4. 底板孔 | cat=底板孔 | params=D_9,PITCH9 | how=Locations((±PITCH9/2, W/2)) Circle(D_9/2) → extrude(T, SUBTRACT)
5. 销孔 | cat=销孔 | params=D_PIN | how=part - Cylinder(D_PIN/2, ARM_T+12, rotation=(0,90,0))（轴沿 X，贯穿两臂）
6. 台阶孔 | cat=台阶孔 | params=D_CB,D_CS,CS_DEPTH | how=part - Cylinder(...) ×2（φ6 浅沉 + φ3 深通，轴沿 Y）

## 易错
- **CenterArc 的 arc_size 符号**：走 (A_UP - A_DN) 是 +176.3°，会绕到反向弧 → 轮廓凸向反侧、圆心落到体外，所有按圆心定位的孔切除量变 0。必须写 (A_UP - A_DN) - 360 = -183.7°（顺时针走大弧）
- **Rectangle 默认不是居中**：align=(CENTER, MIN) 让底板 Y ∈ [0, 24]，与臂的 END_Y 端齐平；当成居中会让孔位和臂错位 12
- 相切点用 tangent_point() 算，不要目测：目测的切线会在投影里出现折角
- 打孔一律用 `part - Cylinder(...)`：BuildSketch + SUBTRACT 在有斜臂时经常切不穿
- 台阶孔的端面归属原图未标注，改这一段前先看 notes/errors.md 里有没有踩过
