# -*- coding: utf-8 -*-
r"""lib/collect.py —— 从投影数据提取几何特征（零件无关）

被 `steps/s5_collect.py` 调用。**只提取，不做任何判断**。

设计要点
--------
1. **按「视图是否存在」自适应**：没有 Right 视图的零件（如垫片）不会报错，只是不产出 `*_right` 键。
   —— 这正是三个零件版与垫片版当年的唯一真差异（零件多读了 Right），现在用存在性判断统一。
2. **同时给出两套键名**，兼容历史上两种消费者 schema：
     * 新（三个零件的 s6_compare 用）: `len_x_top` `len_y_top` `hgt_front` `len_x_right` `len_y_right`
     * 旧（垫片的 s6_compare 用）    : `len_x` `len_y` `height` `steps` `boss_w`
   两套都产出，谁读谁的都能取到。
3. **视图 y 轴方向不保证**（FreeCAD 主视图出现过 `y=50-z` 也出现过 `y=z-50`）：
   高度层用「中心凸台顶线」判断是否翻转后归一。
"""

__all__ = ["collect"]


def _span(v, i):
    """视图 v 的第 i 个坐标分量跨度（外接尺寸）"""
    q = [p[i] for e in v.get("edges", []) for p in e]
    return round(max(q) - min(q), 3) if q else None


def _circles(v):
    """圆特征去重（同一个圆会被投影切成多段弧）；不过滤任何半径，交给 s6 判断"""
    seen, out = set(), []
    for c in (v or {}).get("circles", []):
        k = (round(c["r"], 2), round(c["cx"], 1), round(c["cy"], 1))
        if k in seen:
            continue
        seen.add(k)
        out.append((c["r"], c["cx"], c["cy"]))
    return out


def _height_chain(vf):
    """主视水平线 → (高度层差列表, 中心凸台宽)

    中心凸台顶线 = 最长的、x 居中的水平线（对应 z 最大处）。
    对没有中心凸台的零件，这一步是无害的副产品（返回空/None）。
    """
    hlines = vf.get("hlines", [])
    boss_w, boss_y = None, None
    for h in hlines:
        if abs((h["x0"] + h["x1"]) / 2.0) < 1.0:
            w = h["x1"] - h["x0"]
            if boss_w is None or w > boss_w:
                boss_w, boss_y = w, h["y"]
    lev = sorted({round(h["y"], 3) for h in hlines})
    if boss_y is not None and len(lev) > 1 and abs(boss_y - lev[0]) < abs(boss_y - lev[-1]):
        lev = sorted(round(lev[0] + lev[-1] - y, 3) for y in lev)
    return [round(lev[i + 1] - lev[i], 3) for i in range(len(lev) - 1)], boss_w


def collect(data):
    """把 `_drawing.json` 的内容提炼成几何摘要（dict）"""
    views = {v["name"]: v for v in data.get("views", [])}
    vt, vf, vr = views.get("Top"), views.get("Front"), views.get("Right")

    out = {
        "views_used": [n for n in ("Top", "Front", "Right") if n in views],
        "top_circles": _circles(vt),
        "front_circles": _circles(vf),
        "right_circles": _circles(vr),
        "all_radii": sorted({round(c["r"], 2) for v in (vt, vf, vr)
                             for c in (v or {}).get("circles", [])}),
        "marks": {d["label"]: d["value"] for d in data.get("dims", [])},
    }

    if vt:
        out["len_x_top"] = _span(vt, 0)
        out["len_y_top"] = _span(vt, 1)
    if vf:
        out["hgt_front"] = _span(vf, 1)
        out["steps"], out["boss_w"] = _height_chain(vf)
    if vr:
        out["len_x_right"] = _span(vr, 0)
        out["len_y_right"] = _span(vr, 1)

    # ---- 兼容键：垫片的 s6_compare 读 len_x / len_y / height ----
    for new, old in (("len_x_top", "len_x"), ("len_y_top", "len_y"),
                     ("hgt_front", "height")):
        if new in out:
            out[old] = out[new]
    return out
