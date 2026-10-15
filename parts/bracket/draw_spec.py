# -*- coding: utf-8 -*-
r"""draw_spec —— 铰链支座的图纸渲染数据（2026-10-15 从 steps/s3_render.py 搬来）

原来这些是 `steps/s3_render.py` 里的 Python 字面量。现在是数据。

**顺带修掉一个遗留问题**（`docs/遗留事项与下一步.md` §二-1）：
原来 13 条标注的数值是**硬编码字符串**（`"28"` / `"16"` / `"8"` …），
改 `params.py` 后 PDF 上的数字**不会变**。现在全部改成 `label_from="meas:<label>"`，
取 `_drawing.json` 里 FreeCAD 的**实测值** —— 改参数后图纸自动跟随。

label 与实测值的对应见下表（实测值取自 `_drawing.json` 的 `dims`）：

| 图上标注 | label | 实测值 |
|---|---|---|
| 28   | `arm_outer` | 28.0 |
| 16   | `arm_inner` | 16.0 |
| 8    | `T_base`    | 8.0 |
| 45   | `P9`        | 45.0 |
| 62   | `L`         | 62.0 |
| 2-φ6 | `dia_cbore` | 6.0 |
| 2-φ3 | `dia_thru`  | 3.0 |
| 27   | `head_h`    | 27.0 |
| 14   | `arm_h`     | 14.0 |
| 36   | `arm_len`   | 36.0 |
| R10  | `R_head`    | 10.0 |
| 2-φ8 | `dia_pin`   | 8.0 |
| 2-φ9 | `D9`        | 9.0 |

`2-φ6` 这类带前缀的：`s3_render` 会渲染成 `%.0f` 的数值，
所以直径数字走 meas、前缀在label 模板里表达 —— 见 `LABEL_FMT`。
"""
SCHEMA_VERSION = 1

# ---- ① 视图落位（A3 纸面坐标 mm）----
# Front/Right 的 view2d y 朝下（要翻转），Top 朝上
PLACE = {"Top": (34, 45, False), "Front": (34, 172, True), "Right": (214, 172, True)}

# ---- ② 绘制顺序 ----
# 注意：绘制顺序会影响线条端点的抗锯齿（后画的在上）。这个顺序必须与原实现一致，
# 否则像素对比会出现 ~1% 的「边缘发白」差异（视觉无差，但不是 0 差异）。
VIEW_ORDER = ("Top", "Front", "Right")

# ---- ③ 视图标签 ----
LABELS = (("Front", "正视图"), ("Right", "侧视图"), ("Top", "俯视图"))

# ---- ④ 标题栏 ----
TITLE = {
    "name": "铰链支座",
    "scale": "比例 2:1    单位 mm    第一角投影",
    "material": "材料 未标注        数量 1",
    "bbox": "62 × 46 × 37",
    "note": "视图：FreeCAD TechDraw 投影 · 尺寸经闭环校核通过",
    "date": "2026-09-29",
}

# ---- ⑤ 标注清单（at = ("BB", 索引, 偏移)：BB 是该视图的纸面包围盒）----
DIMS = [
    dict(kind="extent", view="Front", axis=0, at=("BB", 3, +5),
         label_from="meas:arm_outer"),
    dict(kind="h", view="Front", ua=-11, ub=11, at=("BB", 3, +13),
         label_from="meas:arm_inner"),
    dict(kind="v", view="Front", wa=27, wb=35, at=("BB", 0, -8),
         label_from="meas:T_base"),
    dict(kind="h", view="Front", ua=-22.5, ub=22.5, at=("BB", 1, -8),
         label_from="meas:P9"),
    dict(kind="extent", view="Front", axis=0, at=("BB", 1, -18),
         label_from="meas:L"),
    # 带前缀的标注：2-φ6 / 2-φ3
    dict(kind="leader", view="Front", uw=(-11, 8.5), off=(-25, 16),
         label="2-φ%.0f" % 6, label_from="meas:dia_cbore", label_wrap="2-φ%d"),
    dict(kind="leader", view="Front", uw=(11, 8.5), off=(20, -16),
         label="2-φ%.0f" % 3, label_from="meas:dia_thru", label_wrap="2-φ%d"),
    dict(kind="v", view="Right", wa=37, wb=0, at=("BB", 0, -8),
         label_from="meas:head_h"),
    dict(kind="v", view="Right", wa=14, wb=0, at=("BB", 2, +5),
         label_from="meas:arm_h"),
    dict(kind="h", view="Right", ua=-12, ub=24, at=("BB", 1, -8),
         label_from="meas:arm_len"),
    dict(kind="leader", view="Right", uw=(-20, 27), off=(-25, 16),
         label_from="meas:R_head", label_wrap="R%d"),
    dict(kind="leader", view="Right", uw=(-12, 27), off=(28, 12),
         label="2-φ%.0f" % 8, label_from="meas:dia_pin", label_wrap="2-φ%d"),
    dict(kind="leader", view="Top", uw=(22.5, 12), off=(24, 18),
         label="2-φ%.0f" % 9, label_from="meas:D9", label_wrap="2-φ%d"),
]