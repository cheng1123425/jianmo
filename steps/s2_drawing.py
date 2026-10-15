# -*- coding: utf-8 -*-
r"""s2_drawing（共享层 · 数据驱动）—— STEP → 工程图（三视图 + 尺寸标注）

**它让「新增零件不写 Python」成立**：零件没有自带 `steps/s2_drawing.py` 时，
本步骤从**数据**建图：

    views  ← draw_spec.py 的 `VIEWS`（方向/缩放）+ `PLACE`（纸面落位）
    dims   ← ir_anchors.json 的锚点（几何谓词 + 视图 + 期望值）
             + draw_spec.py 的 `DIM_POS`（纸面摆放）

**回落规则**：零件自带 `steps/s2_drawing.py` → 用自带的（老零件/特殊布置）；
没自带 → 落到本共享实现。

数值由 FreeCAD 在 `finalize()` 里从实体实算（`getRawValue()`），不是写死的。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from msgio import run_stage, ref_path, ref_data, exec_module            # noqa: E402
from lib.drawing_fc import DrawingBuilder, _y                           # noqa: E402

#: 视图名 → (投影方向, XDirection)。零件未在 VIEWS 里声明时的兜底约定。
_DIR_CONV = {
    "Top": ((0, 0, 1), None), "Front": ((0, -1, 0), None),
    "Right": ((1, 0, 0), (0, 1, 0)), "Left": ((-1, 0, 0), (0, 1, 0)),
    "Bottom": ((0, 0, -1), None), "Rear": ((0, 1, 0), None),
}


def _part_dir():
    return os.environ.get("MPIPE_HERE") or os.getcwd()


def _load_spec(part_dir):
    p = os.path.join(part_dir, "draw_spec.py")
    if not os.path.exists(p):
        raise SystemExit(
            "s2_drawing（共享 · 数据驱动）：零件 %s 既没有自带 steps/s2_drawing.py，"
            "也没有 draw_spec.py。\n  纯数据零件必须提供 draw_spec.py（视图/标注声明）。"
            % part_dir)
    return exec_module(p, "draw_spec")


def _load_anchors(part_dir):
    p = os.path.join(part_dir, "ir_anchors.json")
    if not os.path.exists(p):
        raise SystemExit(
            "s2_drawing（共享 · 数据驱动）：零件 %s 缺 ir_anchors.json（标注锚点）。\n"
            "  纯数据零件请用 tools/new_part.py 生成骨架后填锚点。" % part_dir)
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("anchors") or []


def _view_specs(spec):
    """VIEW_SPECS：VIEWS 声明优先，未声明则按视图名约定兜底；X/Y 取 PLACE。"""
    place = getattr(spec, "PLACE", {}) or {}
    declared = {v["name"]: v for v in (getattr(spec, "VIEWS", []) or [])}
    order = getattr(spec, "VIEW_ORDER", tuple(place.keys()))
    out = []
    for name in order:
        v = declared.get(name) or {}
        d, xd = _DIR_CONV.get(name, ((0, 0, 1), None))
        pl = place.get(name)
        if isinstance(pl, (list, tuple)):        # 项目约定：(x, y, flip)
            X, Y = float(pl[0]), float(pl[1])
        elif isinstance(pl, dict):
            X, Y = float(pl.get("x", 90.0)), float(pl.get("y", 60.0))
        else:
            X, Y = 90.0, 60.0
        spec_d = dict(name=name,
                      dir=tuple(v.get("dir", d)),
                      xdir=(tuple(v["xdir"]) if v.get("xdir") else xd),
                      X=X, Y=Y,
                      scale=float(v.get("scale", 2.0)))
        # 剖视图：透传类型与剖切参数（见 lib/drawing_fc.DrawingBuilder._make_section）
        if v.get("type"):
            spec_d["type"] = v["type"]
        for k in ("base", "symbol", "hatch"):
            if v.get(k) is not None:
                spec_d[k] = v[k]
        for k in ("normal", "origin", "section_dir"):
            if v.get(k) is not None:
                spec_d[k] = tuple(v[k])
        out.append(spec_d)
    return out


def _fallback_pos(view, i):
    """锚点未在 DIM_POS 声明时的兜底摆放（沿视图右上错开，避免重叠）。"""
    return (_y(view.X) + 40.0 + 12.0 * i, _y(view.Y) + 20.0 + 10.0 * i)


def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"),
                    os.path.basename(ref_path(in_msg, "params"))[:-3])
    STEP = ref_path(in_msg, "model_step")
    out_dir = ref_data(in_msg, "out_dir")
    TD = ref_data(in_msg, "template")
    part_dir = os.path.abspath(_part_dir())

    spec = _load_spec(part_dir)
    anchors = _load_anchors(part_dir)
    view_specs = _view_specs(spec)
    dim_pos = getattr(spec, "DIM_POS", {}) or {}

    b = DrawingBuilder(P.TAG, STEP, P.TAG, TD, view_specs)
    placed = 0
    for i, a in enumerate(anchors):
        label = a.get("label")
        pos = dim_pos.get(label)
        if pos:
            X, Y = float(pos[0]), float(pos[1])
        else:
            v = b.views.get(a.get("view"))
            X, Y = _fallback_pos(v, i) if v is not None else (0.0, 0.0)
        b.add_anchor_dim(a, X, Y)
        placed += 1

    b.finalize()
    jf, fc, data = b.export(out_dir, P.TAG)
    n_found = sum(1 for d in data["dims"] if d.get("found"))
    return [("drawing_json", jf), ("fcstd", fc)], {
        "views": [v["name"] for v in data["views"]],
        "n_edges": sum(len(v["edges"]) for v in data["views"]),
        "n_circles": sum(len(v["circles"]) for v in data["views"]),
        "n_dims": len(data["dims"]),
        "n_anchor_placed": placed,
        "n_anchor_found": n_found,
        "dim_values": {d["label"]: d["value"] for d in data["dims"]},
        "source": "draw_spec.py + ir_anchors.json（数据驱动）",
    }


#: ⚠️ freecadcmd 把 `__name__` 设成**模块名**（不是 `"__main__"`），
#: 所以 `if __name__ == "__main__"` 永不触发 —— 必须**模块级直接调用**。
run_stage("s2_drawing", handler)
