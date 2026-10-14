# -*- coding: utf-8 -*-
r"""rename_params.py —— 参数改名工具（标识符级替换）

为什么不用正则/文本替换：会误伤字符串、注释、以及形近变量。
本工具用 tokenize 精确定位 NAME token，只替换「整个标识符恰好等于旧名」的位置，
其余字节原样保留（注释、空格、缩进、数值一律不动）。

另有一个受控例外：dims_spec.py 里 `key="L"` 这种字符串**引用的是参数名**，
必须跟着改；而 `label="L"` 引用的是图纸标注语义名，**不能改**。
所以只对 `key="..."` 做定点替换，其他字符串一律不碰。

用法
----
    python tools/rename_params.py parts/bracket --map docs/rename_maps/bracket.json
    python tools/rename_params.py parts/bracket --map docs/rename_maps/bracket.json --dry
    --dry   只报告将要改什么，不写文件
"""
import io
import json
import os
import re
import sys
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# dims_spec 里 key="变量名" —— 这个字符串引用参数名，需要跟着改
KEY_STR = re.compile(r'(\bkey\s*=\s*)"([A-Za-z_][A-Za-z0-9_]*)"')
# dims_spec 里 rel="标注 = XXX" —— 这是给人读的推导说明，里面的标识符要跟着改
REL_STR = re.compile(r'(\brel\s*=\s*)"([^"]*)"')
# label="..." 是图纸标注语义名（s2_drawing 用、ref_spec.MARKS 也用它当 key）—— 绝不可改
WORD = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def line_offsets(src):
    offs, pos = [], 0
    for ln in src.splitlines(keepends=True):
        offs.append(pos)
        pos += len(ln)
    if not offs:
        offs.append(0)
    return offs, pos


def rename_identifiers(src, mapping):
    """只替换 NAME token；返回 (新源码, 替换次数)"""
    offs, total = line_offsets(src)

    def abs_pos(row, col):
        return offs[row - 1] + col

    pieces, last, n = [], 0, 0
    try:
        toks = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in toks:
            if tok.type == tokenize.NAME and tok.string in mapping:
                a, b = abs_pos(*tok.start), abs_pos(*tok.end)
                pieces.append(src[last:a])
                pieces.append(mapping[tok.string])
                last = b
                n += 1
    except (tokenize.TokenError, IndentationError) as e:
        raise SystemExit("tokenize 失败（%s）—— 文件可能有语法错误，先修好再改名" % e)
    pieces.append(src[last:])
    return "".join(pieces), n


def rename_key_strings(src, mapping):
    """只改 key="旧名" 这一种字符串"""
    n = 0

    def sub(m):
        nonlocal n
        new = mapping.get(m.group(2))
        if new is None:
            return m.group(0)
        n += 1
        return '%s"%s"' % (m.group(1), new)
    return KEY_STR.sub(sub, src), n


def rename_rel_strings(src, mapping):
    """只改 rel="...（推导说明）" 字符串里的标识符；label= 一律不碰"""
    n = 0

    def sub(m):
        nonlocal n

        def w(mm):
            nonlocal n
            new = mapping.get(mm.group(0))
            if new is None:
                return mm.group(0)
            n += 1
            return new
        return m.group(1) + '"' + WORD.sub(w, m.group(2)) + '"'
    return REL_STR.sub(sub, src), n


def target_files(part_dir):
    """零件目录下的全部 .py（含 steps/），按路径排序"""
    out = []
    for dirpath, dirnames, filenames in os.walk(part_dir):
        dirnames[:] = [d for d in dirnames
                       if d not in (".venv", ".git", "__pycache__", "_msg", "models")]
        for f in sorted(filenames):
            if f.endswith(".py"):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry" in argv
    args = [a for a in argv if not a.startswith("--")]

    map_path = None
    for i, a in enumerate(argv):
        if a == "--map" and i + 1 < len(argv):
            map_path = argv[i + 1]
        elif a.startswith("--map="):
            map_path = a.split("=", 1)[1]
    args = [a for a in args if a != map_path]

    if not args or not map_path:
        print(__doc__)
        return 1

    part_dir = args[0] if os.path.isabs(args[0]) else os.path.join(ROOT, args[0])
    map_file = map_path if os.path.isabs(map_path) else os.path.join(ROOT, map_path)
    if not os.path.isdir(part_dir):
        print("零件目录不存在：%s" % part_dir)
        return 1
    if not os.path.exists(map_file):
        print("映射表不存在：%s" % map_file)
        return 1

    mapping = json.load(open(map_file, encoding="utf-8"))
    mapping = {k: v for k, v in mapping.items() if k != v}      # 去掉自身映射
    print("零件：%s" % os.path.relpath(part_dir, ROOT).replace("\\", "/"))
    print("映射：%d 条（%s）" % (len(mapping), os.path.relpath(map_file, ROOT).replace("\\", "/")))
    if dry:
        print("模式：--dry（只报告，不写文件）")

    files = target_files(part_dir)
    print("扫描：%d 个 .py\n" % len(files))

    total_id = total_key = total_rel = 0
    changed_files = []
    for path in files:
        src = open(path, encoding="utf-8").read()
        new, n_id = rename_identifiers(src, mapping)
        new, n_key = rename_key_strings(new, mapping)
        new, n_rel = rename_rel_strings(new, mapping)
        if n_id or n_key or n_rel:
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            print("  %-46s 标识符 %-3d key %-2d rel %d" % (rel, n_id, n_key, n_rel))
            changed_files.append(rel)
            total_id += n_id
            total_key += n_key
            total_rel += n_rel
            if not dry:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(new)

    print("\n合计：%d 个文件、%d 处标识符、%d 处 key、%d 处 rel"
          % (len(changed_files), total_id, total_key, total_rel))
    if dry:
        print("（--dry 模式，未写入任何文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
