# -*- coding: utf-8 -*-
r"""check_naming.py —— 参数命名规范检查器

对应文档：docs/v3-命名规范与逻辑分层.md §2
纯静态扫描：只读 params.py 的源码，不导入、不执行、不改文件。

用法
----
    python tools/check_naming.py                  扫全项目所有 params.py
    python tools/check_naming.py parts/bracket    只扫指定零件目录
    python tools/check_naming.py --strict         warning 也计入失败（退出码非 0）

规则
----
    E1  数值进名          D_9 / PITCH9 / R2      —— 把数值改成语义名
    E2  单字母/过短名      L / W / T              —— 至少「部位+量型」两段
    E3  D 表距离          D_SIDE（注释写"中心距离"）—— 中心距请用 P
    W1  量型不在封闭词表   首段之后的量型必须在 {L,R,D,T,H,P,N,ANG,C}
    W2  缺轴向后缀        量型是 L/T/H 却没写 X/Y/Z —— 轴混淆 bug 的温床
    W3  部位不在词表       首段应在 §2.1 的部位集合里
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

MEASURE = ("ANG", "L", "W", "R", "D", "T", "H", "P", "GAP", "N", "C")   # §2.2
PARTS = ("BASE", "WALL", "ARM", "EAR", "WIN", "BOSS", "NECK", "CEN",
         "CBORE", "PIN", "BODY", "HOLE", "HEAD", "OPENING", "SIDE")   # §2.1
NEED_AXIS = ("L", "W", "T", "H", "GAP", "C")   # 这几个量必然沿某轴量 → 必须带 X/Y/Z
AXES = ("X", "Y", "Z")
SKIP = {"TAG", "TITLE", "__all__", "__schema__"}
IO_SUFFIX = ("_DIR", "_PATH", "_FILE", "_IMG", "_PNG", "_URL", "_NOTE")  # 非几何参数

SEV_W = "warning"


def top_consts(path):
    """返回 (常量列表, 错误)。常量 = (行号, 名字, 该行原文)"""
    src = open(path, encoding="utf-8").read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return None, "语法错误 %s" % e
    lines = src.splitlines()
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    raw = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                    out.append((node.lineno, t.id, raw))
    return out, None


def comment_of(raw):
    i = raw.find("#")
    return raw[i + 1:].strip() if i >= 0 else ""


def check_one(name, comment):
    hits = []
    if name.endswith(IO_SUFFIX):        # 路径/文件名一类，不参与几何命名检查
        return hits
    toks = [t for t in name.split("_") if t]
    if not toks:
        return hits

    # E1 数值进名（分两级：纯数字 token = 尺寸值混进名字，必改；
    #               字母+数字 = 可能是序号，提示确认；X0/Y0/Z0 是约定的「起点」标记，豁免）
    numeric = []
    for t in toks:
        if re.fullmatch(r"[XYZ]\d+", t):
            continue                                  # 起点/坐标标记，豁免
        if t.isdigit() or any(c.isdigit() for c in t):
            numeric.append(t)
    if any(t.isdigit() for t in numeric):
        hits.append(("error", "E1", "名字含纯数字 %s —— 尺寸值不能进名字（D_9→BASE_HOLE_D）"
                     % ",".join(t for t in numeric if t.isdigit())))
    elif numeric:
        hits.append((SEV_W, "E1", "名字含数字 %s —— 若是尺寸值请去掉（PITCH9→BASE_HOLE_P）；"
                                  "若是序号（HOLE1/HOLE2）可保留"
                     % ",".join(numeric)))
    # E2 单字母 / 过短
    if len(toks) == 1 and len(toks[0]) <= 2:
        hits.append(("error", "E2", "「%s」过短 —— 至少「部位_量型」，如 T→BASE_T_Z" % name))

    has_axis = toks[-1] in AXES and len(toks) > 1
    body = toks[:-1] if has_axis else toks
    meas = next((t for t in body if t in MEASURE), None)
    part = toks[0]

    # E3 D 表距离
    if meas == "D" and re.search(r"距离|距|pitch|间距|中心到", comment, re.I):
        hits.append(("error", "E3", "D 只表示直径；注释是「%s」——中心距请改用 P"
                     % comment[:24]))
    # W1 量型不在词表
    if meas is None:
        hits.append((SEV_W, "W1", "找不到量型段（应在 %s）—— 名字应为 部位_[修饰_]量型[_方向]"
                     % "/".join(MEASURE)))
    # W2 缺轴向后缀
    elif meas in NEED_AXIS and not has_axis:
        hits.append((SEV_W, "W2", "量型 %s 必然沿某轴量，但没写 X/Y/Z —— 加上轴向可防轴混淆 bug"
                     % meas))
    # W3 部位不在词表（两种情况：量型跑到首位 / 首段不是部位）
    if len(toks) > 1 and part not in PARTS:
        if part in MEASURE:
            hits.append((SEV_W, "W3", "量型「%s」在首位 —— 规范是 部位_[修饰_]量型[_方向]"
                                      "（如 %s_XXX → XXX_%s）" % (part, part, part)))
        else:
            hits.append((SEV_W, "W3", "首段「%s」不在部位词表（%s）" % (part, "/".join(PARTS))))
    return hits


def collect_targets(args):
    if args:
        out = []
        for a in args:
            p = a if os.path.isabs(a) else os.path.join(ROOT, a)
            f = os.path.join(p, "params.py") if os.path.isdir(p) else p
            out.append(f if os.path.exists(f) else None)
        return out
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in (".venv", ".git", "__pycache__", "_msg", "history")]
        if "params.py" in filenames:
            out.append(os.path.join(dirpath, "params.py"))
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = sys.argv[1:] if argv is None else argv
    strict = "--strict" in argv
    args = [a for a in argv if not a.startswith("--")]

    files = [f for f in collect_targets(args) if f]
    if not files:
        print("没找到 params.py")
        return 1

    n_err = n_warn = 0
    total = 0
    for f in sorted(files):
        consts, err = top_consts(f)
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        print("\n%s" % rel)
        if err:
            print("    ✗ %s" % err)
            n_err += 1
            continue
        rows = []
        for lineno, name, raw in consts:
            if name in SKIP or name.startswith("__"):
                continue
            total += 1
            hits = check_one(name, comment_of(raw))
            if hits:
                rows.append((lineno, name, hits))
        if not rows:
            print("    ✓ 全部符合规范")
            continue
        for lineno, name, hits in rows:
            for sev, code, msg in hits:
                if sev == "error":
                    n_err += 1
                    mark = "✗"
                else:
                    n_warn += 1
                    mark = "!"
                print("    %s [%s] %-14s %s" % (mark, code, name, msg))

    print("\n" + "=" * 64)
    print("扫描 %d 个 params.py、%d 个参数：%d 个 error、%d 个 warning"
          % (len(files), total, n_err, n_warn))
    if n_err == 0 and (not strict or n_warn == 0):
        print("命名检查通过。")
        return 0
    print("命名检查未通过（改法见 docs/v3-命名规范与逻辑分层.md §2.6 对照表）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
