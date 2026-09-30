# -*- coding: utf-8 -*-
r"""guard.py —— 隔离校验器

静态扫描 steps/ 下的每个步骤脚本，检出违例即**非零退出**（驱动器会拒绝运行）。
目的：把「只允许通过消息传输」从约定变成机制。

静态能查的（本文件）：
  1. 直接 import 人的输入模块（params / ref_spec / dims_spec）—— 应改用 exec_module 按消息加载
  2. import 其他步骤 —— 步骤之间不得互相依赖
  3. 出现硬编码盘符路径 —— 应走消息 in.data 或环境变量
  4. 没有走消息入口 —— 必须调用 boot(...) 或 run_stage(...)

静态查不到的（由 pipe.py 在运行时强制）：
  5. 只有 s8_apply 允许修改 params.py —— 每步执行前后比对 params.py 的 sha256
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = os.path.join(HERE, "steps")

RULES = [
    ("直接 import 人的输入模块（应 exec_module 按消息声明的路径加载）",
     re.compile(r"^\s*(?:import|from)\s+(params|ref_spec|dims_spec)\b", re.M)),
    ("import 其他步骤（步骤之间不得互相依赖）",
     re.compile(r"^\s*(?:import|from)\s+s\d+_", re.M)),
    ("出现硬编码盘符路径（应走消息 in.data 或环境变量）",
     re.compile(r"['\"][A-Za-z]:[\\/]")),
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if not os.path.isdir(STEPS):
        print("找不到 steps/ 目录：%s" % STEPS)
        return 1

    files = sorted(f for f in os.listdir(STEPS) if f.endswith(".py"))
    if not files:
        print("steps/ 下没有步骤脚本")
        return 1

    bad = 0
    for f in files:
        txt = open(os.path.join(STEPS, f), encoding="utf-8").read()
        hits = []
        for name, pat in RULES:
            for m in pat.finditer(txt):
                line = txt[:m.start()].count("\n") + 1
                hits.append("%s\n       第 %d 行：%s" % (name, line, m.group(0).strip()))
        if "boot(" not in txt and "run_stage(" not in txt:
            hits.append("没有走消息入口（必须调用 boot(...) 或 run_stage(...)）")
        if hits:
            bad += 1
            print("✗ %s" % f)
            for h in hits:
                print("    %s" % h)
        else:
            print("✓ %s" % f)

    print()
    if bad:
        print("隔离检查未通过：%d / %d 个步骤有违例" % (bad, len(files)))
        return 1
    print("隔离检查通过：%d 个步骤全部只通过消息通信" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
