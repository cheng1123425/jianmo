# -*- coding: utf-8 -*-
r"""z2c_mine_ops —— 从 Zero-to-CAD 的 ops 轨迹里**挖算子词表**（独立工具）
=====================================================================

**用途**：把 Zero-to-CAD 的 `cadquery_ops_json`（每个零件的建模操作轨迹）挖成一张
「候选算子榜」——即"该把哪些构造模式做成可复用的算子"。这是**词表设计的数据输入**。

**与项目主干解耦**：本工具**独立运行**，只读 parquet、只写报告：
  * 不 import 项目任何模块（lib / steps / msgio / pipe 都不碰）；
  * 不进流水线、不被 guard 管、不改任何主干文件；
  * 只依赖 `pyarrow` + 标准库。产物落在 `--out` 目录。
  * 与 `tools/z2c_distill.py`（挖**语义**）互补：本工具挖**算子**（怎么建）。

**挖三层**（对应"从具体轨迹 → 泛化成算子"的候选发现）：

  L1 单算子    leaf op（如 extrude / circle / fillet）→ 原语词表
  L2 惯用法    链式路径（如 cq.Workplane.rect.extrude）→ 复合模式
  L3 序列      op 序列 n-gram（如 circle→extrude→faces→workplane）→ 长模式

每种都统计 **出现次数** 与 **覆盖零件数**（coverage）——覆盖广的才值得做成算子。

用法
----
    python tools/z2c_mine_ops.py --parquet 验证报告/z2c_sample.parquet \
        --out 验证报告/z2c_mined --top 40
"""
import argparse
import collections
import json
import os
import sys

# 数据集里夹带的"非建模"操作（测量/控制面），从候选算子榜里剔除，避免污染词表
NON_MODELING = {
    "Measures", "range", "len", "print", "self.build", "abs", "round",
    "min", "max", "int", "float", "str", "list", "set", "dict", "enumerate",
    "zip", "map", "filter", "sorted", "sum", "any", "all", "bool", "tuple",
    "getattr", "setattr", "hasattr", "__import__", "compile", "eval", "exec",
}


def _load_rows(parquet, limit=None, columns=("uuid", "cadquery_ops_json", "cadquery_ops_count")):
    import pyarrow.parquet as pq
    t = pq.read_table(parquet, columns=list(columns))
    rows = t.to_pylist()
    return rows[:limit] if limit else rows


def _parse_ops(raw):
    """一条记录的 ops 轨迹 → [{"op_name","function","args","keywords"}, ...]。"""
    if raw is None:
        return []
    try:
        ops = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    out = []
    for o in ops or []:
        if not isinstance(o, dict):
            continue
        out.append({
            "op_name": o.get("op_name") or o.get("function") or o.get("name"),
            "function": o.get("function"),
            "args": o.get("args") or [],
            "keywords": o.get("keywords") or [],
        })
    return out


