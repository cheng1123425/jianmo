# -*- coding: utf-8 -*-
r"""draw_spec —— 图纸渲染的**唯一数据源**（2026-10-15 立）

`steps/s3_render.py` 已被下沉到共享层（`steps/s3_render.py`），零件这边**不再有Python 代码**。
本文件就是原来那些 `PLACE / VIEW_ORDER / LABELS / TITLE / DIMS` 五大块的搬家。

## 为什么

原来这五样写在每个零件的 `s3_render.py` 里（bracket/lbracket/ybracket 各67 行），
**全是数据、没有逻辑**。它们是产品层最后一段"AI 手写的代码"——
架构 `lib/drawing_render.py` 一改签名，4 个零件的调用点同时断，只能逐个重写。

搬成数据文件后：零件 = 纯数据，改架构时产品层 0 波及。

## 五个字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `PLACE` | `{视图名: (纸面x, 纸面y, 是否上下翻转)}` | 视图在A3 纸上的落位（mm） |
| `VIEW_ORDER` | `(视图名, ...)` | 视图绘制顺序 |
| `LABELS` | `((视图名, 中文名), ...)` | 图上的视图标签，如 `("Front", "正视图")` |
| `TITLE` | dict | 标题栏：`name/scale/material/bbox/note/date` |
| `DIMS` | list[dict] | 标注清单，见下|

## DIMS 每条

```python
dict(kind=..., view=..., label=..., **定位参数)
```

| `kind` | 额外必填 | 含义 |
|---|---|---|
| `extent` | `axis`(0横/1竖), `at` | 视图外接范围标注 |
| `h` | `ua`,`ub`, `at` | 水平两点距离 |
| `v` | `wa`,`wb`, `at` | 垂直两点距离 |
| `extent_y` | `wa`,`wb`, `at` | 竖直两点距离（从视图左边引出） |
| `leader` | `uw`=(u,w), `off`=(dx,dy) | 引出线标注 |

`at` 是纸面定位三元组 `("BB", i, j)`：相对视图外接框（BB）/ 画布边界，
偏移 `i`（沿标注轴）、`j`（垂直方向），单位 mm。

## 声明式条件 `when`（可选）

lbracket 的pitch 标注有个条件："**只有确实找到两个φ8 圆时才标**"，
原来写在 s3 里是 6 行 Python。现在用 `when` 声明：

```python
dict(kind="extent_y", view="Right", at=("BB", 0, -8), label=...,
     span="circles",      # 两个端点从 Right 视图的圆心取
     when=dict(kind="circles_near", view="Right", r=4.0, tol=0.3, n=2))
```

`s3_render` 会在渲染前求值 `when`，不满足就跳过这条标注。
支持的谓词见 `steps/s3_render.py` 的 `_eval_when`。

## label 的来源

`label_from="meas:<label>"` → 取 `_drawing.json` 里 FreeCAD **实测值**，
这样改 `params.py` 后图上数字自动跟随（bracket 之前是硬编码字符串，见
`docs/遗留事项与下一步.md` §二-1）。
"""
SCHEMA_VERSION = 1

# ---- ① 视图落位（A3 纸面坐标 mm）----
PLACE = {
    "Top":   (34, 45, False),
    "Front": (34, 172, True),
    "Right": (214, 172, True),
}

# ---- ② 绘制顺序 ----
VIEW_ORDER = ("Top", "Front", "Right")

# ---- ③ 视图标签 ----
LABELS = (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图"))

# ---- ④ 标题栏 ----
TITLE = {
    "name": "L 形支座",
    "scale": "比例 2:1    单位 mm    第一角投影",
    "material": "材料 未标注        数量 1",
    "bbox": "56 × 40 × 39",
    "note": "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过",
    "date": "2026-09-30",
}

# ---- ⑤ 标注清单 ----
DIMS = [
    # Top：L（横）、W（竖）
    dict(kind="extent", view="Top", axis=0, at=("BB", 3, +5),
         label_from="meas:L"),
    dict(kind="extent", view="Top", axis=1, at=("BB", 0, -8),
         label_from="meas:W"),
    # Front：H_total（竖）
    dict(kind="extent", view="Front", axis=1, at=("BB", 0, -8),
         label_from="meas:H_total"),
    # Right：pitch —— 两个 φ8 孔心的Y 向间距
    #只有确实找到两个 φ8 圆时才标（原来这段逻辑在 s3_render 里，6 行 Python）
    dict(kind="extent_y", view="Right", span="circles",
         at=("BB", 0, -8), label_from="meas:pitch",
         when=dict(kind="circles_near", view="Right", r=4.0, tol=0.3, n=2)),
]