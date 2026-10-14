# -*- coding: utf-8 -*-
r"""z2c_distill —— 从 Zero-to-CAD 的 cadquery_file 蒸馏「三维语义层」

背景
----
Zero-to-CAD 数据集（ADSKAILab/Zero-To-CAD-100k）**没有独立的语义字段**，
但它的建模代码里藏着三路可蒸馏的语义线索（见 /workspace/验证报告/
ZeroToCAD语义层蒸馏可行性.md 的实测）：

  ① 参数名本身就是语义 —— `hole_diameter` / `rib_width` / `cbore_depth`
                             （430 行样本里 97.6% 的参数实例可词根识别）
  ② 英文注释写明意图   —— `# base solid` / `# cbore hole through flange side`
                             （53.3% 的样本带注释）
  ③ 操作序列蕴含结构   —— `.union()` 加法 / `.cut()` 减法 / `.chamfer()` 边处理
                             （主体 98.4% / 减法 86.5% / 边处理 90.7% 可自动判定）

本工具把这三路合成 HANDOFF §4.2 要求的三层 IR（语义 / 结构 / 操作），
产出 `feature_semantics.json`。**纯正则 + ast，不依赖 cadquery。**

它**不能**产出 `drawing` 字段（↔二维标注）—— 数据集不含任何图纸，
那一环必须来自真实图纸（jianmo 的 s0b_dwgread）。

用法
----
    python tools/z2c_distill.py --parquet <file> [--limit N] [--out DIR]
    python tools/z2c_distill.py --code <cadquery.py>          # 单文件调试
"""
import argparse
import ast
import json
import os
import re
import sys

# ----------------------------------------------------------------------
# ① 参数名 → 语义。按「词根最长优先」匹配，避免 hole_diameter 被 diameter 抢走。
# ----------------------------------------------------------------------
#   顺序很重要：长词根排前面（cbore_diameter 要先于 diameter）
FEATURE_ROOTS = [
    # (词根, 语义类型, 角色提示)
    ("cbore", "counterbore_hole", "沉孔"),
    ("csk", "countersink_hole", "埋头孔"),
    ("countersink", "countersink_hole", "埋头孔"),
    ("dovetail", "dovetail", "燕尾"),
    ("t_slot", "t_slot", "T 型槽"),
    ("hole", "through_hole", "通孔"),
    ("bore", "bored_hole", "镗孔"),
    ("drill", "drilled_hole", "钻孔"),
    ("slot", "slot", "槽"),
    ("pocket", "pocket", "凹腔"),
    ("groove", "groove", "沟槽"),
    ("notch", "notch", "缺口"),
    ("rib", "rib", "加强肋"),
    ("boss", "boss", "凸台"),
    ("flange", "flange", "法兰"),
    ("leg", "leg", "腿/立柱"),
    ("arm", "arm", "臂"),
    ("wing", "wing", "翼"),
    ("wall", "wall", "壁"),
    ("pad", "pad", "凸台垫"),
    ("base", "base_plate", "底板"),
    ("plate", "plate", "板"),
    ("bracket", "bracket", "支架"),
    ("panel", "panel", "面板"),
    ("fillet", "fillet", "圆角"),
    ("chamfer", "chamfer", "倒角"),
    ("round", "round", "圆角"),
]
# 尺寸类词根（只标"是尺寸"，不单独成特征）
DIM_ROOTS = ["length", "width", "height", "thickness", "depth",
             "diameter", "radius", "angle", "spacing", "pitch", "count",
             "offset", "clearance", "position"]

# 结构层：操作名 → 结构角色
STRUCT_OF_OP = {
    "union": "加法", "add": "加法",
    "cut": "减法", "cutBlind": "减法", "cutThruAll": "减法",
    "hole": "减法", "cboreHole": "减法", "cskHole": "减法",
    "pocket": "减法", "slot": "减法",
    "fillet": "边处理", "chamfer": "边处理",
    "extrude": "构造", "rect": "构造", "circle": "构造", "box": "构造",
    "cylinder": "构造", "sphere": "构造", "cone": "构造",
}
PRIMITIVE_OPS = {"rect", "circle", "box", "cylinder", "sphere", "cone",
                 "polygon", "Workplane"}


