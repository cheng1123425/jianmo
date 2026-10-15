# 「s1 IR 化 + 算子接入词表」方案（草案 · 待批）

> 目标：让**新增零件只交数据（`ir.json`），不写 Python**——把已验证的算子从
> 独立实验工具，接进主干流水线的 s1 建模环节。
>
> 定位：本文只做**设计**，不动代码。落地前需评审。
> 依据：`lib/ir.py`、`tools/ir2build.py`、`tools/ir2partdesign.py`、`pipe.py`、
> 各零件 `ir.json`（均为当前工作区实际代码/数据）。

---

## 0. 一句话

现在 s1 **必须跑零件自带的 `steps/s1_build.py`**（手写 build123d）。
本方案让 s1 在**零件没自带脚本时**，改走「读 `ir.json` → 算子生成 build123d 脚本 → 跑」；
自带的脚本照旧优先（**逃生口保留**）。

---

## 1. 现状（实测锚点）

| 事实 | 位置 | 说明 |
|---|---|---|
| s1 固定跑零件脚本 | `pipe.py:122` | `runner="py"`，读 `params.py`，产出 `model_step/model_stl` |
| s1~s8 缺则启动即报错 | `pipe.py:216-234` | `_check_owned_steps()`，只跳过 `SHARED_STEPS` |
| **本地优先、共享兜底** | `pipe.py:270-291` | `script_of()`：零件有 `steps/<n>.py` 就用；否则若 `<n> ∈ SHARED_STEPS` 且根目录有同名文件，才回落共享 |
| s1 不在共享集 | `pipe.py:171-175` | `SHARED_STEPS` 无 `s1_build`；根目录 `steps/` 里也**没有** `s1_build.py` |
| IR 词表 | `lib/ir.py:56-70` | `KINDS`(主体/加法/减法/边处理)、`TREE_OPS`、`DIM_KINDS`、`GEOM_KINDS` |
| **impl 内部 op 不校验** | `lib/ir.py:113-184` | `validate()` 只查 kind/tree/deps/drawing，**不查 impl 里的 op 名** |
| 生成器覆盖 | `tools/ir2build.py:197-389` | 草图 op（polygon/circle/rect/line/polyline/center_arc）+ `tool_cylinder/box/sphere/cone/torus` + `extrude`；**`revolve` 会被错当 extrude 生成**；`fillet/chamfer` 打 PLACEHOLDER |
| 现有 IR 实际用到的 op | 4 零件 `ir.json` 统计 | `extrude` `cut` `tool_cylinder` `sketch_line` `sketch_center_arc` `sketch_circle` `sketch_polyline` `sketch_polygon` `sketch_rect` `tool_box` |
| s1 输出契约 | `parts/lbracket/steps/s1_build.py` 尾 | 写 `<TAG>.step` + `<TAG>.stl` 到 `models/`；`data` 含 volume/bbox/solids |
| 挖矿给的"该做哪些算子" | `验证报告/z2c_mined_full/op_candidates.md` | extrude84% / chamfer73% / rect73% / hole58% / pushPoints36% / fillet36% / revolve17% / shell16% / rarray15% / cboreHole8% / polarArray8% |

**结论**：接线机制（本地优先/共享兜底）**已经存在**；缺的是
①共享版 `s1_build.py`（IR 驱动）、②IR 能表达新算子、③生成器会生成新算子。

---

## 2. 目标与验收

**目标**：新增零件 = 只交数据文件，0 行 Python。

**验收（硬标准）**
1. `parts/valve_cover` **只给数据**（`params.py` / `ref_spec.py` / `draw_spec.py` /
   `ir.json` / `ir_anchors.json`），`python pipe.py --part parts/valve_cover --loop` 闭环 **pass**；
2. **4 个现有夹具**（gasket/bracket/lbracket/ybracket）闭环结果**不变**（回归零波及）；
3. 任一零件的 `ir.json` 经共享 s1 生成的几何，与"手写脚本版本"体积/外接**一致**（Δ<0.5mm³）；
4. `guard.py` 隔离检查全过（新共享步骤不越消息线）。

---

## 3. 设计

### 3.1 IR 词表扩展（`lib/ir.py`）

**新增 `IMPL_OPS` 词表 + 校验**（补上 `validate()` 的盲区）：

