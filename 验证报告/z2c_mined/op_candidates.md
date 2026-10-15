# Zero-to-CAD 算子挖掘报告（候选算子榜）

> 工具 `tools/z2c_mine_ops.py`（独立于主干）。目的是给「算子词表该做什么」提供**数据依据**：覆盖零件数越多的模式越值得做成算子。

样本：**430** 个零件 | 每零件 op 数 min/max/avg = 4/60/23.9


## L1 单算子（leaf op）—— 原语词表候选

| op | 出现次数 | 覆盖零件 | 覆盖率 |
|---|---|---|---|
| `Workplane` | 1021 | 430 | 100% |
| `edges` | 486 | 384 | 89% |
| `extrude` | 738 | 368 | 86% |
| `faces` | 813 | 360 | 84% |
| `workplane` | 755 | 351 | 82% |
| `chamfer` | 341 | 319 | 74% |
| `rect` | 556 | 297 | 69% |
| `hole` | 328 | 248 | 58% |
| `center` | 451 | 241 | 56% |
| `close` | 264 | 235 | 55% |
| `union` | 336 | 213 | 50% |
| `cutBlind` | 225 | 167 | 39% |
| `circle` | 292 | 158 | 37% |
| `translate` | 256 | 158 | 37% |
| `cut` | 256 | 157 | 37% |
| `pushPoints` | 185 | 154 | 36% |
| `lineTo` | 631 | 138 | 32% |
| `moveTo` | 161 | 137 | 32% |
| `fillet` | 151 | 135 | 31% |
| `box` | 150 | 106 | 25% |

## L2 链式路径（function）—— 惯用法/复合模式候选

| 链式路径 | 出现次数 | 覆盖零件 | 覆盖率 |
|---|---|---|---|
| `cq.Workplane` | 1021 | 430 | 100% |
| `cq.Workplane.rect` | 174 | 115 | 27% |
| `range` | 157 | 115 | 27% |
| `cq.Workplane.moveTo` | 119 | 115 | 27% |
| `cq.Workplane.center` | 163 | 106 | 25% |
| `cq.Workplane.moveTo.lineTo` | 110 | 106 | 25% |
| `cq.Workplane.rect.extrude` | 145 | 102 | 24% |
| `cq.Workplane.box` | 130 | 98 | 23% |
| `Measures` | 133 | 95 | 22% |
| `cq.Workplane.moveTo.lineTo.lineTo` | 98 | 95 | 22% |
| `self.build` | 91 | 91 | 21% |
| `cq.Workplane.polyline` | 95 | 85 | 20% |
| `base.faces` | 148 | 84 | 20% |
| `cq.Workplane.moveTo.lineTo.lineTo.lineTo` | 84 | 83 | 19% |
| `base.faces.workplane` | 139 | 82 | 19% |
| `cq.Workplane.polyline.close` | 92 | 82 | 19% |
| `cq.Workplane.circle` | 118 | 78 | 18% |
| `base.union` | 77 | 73 | 17% |
| `result.faces` | 157 | 69 | 16% |
| `cq.Workplane.circle.extrude` | 94 | 66 | 15% |

## L3 序列模式（2-gram op 序列）

| 序列 | 出现次数 | 覆盖零件 | 覆盖率 |
|---|---|---|---|
| `workplane → faces` | 252 | 180 | 42% |
| `Workplane → Workplane` | 186 | 130 | 30% |
| `faces → faces` | 173 | 118 | 27% |
| `workplane → workplane` | 147 | 108 | 25% |
| `moveTo → Workplane` | 107 | 106 | 25% |
| `Workplane → faces` | 105 | 99 | 23% |
| `extrude → union` | 108 | 98 | 23% |
| `extrude → extrude` | 117 | 92 | 21% |
| `faces → workplane` | 101 | 91 | 21% |
| `lineTo → moveTo` | 87 | 84 | 20% |
| `Workplane → workplane` | 86 | 82 | 19% |
| `center → workplane` | 96 | 80 | 19% |
| `lineTo → faces` | 94 | 76 | 18% |
| `rect → rect` | 103 | 75 | 17% |
| `translate → union` | 88 | 75 | 17% |
| `faces → lineTo` | 88 | 75 | 17% |
| `faces → Workplane` | 77 | 75 | 17% |
| `lineTo → lineTo` | 150 | 69 | 16% |
| `extrude → cut` | 91 | 69 | 16% |
| `workplane → Workplane` | 65 | 65 | 15% |

## L3 序列模式（3-gram op 序列）

| 序列 | 出现次数 | 覆盖零件 | 覆盖率 |
|---|---|---|---|
| `lineTo → moveTo → Workplane` | 71 | 71 | 17% |
| `lineTo → lineTo → moveTo` | 53 | 53 | 12% |
| `workplane → faces → faces` | 46 | 44 | 10% |
| `extrude → extrude → union` | 45 | 43 | 10% |
| `Measures → LBracket → build` | 43 | 43 | 10% |
| `workplane → workplane → faces` | 41 | 40 | 9% |
| `center → workplane → faces` | 53 | 38 | 9% |
| `workplane → lineTo → faces` | 36 | 36 | 8% |
| `faces → lineTo → lineTo` | 36 | 36 | 8% |
| `lineTo → faces → lineTo` | 35 | 35 | 8% |
| `faces → workplane → faces` | 34 | 32 | 7% |
| `lineTo → lineTo → lineTo` | 68 | 30 | 7% |
| `faces → faces → faces` | 44 | 30 | 7% |
| `Workplane → Workplane → Workplane` | 42 | 29 | 7% |
| `LBracket → build → extrude` | 28 | 28 | 7% |
| `workplane → workplane → workplane` | 35 | 26 | 6% |
| `Workplane → faces → faces` | 26 | 26 | 6% |
| `build → close → extrude` | 26 | 26 | 6% |
| `faces → faces → workplane` | 26 | 25 | 6% |
| `Workplane → workplane → workplane` | 25 | 25 | 6% |
