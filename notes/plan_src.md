# 建模方案源 —— 垫片（gasket_fixture）

人工维护。**s0_plan 每轮循环前读这个文件**，把它和 ref_spec（图上标的数）、
dims_spec（关系表）、notes/errors.md（历史错误）拼成一份本轮方案 notes/plan.md。

格式约定：
- `## 读图` 自由文本
- `## 构造` 每行一条 `序号. 标题 | cat=分类 | params=参数名 | how=做法`
  - `cat` 要和 dims_spec.py 里的 `cat` 对得上，s0 才能把差异定位到阶段
- `## 易错` 列表

## 读图
- 来源：教材图 1-19「加工垫片」，低分辨率截图；标定 3.3333 mm/px（侧孔心距 400 ↔ 120 px），容差 3 mm ≈ 1 px
- 俯视：中心 φ300 圆弧，两侧 φ150 凸台（中心距 ±200），中间用 **R400 凹颈**过渡（向内凹，不是外凸腰形）
- 俯视同心圆：φ300 外弧 / φ200 中心凸台 / φ150 中心孔；侧台另有 φ75 孔
- 前视：底板 50 厚；中心凸台再高 50（总 100，实测宽 ±100 → φ200）；侧凸台再高 20（总 70）
- 共识：**同心圆一律按通孔处理**，中心 φ150 是贯通孔，不做沉孔

## 构造
1. 底板（凹颈腰形轮廓） | cat=俯视轮廓,高度 | params=R_OUT_CEN,R_SIDE,D_SIDE,R_NECK,BASE_T | how=8 段弧首尾相接成闭合轮廓（2×中心外弧 + 4×R400 凹颈 + 2×侧弧）→ extrude(BASE_T)
2. 中心凸台 | cat=凸台,高度 | params=R_BOSS,H_CEN | how=Plane.XY 抬到 z=BASE_T，Circle(R_BOSS) → extrude(H_CEN)
3. 两侧凸台 | cat=俯视轮廓,高度 | params=R_SIDE,D_SIDE,H_WING | how=Locations((+D_SIDE,0),(-D_SIDE,0)) 两个 Circle(R_SIDE) → extrude(H_WING)
4. 中心通孔 | cat=孔 | params=D_HOLE_CEN | how=Circle(D_HOLE_CEN/2) → extrude(BASE_T+H_CEN, Mode.SUBTRACT)
5. 两侧通孔 | cat=孔 | params=D_HOLE_SIDE,D_SIDE | how=Locations(±D_SIDE) Circle(D_HOLE_SIDE/2) → extrude(BASE_T+H_WING, Mode.SUBTRACT)

## 易错
- **R400 是凹颈，圆心在零件体外**：弧的方向取反就成了外凸腰形，外接尺寸立刻从 550 变成别的值
- 中心凸台是 **φ200 不是 φ300**：前视图中心凸起实测只有 ±100 宽，被误读成 φ300 过
- 侧孔心距是 200（不是 75）：图上的 ±75 是孔的半径位置，不是孔心距
- 凹颈弧的切点必须**算**出来（外切圆公式），不能目测：目测会让轮廓出现尖角或自交
- 每建一步打印体积：体积没变说明这一步根本没切动/没长出来
