# 挖掘 → 转化 实验（独立于项目主干）

本目录是 **Zero-to-CAD 数据挖掘成果的"转化验证"** 实验区，**不接进 `pipe.py`/`steps`/`lib`**，
自成一体：只读样本 parquet，产出算子 + 验证报告。

## 目录

| 文件 | 作用 |
|---|---|
| `op_lib.py` | **转化后的算子库**（数据化算子 → build123d 实现） |
| `verify_ops.py` | **独立几何验证驱动**（7 项，全 PASS） |
| `convert_test.py` | 最早的单算子（cbore_hole）验证脚本 |
| `repro.py` / `orig.step` | 早期"复现样本"尝试（已弃用，原因见下） |

## 转化流程（已跑通 7 次，可复制）

```
挖出的惯用法（tools/z2c_mine_ops.py 的候选榜）
   ↓ ① 定性：这个惯用法"是什么特征、参数是哪几个"
数据化算子（dict：{op, 具名参数..., 几何谓词}）
   ↓ ② 实现：build123d 里怎么写（查 API、试跑）
build123d 实现（op_lib.py 的函数）
   ↓ ③ 独立验证：建已知基体 + 施算子 + 解析算期望 + 比对
判定 PASS/FAIL（体积差 < 0.5mm³ + 特征半径命中）
```

### ① 定性：惯用法 → 数据

把"怎么做"抽象成"是什么"，参数全部具名、定位用几何谓词：

| 挖到的 CadQuery 惯用法 | 数据化算子 |
|---|---|
| `pushPoints([..]).hole(d)` | `{op:"hole_grid", at:[[x,y]…], d}` |
| `pushPoints(圆周点).hole(d)` | `{op:"bolt_circle", n, d, bcd_r}` |
| `pushPoints([..]).cboreHole(d,cd,dep)` | `{op:"cbore_hole", at, d, cbore_d, cbore_depth}` |
| `edges("|Z").filter(..).fillet(r)` | `{op:"fillet", dir, pos_axis, between, r}` |
| `edges("<<Z").chamfer(d)` | `{op:"chamfer", dir, pos_axis, between, d}` |
| `Polyline(..).close().revolve()` | `{op:"revolve", profile, axis}` |

### ② 实现：build123d API 对应

| CadQuery | build123d | 备注 |
|---|---|---|
| `.hole(d)` | `Hole(radius=d/2)` | 隐式作用于 BuildPart 上下文 |
| `.cboreHole(d,cd,dep)` | `CounterBoreHole(radius, counter_bore_radius, counter_bore_depth)` | |
| `.fillet(r)` | `fillet(edges, radius=r)` | **顶层函数**，非边列表方法 |
| `.chamfer(d)` | `chamfer(edges, length=d)` | 同上 |
| `edges("|Z")` | `edges().filter_by(Axis.Z)` | 边集**不完全等价**，选边要实测 |
| `edges("<<Z")` | 按 center 标高区间筛 | build123d 无等价方向串，用几何谓词 |
| `revolve()` | `revolve(axis=Axis.Z)` | 剖面须在轴一侧 |

### ③ 独立验证（关键纪律）

**不能拿样本的 `step_file` 当基准**——Zero-to-CAD 是「图 → 代码生成」数据集：
`step_file` 是**目标模型**、`cadquery_file` 是 **agent 复现**，两者**不保证匹配**
（实测样本 13d78484：代码算 100 宽，step 是 70 宽）。

故一律**独立验证**：建已知基体 → 施算子 → 用**解析公式**算期望去除量 → 比对
（体积差 < 0.5mm³）；再查圆柱面半径集合是否含预期值。

## 验证结果（7/7 PASS）

| 算子 | 基体 | 实测去除 | 解析期望 | Δ |
|---|---|---|---|---|
| hole_grid (3×2×Ø9) | 80×80×10 板 | 3817.035 | 3817.035 | 0.000 |
| bolt_circle (6×Ø4.5, BCD r20) | Ø60×5 盘 | 477.129 | 477.129 | 0.000 |
| cbore_hole (Ø4/Ø6.5/深3) | 20×20×10 块 | 187.514 | 187.514 | 0.000 |
| fillet (4竖边 R3) | 40×40×10 块 | 77.257 | 77.257 | 0.000 |
| chamfer (2底边 ×1) | 40×40×10 块 | 160.000 | 160.000 | 0.000 |
| composite (法兰+中心孔) | Ø125×10 盘 | 65313.711 | 65313.711 | 0.000 |
| revolve (锥台 R30→R10) | — | 13613.568 | 13613.568 | 0.000 |

## 踩过的坑（转化时必看）

1. **选边谓词别用同一个轴**：`edges().filter_by(Axis.X)` 选出的 X 向边，其 `center().X`
   全都一样（≈0），若 `between` 也按 X 过滤 → 全通过（曾误选 4 条边）。
   必须分 **方向轴 `dir`** 与 **位置轴 `pos_axis`** 两个谓词。
2. **build123d `Box/Cylinder` 默认居中于原点**：`Box(40,40,10)` 的底面在 z=-5 不是 0，
   定位/选边时要算准标高。
3. **`fillet/chamfer` 是顶层函数**（`fillet(edges, radius=)`），不是边列表的方法；
   且选边集与 CadQuery 的方向串**不完全等价**，必须实测。
