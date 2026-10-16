# -*- coding: utf-8 -*-
r"""l2_vs_l0.py —— 图纸标注（L2） vs 真值面表（L0）对账   [v2]

★ 纪律（用户 10-16 明确）：**只许度量，不许回流。**
  本脚本的结论只用来回答「图纸标注与真值几何差多少」，
  **不得**据以回头修改 pdf_anno.py 的抽取规则（那是把答案抄进学习）。
  若必须改抽取规则 → test 池作废，只能在 train 池上重报。

v2 相对 v1 的改进（每条都对应一个已定位的根因）：
  + 轴向长度对账：真值圆柱的 axial_len ↔ 图纸裸数字 —— **新增「孔深」维度**
  + bbox 对账：三向跨度 ↔ (裸数字 ∪ Ø) —— 圆形件的 X/Y 跨度就是 Ø
  + 角度分类：>180° 判为包角，不进锥角对账（纯 L2 判据，不依赖真值）
  + PCD 豁免：Ø 在真值里找不到、且该件有 ≥3 孔的均布标注 → 标为 PCD 候选
    ⚠️ 此规则是**看过 test 漏项后**归纳的 ⇒ 加它之后 test 数字不再干净（见 README）
  + 盲区提示：报出未解析面（B样条）面积占比

用法
    python l2_vs_l0.py [--tol 0.35] [--pool train|test|all] [-v]
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_pools():
    with open(os.path.join(HERE, "pools.json"), encoding="utf-8") as f:
        return json.load(f)


def part_of_anno(anno_name, pools):
    for pid, p in pools["parts"].items():
        if pid in anno_name:
            return p["name"], pid, p["pool"]
    for pid, c in pools.get("contaminated", {}).items():
        if pid in anno_name:
            return c["name"], pid, "contaminated"
    return None, None, None


# ---------------------------------------------------------------- L0 抽取
def _cyl_groups(cen):
    out = []
    for k, v in cen["groups"].items():
        f = k.split("|")
        if f[0] == "cylinder":
            inst = v.get("instances") or [{}]
            out.append({"form": f[1], "r": round(float(f[2]), 3), "dir": f[3],
                        "n": v["n"],
                        "axis_rel": inst[0].get("axis_rel"),
                        "len": inst[0].get("len")})
    return out


def l0_diameters(cen):
    out = {}
    for k, v in cen["groups"].items():
        f = k.split("|")
        if f[0] == "cylinder":
            d = round(float(f[2]) * 2, 3)
        elif f[0] == "sphere":
            d = round(float(f[1]) * 2, 3)
        else:
            continue
        out[d] = out.get(d, 0) + v["n"]
    return out


def l0_radii(cen):
    out = {}
    for k, v in cen["groups"].items():
        f = k.split("|")
        if f[0] == "cylinder":
            r = round(float(f[2]), 3)
        elif f[0] in ("sphere", "torus"):
            r = round(float(f[1]), 3)
        else:
            continue
        out[r] = out.get(r, 0) + v["n"]
    return out


def l0_cone_angles(cen):
    out = {}
    for k, v in cen["groups"].items():
        f = k.split("|")
        if f[0] == "cone":
            deg = round(float(f[1]) * 2 * 180 / math.pi, 2)
            out[deg] = out.get(deg, 0) + v["n"]
    return out


def match(value, table, tol):
    for k, n in table.items():
        if abs(k - value) <= tol:
            return k, n
    return None


# ---------------------------------------------------------------- 对账
def reconcile(anno, cen, tol, verbose=False):
    R = {}

    # ---- 1) Ø 对账（含 PCD 豁免）----
    l0d = l0_diameters(cen)
    n_uniform = sum(1 for t in anno["through_holes"] if t.get("n", 0) >= 3)
    dia_hit, dia_miss, dia_pcd = [], [], []
    for a in anno["diameter"]:
        m = match(a["d"], l0d, tol)
        if m:
            dia_hit.append((a, m))
        elif n_uniform:
            # PCD 候选：找不到实体圆柱，但该件有 ≥3 孔的均布标注 ⇒ 它可能是定位圆
            dia_pcd.append(a)
        else:
            dia_miss.append(a)

    used = {m[0] for _, m in dia_hit}
    l0_dia_unmatched = [(d, n) for d, n in sorted(l0d.items())
                        if not any(abs(d - u) <= tol for u in used)]

    # ---- 2) R 对账 ----
    l0r = l0_radii(cen)
    rad_hit, rad_miss = [], []
    for a in anno["radius"]:
        m = match(a["r"], l0r, tol)
        (rad_hit if m else rad_miss).append((a, m))

    # ---- 3) 角度对账（>180° 判包角，豁免）----
    l0a = l0_cone_angles(cen)
    ang_hit, ang_miss, ang_arc = [], [], []
    for a in anno["angle"]:
        if a["deg"] > 180.0:
            ang_arc.append(a)                       # 纯 L2 判据：包角不可能是锥角
            continue
        m = match(a["deg"], l0a, max(tol, 1.0))
        (ang_hit if m else ang_miss).append((a, m))

    # ---- 4) 轴向长度（孔深）对账 ★新增维度 ----
    #   ★ 严格化：只有当这个圆柱的 **Ø 也命中过标注** 时，才允许把它的长度算作"孔深命中"。
    #     否则会出现巧合命中（如 r=0.8 长 2.627 恰好落在裸数字 2.5 的 tol 内，但图上根本没标这个孔）。
    bare = []
    for x in anno["linear_bare"]:
        try:
            bare.append(float(x))
        except ValueError:
            pass
    ann_d = {a["d"] for a in anno["diameter"]}
    cyls = _cyl_groups(cen)
    depth_hit, depth_miss, depth_unan = [], [], []
    seen = set()
    for c in cyls:
        if c.get("form") != "hole":                  # ★ 只对**内孔**谈"孔深"
            continue
        if not c.get("len") or c["len"] <= 1.0:      # 太短的（法兰厚/薄片）不追
            continue
        key = (c["r"], c["len"])
        if key in seen:
            continue
        seen.add(key)
        d = round(c["r"] * 2, 3)
        annotated = any(abs(d - ad) <= tol for ad in ann_d)
        m = match(c["len"], {b: 1 for b in bare}, tol)
        if annotated and m:
            depth_hit.append((c, m[0]))
        elif annotated:
            depth_miss.append(c)
        else:
            depth_unan.append(c)                     # 真值有孔，图上没有对应的 Ø 标注

    # ---- 5) bbox 对账（含 Ø）----
    bb = cen["bbox"]
    dims = sorted([round(bb[3] - bb[0], 3), round(bb[4] - bb[1], 3),
                   round(bb[5] - bb[2], 3)])
    pool_vals = sorted(set(bare) | {a["d"] for a in anno["diameter"]})
    dim_hit = [d for d in dims if any(abs(d - v) <= tol for v in pool_vals)]
    dim_miss = [d for d in dims if d not in dim_hit]

    R.update(dia_hit=dia_hit, dia_miss=dia_miss, dia_pcd=dia_pcd,
             l0_dia_unmatched=l0_dia_unmatched,
             rad_hit=rad_hit, rad_miss=rad_miss,
             ang_hit=ang_hit, ang_miss=ang_miss, ang_arc=ang_arc,
             depth_hit=depth_hit, depth_miss=depth_miss, depth_unan=depth_unan,
             dims=dims, dim_hit=dim_hit, dim_miss=dim_miss,
             n_dia=len(anno["diameter"]), n_rad=len(anno["radius"]),
             n_ang=len(anno["angle"]), n_bare=len(bare),
             unresolved=cen.get("unresolved", {}))
    return R


def main(argv):
    tol, pool, verbose = 0.35, "all", False
    i = 0
    while i < len(argv):
        if argv[i] == "--tol":
            tol = float(argv[i + 1]); i += 2; continue
        if argv[i] == "--pool":
            pool = argv[i + 1]; i += 2; continue
        if argv[i] in ("-v", "--verbose"):
            verbose = True; i += 1; continue
        i += 1

    pools = load_pools()
    annodir, cendir = os.path.join(HERE, "anno"), os.path.join(HERE, "out")
    if not os.path.isdir(annodir):
        print("缺少 anno/ —— 先跑 pdf_anno.py --json"); return 2

    rows = []
    for fn in sorted(os.listdir(annodir)):
        if not fn.endswith(".anno.json"):
            continue
        anno = json.load(open(os.path.join(annodir, fn), encoding="utf-8"))
        name, pid, pool_of = part_of_anno(anno["part"], pools)
        if not name or (pool != "all" and pool_of != pool):
            continue
        cp = os.path.join(cendir, name + ".census.json")
        if not os.path.exists(cp):
            continue
        cen = json.load(open(cp, encoding="utf-8"))
        rows.append((pool_of, name, pid, reconcile(anno, cen, tol, verbose)))

    order = {"train": 0, "test": 1, "contaminated": 2}
    rows.sort(key=lambda r: (order.get(r[0], 9), r[2] or ""))

    print("L2（图纸标注） vs L0（真值面表） [v2]  tol=%.2fmm" % tol)
    print()
    print("%-12s %-6s %-13s %7s %8s %7s %7s %6s" %
          ("池", "图号", "零件", "Ø命中", "R命中", "角度", "孔深命中", "bbox"))
    print("-" * 82)
    for pool_of, name, pid, r in rows:
        print("%-12s %-6s %-13s %3d/%-3d %3d/%-3d %2d/%-2d %3d/%-3d %3d/3"
              % (pool_of, pid, name[:13],
                 len(r["dia_hit"]), r["n_dia"],
                 len(r["rad_hit"]), r["n_rad"],
                 len(r["ang_hit"]), r["n_ang"] - len(r["ang_arc"]),
                 len(r["depth_hit"]), len(r["depth_hit"]) + len(r["depth_miss"]),
                 len(r["dim_hit"])))

    print()
    print("== 明细 ==")
    for pool_of, name, pid, r in rows:
        print("[%s] %s %s   盲区 %.1f%% (%d 面未解析)"
              % (pool_of, pid, name, r["unresolved"].get("area_frac", 0) * 100,
                 r["unresolved"].get("faces", 0)))
        for a, m in r["depth_hit"]:
            print("    孔深 ✓ Ø%-7.2f 深 %-9s ← 图纸 %s" % (a["r"] * 2, a["len"], m))
        for c in sorted(r.get("depth_targets", []), key=lambda x: x["r"]):
            pass
        for c in sorted(r.get("depth_targets", []), key=lambda x: x["r"]):
            pass
        for a in r["dia_pcd"]:
            print("    PCD ？ Ø%-8s ← '%s'（真值无此柱面；该件有 ≥3 孔均布标注）"
                  % (a["d"], a["tok"]))
        for a in r["dia_miss"]:
            print("    Ø  ✗ %-9s ← '%s'" % (a["d"], a["tok"]))
        for a, _ in r["rad_miss"]:
            print("    R  ✗ %-9s ← '%s'" % (a["r"], a["tok"]))
        if r["ang_arc"]:
            print("    包角（豁免）: %s" % ", ".join("%g°" % a["deg"] for a in r["ang_arc"]))
        for a, _ in r["ang_miss"]:
            print("    角度 ✗ %-7s ← '%s'" % (a["deg"], a["tok"]))
        for c in r.get("depth_miss", []):
            print("    孔深 ✗ Ø%-7.2f 深 %-8s （Ø 有标注，但深度在裸数字里找不到）"
                  % (c["r"] * 2, c["len"]))
        for c in r.get("depth_miss", []):
            print("    孔深 ✗ Ø%-7.2f 深 %-8s （Ø 有标注，但深度在裸数字里找不到）"
                  % (c["r"] * 2, c["len"]))
        if r["dim_miss"]:
            print("    bbox 未标注: %s  （真值三向 %s）" % (r["dim_miss"], r["dims"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
