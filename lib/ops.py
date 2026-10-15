# -*- coding: utf-8 -*-
r"""ops —— 算子注册表（**单源 / Single Source of Truth**）

一个算子的定义**只写这里一处**。以下三处都从本表派生：

    lib/ops.py  ◀── 唯一源
        │
        ├──▶ lib/ir.py                词表（TREE_OPS / IMPL_OPS）+ 校验
        ├──▶ tools/ir2build.py        build123d 生成器
        └──▶ tools/ir2partdesign.py   FreeCAD(PartDesign) 生成器

**为什么需要它**（`lessons.md` §8.7「同步点」）

原先一个算子概念要写在 **≥4 处**（`ir.py` 词表 + 两个生成器 + 验证），
漏改一处就是**静默错误**。实测硬伤：

* `lib/ir.py::TREE_OPS` 声明 6 个算子，其中 `Pocket`/`Fillet`/`Chamfer`/`Hole`
  在生成器里**没有实现**（`Fillet`/`Chamfer` 在 ir2build 只打 `# PLACEHOLDER`）；
* 更危险的是 `revolve`/`loft`/`sweep`：两个生成器**都会把它当 `extrude` 生成**
  —— 不报错、不打警告，**几何直接错**；
* 而 `validate()` 只查 tree 层、从不看 impl ⇒ **「校验通过」≠「能生成」**，且 exit 0。

**判据**：`加一个算子要改几个文件？` —— 是 **1** 就随便加；是 **4** 就先做单源。
本模块就是那个「1」。

**用法**

    from lib import ops
    ops.tree_ops()                      # 派生词表
    ops.impl_ops()                      # {段: 算子元组}
    ops.supported("tool", ops.B3D)      # 该段在 build123d 侧真能生成的算子
    ops.problems()                      # 自检：声明层面的隐患（含 WRONG）
    ops.report()                        # 人类可读覆盖率报告

命令行：`python lib/ops.py`（打印覆盖率与隐患）

隔离：本模块是**纯数据 + 纯函数**，不 import build123d/FreeCAD，不碰消息线。
"""
import sys

# ---------------------------------------------------------------- 状态常量

#: 后端标识
B3D = "b3d"     #: build123d（tools/ir2build.py）
PD = "pd"       #: FreeCAD PartDesign（tools/ir2partdesign.py）
BACKENDS = (B3D, PD)

#: 实现状态
IMPL = "impl"                #: 已实现 —— 真生成几何
PLACEHOLDER = "placeholder"  #: 明确不做 —— 生成器打占位注释（诚实，不硬造）
WRONG = "wrong"              #: ⚠️ 会生成，但**几何是错的**（静默错误，最危险）
UNSUPPORTED = "unsupported"  #: 该后端没有对应物（能力缺口，非 bug）

#: impl 段名（`seg[0]` 的取值）
SEG_SKETCH = "sketch"
SEG_ADD = "add"
SEG_TOOL = "tool"
SEG_CUT = "cut"
SEG_EDGE = "edge"
SEG_SHELL = "shell"

#: structural.kind
K_MAIN = "主体"
K_ADD = "加法"
K_CUT = "减法"
K_EDGE = "边处理"
K_DEFORM = "变形"


# ---------------------------------------------------------------- 注册表（唯一源）

