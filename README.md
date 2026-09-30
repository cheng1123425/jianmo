# 加工垫片（图 1-19）—— 参数化建模与工程图流水线

> 相关文档
> - **`MSG.md`** —— 消息协议：整条链与闭环都是**互相隔离的独立进程**，只通过消息文件通信
> - **`lessons.md`** —— 三次建模（垫片 / 球铰盖 / 铰链支座）的复盘与学习记录
> - **`drawing_techniques.md`** —— build123d 绘图技巧与踩坑
> - **`PUSH.md`** —— 上传 GitHub 的规矩（不自动推送，等你提醒）
> - `socket_log.md` —— 多耳球铰盖的迭代日志（铰链支座的已并入 `parts/bracket/notes/`）

## 快速使用

```bash
# 1) 改参数（唯一数据源）
notepad params.py                       # 垫片
notepad parts\bracket\params.py         # 铰链支座

# 2) 全链：三维 → STEP → 工程图 → PDF → 尺寸表
D:\3d\build123d\.venv\Scripts\python.exe pipe.py
D:\3d\build123d\.venv\Scripts\python.exe pipe.py --part parts/bracket

# 3) 全链 + 闭环校核（对照原图自动检出差异，只报不改）
D:\3d\build123d\.venv\Scripts\python.exe pipe.py --loop

# 4) 全链 + 闭环自动修正（改错参数也能自动改回，最多 6 轮）
D:\3d\build123d\.venv\Scripts\python.exe pipe.py --part parts/bracket --loop --auto

# 5) 想看瓶颈 / 想强制重跑
... pipe.py --part parts/bracket            # 跑完打印耗时排行
... pipe.py --no-cache                      # 忽略指纹缓存
```

**架构**：不再是 `make_all.py` 那种一个大脚本串子进程，而是**消息驱动的隔离流水线**——
每个步骤是独立进程，只读自己的 `_msg/<stage>.in.json`、只写 `_msg/<stage>.out.json`，
步骤之间**只允许通过消息文件传输**（`guard.py` 静态扫描强制，`pipe.py` 运行时校验）。
详见 **`MSG.md`**。

**一个驱动器跑所有零件**：`pipe.py --part parts/bracket`。零件目录里放
`params.py` / `dims_spec.py` / `ref_spec.py` / `steps/` / `notes/`；
`steps/` 里没有的步骤（如 `s0_plan`、`s9_record`）会自动回落到根目录的通用实现。

---

## 上传 GitHub（`jianmo`）

**不会自动推送。** 模型更新后先在本地跑通、提交，等你说「上传」我再 push。
流程与检查清单见 **`PUSH.md`**。

---

## 环境准备（clone 之后要做的三件事）

### 1. 装 Python 依赖

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

本项目在 **Python 3.13.12** 上验证；核心依赖只有 `build123d` 和 `matplotlib`。

### 2. 装 FreeCAD（**不是 pip 包**）

