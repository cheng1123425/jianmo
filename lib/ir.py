# -*- coding: utf-8 -*-
r"""lib/ir.py —— 参数化零件的唯一真值表示（IR / 中间表示）
================================================================

**IR 是什么**

一份**特征图**（feature graph），是零件的唯一真值源。两个后端都从它生成：

    IR ──[build123d 生成器]──▶ 脚本 → 几何/STEP        （生成端几何引擎）
    IR ──[PartDesign 生成器]─▶ FreeCAD 真特征树        （按需物化的交互面）
    IR.drawing.anchors ──────▶ 3D↔2D 绑定              （标注 ↔ 特征 ↔ 视图边）

**为什么需要它**

build123d 脚本本身就是特征树（每个 Box/Cylinder/fillet/布尔就是一个特征），
但它是"代码"，不可校验、不可跨端共享。IR 把同一份构造过程变成**结构化、可校验、
可双向生成**的数据——这是"一份构造描述，两个投影"的地基。

**为什么不能从 STEP 反推 IR**

STEP 是 AP214 纯几何，无参数、无特征树、无历史（是"照片"不是"活体"）；
从形状反推特征是几十年未解难题且语义不唯一。IR 只能从**构造过程**来：
  ① 生成端：图纸 → 解析 → 语义恢复 → IR
  ② 存量：build123d 脚本 ──[执行+录制]──▶ IR（见 tools/recorder.py）

**字段说明（每个 feature 八栏）**

| 栏 | 内容 | 能否自动得到 | 谁消费 |
|---|---|---|---|
| `semantic`   | 这是什么（底板/安装孔/加强筋） | ❌ 必须正向标注 | 出图命名、3D↔2D |
| `structural` | 主体/加法/减法/边处理 + target | ✅ 可从录制推 | 组织建模顺序 |
| `params`     | **具名参数**（不是裸数字） | ✅ 录制 | ★ 改一处两端都变 |
| `impl`       | 操作序列（rect/extrude/cut…） | ✅ 录制 | build123d 生成 |
| `tree`       | 映射到哪种 FreeCAD 特征 | ✅ 由 impl 推 | PartDesign 生成 |
| `deps`       | 依赖哪些 feature | ✅ 录制 | 拓扑排序 |
| `drawing`    | **anchors：3D↔2D 绑定** | ❌ 必须标注 | ★ 差异化核心 |
| `note`       | 自由备注（含"特例放行"留痕） | — | 人读 |

**设计纪律（来自架构定案，勿违）**
1. IR 是唯一真值源；build123d / FreeCAD 都是它的生成物，不是三方同步。
2. 选边一律存**几何谓词**（`geom`），绝不存 `Edge#12`（D3：条件查询替代身份引用）。
3. 图纸**只读**：不允许在图纸上改数反推模型；要改走 IR / FreeCAD。
4. `tree` 里无 PartDesign 对应物的特征，落**只读占位节点**，几何仍由 build123d 出。
5. 内腔不可见特征（三视图无 2D 边可挂）当**特例放行**，在 `note` 里留痕。

隔离：本模块是纯函数 + 数据，无 IO 副作用（dump/load 显式调用），可被任意
步骤/工具导入，`guard.py` 不拦（与 lib/drawing_fc.py 同性质）。
"""

import json
import os

try:                                    # 被 `from lib import ir` 导入
    from . import ops as _ops
except ImportError:                     # 被 `import ir`（sys.path 指向 lib/）导入
    import ops as _ops

# ---------------------------------------------------------------- 常量词表
#
# ⚠️ 词表**不在这里定义**，而是从 `lib/ops.py`（算子注册表 = 单源）派生。
# 理由见 `lessons.md` §8.7「同步点」：原先一个算子要写在 ≥4 处，漏改一处就是
# 静默错误。现在「加一个算子」只需改 `lib/ops.py` 一处，词表与两个生成器自动跟上。

#: structural.kind —— 特征在建模里的角色
KINDS = _ops.kinds()

#: tree.op —— 映射到 FreeCAD 原生特征的算子词表
#: （impl 里的原始算子翻成这些；无对应物的标 None = 只读占位节点）
TREE_OPS = _ops.tree_ops()

#: impl 里的算子名（按段归类）—— 校验 impl 用；同时供生成器查「该段支持哪些算子」
IMPL_OPS = _ops.impl_ops()

#: drawing.dim_kind —— 标注形式（与 s2_drawing / TechDraw 对齐）
DIM_KINDS = ("dia", "rad", "distX", "distY", "extentH", "extentV")

