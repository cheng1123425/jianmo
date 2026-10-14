# 能否从 Zero-to-CAD 蒸馏出语义层？—— 实测核查报告

> **核查人**：WorkBuddy（Linux 沙箱，pyarrow 实测）
> **日期**：2026-10-14
> **样本**：`ADSKAILab/Zero-To-CAD-100k` 真实 parquet（`data/test/89_93ae1850…_000000_000000-0.parquet`，88 MB，**430 行**）
> **数据来源**：`hf-mirror.com`（`huggingface.co` 直连不通，与 HANDOFF §7.2 一致）
> **结论**：**能蒸馏，但只有"部分语义"，且缺口在图纸侧。** 详见下。

---

## 0. 一句话结论

Zero-to-CAD 数据集**没有独立的语义字段**（HANDOFF §6.1 的判断正确），
但它的 `cadquery_file` 里藏着**三路可蒸馏的语义线索**——参数名、英文注释、`Measures` 嵌套结构。
把它们拼起来，能还原出**特征级语义**（这是什么孔/什么肋/什么槽），**silent 覆盖约 50~98%（分项不等）**。
**但它从设计上就不含二维图纸/标注**，所以"3D↔2D 对应关系"这一环，**它给不了，必须你自己造**。

---

## 1. 数据集 schema（决定性证据）

parquet 18 个列，**没有一个叫 semantic / feature / role / label** 的字段：

| 列 | 类型 | 是不是语义 |
|---|---|---|
| `uuid` | string | — |
| `cadquery_file` | **binary** | ⭐ 藏着线索（见 §2） |
| `num_faces` | int64 | 几何量 |
| `face_latency_ms` | double | 性能 |
| `cadquery_ops_json` | **string** | ⭐ 操作层（见 §3） |
| `cadquery_ops_count` | int64 | 计数 |
| `ops_latency_ms` | double | 性能 |
| `num_renders` | int64 | 恒为 8 |
| `image_0` … `image_7` | binary ×8 | 8 视图渲染（PNG） |
| `stl_file` | binary | 几何 |
| `step_file` | binary | 几何 |

**关键词扫描（430 行 ops_json）**：`semantic` 0 行、`role` 0 行、`type` 0 行、`label` 0 行、`annotation` 0 行。
→ **数据集层面确实无语义层。** HANDOFF §6.1「它的终点是操作层」**属实**。

---

## 2. ⭐ 蒸馏线索一：参数名本身就是语义（97.6% 覆盖）

`cadquery_file` 里的建模代码用**语义化参数名**（不是 `a1/a2`）：

```python
m = Measures(
    width=70.0, depth=20.0, height=10.0,
    flange_length=30.0, flange_thickness=5.0,      # ← 法兰
    rib_width=15.0, rib_thickness=4.0, rib_height=5.0,  # ← 加强肋
    chamfer=1.0,
    hole=Measures(                                  # ← 孔（嵌套）
        position_x=20.0, position_y=0.0,
        diameter=4.0, cbore_diameter=6.5, cbore_depth=3.0  # ← 沉孔
    )
)
```

**语义词根覆盖率实测**（430 行，417 种参数名，1604 个参数实例）：

| 语义类别 | 词根 | 命中实例 |
|---|---|---|
| 孔 | hole / cbore / csk / bore / drill | 273 |
| 尺寸 | length / width / height / thickness / depth / diameter | 779 |
| 圆角倒角 | fillet / chamfer / round / radius | 148 |
| 腿/臂 | leg / arm / wing | 114 |
| 凸台/肋 | rib / boss / flange | 105 |
| 槽/凹 | pocket / slot / groove | 90 |
| 板/基 | base / plate / bracket / panel | 56 |
| **合计命中** | | **1565 / 1604 = 97.6%** |

**频率表**（前几名）：`hole_diameter`(38)、`chamfer`(28)、`rib_width`(17)、`cbore_depth`(17)、
`mount_hole_diameter`(10)、`csk_diameter`(8)、`base_thickness`(7)、`pocket_depth`(13)……

→ **参数名直接告诉你"这是什么特征"。** 例如 `cbore_diameter` = 沉孔直径，`csk_angle` = 埋头孔角度。
这是**特征级语义**，比 `dims_spec.py` 的"尺寸映射"高一层。

---

## 3. ⭐ 蒸馏线索二：代码注释写明特征意图（53.3% 覆盖）

229/430（53.3%）的样本带英文注释，平均 2.9 行/文件，注释内容**就是语义标注**：

```python
# base solid                              ← 主体
base = cq.Workplane("XY").rect(m.width, m.depth).extrude(m.height)
# flange solid attached at +X side         ← 加法特征 + 位置
flange = (...)
result = base.union(flange)
# rib on top face, centered in depth       ← 加法特征 + 位置
# cbore hole through flange side (+X face) ← 减法特征 + 类型 + 位置
# chamfer outer vertical edges             ← 边处理
```

→ 注释补上了**"这个特征的作用与位置"**，正是 HANDOFF §4.4 `drawing` 那一环想表达的东西的**三维侧对应物**。

---

## 4. ⭐ 蒸馏线索三：操作序列蕴含"结构层"（98.4% 可判主体）

HANDOFF §4.2 的**结构层**（主体/加法/减法/边处理）可从操作序列**自动判定**：

