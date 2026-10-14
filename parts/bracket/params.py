# -*- coding: utf-8 -*-
r"""
铰链支座 —— 唯一数据源 (single source of truth)
================================================

底板 + 两平行斜臂 + 圆头铰接端。

读图所得（三个投影 + 轴测）：
    底板 62 × 24 × 8
    两个平行臂：各厚 6，内距 16（外宽 28），X 方向居中 → 占 x ∈ ±[8, 14]
    臂是斜板：侧面(YZ)轮廓 = 圆头 R10(圆心 Y=-12, Z=27) + 斜边
              右端(Y=24)总高 14（底板 8 + 臂 6）；臂水平总长 = 12 + 24 = 36
    孔：底板 2×φ9（孔心距 45）；臂圆头处 2×φ8（横向销孔，贯穿两臂）
        臂上 2×φ6 / 2×φ3（台阶孔，方向见下）

【绘图技巧记录】
  1. 先"分块"再"定位"：底板和臂分开做，最后用布尔并起来 —— 比一次画复杂草图好改
  2. **斜面最难画的位置，把它放到"侧视面"去画**
     臂的斜轮廓在 YZ 平面是平面图形（圆+直线），在 XY 或 XZ 里就变成斜拉伸了
     → 用 `Plane.YZ` 做草图，拉伸方向自动沿 X，正好是臂的厚度方向
  3. 圆头和斜边的**相切**不要目测：用切线公式算出切点再连线（见 tangent_point）
  4. 对称件只做一半，另一个用 `mirror(about=Plane.YZ)`
  5. 同规格的孔用 `Locations([...])` 一次打完，不要重复写 4 遍
  6. 台阶孔 = 两次拉伸（大径浅 + 小径深），用 `Mode.SUBTRACT`
"""
# 底板尺寸
BASE_L_X = 62.0          # 底板 X 方向长
BASE_W_Y = 24.0          # 底板 Y 方向宽
BASE_T_Z = 8.0           # 底板厚

# 臂尺寸
ARM_T_X = 6.0       # 臂厚（X 方向）
ARM_GAP_X = 16.0    # 两臂内侧间距 → 臂内侧 x = 8
ARM_IN_C_X = ARM_GAP_X / 2          # 8
ARM_OUT_C_X = ARM_IN_C_X + ARM_T_X       # 14

# 圆头铰接端（在 YZ 平面里是平面图形：圆 + 切线）
HEAD_R = 10.0
HEAD_C_Y = -12.0    # 圆头圆心 Y（左端外侧）
HEAD_C_Z = 27.0     # 圆头圆心高（自底面算）

# 臂右端
ARM_END_C_Y = BASE_W_Y         # 24（与底板 +Y 端齐平）
ARM_END_C_Z = 14.0      # 右端总高 = 底板厚 + 臂厚

# 孔
PIN_HOLE_D = 8.0       # 2-φ8 横向销孔（贯穿两臂，轴沿 X）
ARM_CBORE_D = 6.0        # 2-φ6 沉孔
ARM_THRU_D = 3.0        # 2-φ3 通孔
ARM_CBORE_T_Y = 3.0    # 沉孔深
BASE_HOLE_P = 45.0     # 底板 2-φ9 孔心距
BASE_HOLE_D = 9.0

# 输出
TAG = "bracket"
TITLE = "铰链支座"     # 尺寸对照表标题里的中文名（s4_table 用；零件无关步骤靠它区分）

# ---------------- 派生 ----------------
def tangent_point(P, C, R, upper=True):
    """从外点 P 向圆(C,R)作切线，返回切点坐标"""
    import math
    dx, dy = P[0] - C[0], P[1] - C[1]
    d = math.hypot(dx, dy)
    th = math.atan2(dy, dx) + (math.acos(R / d) if upper else -math.acos(R / d))
    return (C[0] + R * math.cos(th), C[1] + R * math.sin(th))