def _match_root(name):
    """参数名 → (语义类型, 角色) 或 (None, None)。

    匹配规则：把下划线当词边界，**只在词首/词尾命中才算**，
    避免 `dovetail_base` 被 `base` 抢走、`outer_radius` 被 `round` 抢走
    （都是实测踩过的误判）。长词根优先。
    """
    low = name.lower()
    tokens = re.split(r"[_\-]", low)
    for root, ftype, role in FEATURE_ROOTS:
        for tk in tokens:
            if tk == root or tk.startswith(root) or tk.endswith(root):
                # count/spacing 这类是尺寸修饰，不是特征本身，跳过
                if tk in ("count", "spacing", "pitch", "offset"):
                    continue
                return ftype, role
    return None, None


def _is_dim_name(name):
    low = name.lower()
    return any(r in low for r in DIM_ROOTS)


# ----------------------------------------------------------------------
# 解析 Measures(...) 嵌套结构 → 语义层特征树
# ----------------------------------------------------------------------
def parse_measures(code):
    """从源码里抽出 Measures(...) 的嵌套结构。

    返回 (root_var, features)：
      features = [ {path, name, semantic_type, role, dims, children} ]
    用 ast 解析赋值语句，识别 `X = Measures(...)`（含嵌套）。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None, []

    features = []

    def walk_measures(node, path, var_name):
        """node 是 ast.Call(func=Measures)，把它的 kwargs 拆成 dims + 子特征。

        关键：**顶层参数名本身也是语义线索**（第 1 路，97.6% 覆盖）。
        如 `boss_radius=12.0` / `dovetail_depth=4.0` 这种扁平 Measures，
        没有嵌套子特征，语义完全靠参数名 —— 必须把每个带语义词根的
        kwarg 也建成一个特征，否则会漏掉一多半样本。
        """
        dims = {}
        children = []
        for kw in node.keywords:
            if kw.arg is None:
                continue
            v = kw.value
            if isinstance(v, ast.Call) and _is_measures_call(v):
                sub_path = path + [kw.arg]
                children.append(_mk_feature(kw.arg, sub_path))
                walk_measures(v, sub_path, kw.arg)
            elif isinstance(v, ast.Constant) and isinstance(v.value, (int, float)):
                dims[kw.arg] = v.value
                # 参数名带语义词根 → 单独成一个特征（扁平 Measures 的语义来源）
                _ft, _role = _match_root(kw.arg)
                if _ft:
                    _mk_dim_feature(kw.arg, path, v.value, _ft, _role)
            else:
                # 表达式（如 m.width/2）先留字符串，后续可回代
                try:
                    dims[kw.arg] = ast.unparse(v)
                except Exception:
                    dims[kw.arg] = None
        # 回填到已建的 feature 上
        for entry in features:
            if entry["_path"] == path:
                entry["dims"] = dims
                entry["children"] = [c["name"] for c in children]

    def _mk_feature(name, path):
        ftype, role = _match_root(name)
        entry = {"name": name, "path": "/".join(path),
                 "semantic_type": ftype, "role": role,
                 "dims": {}, "children": [], "_path": path}
        features.append(entry)
        return entry

    def _mk_dim_feature(name, parent_path, value, ftype, role):
        """扁平 Measures 里一个带语义词根的标量参数 → 特征条目。

        它不含子结构，所以 dims 只有自己那一项。用 `@值` 记录尺寸，
        便于下游按需回代（如 boss_radius=12 → 直径 24）。
        """
        path = list(parent_path) + [name]
        # 避免与已有同名特征重复
        for e in features:
            if e["_path"] == path:
                e["dims"][name] = value
                return e
        entry = {"name": name, "path": "/".join(path),
                 "semantic_type": ftype, "role": role,
                 "dims": {name: value}, "children": [], "_path": path,
                 "from_param": True}
        features.append(entry)
        return entry

    def _is_measures_call(call):
        fn = call.func
        if isinstance(fn, ast.Name) and fn.id == "Measures":
            return True
        if isinstance(fn, ast.Attribute) and fn.attr == "Measures":
            return True
        return False

    root_var = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _is_measures_call(node.value):
                name = None
                if isinstance(node.targets[0], ast.Name):
                    name = node.targets[0].id
                if root_var is None:
                    root_var = name
                # 顶层的 kwargs 直接挂到"零件根"下
                dims = {}
                for kw in node.value.keywords:
                    if kw.arg is None:
                        continue
                    v = kw.value
                    if isinstance(v, ast.Call) and _is_measures_call(v):
                        p = [kw.arg]
                        _mk_feature(kw.arg, p)
                        walk_measures(v, p, kw.arg)
                    elif isinstance(v, ast.Constant) and isinstance(v.value, (int, float)):
                        dims[kw.arg] = v.value
                        # 顶层标量参数名也带语义（扁平 Measures 的主力来源）
                        _ft, _role = _match_root(kw.arg)
                        if _ft:
                            _mk_dim_feature(kw.arg, [], v.value, _ft, _role)
                    else:
                        try:
                            dims[kw.arg] = ast.unparse(v)
                        except Exception:
                            dims[kw.arg] = None
                features.insert(0, {"name": name or "part", "path": [],
                                    "semantic_type": "part",
                                    "role": "零件主体根",
                                    "dims": dims,
                                    "children": [], "_path": []})

    # 清理内部字段
    for f in features:
        f.pop("_path", None)
    return root_var, features


# ----------------------------------------------------------------------
# 解析操作序列 → 结构层 + 操作层
# ----------------------------------------------------------------------
_OP_RE = re.compile(r"\.(\w+)\s*\(")


def parse_ops(code):
    """按出现顺序抽出链式调用名（不展开，只取序）。

    返回 [ {op, struct, args_text} ]。用正则足够 —— 这里只要"调用了什么、
    结构角色是什么"，不求值（求值是 cadquery_ops_json 的活，数据集已给）。
    """
    ops = []
    for m in _OP_RE.finditer(code):
        op = m.group(1)
        if op in ("Measures",):
            continue
        # 抓该调用的实参文本（到配对的右括号）
        i = m.end()
        depth = 1
        while i < len(code) and depth:
            if code[i] == "(":
                depth += 1
            elif code[i] == ")":
                depth -= 1
            i += 1
        args_text = code[m.end():i - 1]
        ops.append({
            "op": op,
            "struct": STRUCT_OF_OP.get(op),
            "is_feature": op not in PRIMITIVE_OPS and
                          STRUCT_OF_OP.get(op) not in ("构造", None),
            "args": args_text[:80],
        })
    return ops


def parse_comments(code):
    """抽出 # 注释（第 2 路语义线索）"""
    out = []
    for line in code.split("\n"):
        s = line.strip()
        if s.startswith("#"):
            c = s.lstrip("#").strip()
            if c:
                out.append(c)
    return out