从 [freecad.org](https://www.freecad.org/downloads.php) 下载 **FreeCAD 1.1.0** 安装即可。
本项目只用它的**命令行版** `freecadcmd.exe`（无界面 TechDraw 出图）。

### 3. 用环境变量指路径（不用改脚本）

`pipe.py` 通过环境变量读取工具路径，clone 后设一次即可：

| 环境变量 | 应指向 |
|---|---|
| `MPIPE_PY` | 你的 venv `python.exe` |
| `MPIPE_FC` | FreeCAD 的 `freecadcmd.exe` |
| `MPIPE_TD` | FreeCAD 的 A3 图框模板 `A3_Landscape_TD.svg` |

> 模板位置：`<FreeCAD 安装目录>/data/Mod/TechDraw/Templates/ISO/A3_Landscape_TD.svg`
> —— 注意它比 `App.getResourceDir()` 多一层 `data/`，拼不出这个路径。
> （不设环境变量时，脚本会用下面的原开发机默认值。）

### 原开发机的环境（供对照 / 默认值）

| 用途 | 路径 |
|---|---|
| Python 3.13 + build123d 0.13.0 | `D:\3d\build123d\.venv\Scripts\python.exe` |
| FreeCAD 1.1.0 | `D:\3d\新建文件夹\FreeCAD 1.1\bin\freecadcmd.exe` |

---

## 文件与职责

### 数据源（人的接口）

| 文件 | 职责 |
|---|---|
| `params.py` | **唯一数据源**。所有几何尺寸参数。改尺寸只改这里 |
| `dims_spec.py` | 尺寸命名规范 + 三维↔二维推导关系清单 + 推导说明 |
| `ref_spec.py` | **原图基准** —— 从用户二维图量出的参照真值（像素标定 3.3333 mm/px）。校核的"真值" |

### 消息流水线（隔离的独立进程）

| 文件 | 职责 |
|---|---|
| `MSG.md` | 消息协议 `mpipe/1` 说明（格式 / 规则 / 拓扑 / 怎么加步骤）|
| `msgio.py` | 协议实现：`boot`/`finish`/`run_stage`、`ref_path`（按消息声明读入参 + 校验 sha256）|
| `pipe.py` | **驱动器**：只做调度与投递，不做业务计算；读每步消息决定继续/停止/回环 |
| `guard.py` | **隔离校验器**：静态扫描 steps/，违例（跨步骤 import / 硬编码路径）即拒绝运行 |
| `steps/s0_plan.py` | **每轮循环前读图**：图纸基准 + 关系表 + 方案源 + 历史错误 → 本轮建模方案与失误定位（所有零件共用）|
| `steps/s1_build.py` | 三维建模 → STEP / STL |
| `steps/s2_drawing.py` | STEP → 工程图 FCStd + 投影特征（FreeCAD 无界面）|
| `steps/s3_render.py` | 投影特征 → A3 矢量图纸 PDF / PNG |
| `steps/s4_table.py` | 参数 + 投影 → 尺寸对照表 |
| `steps/s5_collect.py` | 投影 → 几何摘要（只提取，不判断）|
| `steps/s6_compare.py` | 几何摘要 vs 原图基准 → 差异清单 |
| `steps/s7_decide.py` | 差异清单 → 判定 + 修正建议 |
| `steps/s8_apply.py` | 修正建议 → 写回 params.py（**唯一**被允许改参数的步骤）|
| `steps/s9_record.py` | **每轮结束记录**：本轮思路、差异、修正、错误条目 → `notes/`（所有零件共用）|

### 建模思路与错误库（`notes/`，人写 + 机器累积）

| 文件 | 谁写 | 说明 |
|---|---|---|
| `notes/plan_src.md` | **人** | 建模方案源：读图结论 + 构造阶段（`cat=` 要跟 `dims_spec.py` 对得上）+ 易错点 |
| `notes/plan.md` | `s0_plan` | 每轮生成的本轮方案：读图 / 构造顺序 / 参数预检 / 疑似失误阶段 / 历史错误提示 |
| `notes/model_notes.md` | `s9_record` | 建模思路时间线：每轮判定、差异、改了什么 |
| `notes/errors.md` | 人 + `s9_record` | 错误库，按分类去重累积并记次数；下轮 `s0_plan` 会读它做风险提示 |

### 产物

| 文件 | 说明 |
|---|---|
| `drawing.pdf` / `.png` | A3 横向矢量图纸（三视图 + 完整标注） |
| `dims_table.pdf` / `.md` | 尺寸命名与推导对照表 |
| `gasket_fixture.FCStd` | FreeCAD 工程图文档（尺寸是真实关联对象，可在 GUI 里编辑） |
| `models/*.step` / `.stl` | 各零件的三维实体导出（`gasket_fixture` / `bracket` / `lbracket` / `socket_cover`）。STEP 为 **AP214 纯几何**，无参数与特征树 |

### 零件目录 `parts/`

| 目录 | 零件 | 状态 |
|---|---|---|
| （根目录） | 加工垫片 | ✅ 主流水线（`pipe.py`，闭环 pass） |
| `parts/bracket/` | 铰链支座（双耳） | ✅ 已迁入消息流水线（`pipe.py --part parts/bracket`，闭环 pass） |
| `parts/lbracket/` | L 形支座（单立板双耳） | ✅ 已建完整流水线（`pipe.py --part parts/lbracket`，闭环 pass；按原图重修：叶形底板 56×40 + 顶双耳 R7/R6,5 + 中央窗口 8×14 + 3×φ8） |
| `parts/socket/` | 多耳球铰盖 | ⏳ **未迁入**（`parts/socket/steps/` 为空；旧脚本 `socket_*.py` 在根目录）。且图纸信息缺 4 项（4×45° 斜面位置、R3.6/R0.6 作用位置、中心凸台外径、13.8 与 2.5 的关系） |

每个零件目录结构相同：

```
parts/<零件>/
  params.py        唯一数据源
  dims_spec.py     标注 ↔ 实体关系（cat 字段要和 notes/plan_src.md 对上）
  ref_spec.py      原图基准（闭环的真值）
  steps/           零件专属步骤（s1_build … s8_apply；s0_plan/s9_record 共用 root/steps/）
  notes/           方案源 + 方案 + 思路记录 + 错误库 + 技能回路
  _msg/            消息（不入库）
  models/          STEP / STL
```

> ⚠️ **每个零件必须有完整的 `steps/` 副本**（s1~s8）。缺步骤时驱动器会**静默回退**到根目录的
> 通用步骤——而根目录的 s6_compare 是垫片专属，schema 对不上会炸在该步，很难第一时间定位
> （lbracket 就因此卡了很久）。

---

## 闭环校核（二维 ↔ 三维 迭代）

这是本工程**核心的工作方式** —— 不是单向出图，而是带反馈的循环：

```
        用户二维图
             │  量测标定（ref_spec.py，3.3333 mm/px）
             ▼
        原图基准 ─────────────┐
                             ├─→ 比对 ─→ 判定 ─→ 相符？─是─→ 结束
        三维 → 投影(JSON) ───┘                    │
                                                 否
                                                  ↓
                          定位：是「三维画错」还是「二维标错」
                                                  ↓
                                    改 params.py（--auto 可自动）
                                                  ↓
                                        重新生成 → 回到比对
```

**判定规则**

| 投影几何 | 标注 | 判定 | 处置 |
|---|---|---|---|
| ✗ | — | **三维画错** | 形状就不对，改 `params.py` 后重出（标注偏差会跟着消失） |
| ✓ | ✗ | **二维标注错** | 形状对、标注没跟上 → 查标注层（`steps/s2_drawing.py` 的边引用） |
| ✓ | ✓ | 通过 | — |

**用法**

```bash
python pipe.py --loop            # 检查一轮，打印差异与建议
python pipe.py --loop --auto     # 自动迭代到通过（改参数由 s8_apply 负责）
python pipe.py --only s6_compare # 只跑某一步（调试）
```

**校核内容**

- 俯视：外接总长/总宽、中心组（外弧/凸台/中心孔）与侧组（侧凸台/侧孔）的半径与圆心、凹颈 R
- 前视：总高、各相邻高度层之差（底板厚 / 侧凸台抬高 / 中心凸台抬高）、中心凸起宽度
- 标注：12 项标注值逐项对照原图
- 圆的配对用**组内一对一最优匹配**（暴力枚举，避免中心孔与凸台半径接近时误配）

**实测效果**：故意把中心凸台改成 φ300、台阶改成 35 → 第 1 轮检出 4 处不符并给出
`R_BOSS=100 / H_WING=20` → 应用 → 第 2 轮通过。

**已知局限**：若两个特征尺寸刚好相等（如凸台半径 = 外轮廓半径），俯视图上两者重合，
该组会被判为「圆数量不符」并**跳过半径比对**（此时靠主视图的宽度/高度仍能抓到错误，
不会漏判，只是定位精度下降）。

---

## 关键设计决策（为什么这么做）

### 1. 单一数据源

所有尺寸只在 `params.py` 出现一次。三维模型、工程图、PDF、表格都是**它的投影**。
不存在"改了模型忘了改图纸"的可能——因为图纸每次都从模型重新算。

### 2. STEP 每次重新生成，不复用

STEP 是 **AP214 纯几何**（`FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 ...'))`），
里面**没有参数、没有尺寸、没有特征树/建模历史**。它是"照片"不是"活体"，
所以只能重新生成，不能改。这也决定了流水线必须是「重跑」模式。

### 3. 尺寸全部关联到视图边

图纸上的每个尺寸都是 FreeCAD 的 `DrawViewDimension`，用 `References2D` 引用投影边。

> **关键点**：`References2D` 里的 `"EdgeN"` 用的是 `getVisibleEdges()` 的 **0-based 下标**，
> **不是** `getEdgeByIndex()` 的 1-based 序号。两者顺序不同（后者会跳过某些边）。

改三维 → `recompute` → 尺寸值自动跟随。唯一的例外是「孔心距 200」：
两条**圆边**做 `DistanceX` 得到的是**最近距离**（两 φ75 孔得 325，不是 400），
所以圆心距无法用边表达，改用**从实体读圆柱面轴线位置**——同样是每次重算。

### 4. 参数值 vs 实测值并置校验

尺寸表同时列出：
- **参数值**：`params.py` 的输入
- **图纸实测**：FreeCAD 从当前实体读出的 `getRawValue()`

两列一致（打 OK）说明建模与图纸没跑偏；不一致会亮红底 `!!`。

**这是整套流程最值钱的部分** —— 它把"图纸对不对"从人工核对变成了自动断言。
已验证：改 `D_SIDE` 200→220，表格自动显示 220/220，且派生总长 550→590。

---

## 三维 ↔ 二维 尺寸关系（摘要，完整见 `dims_spec.py`）

| 类型 | 含义 | 例子 |
|---|---|---|
| **直读型** | 标注 = 参数 或 2×参数 | φ300 = 2·`R_OUT_CEN`；R400 = `R_NECK`；50 = `BASE_T` |
| **派生型** | 多参数算出 | 总长 = **2 ×(D_SIDE + R_SIDE)**；总宽 = **2 × R_OUT_CEN** |
| **构造型** | 只决定图形，不成标注 | 凹颈圆心由「与中心弧、侧弧同时外切」定出 |

**高度链**：`0 → BASE_T（底板顶）→ BASE_T+H_WING（侧凸台顶）/ BASE_T+H_CEN（中心凸台顶）`。
图上 50/50/20 都是**相邻两级之差**，不是绝对高度。

**命名约定**：`R_*` 半径 / `D_*` 直径·中心距 / `H_*` 高出底板的高度 / `BASE_T` 底板厚。

---

## 踩坑记录（FreeCAD 无界面 TechDraw）

1. **无界面不能出 PDF**：`import TechDrawGui` 在 console 模式失败，没有 `exportPageAsPdf`；
   `writeDXFPage` 输出空文件、`writeDXFView` 直接崩进程。
   → 只能导出数据，PDF 由 matplotlib 落盘。
2. **`References2D` 用 0-based 可见边下标**（见上）。
3. **视图 y 轴方向不保证**：主视图出现过 `y = 50 − z`（朝下）也出现过 `y = z − 50`。
   → 不要假设，用包围盒对齐范围 + 用「中心凸台顶线」判断是否翻转，自动适配。
4. **不要把几何特征的位置写死**：R400 原来写死圆心坐标，一改孔心距就找不到弧。
   → 改成按「半径 + 象限」识别。
5. **取尺寸值用 `d.getRawValue()`**；`TheValue` / `TheoreticalValue` 在 1.1 不存在。
6. **尺寸 label 不要含数值**，否则改参数后 label 也变，无法对比。用固定语义名。
7. `freecadcmd` 默认 GBK 输出 → 脚本里 `sys.stdout.reconfigure(encoding="utf-8")`。

---

## 工序拆分建议（我认为还该拆的）

### 建议拆 —— 第 2 段拆成「建文档」和「导数据」

现在 `freecad_drawing.py` 一口气做三件事：建视图/尺寸 → 存 FCStd → 导 JSON。

建议拆成：

| 新脚本 | 职责 |
|---|---|
| `freecad_build.py` | STEP → `gasket_fixture.FCStd`（建视图 + 尺寸） |
| `freecad_export.py` | FCStd → `_td_data.json`（只读数据） |

**为什么值得**：
- 你可以在 **FreeCAD 界面**里打开 FCStd 手动精修（调视图比例、挪标注、补图框、加中心线），
  存盘后**只跑 export + render**，不必重建整个文档、也不会冲掉你的手工调整。
- 顺带绕开"无界面不能出 PDF"：GUI 里调好后直接在 FreeCAD 里导出 PDF，我这边只负责数据。
- 现在 `render_pdf.py` 的定位也就更清楚了：**只是无界面时的替代渲染器**。

### 建议拆 —— 标注位置独立成 `drawing_cfg.py`

现在 12 个尺寸的**纸面位置坐标**硬编码在 `freecad_drawing.py` 里。

建议抽成配置：

```python
LAYOUT = {"OD_boss": (156.7, 60.8), "hole_pitch": (90, 64), ...}
```

**为什么值得**：调标注位置不必碰逻辑代码；将来换图纸规格（A3→A2/A4）
或改比例，只改一处。更进一步可以改成**相对零件中心的偏移**，换比例自动跟随。

### 建议新增 —— 几何合法性检查 `check_geom.py`

改参数时最容易犯的是「改出一个不成立/不合常理的形状」。建议加断言：

- 孔径 < 对应凸台直径、且不超出外轮廓
- 中心凸台不超出俯视外轮廓
- `R_NECK` 能否与中心弧、侧弧同时外切（两圆有交点）
- 侧孔不跑到中心孔里去（`D_SIDE > (D_HOLE_CEN + D_HOLE_SIDE)/2`）

**为什么值得**：改错了立刻报错，而不是生成一张"看起来正常但几何荒谬"的图。

### 不建议拆

- 第 1 段（建模）已经很纯，没什么可拆的。
- 第 3 段（渲染）和第 4 段（表格）已经是分开的两个文件，合理。

---

## 其他有价值的东西

1. **历史快照**：`make_all.py` 跑之前把上一版 `drawing.pdf` / `gasket_fixture.step`
   复制进 `history/YYYYMMDD-HHMM/`，出问题可回退。现在没有，改错了只能靠重建。
2. **图纸和尺寸表合一份 PDF**：现在 `drawing.pdf` 和 `dims_table.pdf` 是两个文件。
   合成一份（图纸页 + 尺寸表页）交付更完整，打印也方便。
3. **标注位置改成相对坐标**：现在是绝对纸面 mm，换图纸规格会全错位。
4. **公差 / 材料 / 热处理进参数**：这些工艺信息现在只写在标题栏文字里（"未注公差""去毛刺"），
   可以纳入 `params.py`，随尺寸表一起输出。
5. **这套流程可迁移**：`params.py` + 四段脚本的结构**不依赖这个垫片**。
   换零件只需改 `build_part.py` 的建模部分和 `dims_spec.py` 的清单，
   `make_all.py` / `render_pdf.py` / `make_table.py` 基本不用动。
   → 值得沉淀成可复用技能。
6. **`verify_link.py` 应成为习惯**：每次大改参数后跑一次，能一次性暴露所有"没跟上"的尺寸。

---

## 本次修正过的关键错误（留作教训）

| 错误 | 后果 | 修正 |
|---|---|---|
| 中心凸台画成 φ300 | 三维形状错 | 前视图剖面实测中心凸起仅 ±100 → 应为 φ200 |
| φ200 当沉孔（自拟深度 25） | 多了一个不存在的特征 | 同心圆一律按**通孔**处理 |
| 5 个尺寸用硬编码坐标 | 改模型后**显示过期错误值** | 全部改为边关联 / 实体派生 |
| R400 圆心坐标写死 | 改孔心距后直接报错 | 改按「半径 + 象限」识别 |
| 新路线做了却没删旧产物 | 用户打开旧文件以为改动没生效 | 换路线必须删旧产物 |
