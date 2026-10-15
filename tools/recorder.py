# -*- coding: utf-8 -*-
r"""tools/recorder.py —— build123d 脚本 ──[执行+录制]──▶ IR（特征树抽取）
=====================================================================

**为什么用"执行+录制"而不是静态 AST 解析**

技术架构设计 §4 决策 **D7** 已实测：AST 丢 5 类信息（17 步 vs 42 条），
**执行+录制全对**。运行时拿得到 AST 拿不到的东西：循环展开后的真实特征个数、
`Pos(...) * Cylinder(...)` 的实际位置、每个特征做完后的中间形状。

**为什么不能从 STEP 反推**

STEP 是 AP214 纯几何，无参数、无特征树、无历史（"照片"不是"活体"）；
从形状反推特征是几十年未解难题且语义不唯一。构造过程只在**代码执行过程**里。

**录制原理（三种注入点，全程可还原）**

1. **模块属性补丁**：在加载零件脚本**之前**，把 `build123d` 模块里的
   `extrude / fillet / Polygon / Cylinder / Box / Pos / BuildSketch / BuildPart`
   换成录制代理。脚本自己的 `from build123d import *` 会拿到代理版。
2. **builder 栈**：代理 `BuildPart` 时给实例的 `__enter__/__exit__` 打补丁压栈/弹栈，
   于是 `extrude` 代理能读到 `栈顶.part` —— 即**该特征做完时的中间形状**。
3. **布尔钩子**：`Compound.__sub__ / __add__` 是减/加运算的真正落点，
   包一层即可录到每次切割/融合，并直接快照**返回值**的形状。

跑完在 `finally` 里原样还原所有补丁，不影响同进程其它代码。

**录制器知道什么、不知道什么**

| 知道（自动） | 不知道（必须正向标注） |
|---|---|
| 特征顺序、操作、参数、中间形状、平面、位置 | **语义**（这是"安装孔"还是"销孔"） |
| 结构角色（加法/减法/边处理） | **3D↔2D 对应**（`drawing.anchors`） |

所以抽出来的 IR 里 `semantic` 为空、`drawing` 为 None，并打 `needs_semantic: true`
——这正是技术架构设计 §2.1 原则一"语义只能正向标注、不能逆向识别"的落地。

**用法**

    python tools/recorder.py --part parts/lbracket
    python tools/recorder.py --part parts/gasket --out parts/gasket/ir.json

隔离：本工具不属于任何流水线步骤（`tools/` 是算法层），只在被显式调用时运行；
它 import build123d 与零件脚本，但不参与 mpipe/1 消息协议，`guard.py` 不管。
"""

import argparse
import importlib.util
import inspect
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "lib"))

import ir as irlib                                        # noqa: E402


# ================================================================ 事件记录

class _Log(object):
    """全局事件日志 + builder 栈（录制期间有效）。"""

    def __init__(self):
        self.events = []          # [{"op":..,"params":{..},"after":{stats}|None}]
        self.pending_tools = []   # 已构造未应用的工具队列（FIFO）
        self._pending_pos = None  # 最近的 Pos(...) 参数，附着到下一个工具

    # ---- 记录 ----
    def ev(self, op, params=None, after=None, **kw):
        d = {"op": op}
        d.update(kw)
        if params:
            d["params"] = params
        if after:
            d["after"] = after
        self.events.append(d)
        return d

    def note_pos(self, x, y, z):
        self._pending_pos = (x, y, z)

    def take_pos(self):
        p = self._pending_pos
        self._pending_pos = None
        return p

    def cur_part_stats(self):
        """当前 BuildPart 的 part 统计（中间形状）。取不到返回 None。"""
        c = _ctx()
        part = getattr(c, "part", None)
        if part is None:
            return None
        try:
            return _stats(part)
        except Exception:
            return None

    def cur_plane(self):
        """当前 BuildSketch 的草图平面（哪个面 = 哪个轴向）。

        直接用真实 `BuildSketch._get_context()` 取，**不替换 build123d.BuildSketch**
        （实测替换会破坏 BuildLine 退出→make_face 的边传递）。
        """
        cls = _REAL.get("BuildSketch")
        if cls is None:
            return None
        try:
            sk = cls._get_context()
        except Exception:
            return None
        pl = getattr(sk, "plane", None)
        return None if pl is None else _plain_plane(pl)


_LOG = None
_REAL = {}          # 保存的真实类（只取用、不打补丁）