# ----------------------------------------------------------------------
# 合成三层 IR
# ----------------------------------------------------------------------
def distill(code, source="<inline>"):
    """cadquery 源码 → 三层 IR 的 feature_semantics"""
    root_var, features = parse_measures(code)
    ops = parse_ops(code)
    comments = parse_comments(code)

    # ---- 结构层：按"是否有布尔/边处理操作"归纳 ----
    structure = {"主体": 0, "加法": 0, "减法": 0, "边处理": 0, "构造": 0}
    for o in ops:
        if o["struct"]:
            structure[o["struct"]] += 1
    kind = []
    if structure["主体"] or structure["构造"]:
        kind.append("主体")
    if structure["加法"]:
        kind.append("加法")
    if structure["减法"]:
        kind.append("减法")
    if structure["边处理"]:
        kind.append("边处理")

    # ---- 语义层：特征清单（从 Measures 抽的 + 从参数名兜底）----
    # 先合并「同父路径 + 同类型」的特征 —— boss_radius / boss_height 应属
    # 同一个"凸台"特征，只是两个尺寸参数，不该拆成两个特征。
    merged = {}
    order = []
    for f in features:
        if not f["semantic_type"] or f["semantic_type"] == "part":
            continue
        parent = f["path"].rsplit("/", 1)[0] if "/" in f["path"] else ""
        key = (parent, f["semantic_type"])
        if key not in merged:
            merged[key] = {"name": f["name"], "path": f["path"],
                           "type": f["semantic_type"], "role": f["role"],
                           "dims": {}, "members": []}
            order.append(key)
        merged[key]["dims"].update(f["dims"])
        merged[key]["members"].append(f["name"])
    sem_feats = [merged[k] for k in order]

    # 兜底：Measures 里没抓到但注释带语义的（第 2 路线索）
    for c in comments:
        ftype, role = _match_root(c)
        if ftype and not any(x["type"] == ftype for x in sem_feats):
            sem_feats.append({"name": c[:40], "path": "comment",
                              "type": ftype, "role": role,
                              "dims": {}, "members": [], "source": "comment"})

    return {
        "source": source,
        "semantics": {                       # ← 三维语义层（本次要的）
            "root_var": root_var,
            "features": sem_feats,
            "n_features": len(sem_feats),
        },
        "structure": {                       # ← 结构层
            "ops_count": structure,
            "kinds": kind,
        },
        "operations": ops,                   # ← 操作层（精简版）
        "comments": comments,                # ← 语义补注
        "drawing": None,                     # ← 数据集给不了，留空（靠图纸补）
        "stats": {
            "n_ops": len(ops),
            "n_comments": len(comments),
            "n_semantic_features": len(sem_feats),
            "has_measures": bool(features),
        },
    }