```python
#: impl 段类型
IMPL_SEGS = ("sketch", "extrude", "revolve", "cut", "tool", "shell")
#: impl 里的算子名（按段归类）
IMPL_OPS = {
  "sketch": ("sketch_polygon", "sketch_circle", "sketch_rect",
             "sketch_line", "sketch_polyline", "sketch_center_arc"),
  "tool":   ("tool_cylinder", "tool_box", "tool_sphere", "tool_cone", "tool_torus",
             "tool_hole", "tool_hole_grid", "tool_bolt_circle", "tool_cbore_hole"),
  "add":    ("extrude", "revolve", "loft", "sweep"),
  "deform": ("shell",),
}
```

**KINDS** 增加 `"变形"`（给 shell）；**TREE_OPS** 增加 FreeCAD 对应物：
`"Revolution"`（revolve）、`"Shell"`、`"PolarPattern"/"LinearPattern"`（阵列），
`Hole` 已有。

**新算子的 IR 表达（形态草案）**——一律**几何谓词/具名参数**，不存 `Edge#N`：

| 类别 | 新 op | impl 段 | params 形态 |
|---|---|---|---|
| 多点孔 | `tool_hole` | `["tool","tool_hole"]` | `{d, at:[[x,y]…], pos, rotation?}` |
| 矩形孔阵 | `tool_hole_grid` | 同上 | `{d, at:[[x,y]…]}`（点列由上游算） |
| 圆周孔阵 | `tool_bolt_circle` | 同上 | `{n, d, bcd_r, phase?, pos}` |
| 沉头孔 | `tool_cbore_hole` | 同上 | `{d, cbore_d, cbore_depth, at:[[x,y]…]}` |
| 回转体 | `revolve` | `["revolve",{...}]` | `{amount, axis:"Z"}` |
| 抽壳 | `shell` | `["shell",{...}]`（kind=变形） | `{thickness, faces}` |
| 圆角/倒角 | `fillet`/`chamfer` | `["edge",{...}]`（kind=边处理） | `{r\|d, dir, pos_axis, between}` |

> 「阵列」表达为**参数化的 tool**（而非新 kind），这样沿用现有
> 「减法 = `part - tool`」的生成路径，改动最小。

### 3.2 生成器扩展（`tools/ir2build.py` + `tools/ir2partdesign.py`）

**ir2build.py**：
- 修 `revolve`：当前 `seg[0] in ("extrude","loft","revolve","sweep")` 收集后**一律生成 `extrude(...)`**（`ir2build.py:333,356`）→ 改为按 seg 名生成 `revolve(axis=Axis.Z)`；
- `tool` 段扩：`tool_hole`→`with Locations(...): Hole(r)`；`tool_hole_grid`/`tool_bolt_circle`→ 先算点列再 `Locations + Hole`；`tool_cbore_hole`→`CounterBoreHole`；
- `边处理`段：`fillet(edges, r)` / `chamfer(edges, length)`，选边用**几何谓词**（`dir` + `pos_axis` + `between`，见 `验证报告/z2c_conv/op_lib.py` 已验证的两轴谓词）；
- `shell` 段：`offset(amount=-t, openings=faces)`。

**ir2partdesign.py**（可选，D 阶段已建）：同批算子映射到 FreeCAD 特征
（Hole→Pocket+Sketch、阵列→PolarPattern/LinearPattern、revolve→Revolution、shell→Shell）。

> 生成器实现可直接复用 `验证报告/z2c_conv/op_lib.py` 的 7 个已验证算子（build123d 侧）。

### 3.3 s1 接入（`pipe.py` + 新增共享 `steps/s1_build.py`）

**改动极小**（利用现成机制）：

1. `pipe.py:171` 的 `SHARED_STEPS` **加入 `"s1_build"`**；
2. 新增**共享** `steps/s1_build.py`，逻辑：
   ```
   若零件有 ir.json：
       ir2build 生成脚本 → 写入 _msg/（或临时文件）→ exec → 复用 s1 输出契约
       （写 models/<TAG>.step + .stl，返回同样的 data）
   否则：
       报错（清晰提示：该零件既无 s1_build.py 也无 ir.json）
   ```
3. 此时行为自动满足：
   - **有本地 `steps/s1_build.py` 的零件**（4 夹具）→ 本地优先，**完全不变**（回归零波及）；
   - **只有 `ir.json` 的零件**（valve_cover）→ 回落共享 IR 版。

**注意**：`_check_owned_steps()` 跳过 `SHARED_STEPS`，所以"s1_build 进共享集"后，
缺 s1 的零件不再启动报错——**由共享版在运行时清晰报错**（无 ir.json 时）。

