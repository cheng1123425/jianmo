# -*- coding: utf-8 -*-
r"""转化算子库（独立于项目主干，供"挖掘→转化"实验用）。

把 Zero-to-CAD 样本里高频出现的建模惯用法，转成【数据化算子】：
    数据(dict) → build123d 实现 → 实体

挖掘来源（430 样本切片，覆盖率见 验证报告/z2c_mined/op_candidates.md）：
    hole_grid    ← pushPoints+hole（矩形布孔，样本 483390ae）
    bolt_circle  ← pushPoints+hole（圆周布孔=螺栓圆，样本 f329590d）
    cbore_hole   ← pushPoints+cboreHole（沉头孔，样本 13d78484）
    fillet       ← edges(..).filter(..).fillet(..)（选择性圆角，样本 483390ae）
    chamfer      ← edges("<<Z").chamfer(..)（选择性倒角，样本 483390ae）

纪律（与项目 IR 一致）：
  * 算子只吃【数据】，不写死零件特性；
  * 选边用【几何谓词】(轴 + 标高区间)，不存 Edge#N（躲 TNP 拓扑命名问题）；
  * 参数用【具名】，数值由调用方给。

用法：须在 `with BuildPart() as bp:` 上下文内调用 `op_xxx(bp, op)`；
      Hole/fillet/chamfer 隐式作用于当前上下文。
"""
import math
from build123d import (Locations, Pos, Axis, Hole, CounterBoreHole, CounterSinkHole,
                       fillet, chamfer, offset, extrude, add, loft, sweep, mirror,
                       Mode, BuildPart, BuildSketch, BuildLine, Plane, Polyline,
                       Rectangle, Circle, Cone)


def op_hole_grid(bp, op):
    """矩形阵列布孔。op = {at:[[x,y]...], d, z?}。at 由上游从 n/pitch/clearance 算好。"""
    z = op.get("z", 0.0)
    for (x, y) in op["at"]:
        with Locations(Pos(x, y, z)):
            Hole(radius=op["d"] / 2.0)


def op_bolt_circle(bp, op):
    """圆周阵列布孔（螺栓圆/法兰孔）。op = {n, d, bcd_r, phase?, z?}。"""
    n, r = op["n"], op["bcd_r"]
    phase, z = op.get("phase", 0.0), op.get("z", 0.0)
    for i in range(n):
        a = phase + 2.0 * math.pi * i / n
        with Locations(Pos(r * math.cos(a), r * math.sin(a), z)):
            Hole(radius=op["d"] / 2.0)


def op_cbore_hole(bp, op):
    """面上若干点钻沉头孔。op = {at:[[x,y]...], d, cbore_d, cbore_depth, z?}。"""
    d, cd, cdep = op["d"], op["cbore_d"], op["cbore_depth"]
    z = op.get("z", 0.0)
    for (x, y) in op["at"]:
        with Locations(Pos(x, y, z)):
            CounterBoreHole(radius=d / 2.0, counter_bore_radius=cd / 2.0,
                            counter_bore_depth=cdep)


def _select_edges(bp, op):
    """按【几何谓词】选边（两个独立轴，避免"方向=位置"自过滤 bug）：

      dir      : 边的方向轴（filter_by，选平行于该轴的边）
      pos_axis : 位置过滤轴（默认同 dir），按 edge.center().<pos_axis> 落区间
      between  : [lo, hi] 位置区间
    """
    ax = {"X": Axis.X, "Y": Axis.Y, "Z": Axis.Z}[op["dir"]]
    pos = op.get("pos_axis", op["dir"])
    lo, hi = op["between"]
    return [e for e in bp.edges().filter_by(ax)
            if lo - 1e-6 <= getattr(e.center(), pos) <= hi + 1e-6]


def op_fillet(bp, op):
    """选择性圆角。op = {dir, pos_axis?, between:[lo,hi], r}。"""
    fillet(_select_edges(bp, op), radius=op["r"])


def op_chamfer(bp, op):
    """选择性倒角。op = {dir, pos_axis?, between:[lo,hi], d}。"""
    chamfer(_select_edges(bp, op), length=op["d"])


def op_shell(bp, op):
    """抽壳（挖空内部、留壁厚）。op = {thickness, open?}。

    build123d 无 `shell`，等价物是 `offset(amount=-t, openings=[面])`：
      * `thickness` 壁厚（正数，内部挖空 → amount 取负）
      * `open` 可选开口方向串，如 `"+Z"`（顶面敞开）；不给则全封闭（内部空腔）
    开口面用**几何谓词**选（filter_by(轴) + sort_by 取最外侧），不写死 Face#N。
    """
    t = float(op["thickness"])
    openings = []
    sel = op.get("open")
    if sel:
        ax = {"X": Axis.X, "Y": Axis.Y, "Z": Axis.Z}[sel[-1]]
        fs = bp.faces().filter_by(ax)
        if fs:
            fs = fs.sort_by(ax)
            openings = [fs[-1] if sel[0] == "+" else fs[0]]
    offset(amount=-t, openings=openings)