#: 算子注册表。键 = `impl` 里的算子名（sketch 段内用 `sketch_*`，
#: tool 段用 `tool_*`，加法/边处理/变形用裸名）。
#:
#: 条目字段：
#:   seg      该算子属于哪个 impl 段
#:   kind     对应 structural.kind（主体/加法/减法/边处理/变形）
#:   tree_op  映射到的 FreeCAD 特征名（同时供给 ir.py 的 TREE_OPS）
#:   b3d      build123d 侧状态（IMPL/PLACEHOLDER/WRONG/UNSUPPORTED）
#:   pd       FreeCAD 侧状态（同上）
#:   note     补充说明（能力缺口、已知 bug、待办）
OPERATORS = {
    # ------------------------------------------------ 草图段（seg='sketch'）
    "sketch_polygon": dict(seg=SEG_SKETCH, tree_op="Sketch", b3d=IMPL, pd=IMPL,
                           note="多边形（闭合折线）"),
    "sketch_line": dict(seg=SEG_SKETCH, tree_op="Sketch", b3d=IMPL, pd=IMPL),
    "sketch_polyline": dict(seg=SEG_SKETCH, tree_op="Sketch", b3d=IMPL, pd=IMPL),
    "sketch_circle": dict(seg=SEG_SKETCH, tree_op="Sketch", b3d=IMPL, pd=UNSUPPORTED,
                          note="FreeCAD 侧只从 pts 建轮廓，尚不认圆"),
    "sketch_rect": dict(seg=SEG_SKETCH, tree_op="Sketch", b3d=IMPL, pd=UNSUPPORTED,
                        note="同上：FreeCAD 侧只认 pts 型草图"),
    "sketch_center_arc": dict(seg=SEG_SKETCH, tree_op="Sketch", b3d=IMPL, pd=UNSUPPORTED,
                              note="同上"),

    # ------------------------------------------------ 加法段（seg='add'）
    "extrude": dict(seg=SEG_ADD, kind=K_ADD, tree_op="Pad", b3d=IMPL, pd=IMPL),
    "revolve": dict(seg=SEG_ADD, kind=K_ADD, tree_op="Revolution", b3d=WRONG, pd=WRONG,
                    note="⚠️ 两个生成器都把它当 extrude 生成（上游 bug，见 s1-IR化方案 §3.2）；"
                         "不报错、几何错"),
    "loft": dict(seg=SEG_ADD, kind=K_ADD, tree_op="Loft", b3d=WRONG, pd=WRONG,
                 note="同 revolve：被当 extrude 生成"),
    "sweep": dict(seg=SEG_ADD, kind=K_ADD, tree_op="Sweep", b3d=WRONG, pd=WRONG,
                  note="同 revolve：被当 extrude 生成"),

    # ------------------------------------------------ 减法的工具（seg='tool'）
    "tool_cylinder": dict(seg=SEG_TOOL, kind=K_CUT, tree_op="Pocket", b3d=IMPL, pd=IMPL,
                          b3d_call="Cylinder"),
    "tool_box": dict(seg=SEG_TOOL, kind=K_CUT, tree_op="Pocket", b3d=IMPL, pd=IMPL,
                     b3d_call="Box"),
    "tool_sphere": dict(seg=SEG_TOOL, kind=K_CUT, tree_op="Pocket", b3d=IMPL, pd=UNSUPPORTED,
                        b3d_call="Sphere"),
    "tool_cone": dict(seg=SEG_TOOL, kind=K_CUT, tree_op="Pocket", b3d=IMPL, pd=UNSUPPORTED,
                      b3d_call="Cone"),
    "tool_torus": dict(seg=SEG_TOOL, kind=K_CUT, tree_op="Pocket", b3d=IMPL, pd=UNSUPPORTED,
                       b3d_call="Torus"),

    # ------------------------------------------------ 布尔减动作（seg='cut'）
    "cut": dict(seg=SEG_CUT, kind=K_CUT, tree_op="Pocket", b3d=IMPL, pd=IMPL,
                note="布尔减动作（impl payload 为 None）"),

    # ------------------------------------------------ 边处理（seg='edge'）
    "fillet": dict(seg=SEG_EDGE, kind=K_EDGE, tree_op="Fillet",
                   b3d=PLACEHOLDER, pd=PLACEHOLDER,
                   note="两后端都只打 PLACEHOLDER（未实现）"),
    "chamfer": dict(seg=SEG_EDGE, kind=K_EDGE, tree_op="Chamfer",
                    b3d=PLACEHOLDER, pd=PLACEHOLDER,
                    note="同 fillet"),

    # ------------------------------------------------ 变形（seg='shell'）
    "shell": dict(seg=SEG_SHELL, kind=K_DEFORM, tree_op="Shell",
                  b3d=PLACEHOLDER, pd=PLACEHOLDER,
                  note="两后端都未实现"),
}


# ---------------------------------------------------------------- 派生：词表

#: `TREE_OPS` 的输出顺序（保持与上游词表一致，避免校验报错文本发生变化）
_TREE_ORDER = ("Sketch", "Pad", "Pocket", "Fillet", "Chamfer", "Hole", "Placeholder")


def tree_ops():
    """派生 `TREE_OPS`。

    `_TREE_ORDER` 里的名字是**保留名**（无条件包含，保证与上游词表向后兼容——
    例如 `Hole` 目前没有对应算子，但旧 IR 可能写过），注册表里其余 `tree_op`
    按字典序追加在后。结果一定是上游词表的**超集**。
    """
    have = {d["tree_op"] for d in OPERATORS.values()}
    out = list(_TREE_ORDER)
    out += sorted(have - set(_TREE_ORDER))
    return tuple(out)


def impl_ops(seg=None):
    """派生 `IMPL_OPS`（impl 里的算子名，按段归类）。

    `seg=None` → 返回 `{段: 算子元组}`；给了 `seg` → 只返回该段的元组。
    """
    by = {}
    for name, d in OPERATORS.items():
        by.setdefault(d["seg"], []).append(name)
    by = {k: tuple(sorted(v)) for k, v in by.items()}
    return by if seg is None else by.get(seg, ())