def _ctx():
    """当前 build123d builder（BuildSketch 或 BuildPart），取不到返回 None。

    用官方 `Builder._get_context()`（只读、无副作用）。**不要**用工厂函数替换
    `build123d.BuildPart`——实测那样会破坏 BuildSketch 退出时向 BuildPart 传递
    pending_faces，导致后续 extrude 报 "A face or sketch must be provided"。
    """
    try:
        from build123d.build_common import Builder
        return Builder._get_context()
    except Exception:
        return None


def _stats(shape):
    """形状统计：bbox 尺寸 + 体积 + 面数 + 实体数（中间形状的"指纹"）。"""
    try:
        bb = shape.bounding_box()
        return {
            "bbox": [round(bb.max.X - bb.min.X, 3),
                     round(bb.max.Y - bb.min.Y, 3),
                     round(bb.max.Z - bb.min.Z, 3)],
            "volume": round(float(shape.volume), 3),
            "faces": len(shape.faces()),
            "solids": len(shape.solids()),
        }
    except Exception:
        return None


def _plain(v, depth=0):
    """把参数转成可 JSON 化的（Vector/Location/Plane → 简明 dict）。"""
    if depth > 3:
        return "..."
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_plain(x, depth + 1) for x in v]
    for attrs in (("X", "Y", "Z"), ("x", "y", "z")):
        if all(hasattr(v, a) for a in attrs):
            try:
                return [round(float(getattr(v, a)), 4) for a in attrs]
            except Exception:
                pass
    if hasattr(v, "radius") and hasattr(v, "height"):
        try:
            return {"r": round(float(v.radius), 4), "h": round(float(v.height), 4)}
        except Exception:
            pass
    cn = type(v).__name__
    if cn in ("Plane", "Location", "Vector", "Axis", "Circle", "Cylinder", "Box"):
        return {"_type": cn}
    return {"_type": cn}


def _kwargs_params(fn, args, kwargs, var_name=None):
    """把 (args, kwargs) 按函数签名归一到具名参数字典。

    特别处理**变长位置参数**（`*pts`）：脚本里 `Polygon(*pts, align=None)` 的
    点列会全部收进该名下，而不是错落成 args/kwargs。
    `var_name` 可覆盖默认名（build123d 很多 op 的 `__init__` 是 slot wrapper，
    签名就是 `(*args, **kwargs)`，此时默认名 "args" 无意义，调用方传 "pts"）。
    """
    import inspect
    try:
        sig = inspect.signature(fn)
    except Exception:
        # 类（如 Polygon/Cylinder）的 signature 可能取不到 → 退回 __init__
        try:
            sig = inspect.signature(getattr(fn, "__init__", fn))
        except Exception:
            return {"args": [_plain(a) for a in args],
                    "kwargs": {k: _plain(v) for k, v in kwargs.items()}}
    try:
        out = {}
        varp = None
        idx = 0
        for name, prm in sig.parameters.items():
            if prm.kind is inspect.Parameter.VAR_POSITIONAL:
                varp = name
                continue
            if prm.kind is inspect.Parameter.VAR_KEYWORD:
                continue
            if name == "self":
                continue
            if idx < len(args):
                out[name] = _plain(args[idx])
                idx += 1
        if varp is not None:
            key = var_name or varp
            out[key] = [_plain(a) for a in args[idx:]]
        for k, v in kwargs.items():
            out[k] = _plain(v)
        return out
    except Exception:
        return {"args": [_plain(a) for a in args],
                "kwargs": {k: _plain(v) for k, v in kwargs.items()}}


# ================================================================ 补丁

#: 需要包一层的模块级函数/类：名字 → 录制出的 op 名
_WRAP_FUNCS = {
    "extrude": "extrude",
    "loft": "loft",
    "revolve": "revolve",
    "sweep": "sweep",
    "fillet": "fillet",
    "chamfer": "chamfer",
    "Polygon": "sketch_polygon",
    "Rectangle": "sketch_rect",
    "Circle": "sketch_circle",
    "Line": "sketch_line",
    "Cylinder": "tool_cylinder",
    "Box": "tool_box",
    "Sphere": "tool_sphere",
    "Cone": "tool_cone",
    "Torus": "tool_torus",
}

#: 这些 op 做完后要快照"中间形状"
_SNAPSHOT_OPS = {"extrude", "loft", "revolve", "sweep", "fillet", "chamfer"}


