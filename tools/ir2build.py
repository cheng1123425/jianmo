# -*- coding: utf-8 -*-
r"""tools/ir2build.py —— IR（特征图）──▶ build123d 脚本（C：单向代码生成）
=====================================================================

这是 IR 路线的 **C 阶段**：把 `lib/ir.py` 的特征图**反向生成**成可运行的
build123d 脚本。配合 `tools/recorder.py`（script→IR）就打通了「IR 为唯一真值源」
的往返：录得进、也生得出。

    python tools/ir2build.py --part parts/lbracket --out /tmp/lbracket_gen.py

**与 recorder 的关系**：recorder 把 `script → IR`（执行+录制）；本工具把
`IR → script`（遍历特征图生成代码）。两者合起来验证「改 IR 一处 → 全链路跟着变」。

**覆盖范围（最小版，按 lbracket 实测用到的构造）**
  - 加法特征：`BuildSketch(<plane>) + Polygon(...) + extrude(amount)`，
    以及 `BuildSketch(<plane>) + BuildLine{Line...} + make_face() + extrude`
  - 减法特征：`part = part - Pos(...) * Cylinder(...)` / `Pos(...) * Box(...)`
  - 边处理（Fillet/Chamfer）：**本版不生成**，打 PLACEHOLDER 注释（诚实，不硬造）

**平面 offset 解析**：IR 里草图平面只存了表达式（`resolved:false`，如
`Plane.YZ.offset(P.WALL_C_X)` / `Plane.XZ.offset(-wy)`）。本工具用
`params.py` 的 `P.*` + 常见派生半宽（hw=BASE_W_Y/2, wy=WALL_W_Y/2）求值。
解析不了的 offset 会**报错退出**，绝不猜（与 recorder 的 resolved:false 一致）。

**已知限制（最小版，非缺陷）**：
  1. 假设所有「加法」特征连续出现在「减法」之前（lbracket 成立；交错未处理）。
  2. 只认 recorder 记过的 op 词表；新 op 落 Placeholder。
  3. params 是求值后的数值，生成的脚本是**全数值**版（非 P.BASE_H 具名）——
     数值可精确复现几何；「人可读参数名」的 linkage 仍靠 params.py（见路线文档缺口③）。

隔离：本工具是算法层（`tools/`），不参与 mpipe/1 消息协议，`guard.py` 不管。
它读零件 ir.json + params.py，纯生成文本，无几何副作用。
"""

import argparse
import importlib.util
import json
import os
import re
import sys


# ---------------------------------------------------------------- 参数解析

