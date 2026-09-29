# -*- coding: utf-8 -*-
r"""铰链支座 —— 校核：三维投影 vs 图纸基准；循环上限 3 轮，每轮写日志"""
import json
import os
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "bracket_log.md")
DATA = os.path.join(HERE, "_bracket_data.json")
MAXIT = 10

REF = [
    ("底板长 (X)", 62.0), ("俯视外接 (Y)", 46.0), ("主视总高", 37.0),
]
TOL = 0.3
# 分视图核对：同一个圆被投影切成多段时，按 (r, cx, cy) 去重后只算 1 个
#   Top  —— 轴沿 Z 的孔显示为圆：2-φ9
#   Front—— 轴沿 Y 的孔显示为圆：2-φ6（沉孔）/ 2-φ3（通孔）
#   Right—— 轴沿 X 的孔显示为圆：2-φ8（两臂重合成 1）；圆头 R10 两臂重合
EXPECT = [
    ("Top",   "底板孔 φ9", 4.5, 2),
    ("Front", "台阶孔 φ6", 3.0, 2),
    ("Front", "台阶孔 φ3", 1.5, 2),
    ("Right", "圆头 R10", 10.0, 1),
    ("Right", "销孔 φ8", 4.0, 1),
]


def log(s=""):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")


def ccount(v):
    """同半径且同心 (r,cx,cy) 的多段弧合并为 1 个圆，再按半径计数"""
    uniq = {(round(c["r"], 2), round(c["cx"], 1), round(c["cy"], 1)) for c in v["circles"]}
    return Counter(r for r, _, _ in uniq)


def collect():
    d = json.load(open(DATA, encoding="utf-8"))
    g = lambda n: next(v for v in d["views"] if v["name"] == n)
    top, front, right = g("Top"), g("Front"), g("Right")
    def span(v, i):
        q = [p[i] for e in v["edges"] for p in e]
        return round(max(q) - min(q), 3)
    return {
        "len_x": span(top, 0), "wid_y": span(top, 1),
        "hgt": span(front, 1), "right_x": span(right, 0),
        "cnt": {nm: ccount(v) for nm, v in (("Top", top), ("Front", front), ("Right", right))},
    }


def check(cur):
    iss = []
    if abs(cur["len_x"] - 62.0) > TOL:
        iss.append(("底板长", 62.0, cur["len_x"]))
    if abs(cur["wid_y"] - 46.0) > TOL:            # 圆头最左 -22 到臂右端 +24
        iss.append(("俯视外接", 46.0, cur["wid_y"]))
    if abs(cur["hgt"] - 37.0) > TOL:              # 圆头圆心高 27 + R10
        iss.append(("主视总高", 37.0, cur["hgt"]))
    for vn, label, r, n in EXPECT:
        got = cur["cnt"][vn].get(round(r, 2), 0)
        if got != n:
            iss.append(("%s·%s（圆个数）" % (vn, label), n, got))
    return iss


def main():
    it = 1
    for a in sys.argv:
        if a.startswith("--iter="):
            it = int(a.split("=", 1)[1])
    cur = collect()
    iss = check(cur)
    print("\n" + "=" * 68)
    print("【几何比对】三维投影 vs 图纸基准（第 %d 轮 / 上限 %d）" % (it, MAXIT))
    print("-" * 68)
    print("  俯视外接   基准 62.00 × 46.00   当前 %.2f × %.2f" % (cur["len_x"], cur["wid_y"]))
    print("  主视总高   基准 37.00(=27+R10) 当前 %.2f" % cur["hgt"])
    print("  侧视外接   基准 46.00(=10+36)  当前 %.2f" % cur["right_x"])
    for vn, label, r, n in EXPECT:
        got = cur["cnt"][vn].get(round(r, 2), 0)
        mark = "OK" if got == n else "!!"
        print("  [%s] %-12s 期望 %d 个  实际 %d 个  %s" % (vn, label, n, got, mark))
    if iss:
        print("  → 不符 %d 处：" % len(iss))
        for a_, b_, c_ in iss:
            print("     ! %-20s 基准 %-8s 当前 %-8s" % (a_, b_, c_))
    else:
        print("  → 与基准一致 ✓")

    log()
    log("### 第 %d 轮（铰链支座，上限 %d）" % (it, MAXIT))
    log()
    log("- 外接 %.2f × %.2f（基准 62 × 24）" % (cur["len_x"], cur["wid_y"]))
    if iss:
        log("- 不符 **%d** 处：" % len(iss))
        for a_, b_, c_ in iss:
            log("  - %s：基准 %s / 当前 %s" % (a_, b_, c_))
    else:
        log("- 结果：**通过**")
    log()
    print("\n日志已追加：", LOG)


if __name__ == "__main__":
    main()
