# Zero-to-CAD 算子挖掘报告（候选算子榜）

> 工具 `tools/z2c_mine_ops.py`（独立于主干）。目的是给「算子词表该做什么」提供**数据依据**：覆盖零件数越多的模式越值得做成算子。

样本：**100513** 个零件 | 每零件 op 数 min/max/avg = 3/94/24.0


## L1 单算子（leaf op）—— 原语词表候选

| op | 出现次数 | 覆盖零件 | 覆盖率 |
|---|---|---|---|
| `Workplane` | 239870 | 99997 | 99% |
| `edges` | 117204 | 90654 | 90% |
| `faces` | 202359 | 84728 | 84% |
| `extrude` | 182507 | 84233 | 84% |
| `workplane` | 187624 | 82922 | 82% |
| `chamfer` | 79222 | 73870 | 73% |
| `rect` | 151305 | 72970 | 73% |
| `hole` | 76595 | 58375 | 58% |
| `center` | 106660 | 54269 | 54% |
| `union` | 86819 | 52429 | 52% |
| `circle` | 83091 | 43369 | 43% |
| `cutBlind` | 58026 | 41642 | 41% |
| `close` | 44826 | 40189 | 40% |
| `pushPoints` | 43803 | 36438 | 36% |
| `fillet` | 40763 | 36402 | 36% |
| `cut` | 57838 | 35461 | 35% |
| `translate` | 61002 | 35362 | 35% |
| `box` | 34479 | 24671 | 25% |
| `moveTo` | 29018 | 24282 | 24% |
| `lineTo` | 105050 | 23968 | 24% |
| `polyline` | 18852 | 16967 | 17% |
| `revolve` | 18265 | 16956 | 17% |
| `shell` | 16511 | 16240 | 16% |
| `rarray` | 18075 | 14913 | 15% |
| `build` | 11684 | 11618 | 12% |
| `rotate` | 13912 | 10445 | 10% |
| `append` | 12684 | 8647 | 9% |
| `cboreHole` | 9310 | 8168 | 8% |
| `radians` | 12683 | 7983 | 8% |
| `polarArray` | 8670 | 7655 | 8% |

## L2 链式路径（function）—— 惯用法/复合模式候选

| 链式路径 | 出现次数 | 覆盖零件 | 覆盖率 |
|---|---|---|---|
| `cq.Workplane` | 239863 | 99993 | 99% |
| `cq.Workplane.rect` | 46748 | 32066 | 32% |
| `cq.Workplane.rect.extrude` | 40743 | 29002 | 29% |
| `range` | 40952 | 28880 | 29% |
| `cq.Workplane.center` | 39970 | 24150 | 24% |
| `cq.Workplane.box` | 30801 | 23096 | 23% |
| `cq.Workplane.circle` | 36593 | 21565 | 21% |
| `cq.Workplane.moveTo` | 23022 | 20796 | 21% |
| `result.faces` | 48403 | 20097 | 20% |
| `cq.Workplane.moveTo.lineTo` | 20707 | 19141 | 19% |
| `cq.Workplane.circle.extrude` | 31562 | 19077 | 19% |
| `result.faces.workplane` | 41318 | 18226 | 18% |
| `base.faces` | 26268 | 16821 | 17% |
| `cq.Workplane.moveTo.lineTo.lineTo` | 17766 | 16449 | 16% |
| `base.union` | 17237 | 16288 | 16% |
| `result.edges` | 18513 | 15738 | 16% |
| `base.faces.workplane` | 23751 | 15668 | 16% |
| `Measures` | 20680 | 15058 | 15% |
| `cq.Workplane.center.rect` | 19677 | 14242 | 14% |
| `cq.Workplane.polyline` | 15125 | 14102 | 14% |
| `cq.Workplane.polyline.close` | 14756 | 13747 | 14% |
| `cq.Workplane.moveTo.lineTo.lineTo.lineTo` | 14447 | 13722 | 14% |
| `cq.Workplane.center.rect.extrude` | 18304 | 13312 | 13% |
| `int` | 16585 | 12362 | 12% |
| `result.edges.chamfer` | 12705 | 12279 | 12% |
| `cq.Workplane.center.circle` | 13635 | 10062 | 10% |
| `cq.Workplane.center.circle.extrude` | 13128 | 9754 | 10% |
| `cq.Workplane.moveTo.lineTo.lineTo.lineTo.lineTo` | 9828 | 9695 | 10% |
| `profile.revolve` | 9695 | 9641 | 10% |
| `self.build` | 9564 | 9504 | 9% |