| 结构判定 | 判据 | 覆盖率（430 行） |
|---|---|---|
| 主体 | `= cq.Workplane(...)` | **98.4%** |
| 减法 | `.cut(` / `.hole(` / `.cboreHole(` / `.cskHole(` | **86.5%** |
| 边处理 | `.chamfer(` / `.fillet(` | **90.7%** |
| 加法 | `.union(` | 49.5% |
| 嵌套子特征（如 `hole=Measures(...)`） | 多层 `Measures(` | 仅 3.5% |

→ **结构层可自动蒸馏**（主体 98%、减法 87%、边处理 91%），**与 HANDOFF §5.8「特征块可自动切分」一致**。
唯一弱项是"加法"（union），因为大量零件是单一 `Workplane` 链式构造、根本不用 union——**不是缺陷，是写法差异**。

---

## 5. ❌ 给不了的那一环：图纸 / 标注（3D↔2D 对应）

数据集**完全没有**：

- ❌ 二维图纸（DXF / PDF / 投影视图的标注）
- ❌ 尺寸标注文本（`4×Φ8`、`R3`、`C1`）
- ❌ 标注 ↔ 特征的关联
- ❌ 语义分类（这个孔是"安装孔"而不是"销孔"—— HANDOFF §5.9 说的逆向难题）

有 8 张**渲染图**（`image_0..7`），但那是**无标注的等轴/正交渲染**，不是工程图。
→ **Zero-to-CAD 无法帮你补上图纸侧。** 这正是 HANDOFF §10 的判断：

> 用户的活是「操作层 → 语义层 → **国标工程图**」这一层，而这一层他有它没有的资产——
> **真实图纸上的标注（`4×Φ8`）就是现成的语义标签**。

---

## 6. 蒸馏方案（如果你要用）

可以把 `cadquery_file` 喂给一个**解析器**，产出你项目要的三层 IR：

```
cadquery_file
  ├─ 解析 Measures(...) 嵌套  → 语义层（特征树 + 参数名语义）
  ├─ 解析操作序列(.union/.cut/.chamfer) → 结构层（主体/加/减/边处理）
  ├─ 取 cadquery_ops_json            → 操作层（数据集已给）
  └─ 注释文本                        → 语义补注（作用 + 位置）
              ↓
     ┌─────────────────────────────┐
     │  feature_semantics.json      │  ← 你要的"三维语义层"
     └─────────────────────────────┘
              ↓
     缺：drawing 字段（↔二维标注）← 只能用你自己的图纸解析补
```

**可行性评级**：

| 目标 | 可行性 | 依据 |
|---|---|---|
| 从数据集蒸馏**三维语义层**（特征类型 + 角色） | ✅ **可做**（覆盖 50~98% 分项） | 参数名 97.6% + 注释 53.3% + 结构序列 87~98% |
| 从数据集蒸馏**完整语义层**（含"安装孔/销孔"级角色） | ⚠️ **部分** | 参数名给"类型"，给不了"用途"——那是设计意图，需 LLM 或人工 |
| 从数据集得到 **3D↔2D 对应**（drawing 字段） | ❌ **不能** | 数据集不含任何图纸/标注 |
| 从数据集得到**国标工程图** | ❌ **不能** | 同上 |

---

## 7. 与 HANDOFF 结论的对照（诚实修正）

| HANDOFF 说法 | 实测 | 修正 |
|---|---|---|
| §6.1「它的终点是操作层，无语义层」 | schema 确无语义字段 | ✅ **准确** |
| §6.1「⚠️ 论文称面数≥7，但 viewer 显示最小 2」 | 本批 430 行 `num_faces` 最小值 **7**，0 行 <7 | ⚠️ **本批数据不矛盾**（可能 viewer 那批不同） |
| §5.8「特征块可自动切分，加减法分类全对」 | 结构序列判定：主体 98.4% / 减法 86.5% / 边处理 90.7% | ✅ **大体成立**（加法需 union 写法才可判） |
| §10「语义才是瓶颈，要打通 2D 对应」 | 数据集**确无** 2D 侧 | ✅ **准确**——且这才是你的差异化 |
| （未提）数据集参数名含语义 | **97.6% 参数实例可语义词根识别** | 🆕 **新发现：比 HANDOFF 预期更乐观** |

**关键修正**：HANDOFF 说"无语义层"是**就数据集字段而言正确**，但它没说透——
**语义信息以"参数名 + 注释 + 结构序列"的形式隐式存在**，可蒸馏出**特征级语义**（虽拿不到"用途级语义"）。
这比"完全无语义"要乐观，但**仍补不上图纸侧**。

---

## 8. 建议

1. **可以用**：拿 Zero-to-CAD 的 10 万条做**三维语义层的预训练数据**——蒸馏出"特征树 + 类型"，
   数量大、覆盖广，适合喂给模型学"什么参数名对应什么特征"。
2. **必须自己造**：`drawing`（↔二维标注）这一环**只能来自真实图纸**——
   正是你现在 `s0b_dwgread` 在做的（从图纸读 `4×Φ8`）。
3. **两者结合**：数据集给你**大量三维语义样本**，你的图纸解析给你**2D↔3D 对应**——
   **合起来才是完整的语义层**，这正是 HANDOFF §10「你有它没有的资产」的确切含义。
4. **别指望用它补图纸**：8 张渲染图是无标注的，不是工程图，无标注文本可提取。

---

## 附：核查产物

```
/tmp/z2c_sample.parquet   真实数据集样本（88 MB，430 行）
/tmp/z2c_100k.json        数据集元信息（id/license/siblings）
```
