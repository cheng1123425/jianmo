# -*- coding: utf-8 -*-
r"""架构改动影响面分析器 —— 改完架构跑一次，就知道要不要重写产品。

原理
    1. 扫架构模块（msgio / lib.* / facelevels），用 AST 提取对外符号与函数签名
    2. 扫所有 parts/*/steps/*.py，提取每个产品文件 import 了哪些架构符号
    3. 与基线快照对比：符号被删 / 签名被改 → 定位到具体哪几个产品文件会断

用法
    python tools/arch_impact.py --snapshot   # 记录当前架构 API 基线（架构改动前先跑一次）
    python tools/arch_impact.py              # 对比当前 vs 基线，输出波及面
    python tools/arch_impact.py --strict     # 同上，但有破坏性变更时退出码 2（上传前检查用）
    python tools/arch_impact.py --deps       # 只看当前依赖关系表

退出码（--strict）
    0  无破坏性变更，或变更不影响任何产品文件
    2  删除/改签名后仍有产品依赖 → 禁止提交（见 MSG.md §〇 接口演进纪律）

输出解读
    删除的符号  → 调用点必然报错，必须改
    改签名的函数 → 调用点可能报错，要人工核对参数
    新增的符号  → 无需处理
"""
import ast
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASELINE = os.path.join(ROOT, "docs", "arch_api_baseline.json")

# 架构模块白名单（产品只允许依赖这些）
ARCH_MODULES = [
    "msgio",
    "facelevels",
    "lib.ir",
    "lib.collect",
    "lib.drawing_fc",
    "lib.drawing_render",
]


def mod2path(mod):
    """模块名 → 源码路径；找不到返回 None。"""
    if mod.startswith("lib."):
        p = os.path.join(ROOT, "lib", mod.split(".", 1)[1] + ".py")
        return p if os.path.exists(p) else None
    for c in (os.path.join(ROOT, mod + ".py"),
              os.path.join(ROOT, "tools", mod + ".py")):
        if os.path.exists(c):
            return c
    return None


def extract_api(path):
    """AST 提取一个架构模块的对外符号：函数名+参数列表 / 类名+公共方法。"""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    api = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            api[node.name] = {"kind": "func",
                              "args": [a.arg for a in node.args.args]}
        elif isinstance(node, ast.ClassDef):
            methods = {}
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef):
                    methods[sub.name] = [a.arg for a in sub.args.args]
            api[node.name] = {"kind": "class", "methods": methods}
    return api


def collect_arch_api():
    """扫所有架构模块，返回 {模块名: {符号: 定义}}。"""
    out = {}
    for mod in ARCH_MODULES:
        p = mod2path(mod)
        if p:
            out[mod] = extract_api(p)
    return out


def collect_deps():
    """扫所有产品 steps，返回 [(文件, 模块, 符号)]。"""
    deps = []
    files = sorted(glob.glob(os.path.join(ROOT, "parts", "*", "steps", "*.py")))
    for f in files:
        if "__pycache__" in f:
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
        except SyntaxError:
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                is_arch = mod in ARCH_MODULES or mod.startswith("lib.") or mod == "facelevels"
                if is_arch:
                    for a in node.names:
                        deps.append((rel, mod, a.name))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in ARCH_MODULES or a.name.startswith("lib."):
                        deps.append((rel, a.name, "*"))
    return deps


def impacted_files(deps, mod, symbol=None):
    """哪些产品文件依赖了 (模块, 符号)。"""
    hits = []
    for f, m, s in deps:
        if m != mod:
            continue
        if symbol is None or s == symbol or s == "*":
            hits.append(f)
    return sorted(set(hits))


def cmd_snapshot():
    api = collect_arch_api()
    os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
    with open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(api, f, ensure_ascii=False, indent=2)
    total = sum(len(v) for v in api.values())
    print("已记录架构 API 基线 → %s" % os.path.relpath(BASELINE, ROOT))
    print("  %d 个模块，%d 个对外符号" % (len(api), total))
    for mod in sorted(api):
        print("    %-20s %d 个符号" % (mod, len(api[mod])))


def cmd_deps():
    deps = collect_deps()
    print("产品 → 架构 依赖表（共 %d 条）" % len(deps))
    print("")
    bymod = {}
    for f, m, s in deps:
        bymod.setdefault((m, s), []).append(f)
    for (m, s) in sorted(bymod):
        files = sorted(set(bymod[(m, s)]))
        print("  %s.%s" % (m, s))
        for f in files:
            print("      ← %s" % f)


def cmd_report(strict=False):
    if not os.path.exists(BASELINE):
        print("没有基线，先跑：python tools/arch_impact.py --snapshot")
        return 1
    with open(BASELINE, encoding="utf-8") as f:
        old = json.load(f)
    new = collect_arch_api()
    deps = collect_deps()

    removed, changed, added = [], [], []
    for mod in sorted(set(old) | set(new)):
        o, n = old.get(mod, {}), new.get(mod, {})
        for sym in o:
            if sym not in n:
                removed.append((mod, sym))
            elif o[sym].get("args") != n[sym].get("args"):
                changed.append((mod, sym, o[sym].get("args"), n[sym].get("args")))
            elif o[sym].get("kind") == "class" and \
                    o[sym].get("methods") != n[sym].get("methods"):
                changed.append((mod, sym, None, None))
        for sym in n:
            if sym not in o:
                added.append((mod, sym))

    print("=" * 60)
    print("架构改动影响面报告")
    print("=" * 60)

    hit = set()
    if removed:
        print("")
        print("[删除的符号] 调用点必然报错，必须改")
        for mod, sym in removed:
            files = impacted_files(deps, mod, sym)
            hit.update(files)
            print("  %s.%s" % (mod, sym))
            for f in files:
                print("      × %s" % f)
            if not files:
                print("      （无产品文件依赖）")

    if changed:
        print("")
        print("[改签名的符号] 调用点要核对参数")
        for mod, sym, oa, na in changed:
            files = impacted_files(deps, mod, sym)
            hit.update(files)
            print("  %s.%s" % (mod, sym))
            if oa is not None:
                print("      (%s) → (%s)" % (", ".join(oa), ", ".join(na)))
            for f in files:
                print("      ! %s" % f)
            if not files:
                print("      （无产品文件依赖）")

    if added:
        print("")
        print("[新增的符号] 无需处理")
        for mod, sym in added:
            print("  + %s.%s" % (mod, sym))

    print("")
    print("-" * 60)
    total_files = len(set(f for f, _, _ in deps))
    if not removed and not changed:
        print("结论：架构对外 API 无破坏性变更 → 产品层 0 个文件需要重写")
        print("      （%d 个产品步骤文件全部不受影响）" % total_files)
        return 0

    print("结论：本次架构改动波及 %d 个产品文件（共 %d 个）" % (len(hit), total_files))
    for f in sorted(hit):
        print("    → %s" % f)
    print("")
    print("注意：波及的是 import 行与调用点，通常不是整个文件重写。")

    if strict and hit:
        print("")
        print("[严格模式] 存在破坏性变更且仍有产品依赖 —— 禁止提交。")
        print("  对策 ①：把老函数改成 3 行转发，保留兼容（见 MSG.md §〇-1）")
        print("  对策 ②：或先把这些产品迁完，确认 0 依赖后再删")
        return 2
    return 0


def main():
    args = sys.argv[1:]
    if "--snapshot" in args:
        cmd_snapshot()
    elif "--deps" in args:
        cmd_deps()
    else:
        return cmd_report(strict="--strict" in args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