## L3 序列模式（2-gram op 序列）

| 序列 | 出现次数 | 覆盖零件 | 覆盖率 |
|---|---|---|---|
| `workplane → faces` | 63754 | 43766 | 44% |
| `Workplane → Workplane` | 49908 | 31775 | 32% |
| `faces → faces` | 45720 | 30652 | 30% |
| `workplane → workplane` | 37040 | 25834 | 26% |
| `extrude → extrude` | 32273 | 24986 | 25% |
| `Workplane → faces` | 26449 | 24776 | 25% |
| `extrude → union` | 28306 | 24674 | 25% |
| `Workplane → workplane` | 22555 | 21583 | 21% |
| `rect → rect` | 28777 | 20659 | 21% |
| `center → workplane` | 23204 | 19813 | 20% |
| `faces → workplane` | 22220 | 19530 | 19% |
| `workplane → Workplane` | 19017 | 18268 | 18% |
| `faces → Workplane` | 18610 | 17768 | 18% |
| `moveTo → Workplane` | 17769 | 17562 | 17% |
| `translate → union` | 20051 | 17541 | 17% |
| `extrude → cut` | 22216 | 17296 | 17% |
| `rect → edges` | 16759 | 16087 | 16% |
| `center → center` | 23240 | 15971 | 16% |
| `center → Workplane` | 15635 | 14558 | 14% |
| `edges → rect` | 14903 | 14545 | 14% |
| `rect → Workplane` | 14447 | 13976 | 14% |
| `edges → Workplane` | 14092 | 13949 | 14% |
| `rect → workplane` | 17360 | 13708 | 14% |
| `lineTo → moveTo` | 14314 | 13565 | 14% |
| `Workplane → center` | 14619 | 13491 | 13% |
| `circle → circle` | 16671 | 11748 | 12% |
| `workplane → center` | 12350 | 11651 | 12% |
| `lineTo → faces` | 13878 | 11258 | 11% |
| `translate → cut` | 13424 | 10950 | 11% |
| `hole → chamfer` | 10722 | 10660 | 11% |

## L3 序列模式（3-gram op 序列）

| 序列 | 出现次数 | 覆盖零件 | 覆盖率 |
|---|---|---|---|
| `workplane → faces → faces` | 15338 | 14652 | 15% |
| `lineTo → moveTo → Workplane` | 11627 | 11549 | 11% |
| `workplane → workplane → faces` | 11707 | 11420 | 11% |
| `extrude → extrude → union` | 10780 | 10351 | 10% |
| `Workplane → Workplane → Workplane` | 13555 | 9269 | 9% |
| `faces → faces → faces` | 12348 | 8765 | 9% |
| `lineTo → lineTo → moveTo` | 8361 | 8259 | 8% |
| `Workplane → workplane → faces` | 7716 | 7646 | 8% |
| `faces → workplane → faces` | 7967 | 7601 | 8% |
| `center → workplane → faces` | 9029 | 7193 | 7% |
| `workplane → Workplane → faces` | 6996 | 6926 | 7% |
| `extrude → extrude → cut` | 7135 | 6779 | 7% |
| `workplane → workplane → workplane` | 9399 | 6761 | 7% |
| `Workplane → Workplane → faces` | 6379 | 6313 | 6% |
| `rect → workplane → faces` | 9191 | 6153 | 6% |
| `Workplane → workplane → workplane` | 5929 | 5870 | 6% |
| `Workplane → faces → faces` | 5947 | 5869 | 6% |
| `lineTo → lineTo → lineTo` | 12144 | 5447 | 5% |
| `workplane → lineTo → faces` | 5443 | 5337 | 5% |
| `rect → rect → rect` | 6467 | 4789 | 5% |
| `faces → workplane → workplane` | 4813 | 4709 | 5% |
| `workplane → Workplane → Workplane` | 4632 | 4603 | 5% |
| `center → workplane → workplane` | 4646 | 4584 | 5% |
| `center → Workplane → Workplane` | 4702 | 4562 | 5% |
| `workplane → faces → extrude` | 5559 | 4558 | 5% |
| `faces → faces → workplane` | 4564 | 4464 | 4% |
| `lineTo → faces → lineTo` | 4511 | 4394 | 4% |
| `extrude → cut → extrude` | 5215 | 4349 | 4% |
| `faces → chamfer → edges` | 4562 | 4313 | 4% |
| `Workplane → Workplane → workplane` | 4350 | 4310 | 4% |