def mine(rows, top=40, ngram=3):
    """返回统计结果 dict。"""
    leaf = collections.Counter()               # L1 op_name 次数
    leaf_cov = collections.defaultdict(set)    # op_name → 覆盖的零件 uuid
    path = collections.Counter()               # L2 链式路径次数
    path_cov = collections.defaultdict(set)
    ng = collections.defaultdict(collections.Counter)   # L3 n → Counter(gram)
    ng_cov = collections.defaultdict(lambda: collections.defaultdict(set))

    n_parts = 0
    ops_per_part = []
    for r in rows:
        ops = _parse_ops(r.get("cadquery_ops_json"))
        if not ops:
            continue
        n_parts += 1
        uid = r.get("uuid") or ("part%d" % n_parts)
        names = []
        for o in ops:
            nm = o["op_name"]
            fp = o["function"]
            names.append(nm)
            if nm:
                leaf[nm] += 1
                leaf_cov[nm].add(uid)
            if fp:
                path[fp] += 1
                path_cov[fp].add(uid)
        ops_per_part.append(len(ops))
        for n in range(2, ngram + 1):
            for i in range(len(names) - n + 1):
                g = tuple(names[i:i + n])
                ng[n][g] += 1
                ng_cov[n][g].add(uid)

    def _rank(counter, cov, filt=None, k=top):
        items = []
        for key, cnt in counter.items():
            if filt and not filt(key):
                continue
            items.append({
                "key": list(key) if isinstance(key, tuple) else key,
                "count": cnt,
                "parts": len(cov.get(key, ())),
                "coverage": round(len(cov.get(key, ())) / n_parts, 4) if n_parts else 0,
            })
        items.sort(key=lambda d: (-d["parts"], -d["count"]))
        return items[:k]

    def _is_modeling(name):
        base = name.split(".")[-1] if name else ""
        return name not in NON_MODELING and base not in NON_MODELING

    return {
        "n_parts": n_parts,
        "ops_per_part": {
            "min": min(ops_per_part) if ops_per_part else 0,
            "max": max(ops_per_part) if ops_per_part else 0,
            "avg": round(sum(ops_per_part) / len(ops_per_part), 1) if ops_per_part else 0,
        },
        "L1_leaf": _rank(leaf, leaf_cov),
        "L1_leaf_modeling": _rank(leaf, leaf_cov, filt=_is_modeling),
        "L2_path": _rank(path, path_cov),
        "L3_ngram": {n: _rank(ng[n], ng_cov[n]) for n in ng},
    }


def _md(res, top):
    L = []
    L.append("# Zero-to-CAD 算子挖掘报告（候选算子榜）\n")
    L.append("> 工具 `tools/z2c_mine_ops.py`（独立于主干）。目的是给「算子词表该做什么」"
             "提供**数据依据**：覆盖零件数越多的模式越值得做成算子。\n")
    L.append("样本：**%d** 个零件 | 每零件 op 数 min/max/avg = %d/%d/%s\n"
             % (res["n_parts"], res["ops_per_part"]["min"], res["ops_per_part"]["max"],
                res["ops_per_part"]["avg"]))

    L.append("\n## L1 单算子（leaf op）—— 原语词表候选\n")
    L.append("| op | 出现次数 | 覆盖零件 | 覆盖率 |")
    L.append("|---|---|---|---|")
    for d in res["L1_leaf_modeling"][:top]:
        L.append("| `%s` | %d | %d | %.0f%% |" % (d["key"], d["count"], d["parts"], d["coverage"] * 100))

    L.append("\n## L2 链式路径（function）—— 惯用法/复合模式候选\n")
    L.append("| 链式路径 | 出现次数 | 覆盖零件 | 覆盖率 |")
    L.append("|---|---|---|---|")
    for d in res["L2_path"][:top]:
        L.append("| `%s` | %d | %d | %.0f%% |" % (d["key"], d["count"], d["parts"], d["coverage"] * 100))

    for n in sorted(res["L3_ngram"]):
        L.append("\n## L3 序列模式（%d-gram op 序列）\n" % n)
        L.append("| 序列 | 出现次数 | 覆盖零件 | 覆盖率 |")
        L.append("|---|---|---|---|")
        for d in res["L3_ngram"][n][:top]:
            L.append("| `%s` | %d | %d | %.0f%% |"
                     % (" → ".join(d["key"]), d["count"], d["parts"], d["coverage"] * 100))
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="从 Zero-to-CAD ops 轨迹挖算子词表（独立工具）")
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--out", required=True, help="报告输出目录")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--limit", type=int, default=None, help="只取前 N 条样本")
    a = ap.parse_args(argv)

    rows = _load_rows(a.parquet, a.limit)
    res = mine(rows, top=a.top)
    os.makedirs(a.out, exist_ok=True)
    jf = os.path.join(a.out, "op_candidates.json")
    mf = os.path.join(a.out, "op_candidates.md")
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    with open(mf, "w", encoding="utf-8") as f:
        f.write(_md(res, a.top))
    print("[z2c_mine_ops] %d 零件 → %s" % (res["n_parts"], mf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
