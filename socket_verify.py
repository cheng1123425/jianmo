# -*- coding: utf-8 -*-
r"""
多耳球铰盖 —— 校核：三维投影 vs 图纸基准
每轮的问题写进 socket_log.md（格式与 loop_log.md 一致）
"""
import json
import os
import sys
import time
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "socket_log.md")
DATA = os.path.join(HERE, "_socket_data.json")

# ---------------- 图纸基准（B 向视图 + A-A 剖视 + 轴测） ----------------
REF = [
    ("外接总长 (X)", 45.0, "B 向视图"),
    ("外接总宽 (Y)", 35.0, "B 向视图"),
    ("总高 (Z)", 7.0, "A-A 剖视 6+1"),
    ("台阶长", 40.0, "B 向视图"),
    ("台阶宽", 30.0, "B 向视图"),
    ("孔心距 X", 32.0, "俯视图"),
    ("孔心距 Y", 22.0, "俯视图"),
    ("中心圆 φ", 22.5, "A-A 剖视 Sφ22.5"),
]
TOL = 0.2
# 期望的圆特征：半径 → 个数
EXPECT = [("外形圆角 R4", 4.0, 4), ("台阶圆角 R2", 2.0, 4),
          ("通孔 φ3", 1.5, 4), ("沉孔 φ6", 3.0, 4),
          ("耳部凹弧（4 处凹口，腰宽 10）", 6.0, 4)]
EXPECT_ATLEAST = [("球窝口 φ22.5 圆弧", 11.25, 1)]


def log(s=""):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")


def collect():
    d = json.load(open(DATA, encoding="utf-8"))
    top = next(v for v in d["views"] if v["name"] == "Top")
    front = next(v for v in d["views"] if v["name"] == "Front")
    xs = [q[0] for e in top["edges"] for q in e]
    ys = [q[1] for e in top["edges"] for q in e]
    fy = [q[1] for e in front["edges"] for q in e]
    return {
        "len_x": round(max(xs) - min(xs), 3),
        "len_y": round(max(ys) - min(ys), 3),
        "height": round(max(fy) - min(fy), 3),
        "circle_cnt": Counter(round(c["r"], 2) for c in top["circles"]),
        "n_edges_top": len(top["edges"]),
    }


def check(cur):
    issues = []

    def add(name, base, now, note=""):
        issues.append({"name": name, "base": base, "now": now,
                       "dev": None if now is None else now - base, "note": note})

    vals = {"外接总长 (X)": cur["len_x"], "外接总宽 (Y)": cur["len_y"], "总高 (Z)": cur["height"]}
    for name, base, src in REF:
        if name in vals:
            if abs(vals[name] - base) > TOL:
                add(name, base, vals[name], src)
    if abs(cur["len_x"] - 45.0) <= TOL and abs(cur["len_y"] - 35.0) <= TOL:
        pass

    for label, r, n in EXPECT:
        got = cur["circle_cnt"].get(round(r, 2), 0)
        if got != n:
            add(label, n, got, "圆个数（半径 %.2f）" % r)
    for label, r, n in EXPECT_ATLEAST:
        got = cur["circle_cnt"].get(round(r, 2), 0)
        if got < n:
            add(label, "≥%d" % n, got, "圆弧缺失（半径 %.2f）" % r)
    return issues, vals


def report(issues, vals, cur):
    print("\n" + "=" * 70)
    print("【几何比对】三维投影 vs 图纸基准")
    print("-" * 70)
    print("  外接     基准 45.0 × 35.0      当前 %.1f × %.1f" % (vals["外接总长 (X)"], vals["外接总宽 (Y)"]))
    print("  总高     基准 7.0             当前 %.1f" % vals["总高 (Z)"])
    print("  俯视可见边数 %d" % cur["n_edges_top"])
    if issues:
        print("  → 发现 %d 处不符：" % len(issues))
        for x in issues:
            d = "" if x["dev"] is None else "（差 %+.2f）" % x["dev"]
            print("     ! %-16s 基准 %-8s 当前 %-8s %s%s" % (x["name"], x["base"], x["now"], d, x["note"]))
    else:
        print("  → 与基准一致 ✓")
    print("\n【结论】")
    print("-" * 70)
    print("  通过" if not issues else "  **未通过**（详见上面的不符项）")


def main():
    it = 1
    for a in sys.argv:
        if a.startswith("--iter="):
            it = int(a.split("=", 1)[1])
    if not os.path.exists(DATA):
        raise SystemExit("先跑 socket_draw.py 生成投影数据")

    cur = collect()
    issues, vals = check(cur)
    report(issues, vals, cur)

    log()
    log("### 第 %d 轮（多耳球铰盖）" % it)
    log()
    log("- 外接：%.1f × %.1f（基准 45 × 35）　总高 %.1f（基准 7）"
        % (vals["外接总长 (X)"], vals["外接总宽 (Y)"], vals["总高 (Z)"]))
    if issues:
        log("- 不符 **%d** 处：" % len(issues))
        for x in issues:
            d = "" if x["dev"] is None else "（差 %+.2f）" % x["dev"]
            log("  - %s：基准 %s / 当前 %s %s%s" % (x["name"], x["base"], x["now"], d, x["note"]))
    else:
        log("- 结果：**通过**")
    log()
    print("\n日志已追加：", LOG)


if __name__ == "__main__":
    main()
