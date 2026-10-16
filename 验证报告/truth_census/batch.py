# -*- coding: utf-8 -*-
r"""batch.py —— 12 件批量：PDF → 三维 → 对拍真值，逐轮收敛

用法
    python batch.py                 # 跑全部 12 件
    python batch.py --pool train    # 只跑训练池
    python batch.py --only sj-010   # 只跑一件（调试用）
    python batch.py --json out.json # 落盘明细

数据根目录（2026-10-16 修：原来是写死的绝对路径，换机器必崩）
    TRUTH_DATA_ROOT = 指向「生产图纸/生产图纸」目录（含 *.pdf / *.STEP / *.DWG）
    例：  set TRUTH_DATA_ROOT=D:\工作内容\生产图纸\生产图纸      （cmd）
         $env:TRUTH_DATA_ROOT="D:\工作内容\生产图纸\生产图纸"     （PowerShell）

    解析顺序：① 环境变量 TRUTH_DATA_ROOT → ② pools.json 的 dataset.root → 报错
    报错信息里会把两条候选连路径一起打出来，照抄即可。
"""
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

#: 数据根目录的环境变量名（唯一入口，别再往本文件里写死绝对路径）
DATA_ENV = "TRUTH_DATA_ROOT"


def resolve_data_root(pools):
    """返回 (root, 来源)。三级解析都落空就 SystemExit，并给出可照抄的提示。

    为什么不再写死：原实现把 `D:/桌面文件/胀断器/新建文件夹 (2)/生产图纸/生产图纸`
    焊在代码里 —— 那是**建库那台机器**的路径，换一台机器直接 FileNotFoundError，
    且 pools.json / anno/*.json / geom/*.json / out/*.census.json 里各焊了一份。
    """
    cands = []
    env = os.environ.get(DATA_ENV)
    if env:
        cands.append((env, "环境变量 %s" % DATA_ENV))
    root = (pools.get("dataset") or {}).get("root")
    if root:
        cands.append((root, "pools.json 的 dataset.root"))
    for p, src in cands:
        if os.path.isdir(p):
            return p, src
    raise SystemExit(
        "找不到数据根目录（含 *.pdf / *.STEP / *.DWG 的那一层）。\n"
        "请先设置环境变量 %s，例如：\n"
        "    set %s=D:\\工作内容\\生产图纸\\生产图纸\n"
        "已试过：%s"
        % (DATA_ENV, DATA_ENV,
           "; ".join("%s（来源：%s）" % (p, s) for p, s in cands) or "无候选"))


def load_pools():
    with open(os.path.join(HERE, "pools.json"), encoding="utf-8") as f:
        return json.load(f)


def data_root():
    """便捷入口：自己读 pools.json 解析数据根目录，返回路径字符串。

    给 _diag_*.py / _proto_*.py 这类一次性脚本用，替代原来的
        D = r'D:/桌面文件/.../生产图纸/生产图纸'
    """
    return resolve_data_root(load_pools())[0]


def run_one(pid, p, out_dir, root):
    """把 pools.json 的一条跑成三维。返回结果 dict（不抛异常）。"""
    import views_to_3d
    pdf = os.path.join(root, p["pdf"]) if p.get("pdf") else None
    step = os.path.join(root, p["step"]) if p.get("step") else None
    r = {"pid": pid, "name": p["name"], "pool": p["pool"]}
    # 缺输入 ≠ 失败：记 SKIP 让批量继续跑（原实现会整件 FileNotFoundError，
    # 且看不出是"缺文件"还是"算法炸了"—— sj-001/sj-002 在本机没有矢量 PDF）。
    if not pdf or not os.path.exists(pdf):
        r["verdict"] = "SKIP"
        r["why"] = "无矢量 PDF（%s）→ 需走 DWG→DXF 支路" % (p.get("pdf") or "pools.json 未声明")
        return r
    try:
        res = views_to_3d.run(pdf, step if (step and os.path.exists(step)) else None, out_dir)
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
    root, root_src = resolve_data_root(pools)
    print("数据根目录：%s（来源：%s）" % (root, root_src))
    items = [(pid, p) for pid, p in sorted(pools["parts"].items())
             if (not only or pid == only) and (not pool or p["pool"] == pool)]

    out_dir = os.path.join(HERE, "built")
    results = []
    print("%-8s %-13s %-6s %-9s %8s %9s  %s"
          % ("图号", "零件", "池", "结果", "体积差%", "实测Ø", "原因"))
    print("-" * 96)
    for pid, p in items:
        r = run_one(pid, p, out_dir, root)
        results.append(r)
        md = r.get("measured_diameters_mm") or []
        print("%-8s %-13s %-6s %-9s %8s %9s  %s"
              % (pid, p["name"][:13], p["pool"], r["verdict"],
                 ("%+.3f" % r["diff"]["volume_pct"]) if r.get("diff") else "-",
                 ",".join("%.2f" % d for d in md[:3]) or "-",
                 why(r)))

    # 跳过件单独报，不混进分母 —— 否则"缺文件"会被误读成"算法没做出来"
    tried = [r for r in results if r.get("verdict") != "SKIP"]
    skipped = [r for r in results if r.get("verdict") == "SKIP"]
    ok = [r for r in tried if r.get("verdict") == "PASS"]
    print("-" * 96)
    print("PASS %d / %d" % (len(ok), len(tried)))
    if skipped:
        print("跳过 %d 件（缺输入，非失败）：%s"
              % (len(skipped), ", ".join(r["pid"] for r in skipped)))
    for pool_name in ("train", "test"):
        sub = [r for r in tried if r["pool"] == pool_name]
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
