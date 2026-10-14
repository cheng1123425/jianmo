# 建模方案源 —— 双耳直角支座（ybracket）

人工维护。**s0_plan 每轮循环前读这个文件**，把它和 ref_spec、dims_spec、
notes/errors.md 拼成一份本轮方案 notes/plan.md。

## 读图
- 三视图 + 剖视端视图 + 轴测（主视 X×Z、剖视端视图 Y×Z、俯视 X×Y、轴测）
- 总宽 200、总深 144、总高 120（C 形夹持支架）
- 背板厚 20，顶部背面斜切 30（高）；开口 96
- 顶臂厚 32（Z∈[88,120]），伸出 Y 到 116
- 底座高 48（Z∈[0,48]），前部斜削（半宽 58→33，前端宽 66）
- 双耳 R42 圆头（圆心 ±58,72），耳厚 32；耳孔 2-Ø42（心距 116）
- 顶臂中央台阶孔：Ø54 沉孔深 22 + Ø32 通孔贯穿

## 构造
1. 背板 | cat=背板 | params=WALL_T,WALL_CHAMF_Z,WALL_W,HEIGHT_Z | how=Plane.YZ 画梯形（底 20、顶斜切 30）→ extrude(±58)
2. 顶臂 | cat=顶臂 | params=ARM_LEN,ARM_T,HEIGHT_Z,WALL_W | how=Plane.YZ.offset(-58) 画矩形(116×32) → extrude(116)
3. 底座 | cat=底座 | params=DEPTH_Y,BASE_H,BASE_TAPER_Y0,BASE_FRONT_W,WALL_W | how=Plane.YZ.offset(-58) 画带斜削轮廓 → extrude(116)
4. 双耳 | cat=双耳 | params=EAR_R,EAR_T,EAR_PITCH,EAR_CY | how=Plane.XY 两个 R42 圆（心 ±58,72）→ extrude(32)
5. 中心台阶孔 | cat=中央孔 | params=D_CBORE,D_THRU,CBORE_DEPTH | how=part − Cylinder(Ø54,深22) − Cylinder(Ø32,贯穿)
6. 双耳孔 | cat=双耳 | params=EAR_PITCH,EAR_CY,EAR_T | how=part − 2×Cylinder(Ø42,贯穿耳厚)

## 易错
- **双耳圆头圆心在 ±58 而非 ±100**：总宽 200 = 耳孔心距 116 + 2×R42，圆心在 X=±58（中央块边缘），圆头向外凸到 ±100
- **耳心 Y=72**：总深 144 的一半，双耳落在底座前部中深位置
- **双耳厚 32（Z∈[0,32]）**：与底座高 48 不同，耳是独立薄片贴在底座两侧
- **中心台阶孔在 (0,72)**：Ø54 沉孔自顶面 Z=120 向下 22，Ø32 通孔贯穿顶臂 32
- **坐标系原点**：背面·底面·对称中心（X=0 对称面、Y=0 背面、Z=0 底面）
- **底座斜削**：Y∈[102,144] 半宽从 58 斜削到 33（前端宽 66）