def _make_func_wrapper(name, op, real):
    def w(*args, **kwargs):
        res = real(*args, **kwargs)
        params = _kwargs_params(real, args, kwargs,
                                var_name="pts" if op.startswith("sketch_") else None)
        extra = {}
        if op in _SNAPSHOT_OPS:
            extra["after"] = _LOG.cur_part_stats()
        elif op.startswith("sketch_"):
            extra["plane"] = _plane_from_result(res)
        elif op.startswith("tool_") and _LOG._pending_pos is not None:
            # Pos(...) * Cylinder(...)：Pos 先求值，此刻把位置并进工具参数
            params["pos"] = _LOG.take_pos()
        _LOG.ev(op, params=params, **extra)
        return res
    w.__name__ = getattr(real, "__name__", name)
    w.__doc__ = getattr(real, "__doc__", None)
    return w


def _wrap_pos(real):
    def w(*args, **kwargs):
        loc = real(*args, **kwargs)
        p = _kwargs_params(real, args, kwargs)
        _LOG.ev("pos", params=p)
        _LOG._pending_pos = p          # 挂到下一个工具（Pos(...) * Cylinder(...) 里 Pos 先求值）
        return loc
    w.__name__ = real.__name__
    return w


def _plain_plane(v):
    """把 Plane 参数转成 {origin, z_dir}（哪个面 = 哪个轴向，抽特征必须知道）。"""
    try:
        o = getattr(v, "origin", None)
        z = getattr(v, "z_dir", None)
        if o is None or z is None:
            return {"_type": type(v).__name__}
        return {"origin": [round(float(o.X), 4), round(float(o.Y), 4), round(float(o.Z), 4)],
                "z_dir": [round(float(z.X), 4), round(float(z.Y), 4), round(float(z.Z), 4)]}
    except Exception:
        return {"_type": type(v).__name__}


def _plane_from_result(res):
    """从草图 op 的**返回值几何**推所在平面（法向 + 原点）。

    比"取当前 BuildSketch"可靠：`BuildSketch._get_context()` 在 BuildSketch 块内
    可能返回的是外层 BuildPart（拿不到 plane）；而 op 造出来的对象自带法向。
    """
    try:
        c = res.center()
        n = res.normal_at(c)
        return {"origin": [round(float(c.x), 4), round(float(c.y), 4), round(float(c.z), 4)],
                "z_dir": [round(float(n.X), 4), round(float(n.Y), 4), round(float(n.Z), 4)]}
    except Exception:
        return None


def _wrap_boolop(real, op):
    def w(self, other):
        res = real(self, other)
        params = {"tool": _plain(type(other).__name__)}
        _LOG.ev(op, params=params, after=_stats(res))
        return res
    w.__name__ = "__%s__" % op
    return w


def _patch():
    """打补丁，返回 (原属性dict, 原布尔方法dict)。"""
    import build123d
    from build123d.topology.composite import Compound

    saved_funcs = {}
    _REAL["BuildSketch"] = getattr(build123d, "BuildSketch", None)   # 只取用，不打补丁
    for name, op in _WRAP_FUNCS.items():
        if hasattr(build123d, name):
            saved_funcs[name] = getattr(build123d, name)
            setattr(build123d, name, _make_func_wrapper(name, op, saved_funcs[name]))

    if hasattr(build123d, "Pos"):
        saved_funcs["Pos"] = build123d.Pos
        build123d.Pos = _wrap_pos(build123d.Pos)

    saved_bool = {
        ("__sub__",): Compound.__sub__,
    }
    Compound.__sub__ = _wrap_boolop(Compound.__sub__, "cut")
    saved_bool[("__add__",)] = Compound.__add__
    Compound.__add__ = _wrap_boolop(Compound.__add__, "fuse")
    return saved_funcs, saved_bool


def _unpatch(saved_funcs, saved_bool):
    import build123d
    from build123d.topology.composite import Compound
    for name, real in saved_funcs.items():
        setattr(build123d, name, real)
    Compound.__sub__ = saved_bool[("__sub__",)]
    Compound.__add__ = saved_bool[("__add__",)]


# ================================================================ 事件 → IR

#: 草图类 op（属于同一个 Sketch 特征）
_SKETCH_OPS = {"sketch_polygon", "sketch_rect", "sketch_circle", "sketch_line",
               "sketch_begin", "sketch_end"}

#: op → (structural.kind, tree op)
_ROLE = {
    "extrude": ("加法", "Pad"),
    "loft": ("加法", "Pad"),
    "revolve": ("加法", "Pad"),
    "sweep": ("加法", "Pad"),
    "fillet": ("边处理", "Fillet"),
    "chamfer": ("边处理", "Chamfer"),
    "cut": ("减法", "Pocket"),
    "fuse": ("加法", "Pad"),
}


