# -*- coding: utf-8 -*-
r"""tools/ir2partdesign.py —— IR（特征图）──▶ FreeCAD PartDesign 真特征树（D）
=====================================================================

C（`tools/ir2build.py`）把 IR 生成 **build123d 脚本**（几何引擎路线）。本工具把
同一份 IR 生成 **FreeCAD PartDesign 特征树**（按需物化的交互面路线）——即路线文档
的 **D** 阶段：`rect→Sketch / extrude→Pad·Pocket / fillet→Fillet`。

    python tools/ir2partdesign.py --part parts/lbracket \
        --out-script _pd/lbracket_pd.py --fcstd _pd/lbracket_pd.FCStd \
        --report _pd/lbracket_pd_report.json

产出**带真实特征树**（Sketch/Pad/Pocket + Spreadsheet 参数表）的 FCStd：可在 FreeCAD
GUI 里打开、改参数、重算——这正是 build123d+STEP 路线给不了的（那条路线 FCStd 里
只有死的 Part::Feature）。

**与 C 的分工**：C/D 同源，都读同一份 IR——C 验证「IR 能重生成几何」，D 验证「IR 能
物化成可交互的真特征树」。

**覆盖（最小版，按 lbracket 实测）**：加法→闭合草图+Pad；圆柱减法→⊥轴圆草图+Pocket
(ThroughAll)；Box 窗口→运行时以 IR 录制体积为 oracle 探测贯通轴→矩形草图+Pocket；
边处理未覆盖（诚实标注）。

**参数化**：建 `Spreadsheet`，Pad 长度 / 孔半径用 `setExpression` 绑单元格 → 改单元格
→ recompute → 实体跟着变（E 阶段的基础）。

隔离：算法层（tools/），不参与 mpipe/1 消息协议。只读 ir.json + params.py 生成文本；
几何交给 freecadcmd。
"""

import argparse
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- 参数 / 平面