### 3.4 数据契约（谁管什么）

| 文件 | 角色 | 谁写 |
|---|---|---|
| `params.py` | **数值真值**（具名尺寸） | 人或生成 |
| `ir.json` | **构造真值**（特征图：结构+impl+params） | 人或 recorder |
| `ref_spec.py` | 闭环基准 | 数据 |
| `draw_spec.py` | 出图数据（已数据化） | 数据 |
| `ir_anchors.json` | 标注↔特征绑定（G 阶段） | 数据 |

> 已识别的**缺口③**：`ir.json` 里 params 是**求值后的裸数字**（`8.0`），
> 与 `params.py` 的具名值（`P.BASE_T_Z`）脱钩。本方案**不解决**它（数值可精确复现几何）；
> 若要"IR 改一处 → 参数名联动"，需另立项（recorder 录符号名）。

---

## 4. 关键设计决策与取舍

| # | 决策 | 取舍 |
|---|---|---|
| D1 | **沿用「本地优先、共享兜底」**，不改优先级 | 4 夹具零波及；逃生口天然保留 |
| D2 | 阵列做成**参数化 tool**，不新增 kind | 复用现有减法路径，改动最小；但"阵列"语义偏弱 |
| D3 | 词表**扩到挖矿榜 top 级**（hole/阵列/revolve/shell/fillet/chamfer），**不追长尾** | 覆盖 80%+；避免词表膨胀（榜显示机械特征有界收敛） |
| D4 | 先支持**手写 IR**（数据驱动），recorder 扩展列为后续 | 目标就是"填数据"；recorder 仅用于逆向存量脚本 |
| D5 | 4 个夹具**保持手写 s1_build.py 不动** | 它们是回归基线，动它们会污染基线；valve_cover 当第一个 IR 驱动件 |

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 序列假设：ir2build 假设"加法全在减法前"（`ir2build.py:315-318`） | 交错的 IR 生成错几何 | 词表校验 + 生成器交错检测（已有 WARNING），必要时显式报错 |
| 边处理算子依赖拓扑 | 选边不稳（TNP） | 用**几何谓词**（dir+pos_axis+between），已在 op_lib 验证 |
| 共享 s1 改动波及既有零件 | 回归 | 本地优先保证零波及；跑 4 夹具回归验证 |
| `revolve` 现被错当 extrude | 静默错几何 | 本方案修它；补 round-trip 自测 |
| IR 词表演进破坏旧 IR | 兼容 | `ir_version` 递增 + validate 给出明确报错 |

---

## 6. 分期与工时（估算，人日）

| 阶段 | 内容 | 工时 |
|---|---|---|
| **S1-a** | 词表扩展 + validate 补 impl 校验（`lib/ir.py`） | 0.5 |
| **S1-b** | ir2build 扩算子（hole/阵列/revolve/shell/fillet/chamfer）+ 修 revolve | 1.5–2 |
| **S1-c** | 共享 `steps/s1_build.py` + `pipe.py` 接线（SHARED_STEPS） | 0.5 |
| **S1-d** | valve_cover 数据（ir.json 等）+ 端到端调试 | 1–1.5 |
| **S1-e** | 4 夹具回归 + guard + round-trip 自测 | 0.5 |
| （可选） | ir2partdesign 同步扩算子 | +1 |
| **合计** | | **约 4–5 人日（含可选 5–6）** |

---

## 7. 不做（边界）

- **不迁移 4 个夹具**到 IR 驱动（保持基线不动；日后另立"逐件迁移+几何对比"专项）。
- **不解决缺口③**（IR 裸数值 vs 具名参数）——另立项。
- **不扩长尾算子**——只做挖矿榜 top 级；长尾留手写 s1_build.py 逃生口。
- **不做三方同步**——IR 仍是唯一真值源，build123d/FreeCAD 都是它的下游。

---

## 8. 验收清单（逐条可核）

- [ ] `python tools/ir2build.py --part parts/valve_cover --out _tmp/vc.py` 生成成功，无 PLACEHOLDER
- [ ] 生成的脚本重跑，几何与设计值一致（体积/外接，Δ<0.5）
- [ ] `python pipe.py --part parts/valve_cover --loop` → **闭环 pass**
- [ ] gasket/bracket/lbracket/ybracket 四件闭环结果与改前**逐条一致**
- [ ] `python guard.py --steps steps` 通过
- [ ] `parts/valve_cover/` 下**无 `steps/*.py`**（证明"0 行 Python"）