def events_to_ir(events, part_name, plane_hints=None, source=None):
    """把事件流分组成 IR 特征表。

    分组规则（启发式，但确定）：
      * 连续的草图 op + 紧随的 extrude/loft/revolve/sweep = **一个加法特征**
      * fillet/chamfer = **一个边处理特征**
      * 布尔 cut（带前面最近的 pos + tool）= **一个减法特征**
      * 布尔 fuse = 一个加法特征

    `plane_hints`：从源码静态扫出的 `BuildSketch(Plane...)` 表达式列表，按组序
    对齐到各草图。**这是 hint 不是运行时实测**——BuildSketch 一点都不能打补丁
    （实测替换类或改 __init__ 都会破坏 BuildLine 退出→make_face 的边传递），
    所以平面只能这样拿；带 `.offset(expr)` 的只记原始表达式，分辨率留给后续。
    """
    plane_hints = list(plane_hints or [])
    feats = []
    n = 0
    i = 0
    pending_sketch = []
    pending_plane = None
    pending_tools = []          # FIFO：脚本常"先构造全部工具，再统一切割"

    def newfid():
        nonlocal n
        n += 1
        return "F%d" % n

    def next_plane_hint():
        return plane_hints.pop(0) if plane_hints else None

    while i < len(events):
        e = events[i]
        op = e.get("op")

        if op in _SKETCH_OPS:
            if op not in ("sketch_begin", "sketch_end"):
                if not pending_sketch:            # 新草图组开始 → 取下一个平面 hint
                    pending_plane = next_plane_hint()
                pending_sketch.append(e)
                if pending_plane is None and e.get("plane"):
                    pending_plane = e["plane"]
            i += 1
            continue

        if op == "pos":
            i += 1                      # 位置已并入工具参数，跳过
            continue

        if op.startswith("tool_"):
            pending_tools.append(e)
            i += 1
            continue

        if op in ("extrude", "loft", "revolve", "sweep", "fillet", "chamfer"):
            kind, treeop = _ROLE[op]
            fid = newfid()
            impl = [("sketch", _sketch_summary(pending_sketch, pending_plane))]
            impl.append((op, e.get("params", {})))
            feats.append(irlib.new_feature(
                fid,
                semantic={"type": None, "role": kind},
                structural={"kind": kind, "target": feats[0]["id"] if feats else None},
                params=e.get("params", {}),
                impl=impl,
                tree=[("Sketch", None), (treeop, _tree_param(op, e.get("params", {})))],
                deps=[feats[0]["id"]] if feats else [],
                note=None,
            ))
            feats[-1]["_recorded"] = {"after": e.get("after")}
            pending_sketch = []
            pending_plane = None
            i += 1
            continue

        if op in ("cut", "fuse"):
            kind, treeop = _ROLE[op]
            fid = newfid()
            tool = pending_tools.pop(0) if pending_tools else {}
            params = dict(tool.get("params", {}))
            feats.append(irlib.new_feature(
                fid,
                semantic={"type": None, "role": kind},
                structural={"kind": kind, "target": feats[0]["id"] if feats else None},
                params=params,
                impl=[("tool", tool.get("op")), (op, None)],
                tree=[("Sketch", None), (treeop, "through" if op == "cut" else None)],
                deps=[feats[0]["id"]] if feats else [],
            ))
            feats[-1]["_recorded"] = {"after": e.get("after")}
            i += 1
            continue

        if op == "buildpart_end":
            i += 1
            continue

        # 未识别 op：原样留一条，避免静默丢信息
        feats.append(irlib.new_feature(
            newfid(),
            semantic={"type": None, "role": None},
            structural={"kind": None, "target": None},
            params=e.get("params", {}),
            impl=[(op, e.get("params", {}))],
            tree=[("Placeholder", None)],
            note="录制器未识别的 op，待人工归类",
        ))
        i += 1

    # 语义必须正向标注：录制不出来，显式标记
    for f in feats:
        f["needs_semantic"] = True
        if f.get("semantic", {}).get("type") is None:
            f["semantic"]["type"] = None

    R = irlib.new_part_ir(part_name, features=feats, source=source or {})
    R["recorded_events"] = len(events)
    R["_events"] = events          # 原始事件流也留着，便于复查/重新分组
    return R


def _sketch_summary(sk_events, plane=None):
    if not sk_events and plane is None:
        return None
    return {"plane": plane,
            "ops": [{"op": e["op"], "params": e.get("params", {})} for e in sk_events]}