def op_cut_blind(bp, op):
    """盲切 / 盲孔：在指定标高的平面上、按草图轮廓切**固定深度**。

    CadQuery `cutBlind(-depth)` 的等价（不是通孔）。
    op = {z, depth, at:[x,y], profile:{kind:'rect', w, l} | {kind:'circle', r}}

    ⚠️ 实现要点：**不能在辅助函数里直接嵌套 `BuildSketch`** ——
    build123d 靠调用帧找父 Builder，函数内的 `with BuildSketch(...)` 会丢失
    `BuildPart` 上下文（extrude 报 "A face or sketch must be provided"）。
    正解：先在自己的上下文里造**独立 cutter**，再 `add(cutter, mode=SUBTRACT)`。
    """
    z = float(op.get("z", 0.0))
    d = float(op["depth"])
    at = op.get("at") or [0.0, 0.0]
    prof = op["profile"]
    with BuildPart() as tool:                      # 独立上下文，不受调用帧影响
        with BuildSketch(Plane.XY.offset(z)):
            with Locations(Pos(at[0], at[1])):
                if prof["kind"] == "rect":
                    Rectangle(float(prof["w"]), float(prof["l"]))
                elif prof["kind"] == "circle":
                    Circle(float(prof["r"]))
                else:
                    raise ValueError("cut_blind 未支持的轮廓 %r" % (prof["kind"],))
        extrude(amount=-d)
    add(tool.part, mode=Mode.SUBTRACT)


def op_hole(bp, op):
    """标准孔（CadQuery 一等公民 `.hole()`）。op = {at:[[x,y]...], d, z?}。

    与 hole_grid 同实现（多点布孔）；单列出来是为了对应榜上的 `hole`(58%)。
    """
    z = op.get("z", 0.0)
    for (x, y) in op["at"]:
        with Locations(Pos(x, y, z)):
            Hole(radius=op["d"] / 2.0)


def op_cut_thru(bp, op):
    """通切（CadQuery `cutThruAll()`）：按轮廓**打通整个零件**。

    op = {z, at:[x,y], profile:{kind:'rect',w,l}|{kind:'circle',r}, margin?}
    与 cut_blind 的区别：不传 depth，深度由零件包围盒算出（打通 + 余量）。
    """
    z = float(op.get("z", 0.0))
    at = op.get("at") or [0.0, 0.0]
    prof = op["profile"]
    bb = bp.part.bounding_box()
    h = (bb.max.Z - bb.min.Z) + 2.0 * float(op.get("margin", 1.0)) + abs(z - bb.max.Z)
    with BuildPart() as tool:
        with BuildSketch(Plane.XY.offset(z)):
            with Locations(Pos(at[0], at[1])):
                if prof["kind"] == "rect":
                    Rectangle(float(prof["w"]), float(prof["l"]))
                elif prof["kind"] == "circle":
                    Circle(float(prof["r"]))
                else:
                    raise ValueError("cut_thru 未支持的轮廓 %r" % (prof["kind"],))
        extrude(amount=-h)
    add(tool.part, mode=Mode.SUBTRACT)


def op_csk_hole(bp, op):
    """沉头孔（锥形沉孔，CadQuery `cskHole`）。
    op = {at:[[x,y]...], d, cs_d, angle?, depth?, z?}

    ⚠️ build123d 的 `depth` 是**孔深**（不是沉孔深）——不传则钻通；
    沉孔形状由 `counter_sink_angle` + `cs_d` 决定（沉深 = (cs_r − r)/tan(angle/2)）。
    """
    d, csd = op["d"], op["cs_d"]
    z = op.get("z", 0.0)
    angle = float(op.get("angle", 90.0))
    depth = op.get("depth")                      # None → 钻通
    for (x, y) in op["at"]:
        with Locations(Pos(x, y, z)):
            CounterSinkHole(radius=d / 2.0, counter_sink_radius=csd / 2.0,
                            depth=depth, counter_sink_angle=angle)


def op_cone(bp, op):
    """圆锥/圆锥台（挖料用，CadQuery `makeCone`）。
    op = {r1, r2, h, at:[x,y,z], mode?:'cut'}  —— 默认作为减法施加。
    """
    r1, r2, h = float(op["r1"]), float(op["r2"]), float(op["h"])
    at = op.get("at") or [0.0, 0.0, 0.0]
    add(Pos(at[0], at[1], at[2]) * Cone(bottom_radius=r1, top_radius=r2, height=h),
        mode=Mode.SUBTRACT)