# ----------------------------------------------------------------------
# 批量跑 parquet
# ----------------------------------------------------------------------
def run_parquet(path, limit=None, out_dir=None):
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("需要 pyarrow：sudo pip3 install pyarrow")

    t = pq.read_table(path, columns=["uuid", "cadquery_file"])
    n = t.num_rows if limit is None else min(limit, t.num_rows)
    results = []
    stat = {"ok": 0, "semantic_hit": 0, "with_comments": 0, "total_feats": 0}
    for i in range(n):
        uuid = t.column("uuid")[i].as_py()
        c = t.column("cadquery_file")[i].as_py()
        if isinstance(c, bytes):
            c = c.decode("utf-8", "ignore")
        r = distill(c, source=uuid)
        results.append({"uuid": uuid, **r})
        if r["stats"]["n_ops"] > 0:
            stat["ok"] += 1
        if r["stats"]["n_semantic_features"] > 0:
            stat["semantic_hit"] += 1
        if r["stats"]["n_comments"] > 0:
            stat["with_comments"] += 1
        stat["total_feats"] += r["stats"]["n_semantic_features"]

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "z2c_semantics.jsonl"), "w",
                  encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("[蒸馏] 样本 %d 个" % n)
    print("[蒸馏] 解析成功 %d（%.1f%%）" % (stat["ok"], 100 * stat["ok"] / max(n, 1)))
    print("[蒸馏] 蒸馏出语义特征 %d（%.1f%%）"
          % (stat["semantic_hit"], 100 * stat["semantic_hit"] / max(n, 1)))
    print("[蒸馏] 平均特征数 %.2f" % (stat["total_feats"] / max(n, 1)))
    print("[蒸馏] 带注释 %d（%.1f%%）"
          % (stat["with_comments"], 100 * stat["with_comments"] / max(n, 1)))
    return results, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet")
    ap.add_argument("--code", help="单个 cadquery 文件")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.code:
        with open(args.code, encoding="utf-8") as f:
            code = f.read()
        print(json.dumps(distill(code, source=args.code),
                         ensure_ascii=False, indent=2))
        return
    if not args.parquet:
        ap.error("需要 --parquet 或 --code")
    run_parquet(args.parquet, args.limit, args.out)


if __name__ == "__main__":
    main()