#: drawing.anchor.geom.kind —— 几何查询谓词类型
GEOM_KINDS = ("circle", "hline", "vline", "level_pair", "extent")

#: drawing.draw_mode —— 怎么画这条标注
DRAW_MODES = ("edge", "point_distance")


# ---------------------------------------------------------------- 构造helper

def new_feature(fid, semantic=None, structural=None, params=None,
                impl=None, tree=None, deps=None, drawing=None, note=None):
    """造一个 feature（只填必要的，其余留空由录制/标注补）。"""
    return {
        "id": fid,
        "semantic": semantic or {},
        "structural": structural or {"kind": None, "target": None},
        "params": params or {},
        "impl": impl or [],
        "tree": tree or [],
        "deps": deps or [],
        "drawing": drawing,          # None = 该特征不直接成标注（如主体）
        "note": note,
    }


def new_part_ir(part, features=None, source=None, meta=None):
    """造一份零件 IR。"""
    return {
        "ir_version": 1,
        "part": part,
        "source": source or {},      # 来源：{"from": "build123d 录制"/"图纸解析", "script": ...}
        "meta": meta or {},
        "features": features or [],
    }


def feature_index(ir):
    """{feature_id: feature}"""
    return {f["id"]: f for f in ir.get("features", [])}


def feature_of(ir, fid):
    return feature_index(ir).get(fid)


# ---------------------------------------------------------------- 校验

def validate(ir):
    """校验 IR 自洽性，返回问题列表（不抛异常）。

    抓四类错：
      * 结构缺失 / 类型错
      * id 重复
      * deps 指向不存在的 feature
      * drawing.anchor 指向不存在的 feature / geom 谓词不合法
    """
    problems = []
    if not isinstance(ir, dict):
        return ["IR 不是 dict"]
    for k in ("ir_version", "part", "features"):
        if k not in ir:
            problems.append("缺少顶层字段：%s" % k)

    feats = ir.get("features", [])
    if not isinstance(feats, list):
        problems.append("features 不是 list")
        return problems

    seen = set()
    for i, f in enumerate(feats):
        tag = "feature[%d]" % i
        if not isinstance(f, dict):
            problems.append("%s 不是 dict" % tag)
            continue
        fid = f.get("id")
        if not fid:
            problems.append("%s 缺少 id" % tag)
            continue
        tag = "feature %s" % fid
        if fid in seen:
            problems.append("%s id 重复" % tag)
        seen.add(fid)

        # 必备栏
        for k in ("semantic", "structural", "params", "impl", "tree", "deps"):
            if k not in f:
                problems.append("%s 缺少字段 %s" % (tag, k))

        kind = (f.get("structural") or {}).get("kind")
        if kind is not None and kind not in KINDS:
            problems.append("%s structural.kind=%r 不在词表 %s" % (tag, kind, KINDS))

        for op in (f.get("tree") or []):
            opname = op[0] if isinstance(op, (list, tuple)) else op
            if opname not in TREE_OPS:
                problems.append("%s tree.op=%r 不在词表 %s" % (tag, opname, TREE_OPS))

        for d in (f.get("deps") or []):
            if d not in seen and d not in {x.get("id") for x in feats}:
                problems.append("%s deps 指向不存在的 %r" % (tag, d))

        dw = f.get("drawing")
        if dw:
            if dw.get("dim_kind") not in DIM_KINDS:
                problems.append("%s drawing.dim_kind=%r 不在词表 %s"
                                % (tag, dw.get("dim_kind"), DIM_KINDS))
            anc = dw.get("anchor") or {}
            af = anc.get("feature")
            if af is not None and af != fid and af not in {x.get("id") for x in feats}:
                problems.append("%s drawing.anchor.feature=%r 不存在" % (tag, af))
            g = anc.get("geom") or {}
            if g and g.get("kind") not in GEOM_KINDS:
                problems.append("%s anchor.geom.kind=%r 不在词表 %s"
                                % (tag, g.get("kind"), GEOM_KINDS))
            if dw.get("draw_mode") not in (None,) + DRAW_MODES:
                problems.append("%s drawing.draw_mode=%r 不在词表 %s"
                                % (tag, dw.get("draw_mode"), DRAW_MODES))

    return problems


# ---------------------------------------------------------------- IO

def dump(ir, path):
    """写 JSON（ensure_ascii=False，和项目其它 json 产物一致）。"""
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ir, f, ensure_ascii=False, indent=2)
    return path


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