# ------------------------------------------------------- ⑭⑮⑯⑰ 异族批次

def _sketch_of(plane_info, profile):
    """在**独立** BuildSketch 上下文里造一个草图，返回 Sketch 对象。

    ⚠️ 独立上下文是必须的：在辅助函数里 `with BuildSketch(...)` 找不到父 BuildPart
    （build123d 靠调用帧），所以它只会得到自己那个草图 —— 这正好是我们想要的。
    """
    pl = plane_info.get("plane", "XY")
    base = {"XY": Plane.XY, "YZ": Plane.YZ, "XZ": Plane.XZ}.get(pl, Plane.XY)
    off = plane_info.get("offset")
    plane = base.offset(float(off)) if off else base
    with BuildSketch(plane) as sk:
        k = profile.get("kind")
        for (x, y) in (profile.get("at_all") or [[0.0, 0.0]]):
            with Locations(Pos(x, y)):
                if k == "rect":
                    Rectangle(float(profile["w"]), float(profile["l"]))
                elif k == "circle":
                    Circle(float(profile["r"]))
                else:
                    raise ValueError("未支持的剖面 %r" % (k,))
    return sk.sketch


def op_loft(bp, op):
    """放样（CadQuery `loft`）：在多个剖面之间过渡。
    op = {sections:[{plane:{plane,offset}, profile:{kind,w,l}|{kind,r}}...]}
    """
    secs = [_sketch_of(s.get("plane") or {}, s["profile"]) for s in op["sections"]]
    loft(sections=secs)


def op_sweep(bp, op):
    """扫掠（CadQuery `sweep`）：把剖面沿路径扫出去。
    op = {profile:{kind,w,l}|{kind,r}, path:[[x,y,z]...]}  —— 路径用 Polyline 近似。
    """
    prof = _sketch_of({"plane": "XY"}, op["profile"])
    pts = [tuple(p) for p in op["path"]]
    with BuildLine() as bl:
        Polyline(*pts)
    sweep(sections=prof, path=bl.line)


def op_mirror(bp, op):
    """镜像（CadQuery `mirror`）：把当前 part 关于某平面镜像后合并。
    op = {plane:'YZ'|'XZ'|'XY'}（默认 'YZ'）。
    """
    pl = {"YZ": Plane.YZ, "XZ": Plane.XZ, "XY": Plane.XY}.get(op.get("plane", "YZ"),
                                                              Plane.YZ)
    add(mirror(bp.part, about=pl), mode=Mode.ADD)


def op_face_plane(bp, op):
    """在**选中的面**上再长一块（CadQuery `workplaneFromTagged` / `faces().workplane()`
    这类"换到某个面继续画"的惯用法；L2 里 `faces.workplane` 覆盖 18%）。
    op = {sel:'+Z'|'-Z'|'+X'..., profile:{kind,w,l}|{kind,r}, height, offset?}
    """
    sel = op.get("sel", "+Z")
    ax = {"X": Axis.X, "Y": Axis.Y, "Z": Axis.Z}[sel[-1]]
    fs = bp.faces().filter_by(ax).sort_by(ax)
    face = fs[-1] if sel[0] == "+" else fs[0]
    c = face.center()
    pl = Plane(origin=c, z_dir=face.normal_at(c))
    prof = op["profile"]
    off = op.get("offset") or [0.0, 0.0]
    with BuildPart() as boss:                     # 独立上下文（同 cut_blind 的理由）
        with BuildSketch(pl):
            with Locations(Pos(off[0], off[1])):
                if prof["kind"] == "rect":
                    Rectangle(float(prof["w"]), float(prof["l"]))
                else:
                    Circle(float(prof["r"]))
        extrude(amount=float(op["height"]))
    add(boss.part, mode=Mode.ADD)


DISPATCH = {
    "hole_grid": op_hole_grid,
    "bolt_circle": op_bolt_circle,
    "cbore_hole": op_cbore_hole,
    "fillet": op_fillet,
    "chamfer": op_chamfer,
    "shell": op_shell,
    "cut_blind": op_cut_blind,
    "hole": op_hole,
    "cut_thru": op_cut_thru,
    "csk_hole": op_csk_hole,
    "cone": op_cone,
    "loft": op_loft,
    "sweep": op_sweep,
    "mirror": op_mirror,
    "face_plane": op_face_plane,
}


def apply_ops(bp, ops):
    """在当前 BuildPart 上下文内，按序施加减法类算子。"""
    for op in ops:
        DISPATCH[op["op"]](bp, op)