def _load_params(part_dir):
    path = os.path.join(part_dir, "params.py")
    spec = importlib.util.spec_from_file_location("_ir2pd_params", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _resolver_ns(P):
    ns = {k: v for k, v in vars(P).items() if not k.startswith("_")}
    ns["P"] = P
    for full, half in (("BASE_W_Y", "hw"), ("WALL_W_Y", "wy")):
        if hasattr(P, full):
            ns[half] = getattr(P, full) / 2.0
    return ns


def _resolve_offset(expr, ns):
    try:
        return float(eval(expr, {"__builtins__": {}}, dict(ns)))
    except Exception as e:
        raise ValueError("无法解析平面 offset %r：%s" % (expr, e))


_PLANE_RE = re.compile(r"Plane\.(XY|YZ|XZ)")


def _plane_base_offset(plane_info, ns):
    raw = plane_info.get("plane") or "Plane.XY"
    m = _PLANE_RE.search(raw)
    base = m.group(1) if m else "XY"
    off = plane_info.get("offset")
    return base, (_resolve_offset(off, ns) if off else 0.0)


def _dedupe_ring(pts, eps=1e-7):
    """build123d Polygon 允许重复点/自动闭合；PartDesign LineSegment 不允许零长边。
    去连续重复点并保证首尾不重复。"""
    out = []
    for p in pts:
        p = [float(p[0]), float(p[1])]
        if out and abs(p[0] - out[-1][0]) < eps and abs(p[1] - out[-1][1]) < eps:
            continue
        out.append(p)
    while len(out) >= 2 and abs(out[0][0] - out[-1][0]) < eps and abs(out[0][1] - out[-1][1]) < eps:
        out.pop()
    return out


# ---------------------------------------------------------------- 构建计划

def build_plan(ir, params_ns):
    plan = []
    for f in ir.get("features", []):
        kind = (f.get("structural") or {}).get("kind")
        fid = f["id"]
        after = (f.get("_recorded") or {}).get("after")
        if kind == "加法":
            sketch_seg = extrude_params = None
            for seg in f.get("impl", []):
                if seg[0] == "sketch":
                    sketch_seg = seg[1]
                elif seg[0] in ("extrude", "loft", "revolve", "sweep"):
                    extrude_params = seg[1] or {}
            if sketch_seg is None or not extrude_params:
                plan.append({"op": "placeholder", "fid": fid, "why": "无草图/extrude 段"})
                continue
            base, off = _plane_base_offset(sketch_seg.get("plane") or {}, params_ns)
            pts = []
            for o in sketch_seg.get("ops", []):
                if o.get("op") == "sketch_polygon":
                    pts = o["params"].get("pts", [])
                elif o.get("op") == "sketch_line":
                    sp = o["params"].get("pts", [])
                    if sp and not pts:
                        pts = list(sp)
                    elif sp:
                        pts.append(sp[-1])
            ring = _dedupe_ring(pts)
            if len(ring) < 3:
                plan.append({"op": "placeholder", "fid": fid, "why": "草图点数不足"})
                continue
            plan.append({"op": "pad", "fid": fid, "base": base, "offset": off,
                         "pts": ring, "amount": extrude_params.get("amount"), "after": after})
        elif kind == "减法":
            tool_op = None
            for seg in f.get("impl", []):
                if seg[0] == "tool":
                    tool_op = seg[1]
            p = f.get("params", {})
            pos = (p.get("pos") or {}).get("args")
            args = p.get("args", [])
            rot = p.get("rotation")
            if tool_op == "tool_cylinder" and pos:
                axis = "X" if (rot and len(rot) == 3 and abs(rot[1] - 90) < 1e-6) else "Z"
                aidx = {"X": 0, "Y": 1, "Z": 2}[axis]
                plan.append({"op": "pocket_cyl", "fid": fid, "axis": axis, "axis_idx": aidx,
                             "center": list(pos), "r": args[0],
                             "h": (args[1] if len(args) > 1 else None), "after": after})
            elif tool_op == "tool_box" and pos:
                plan.append({"op": "pocket_box", "fid": fid, "center": list(pos),
                             "dims": list(args), "expected_vol": (after or {}).get("volume"),
                             "after": after})
            else:
                plan.append({"op": "placeholder", "fid": fid,
                             "why": "未支持的减法工具 %r" % tool_op})
        else:
            plan.append({"op": "placeholder", "fid": fid, "why": "%s 未覆盖" % kind})
    return plan


# ---------------------------------------------------------------- FreeCAD 模板

_FC_TEMPLATE = r'''# -*- coding: utf-8 -*-
# 由 tools/ir2partdesign.py 生成（D：IR → FreeCAD PartDesign 真特征树）
import FreeCAD as App
import Part, Sketcher, json, os, traceback

PLAN = json.loads(r"""__PLAN_JSON__""")
OUT_FCSTD = r"__OUT_FCSTD__"
OUT_JSON  = r"__OUT_JSON__"
report = {"steps": []}
V = App.Vector

def _dump():
    try:
        os.makedirs(os.path.dirname(os.path.abspath(OUT_JSON)), exist_ok=True)
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _plane_placement(base, offset):
    # build123d 平面(u,v,拉伸向) → FreeCAD 局部(X,Y,Z)
    if base == "YZ":
        return App.Placement(V(offset, 0, 0), App.Rotation(V(1, 1, 1), 120))
    if base == "XZ":
        return App.Placement(V(0, -offset, 0), App.Rotation(V(1, 0, 0), 90))
    return App.Placement(V(0, 0, offset), App.Rotation())

_AXIS_PLANE = {"Z": "XY_Plane", "X": "YZ_Plane", "Y": "XZ_Plane"}

def _close_ring(sk, pts):
    n = len(pts)
    for i in range(n):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % n]), False)
    for i in range(n):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % n, 1))

def _g2l(pl, x, y, z):
    return pl.inverse().multVec(V(x, y, z))

doc = App.newDocument("ir2pd")
body = doc.addObject("PartDesign::Body", "Body")
planes = {o.Role: o for o in body.Origin.OriginFeatures if hasattr(o, "Role")}
sheet = doc.addObject("Spreadsheet::Sheet", "Params")
sheet.set("A1", "fid"); sheet.set("B1", "param"); sheet.set("C1", "value")
_row = 1
def _put(fid, name, value):
    global _row
    _row += 1
    sheet.set("A%d" % _row, fid); sheet.set("B%d" % _row, name); sheet.set("C%d" % _row, repr(value))
    return "C%d" % _row

skn = 0
def _vol():
    try:
        return round(body.Shape.Volume, 3)
    except Exception:
        return None
def _valid():
    try:
        return bool(body.Shape.isValid())
    except Exception:
        return None

def do_pad(step):
    global skn
    skn += 1
    sk = doc.addObject("Sketcher::SketchObject", "S_%d" % skn)
    body.addObject(sk)
    sk.Placement = _plane_placement(step["base"], step["offset"])
    _close_ring(sk, [V(p[0], p[1], 0) for p in step["pts"]])
    sk_valid = None
    try:
        sk_valid = bool(sk.Shape.isValid())
    except Exception:
        pass
    pad = doc.addObject("PartDesign::Pad", "Pad_%s" % step["fid"])
    body.addObject(pad); pad.Profile = sk; pad.Length = float(step["amount"])
    try:
        pad.setExpression("Length", "Params.%s" % _put(step["fid"], "Length", float(step["amount"])))
    except Exception as e:
        report.setdefault("expr_errors", []).append("%s: %s" % (step["fid"], e))
    doc.recompute()
    report["steps"].append({"fid": step["fid"], "op": "pad", "sketch_valid": sk_valid,
                            "volume": _vol(), "valid": _valid()})

def do_pocket_cyl(step):
    global skn
    skn += 1
    axis = step["axis"]; plane = planes[_AXIS_PLANE[axis]]
    sk = doc.addObject("Sketcher::SketchObject", "S_%d" % skn)
    body.addObject(sk); sk.AttachmentSupport = [(plane, "")]; sk.MapMode = "FlatFace"
    c = list(step["center"])
    g = _g2l(plane.Placement, c[0], c[1], c[2]); g.z = 0.0
    r = float(step["r"])
    gi = sk.addGeometry(Part.Circle(g, V(0, 0, 1), r), False)
    ci = sk.addConstraint(Sketcher.Constraint("Radius", gi, r))
    try:
        sk.setExpression("Constraints[%d]" % ci, "Params.%s" % _put(step["fid"], "Radius", r))
    except Exception as e:
        report.setdefault("expr_errors", []).append("%s: %s" % (step["fid"], e))
    pk = doc.addObject("PartDesign::Pocket", "Pocket_%s" % step["fid"])
    body.addObject(pk); pk.Profile = sk
    # 原 build123d 用「有限高圆柱」(Pos(...,z) * Cylinder(r, h))，不是 ThroughAll。
    # 这里复刻其材料相关区间：从原点平面朝 +axis 切到圆柱顶 pos[axis]+h/2。
    # 若用 ThroughAll 会把三角筋等无关材料整条切穿（实测多切 2.0）。
    h = step.get("h")
    aidx = step.get("axis_idx", 2)
    if h:
        pk.Type = 0  # Length
        pk.Length = float(step["center"][aidx]) + float(h) / 2.0
    else:
        pk.Type = 1  # ThroughAll (fallback)
    pk.Reversed = True  # 朝材料方向切
    pk.Midplane = False
    doc.recompute()
    report["steps"].append({"fid": step["fid"], "op": "pocket_cyl", "axis": axis,
                            "volume": _vol(), "valid": _valid()})

def do_pocket_box(step):
    # 原脚本减的是「有界 Box」(各向有限)。ThroughAll 会把近端面与原点平面之间的
    # 其它材料(如三角筋)也切穿 → 必须把草图放在箱体近端面、用 Length 有界切。
    # 只试 X/Z 两个旋转干净的轴（Y 轴局部映射是镜像，暂不支持）；对 lbracket 窗口(穿X)够用。
    center = step["center"]; dims = step["dims"]; target = step.get("expected_vol")
    for ax in (0, 2):
        span = [i for i in range(3) if i != ax]
        near = list(center); near[ax] = center[ax] - dims[ax] / 2.0
        if ax == 0:
            pl = App.Placement(V(near[0], near[1], near[2]), App.Rotation(V(1, 1, 1), 120))
        else:
            pl = App.Placement(V(near[0], near[1], near[2]), App.Rotation())
        B, C = span
        hb, hc = dims[B] / 2.0, dims[C] / 2.0
        # origin 已把剖面中心放到箱体中心(B,C)与近端面(A)，故局部坐标以原点为中心，
        # 不能再加 (center[B], center[C]) —— 否则 B/C 重复计入（曾致 Z 被加两次）。
        pts = [V(-hb, -hc, 0), V(hb, -hc, 0), V(hb, hc, 0), V(-hb, hc, 0)]
        global skn
        skn += 1
        sk = doc.addObject("Sketcher::SketchObject", "S_%d" % skn)
        body.addObject(sk); sk.Placement = pl
        _close_ring(sk, pts)
        pk = doc.addObject("PartDesign::Pocket", "Pocket_%s" % step["fid"])
        body.addObject(pk); pk.Profile = sk
        pk.Type = 0; pk.Length = dims[ax]; pk.Reversed = True
        doc.recompute()
        vol = _vol()
        report.setdefault("box_attempts", []).append(
            {"fid": step["fid"], "axis": ax, "volume": vol, "target": target,
             "delta": (round(vol - target, 3) if (vol is not None and target is not None) else None),
             "valid": _valid()})
        if target is None or (vol is not None and abs(vol - target) < 0.5):
            report["steps"].append({"fid": step["fid"], "op": "pocket_box",
                                    "axis": ax, "volume": vol, "valid": _valid()})
            return
        doc.removeObject(pk.Name); doc.removeObject(sk.Name); skn -= 1
        doc.recompute()
    report["steps"].append({"fid": step["fid"], "op": "pocket_box", "ERROR": "no axis matched"})

HANDLERS = {"pad": do_pad, "pocket_cyl": do_pocket_cyl, "pocket_box": do_pocket_box}

for step in PLAN:
    op = step["op"]; fid = step.get("fid")
    if op == "placeholder":
        report["steps"].append({"fid": fid, "op": op, "why": step.get("why")})
        continue
    try:
        HANDLERS[op](step)
    except Exception:
        report["steps"].append({"fid": fid, "op": op,
                                "ERROR": traceback.format_exc()[-700:]})
    _dump()

try:
    doc.recompute()
    report["final_volume"] = _vol()
    report["solids"] = len(body.Shape.Solids)
    bb = body.Shape.BoundBox
    report["bbox"] = [round(bb.XLength, 3), round(bb.YLength, 3), round(bb.ZLength, 3)]
    report["feature_tree"] = [(o.Name, o.TypeId.split("::")[-1]) for o in body.Group]
    os.makedirs(os.path.dirname(os.path.abspath(OUT_FCSTD)), exist_ok=True)
    doc.saveAs(OUT_FCSTD)
    report["saved"] = OUT_FCSTD
except Exception:
    report["final_error"] = traceback.format_exc()[-700:]
_dump()
'''


def emit_script(plan, out_fcstd, out_json):
    return (_FC_TEMPLATE
            .replace("__PLAN_JSON__", json.dumps(plan, ensure_ascii=False))
            .replace("__OUT_FCSTD__", out_fcstd)
            .replace("__OUT_JSON__", out_json))


def main(argv=None):
    ap = argparse.ArgumentParser(description="IR → FreeCAD PartDesign 真特征树（D）")
    ap.add_argument("--part", required=True)
    ap.add_argument("--ir", default=None)
    ap.add_argument("--out-script", required=True)
    ap.add_argument("--fcstd", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args(argv)

    part_dir = os.path.abspath(a.part)
    ir_path = a.ir or os.path.join(part_dir, "ir.json")
    with open(ir_path, encoding="utf-8") as fh:
        ir = json.load(fh)
    ns = _resolver_ns(_load_params(part_dir))
    plan = build_plan(ir, ns)

    d = os.path.dirname(os.path.abspath(a.out_script))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(a.out_script, "w", encoding="utf-8") as fh:
        fh.write(emit_script(plan, a.fcstd, a.report))
    print("[ir2partdesign] %s（%d 步：%s）"
          % (a.out_script, len(plan), "/".join(s["op"] for s in plan)))
    return 0


if __name__ == "__main__":
    sys.exit(main())