def _tree_param(op, params):
    if op in ("extrude", "loft", "revolve", "sweep"):
        return params.get("amount")
    if op in ("fillet", "chamfer"):
        return params.get("radius")
    return None


# ================================================================ 驱动

def _load_script_module(path):
    """加载零件 s1_build.py 为模块，但不跑它的 __main__ 块。"""
    name = "_rec_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_in_msg(part_dir):
    """合成一份 s1_build 的入参消息（照 _msg/s1_build.in.json 的结构）。"""
    import hashlib
    params = os.path.join(part_dir, "params.py")
    with open(params, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    out_dir = os.path.join(tempfile.gettempdir(), "_ir_record_out")
    os.makedirs(out_dir, exist_ok=True)
    return {
        "protocol": "mpipe/1", "stage": "s1_build", "seq": 1, "status": "request",
        "in": {
            "refs": [{"role": "params", "path": os.path.abspath(params),
                      "sha256": h, "bytes": os.path.getsize(params)}],
            "data": {"out_dir": out_dir},
        },
        "out": {"refs": [], "data": {}}, "error": None,
    }


def _scan_sketch_planes(script_path):
    """静态扫源码里的 `BuildSketch(Plane...)`，按出现顺序返回平面表达式列表。

    为什么用静态扫：运行时拿不到（BuildSketch 打任何补丁都会破坏
    BuildLine→make_face，实测过）。返回形如：
        [{"plane": "Plane.XY", "offset": None},
         {"plane": "Plane.YZ", "offset": "-hw"}]
    `offset` 是**原始表达式文本**（如 "-hw"），分辨率需要 params —— 留给后续，
    这里如实标记 `resolved: false`，不猜。
    """
    import re
    try:
        src = open(script_path, encoding="utf-8").read()
    except Exception:
        return []
    out = []
    pat = re.compile(r"BuildSketch\(\s*(Plane\.[A-Za-z_]+(?:\s*\.\s*offset\(([^()]*)\))?)")
    for m in pat.finditer(src):
        out.append({"plane": m.group(1), "offset": m.group(2), "resolved": False})
    return out


def record_part(part_dir, out_path=None, verbose=True):
    """录制一个零件，返回 IR dict。"""
    global _LOG
    part_dir = os.path.abspath(part_dir)
    script = os.path.join(part_dir, "steps", "s1_build.py")
    if not os.path.exists(script):
        raise FileNotFoundError("找不到 %s" % script)

    _LOG = _Log()
    saved = _patch()
    try:
        mod = _load_script_module(script)
        if not hasattr(mod, "handler"):
            raise AttributeError("%s 没有 handler()，不是标准 s1_build" % script)
        msg = _build_in_msg(part_dir)
        res = mod.handler(msg)
    finally:
        _unpatch(*saved)

    events = _LOG.events
    part_name = os.path.basename(part_dir.rstrip("/\\"))
    R = events_to_ir(events, part_name,
                     plane_hints=_scan_sketch_planes(script),
                     source={"from": "build123d 执行+录制",
                             "script": os.path.relpath(script, ROOT),
                             "tool": "tools/recorder.py"})

    probs = irlib.validate(R)
    R["validate_problems"] = probs

    if out_path:
        irlib.dump(R, out_path)
    if verbose:
        print("[recorder] 零件 %s：录到 %d 个事件 → %d 个特征"
              % (part_name, len(events), len(R["features"])))
        for f in R["features"]:
            kind = (f.get("structural") or {}).get("kind")
            aft = (f.get("_recorded") or {}).get("after") or {}
            v = aft.get("volume")
            impl = ",".join(str(x[0]) for x in (f.get("impl") or []))
            print("   %-4s %-6s impl=%-30s volume=%s"
                  % (f["id"], kind, impl, ("%.1f" % v) if v is not None else "-"))
        if probs:
            print("[recorder] ⚠️ IR 校验问题 %d 条：" % len(probs))
            for x in probs:
                print("   -", x)
        else:
            print("[recorder] IR 校验通过")
    return R


def main(argv=None):
    ap = argparse.ArgumentParser(description="build123d 脚本 → IR（执行+录制）")
    ap.add_argument("--part", required=True, help="零件目录，如 parts/lbracket")
    ap.add_argument("--out", default=None, help="输出 ir.json 路径（默认 <part>/ir.json）")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(a.part, "ir.json")
    R = record_part(a.part, out_path=out)
    print("[recorder] 已写出 %s" % out)
    return 0 if not R.get("validate_problems") else 1


if __name__ == "__main__":
    sys.exit(main())
