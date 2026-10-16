# -*- coding: utf-8 -*-
r"""batch.py —— 12 件批量：PDF → 三维 → 对拍真值，逐轮收敛

用法
    python batch.py                 # 跑全部 12 件
    python batch.py --pool train    # 只跑训练池
    python batch.py --only sj-010   # 只跑一件（调试用）
    python batch.py --json out.json # 落盘明细
"""
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DATA = r"D:/桌面文件/胀断器/新建文件夹 (2)/生产图纸/生产图纸"


def load_pools():
    with open(os.path.join(HERE, "pools.json"), encoding="utf-8") as f:
        return json.load(f)


def run_one(pid, p, out_dir):
    """把 pools.json 的一条跑成三维。返回结果 dict（不抛异常）。"""
    import views_to_3d
    pdf = os.path.join(DATA, p["pdf"])
    step = os.path.join(DATA, p["step"])
    r = {"pid": pid, "name": p["name"], "pool": p["pool"]}
    try:
        res = views_to_3d.run(pdf, step if os.path.exists(step) else None, out_dir)
        r.update(res)
        if res.get("ok"):
            d = res.get("diff", {})
            r["verdict"] = "PASS" if abs(d.get("volume_pct", 99)) < 1.0 else "MISMATCH"
        else:
            r["verdict"] = "FAIL"
    except Exception as e:
        r["verdict"] = "ERROR"
        r["why"] = "%s: %s" % (type(e).__name__, str(e)[:90])
        r["trace"] = traceback.format_exc()[-400:]
    return r


def why(res):
    if res.get("why"):
        return res["why"]
    if res.get("verdict") == "MISMATCH":
        return "体积差 %.2f%%" % res.get("diff", {}).get("volume_pct", 0)
    # 失败时给线索
    bits = []
    if not res.get("measured_diameters_mm"):
        bits.append("无圆")
    if res.get("thickness_mm") is None:
        bits.append("无厚度")
    if not res.get("views"):
        bits.append("无视图")
    return " / ".join(bits) or "-"


def main(argv):
    only = pool = None
    out_json = None
    i = 0
    while i < len(argv):
        if argv[i] == "--only":
            only = argv[i + 1]; i += 2; continue
        if argv[i] == "--pool":
            pool = argv[i + 1]; i += 2; continue
        if argv[i] == "--json":
            out_json = argv[i + 1]; i += 2; continue
        i += 1

    pools = load_pools()
    items = [(pid, p) for pid, p in sorted(pools["parts"].items())
             if (not only or pid == only) and (not pool or p["pool"] == pool)]

    out_dir = os.path.join(HERE, "built")
    results = []
    print("%-8s %-13s %-6s %-9s %8s %9s  %s"
          % ("图号", "零件", "池", "结果", "体积差%", "实测Ø", "原因"))
    print("-" * 96)
    for pid, p in items:
        r = run_one(pid, p, out_dir)
        results.append(r)
        md = r.get("measured_diameters_mm") or []
        print("%-8s %-13s %-6s %-9s %8s %9s  %s"
              % (pid, p["name"][:13], p["pool"], r["verdict"],
                 ("%+.3f" % r["diff"]["volume_pct"]) if r.get("diff") else "-",
                 ",".join("%.2f" % d for d in md[:3]) or "-",
                 why(r)))

    ok = [r for r in results if r.get("verdict") == "PASS"]
    print("-" * 96)
    print("PASS %d / %d" % (len(ok), len(results)))
    for pool_name in ("train", "test"):
        sub = [r for r in results if r["pool"] == pool_name]
        if sub:
            print("  %-6s %d/%d" % (pool_name,
                                    sum(1 for r in sub if r.get("verdict") == "PASS"),
                                    len(sub)))
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
        print("明细已写:", out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