def _load_params(part_dir):
    path = os.path.join(part_dir, "params.py")
    if not os.path.exists(path):
        raise FileNotFoundError("找不到 %s" % path)
    spec = importlib.util.spec_from_file_location("_ir2b_params", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolver_ns(P):
    """求值平面 offset 表达式用的命名空间：params 全量 + 常见派生半宽。

    offset 表达式可能写成 `P.WALL_C_X`（带模块前缀）或裸派生名 `-wy`，
    所以同时提供：① 模块对象 `P`；② params 全部属性（裸名）；③ 派生半宽。
    """
    ns = {k: v for k, v in vars(P).items() if not k.startswith("_")}
    ns["P"] = P
    for full, half in (("BASE_W_Y", "hw"), ("WALL_W_Y", "wy")):
        if hasattr(P, full):
            ns[half] = getattr(P, full) / 2.0
    return ns


def _resolve_offset(expr, ns):
    """把 'P.WALL_C_X' / '-wy' 之类的 offset 表达式求成数。失败即抛错（不猜）。"""
    try:
        val = eval(expr, {"__builtins__": {}}, dict(ns))
    except Exception as e:
        raise ValueError("无法解析平面 offset 表达式 %r：%s"
                         % (expr, e))
    if not isinstance(val, (int, float)):
        raise ValueError("平面 offset 表达式 %r 求值不是数：%r" % (expr, val))
    return float(val)


# ---------------------------------------------------------------- 数值格式化

def _num(v):
    """float 用最短往返表示，保留录制全精度。"""
    if isinstance(v, bool):
        return repr(v)
    if isinstance(v, int):
        return repr(v)
    f = float(v)
    if f == int(f) and abs(f) < 1e15:
        return "%d.0" % int(f)
    return repr(f)


def _pt(p):
    return "(%s, %s)" % (_num(p[0]), _num(p[1]))


# ---------------------------------------------------------------- 代码生成

_PLANE_RE = re.compile(r"(Plane\.[A-Za-z]+)")


def _plane_expr(plane_info, ns):
    """plane_info={'plane':'Plane.YZ.offset(P.WALL_C_X)','offset':'P.WALL_C_X',...}
    → 'Plane.YZ.offset(48.0)' 或 'Plane.XY'。"""
    raw = plane_info.get("plane") or "Plane.XY"
    m = _PLANE_RE.search(raw)
    if not m:
        raise ValueError("无法识别的平面表达式：%r" % raw)
    base = m.group(1)
    off = plane_info.get("offset")
    if off:
        return "%s.offset(%s)" % (base, _num(_resolve_offset(off, ns)))
    return base


def _emit_sketch_ops(ops, indent):
    """把一组草图 op 生成 build123d 代码行。返回 (lines, needs_buildline)。"""
    pad = " " * indent
    lines = []
    line_ops = [o for o in ops if o.get("op") == "sketch_line"]
    poly_ops = [o for o in ops if o.get("op") == "sketch_polygon"]
    other = [o for o in ops if o.get("op") not in ("sketch_line", "sketch_polygon")]

    for o in poly_ops:
        p = o.get("params", {})
        pts = ", ".join(_pt(q) for q in p.get("pts", []))
        align = p.get("align", None)
        lines.append("%sPolygon(%s, align=%s)" % (pad, pts, repr(align)))

    if line_ops:
        lines.append("%swith BuildLine() as ln:" % pad)
        for o in line_ops:
            q = o.get("params", {}).get("pts", [])
            if len(q) != 2:
                raise ValueError("sketch_line 期望 2 点，得到 %r" % (q,))
            lines.append("%s    Line(%s, %s)" % (pad, _pt(q[0]), _pt(q[1])))
        lines.append("%smake_face()" % pad)

    for o in other:
        lines.append("%s# PLACEHOLDER: 未支持的草图 op %r" % (pad, o.get("op")))

    if not lines:
        lines.append("%spass  # 空草图" % pad)
    return lines


def _emit_tool(params):
    """减法工具：params={args:[...], rotation?:[...], pos:{args:[x,y,z]}}"""
    pos = (params.get("pos") or {}).get("args")
    args = params.get("args", [])
    rot = params.get("rotation")
    # impl 里记的是 tool op 名（tool_cylinder / tool_box），由调用方给出
    return pos, args, rot


def generate(ir, part_name, params_ns):
    """遍历特征图 → 生成 build123d 脚本文本。"""
    feats = ir.get("features", [])
    lines = []
    lines.append("# -*- coding: utf-8 -*-")
    lines.append('r"""%s —— 由 tools/ir2build.py 从 ir.json 自动生成，请勿手改。' % part_name)
    lines.append("")
    lines.append("C 阶段产物：IR（唯一真值源）→ build123d 脚本（全数值版）。")
    lines.append("往返自测：本脚本重跑的几何应与 recorder 录制的体积/外接一致。")
    lines.append('"""')
    lines.append("import os")
    lines.append("import sys")
    lines.append("from build123d import *  # noqa: F401,F403")
    lines.append("")
    lines.append("OUT_STEP = os.environ.get('IR2B_STEP', os.path.join(")
    lines.append("    os.path.dirname(os.path.abspath(__file__)), '%s_regen.step'))" % part_name)
    lines.append("")

    # 分桶：加法进 BuildPart，减法在块外做布尔
    adds = [f for f in feats if (f.get("structural") or {}).get("kind") == "加法"]
    cuts = [f for f in feats if (f.get("structural") or {}).get("kind") == "减法"]
    edges = [f for f in feats if (f.get("structural") or {}).get("kind") == "边处理"]
    # 交错检测：减法不应夹在加法中间
    kinds = [(f.get("structural") or {}).get("kind") for f in feats]
    if "减法" in kinds and "加法" in kinds:
        first_cut = kinds.index("减法")
        if "加法" in kinds[first_cut:]:
            lines.append("# WARNING: 加法/减法特征交错，本最小版未处理，结果可能不符。")

    # ---- BuildPart：加法 ----
    lines.append("with BuildPart() as bp:")
    if not adds:
        lines.append("    pass")
    for f in adds:
        fid = f["id"]
        impl = f.get("impl", [])
        # 找 sketch 段与 extrude 段
        sketch_seg = None
        extrude_params = None
        for seg in impl:
            if seg[0] == "sketch":
                sketch_seg = seg[1]
            elif seg[0] in ("extrude", "loft", "revolve", "sweep"):
                extrude_params = seg[1] or {}
        if sketch_seg is None:
            lines.append("    # PLACEHOLDER: %s 无草图段" % fid)
            continue
        plane = _plane_expr(sketch_seg.get("plane") or {}, params_ns)
        lines.append("    with BuildSketch(%s) as sk_%s:" % (plane, fid))
        lines.extend(_emit_sketch_ops(sketch_seg.get("ops", []), indent=8))
        amt = (extrude_params or {}).get("amount")
        if amt is None:
            lines.append("    # PLACEHOLDER: %s 缺 extrude amount" % fid)
        else:
            lines.append("    extrude(amount=%s)" % _num(amt))

    lines.append("")
    lines.append("part = bp.part")

    # ---- 减法：part = part - Pos(...) * tool ----
    for f in cuts:
        fid = f["id"]
        impl = f.get("impl", [])
        tool_op = None
        for seg in impl:
            if seg[0] == "tool":
                tool_op = seg[1]
        params = f.get("params", {})
        pos, args, rot = _emit_tool(params)
        cls = {"tool_cylinder": "Cylinder", "tool_box": "Box",
               "tool_sphere": "Sphere", "tool_cone": "Cone",
               "tool_torus": "Torus"}.get(tool_op)
        if cls is None or pos is None:
            lines.append("# PLACEHOLDER: %s 未支持的减法工具 %r" % (fid, tool_op))
            continue
        arg_s = ", ".join(_num(a) for a in args)
        if rot:
            tool = "%s(%s, rotation=(%s))" % (cls, arg_s,
                                              ", ".join(str(int(x)) for x in rot))
        else:
            tool = "%s(%s)" % (cls, arg_s)
        pos_s = ", ".join(_num(x) for x in pos)
        lines.append("part = part - Pos(%s) * %s" % (pos_s, tool))

    # ---- 边处理：本版不生成 ----
    for f in edges:
        lines.append("# PLACEHOLDER: %s 边处理（Fillet/Chamfer）本最小版未生成"
                     % f["id"])

    # ---- 输出 + 统计 ----
    lines.append("")
    lines.append("os.makedirs(os.path.dirname(os.path.abspath(OUT_STEP)), exist_ok=True)")
    lines.append("export_step(part, OUT_STEP)")
    lines.append("_bb = part.bounding_box()")
    lines.append("_stats = {")
    lines.append("    'volume': round(part.volume, 3),")
    lines.append("    'bbox': [round(_bb.max.X - _bb.min.X, 3),")
    lines.append("              round(_bb.max.Y - _bb.min.Y, 3),")
    lines.append("              round(_bb.max.Z - _bb.min.Z, 3)],")
    lines.append("    'solids': len(part.solids()),")
    lines.append("}")
    lines.append("print('IR2B_STATS ' + __import__('json').dumps(_stats))")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="IR（特征图）→ build123d 脚本")
    ap.add_argument("--part", required=True, help="零件目录，如 parts/lbracket")
    ap.add_argument("--ir", default=None, help="ir.json 路径（默认 <part>/ir.json）")
    ap.add_argument("--out", required=True, help="输出 .py 脚本路径")
    a = ap.parse_args(argv)

    part_dir = os.path.abspath(a.part)
    ir_path = a.ir or os.path.join(part_dir, "ir.json")
    with open(ir_path, encoding="utf-8") as fh:
        ir = json.load(fh)
    part_name = os.path.basename(part_dir.rstrip("/\\"))
    P = _load_params(part_dir)
    ns = _resolver_ns(P)

    code = generate(ir, part_name, ns)
    d = os.path.dirname(os.path.abspath(a.out))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(code)
    print("[ir2build] 已生成 %s（%d 特征）" % (a.out, len(ir.get("features", []))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