#: `KINDS` 的固定顺序。前四个是**基础角色**（无条件保留——它们描述特征的
#: 结构角色，不是「算子」，注册表里不会有 `kind=主体` 的算子）；`变形` 由
#: 注册表引入（`shell`）。
_KIND_ORDER = (K_MAIN, K_ADD, K_CUT, K_EDGE, K_DEFORM)
_BASE_KINDS = frozenset((K_MAIN, K_ADD, K_CUT, K_EDGE))


def kinds():
    """派生 `KINDS`：基础角色无条件保留 + 注册表引入的角色，顺序固定。"""
    have = {d["kind"] for d in OPERATORS.values() if d.get("kind")}
    return tuple(k for k in _KIND_ORDER if k in _BASE_KINDS or k in have)


# ---------------------------------------------------------------- 派生：后端能力

def supported(seg, backend):
    """某段在某后端**真能生成几何**的算子集合（只有 `IMPL` 才算）。

    生成器用它决定「要不要处理这个算子」——这就是「从注册表派生」的落点。
    """
    return frozenset(n for n, d in OPERATORS.items()
                     if d["seg"] == seg and d.get(backend) == IMPL)


def state(name, backend):
    """某算子在某后端的状态（IMPL/PLACEHOLDER/WRONG/UNSUPPORTED/None）。"""
    d = OPERATORS.get(name)
    return None if d is None else d.get(backend)


def tree_op_of(name):
    """某算子映射到的 FreeCAD 特征名。"""
    d = OPERATORS.get(name)
    return None if d is None else d.get("tree_op")


def b3d_call(name):
    """某算子在 build123d 侧用的类/函数名（如 `tool_cylinder` → `Cylinder`）。"""
    d = OPERATORS.get(name)
    return None if d is None else d.get("b3d_call")


def seg_of(name):
    """某算子所属的 impl 段。"""
    d = OPERATORS.get(name)
    return None if d is None else d.get("seg")


# ---------------------------------------------------------------- 自检

def problems():
    """自检：返回「声明层面」的隐患清单（供 CI / 上传前检查调用）。

    覆盖三类：
      1. **WRONG** —— 会生成但几何错（最危险，必须暴露）
      2. **两后端能力不对等** —— 同一算子一边 IMPL、另一边 UNSUPPORTED/PLACEHOLDER
         （未必是错，但**必须显式知情**，否则就是 §8.7 说的「漏改一处」）
      3. 缺 `tree_op`（无法映射到 FreeCAD 特征）
    """
    out = []
    for name in sorted(OPERATORS):
        d = OPERATORS[name]
        if d.get(B3D) == WRONG or d.get(PD) == WRONG:
            who = [b for b in BACKENDS if d.get(b) == WRONG]
            out.append((WRONG, name,
                        "会生成但几何错（%s）%s" % ("/".join(who), d.get("note") or "")))
        if not d.get("tree_op"):
            out.append(("no_tree_op", name, "缺 tree_op，无法映射 FreeCAD 特征"))
        b, p = d.get(B3D), d.get(PD)
        if (b == IMPL) != (p == IMPL):
            out.append(("asym", name,
                        "两后端不对等：b3d=%s / pd=%s%s"
                        % (b, p, ("（%s）" % d["note"]) if d.get("note") else "")))
    return out


def coverage():
    """覆盖率统计（供报告用）。"""
    total = len(OPERATORS)
    st = {}
    for b in BACKENDS:
        st[b] = {s: sum(1 for d in OPERATORS.values() if d.get(b) == s)
                 for s in (IMPL, PLACEHOLDER, WRONG, UNSUPPORTED)}
    return {"total": total, "by_backend": st}


def report(stream=None):
    """打印人类可读的覆盖率报告 + 隐患清单。返回隐患条数。"""
    fh = stream or sys.stdout
    cov = coverage()
    print("ops 注册表：%d 个算子" % cov["total"], file=fh)
    for b, label in ((B3D, "build123d"), (PD, "FreeCAD")):
        s = cov["by_backend"][b]
        print("  %-10s impl=%d  placeholder=%d  WRONG=%d  unsupported=%d"
              % (label, s[IMPL], s[PLACEHOLDER], s[WRONG], s[UNSUPPORTED]), file=fh)
    print("\n分段：", file=fh)
    for seg, names in sorted(impl_ops().items()):
        print("  %-8s %s" % (seg, ", ".join(names)), file=fh)
    probs = problems()
    print("\n隐患 %d 条：" % len(probs), file=fh)
    for kind, name, why in probs:
        mark = "!!" if kind == WRONG else "  "
        print("  %s [%-10s] %-18s %s" % (mark, kind, name, why), file=fh)
    return len([p for p in probs if p[0] == WRONG])


if __name__ == "__main__":
    n_wrong = report()
    sys.exit(2 if n_wrong else 0)
