# -*- coding: utf-8 -*-
r"""pool_guard.py —— 训练/测试分池准入检查（可执行，不靠记性）

解决的问题：read（读图）这一步**永远不许看到 test 池的三维真值**，
否则就是把答案抄进学习。这条靠人记会忘，所以做成会报错的检查。

用法
----
    python pool_guard.py list                         # 打印分池清单
    python pool_guard.py check --role read  <文件…>   # 准入检查；违规退出码 1
    python pool_guard.py check --role judge <文件…>   # 评判阶段；允许 test 的 STEP

角色
----
    read   读图 / 调参 / 合成训练数据  → 只许 train 池的 STEP；test 的 STEP 一律违规
    judge  最终评判                    → test / assembly 的 STEP 合法；contaminated 一律违规

文件可用完整路径、文件名，或零件号（sj-00x）。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POOLS = os.path.join(HERE, "pools.json")


def load():
    with open(POOLS, encoding="utf-8") as f:
        return json.load(f)


def index(pools):
    """把 pools.json 摊平成 {标识 -> (零件号, 池, 角色标签)}，标识含零件号/名/各文件名。"""
    idx = {}

    def put(key, pid, pool, tag):
        if key:
            idx[os.path.basename(str(key)).lower()] = (pid, pool, tag)

    for pid, p in pools["parts"].items():
        put(pid, pid, p["pool"], "part")
        put(p["name"], pid, p["pool"], "part")
        for kind in ("pdf", "dwg", "step"):
            put(p.get(kind), pid, p["pool"], kind)
    a = pools["assembly"]
    put(a["step"], "装配体", a["pool"], "step")
    put(a["name"], "装配体", a["pool"], "assembly")
    for pid, c in pools.get("contaminated", {}).items():
        put(pid, pid, "contaminated", "part")
        put(c["name"], pid, "contaminated", "part")
        for kind in ("pdf", "dwg", "step"):
            put(c.get(kind), pid, "contaminated", kind)
    return idx


def cmd_list(pools):
    print("池        零件号     名称            面数  说明")
    print("-" * 72)
    order = {"train": 0, "test": 1, "contaminated": 2}
    for pid, p in sorted(pools["parts"].items(),
                         key=lambda kv: (order.get(kv[1]["pool"], 9), kv[0])):
        print("%-9s %-10s %-14s %5d  %s"
              % (p["pool"], pid, p["name"], p["faces"], p.get("class", "")))
    for pid, c in pools.get("contaminated", {}).items():
        print("%-9s %-10s %-14s %5d  %s" % ("contaminated", pid, c["name"],
                                            c["faces"], c["why"][:30]))
    a = pools["assembly"]
    print("%-9s %-10s %-14s %5d  %s" % (a["pool"], "—", a["name"], a["faces"], a["why"][:24]))
    sc = pools["split_check"]
    print("-" * 72)
    print("train %d 件 / test %d 件 / 污染 %d 件 / 装配体 1"
          % (sc["train"]["n"], sc["test"]["n"], sc["contaminated"]["n"]))
    print("垫片族拆分：", sc["gaskets_split"])
    return 0


def cmd_check(pools, role, files):
    idx = index(pools)
    bad, unknown, ok = [], [], []
    for raw in files:
        key = os.path.basename(raw).lower()
        hit = idx.get(key)
        if not hit:
            # 允许用零件号模糊匹配
            for k, v in idx.items():
                if raw.lower() in k or k in raw.lower():
                    hit = v
                    break
        if not hit:
            unknown.append(raw)
            continue
        pid, pool, tag = hit
        # ---- 规则 ----
        if pool == "contaminated":
            bad.append((raw, pid, pool, "污染池：被真值修正过，任何阶段都不许用"))
        elif role == "read":
            if pool in ("test", "test_only") and tag in ("step", "assembly"):
                bad.append((raw, pid, pool,
                            "读图/调参阶段不许看 test 的三维真值 —— 这是把答案抄进学习"))
            elif pool in ("test", "test_only"):
                ok.append((raw, pid, pool, "二维输入，train/test 皆可读"))
            else:
                ok.append((raw, pid, pool, "train 池"))
        elif role == "judge":
            ok.append((raw, pid, pool, "评判阶段允许" if pool.startswith("test") else "train"))
        else:
            bad.append((raw, pid, pool, "未知 role=%s" % role))

    print("role=%s，共 %d 个输入" % (role, len(files)))
    for raw, pid, pool, why in ok:
        print("  ✅ %-42s %s/%s  %s" % (raw[:42], pid, pool, why))
    for raw in unknown:
        print("  ⚠️ %-42s 不在分池清单里（新零件需先登记）" % raw[:42])
    for raw, pid, pool, why in bad:
        print("  ❌ %-42s %s/%s  %s" % (raw[:42], pid, pool, why))
    if bad:
        print("\n准入失败：%d 项违规" % len(bad))
        return 1
    print("\n准入通过（%d 项；%d 项未登记）" % (len(ok), len(unknown)))
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    pools = load()
    if argv[0] == "list":
        return cmd_list(pools)
    if argv[0] == "check":
        if len(argv) < 2 or not argv[1].startswith("--role"):
            print("需要 --role read|judge"); return 2
        role = argv[1].split("=", 1)[1] if "=" in argv[1] else argv[2]
        rest = argv[2:] if "=" in argv[1] else argv[3:]
        return cmd_check(pools, role, rest)
    print("未知子命令:", argv[0]); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