4. **`Hole`/`fillet` 隐式作用于当前 `BuildPart` 上下文**，无需显式传 part（但选边要
   `bp.edges()`）。

## 下一步

- 转化流程已验证可复制（7 算子走同一套 ①→②→③）。
- 可进 **全量挖掘**（10 万条 `z2c_100k.json`），出完整候选算子榜，按覆盖率排序造算子。
- 或把这批算子（`op_lib.py`）**接进项目 IR 词表**（`lib/ir.py`）+ 生成器（`ir2build.py`），
  让 valve_cover 这类零件能纯数据建模。

---

## 追加批次（2026-10-15 下午）：补 shell / cutBlind 及同族

**新增 4 个算子**（`op_lib.py` 的 `DISPATCH`，全部独立几何验证 PASS）：

| 算子 | 来源惯用法 | 独立验证 | 结果 |
|---|---|---|---|
| `shell` 抽壳 | CadQuery `shell(-t)` | 40×40×10 块、t=2、顶开 → V=外包−内腔(36×36×8) | 5632.000 / 5632.000 ✅ |
| `cut_blind` 盲切 | `cutBlind(-depth)` | 矩形 20×30×4 → 2400；圆 r5×3 → 235.619 | 均 Δ=0.000 ✅ |
| `hole` 标准孔 | `.hole(d)` | 2×Ø8 通孔 → 2π·16·10 | 1005.310 ✅ |
| `cut_thru` 通切 | `cutThruAll()` | 10×10 方孔打通 → 1000 | 1000.000 ✅ |
| `csk_hole` 沉头孔 | `cskHole` | Ø6通+Ø12锥沉 → 通孔 + 锥体 | 395.841 ✅（另有锥面断言） |
| `cone` 圆锥(减料) | `makeCone` | 底R5顶0高6 → π·25·6/3 | 157.080 ✅ |

合计 `verify_ops.py` 现在 **13 条验证全 PASS**（11 个 dispatch 算子 + `revolve` + `composite` 组合演示）。

### 本次新踩的两个坑（都值钱）

**① 辅助函数里不能嵌套 `BuildSketch`**（`cut_blind` 一开始就栽在这）
build123d 靠**调用帧**找父 Builder：`with BuildSketch(...)` 写在**辅助函数里**，
调用栈上是那个函数的帧 → 找不到 `BuildPart` 上下文 → `extrude` 报
`A face or sketch must be provided`（对照：词法上直接写在 `with BuildPart()` 块内则正常）。
**正解**：在自己的 `BuildPart()` 上下文里造**独立 cutter**，再 `add(cutter, mode=Mode.SUBTRACT)`。

**② `CounterSinkHole` 的 `depth` 是【孔深】不是【沉孔深】**
传 `depth=3` 会让孔只钻 3mm（盲孔）。要钻通就别传 `depth`，沉孔形状由
`counter_sink_angle` + `cs_d` 决定。另外它的沉孔形状是**圆锥**（底半径 `cs_r`、
高 `cs_r − r`），不是圆锥台 —— 用台体公式算体积会差 `π·(cs_r−r)·r²`。

### 仍未处理

`threePointArc`(6.6%) / `sweep`(4.8%) / `loft`(2.5%) / `spline`(1.1%) / `mirror`(1.1%)
/ `workplaneFromTagged`(1.2%) —— 属"异族"，待做。

### 第三批（同日）：异族 6 个全数完成

| 算子 | 对应 CadQuery | 独立验证 | 结果 |
|---|---|---|---|
| `loft` 放样 | `loft` | 20×20(z=0)→10×10(z=10)，棱柱体公式 | 2333.333 / 2333.333 ✅ |
| `sweep` 扫掠 | `sweep` | φ4 沿 20 长直线 → π·4·20 | 251.327 ✅ |
| `mirror` 镜像 | `mirror` | 20×20×10 关于 YZ 镜像 → 翻倍 | 8000.000 ✅ |
| `face_plane` 面上生长 | `workplaneFromTagged` / `faces().workplane()` | 板+顶面凸台 | 16500.000 ✅ |
| `three_point_arc` 三点弧 | `threePointArc` | 半圆盘 r10 拉伸 5 | 785.398 ✅ |
| `spline` 样条 | `spline` | 8 点闭合近似圆（3% 容差） | 1569.715（Δ=1.08）✅ |

**`verify_ops.py` 现共 19 条验证，全 PASS。**

### 一条重要经验（决定算子能不能做成"函数"）

**build123d 找父上下文靠【调用帧】，所以只有两种算子能做成辅助函数：**

| 算子形态 | 能否做成函数 | 例子 |
|---|---|---|
| **普通操作**（`Hole`/`fillet`/`offset`/`add`/`loft`/`mirror`…） | ✅ 能 | 全部 dispatch 算子 |
| **上下文管理器**（`with BuildSketch/BuildLine/BuildPart(...)`） | ❌ 不能（函数里丢父上下文） | `three_point_arc`/`spline` 这类**草图算子**必须**词法内联**；需要"自带上下文"时要 `with BuildPart() as sub:` + `add(sub.part, mode=...)` |

⟹ **结论**：`threePointArc`/`spline` 属于 **sketch op 层**（应由 IR 生成器在 `with BuildLine()` 内**内联生成代码**），不适合做成 op_lib 的运行时函数。
