# -*- coding: utf-8 -*-
r"""
闭环校核（closed-loop check）
==============================
把线性流水线接成带反馈的循环：

    原图基准 ref_spec.py ──┐
                           ├─→ 比对 ─→ 判定 ─→ 通过？─是─→ 结束
    当前三维→投影 JSON  ──┘                    │
                                             否
                                              ↓
                      定位：是「三维画错」还是「二维标错」
                                              ↓
                                给出参数修正建议 → 改 params.py
                                              ↓
                              重新生成（三维→投影）→ 回到比对

判定规则
--------
    投影几何 ✗            → **三维画错**（形状就不对）
    投影几何 ✓  但标注 ✗   → **二维标注错**（形状对，标注没跟上）
    两者都 ✓              → 通过

用法
----
    python check_loop.py            检查一轮，打印差异与建议
    python check_loop.py --auto     自动迭代：应用建议→重跑→再检，直到通过（最多 6 轮）
    python check_loop.py --no-run   跳过重新生成，直接用现有 _td_data.json 检查
"""
import itertools
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS = os.path.join(HERE, "params.py")
LOG = os.path.join(HERE, "loop_log.md")
PY = r"D:\3d\build123d\.venv\Scripts\python.exe"

import params as P
import ref_spec as R

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ================= 基准 → 应有的参数值（修正建议直接用这些，不从当前反解） =================
def _group(circles):
    cen = sorted([c for c in circles if abs(c[1]) < 1.0], key=lambda c: -c[0])
    side = sorted([c for c in circles if abs(c[1]) >= 1.0], key=lambda c: -c[0])
    return cen, side


_CEN, _SIDE = _group(R.TOP["circles"])
_Z = R.FRONT["z_levels"]

BASE_P = {
    "R_OUT_CEN":   _CEN[0][0],
    "R_BOSS":      _CEN[1][0],
    "D_HOLE_CEN":  2 * _CEN[2][0],
    "R_SIDE":      _SIDE[0][0],
    "D_HOLE_SIDE": 2 * _SIDE[-1][0],
    "D_SIDE":      abs(_SIDE[0][1]),
    "R_NECK":      R.TOP["neck_R"],
    "BASE_T":      _Z[1] - _Z[0],
    "H_WING":      _Z[2] - _Z[1],
    "H_CEN":       _Z[3] - _Z[1],
}
BASE_LEN_X, BASE_LEN_Y, BASE_H = R.TOP["len_x"], R.TOP["len_y"], R.FRONT["height"]

# 角色 → (参数名, 半径→参数 的倍数, 中文名)
ROLE2PARAM = {
    "OD_center_arc": ("R_OUT_CEN",   1, "中心外弧"),
    "OD_boss":       ("R_BOSS",      1, "中心凸台"),
    "ID_center":     ("D_HOLE_CEN",  2, "中心通孔"),
    "OD_wing":       ("R_SIDE",      1, "侧凸台"),
    "ID_side":       ("D_HOLE_SIDE", 2, "侧通孔"),
}


def roles_for(bases, cen=True):
    """按半径降序给组内每个圆定角色"""
    names = ["OD_center_arc", "OD_boss", "ID_center"] if cen else ["OD_wing", "ID_side"]
    order = sorted(range(len(bases)), key=lambda i: -bases[i][0])
    out = [None] * len(bases)
    for rank, i in enumerate(order):
        out[i] = names[rank] if rank < len(names) else None
    return out


def best_match(bases, curs):
    """组内一对一最优配对（数量少，暴力枚举，避免半径接近时误配）"""
    n = min(len(bases), len(curs))
    if n == 0:
        return [], len(bases), len(curs)
    best, bc = None, None
    for perm in itertools.permutations(range(len(curs)), n):
        cost = sum(abs(curs[perm[i]][0] - bases[i][0])
                   + abs(curs[perm[i]][1] - bases[i][1])
                   + abs(curs[perm[i]][2] - bases[i][2]) for i in range(n))
        if bc is None or cost < bc:
            bc, best = cost, perm
    return [(bases[i], curs[best[i]]) for i in range(n)], len(bases) - n, len(curs) - n


# ================= 读取当前投影 =================
def load():
    return json.load(open(os.path.join(HERE, "_td_data.json"), encoding="utf-8"))


def collect(data):
    vt = next(v for v in data["views"] if v["name"] == "Top")
    vf = next(v for v in data["views"] if v["name"] == "Front")

    tx = [q[0] for e in vt["edges"] for q in e]
    ty = [q[1] for e in vt["edges"] for q in e]
    fy = [q[1] for e in vf["edges"] for q in e]

    boss_w, boss_y = None, None
    for h in vf["hlines"]:
        if abs((h["x0"] + h["x1"]) / 2.0) < 1.0:
            w = h["x1"] - h["x0"]
            if boss_w is None or w > boss_w:
                boss_w, boss_y = w, h["y"]

    lev = sorted(set(round(h["y"], 3) for h in vf["hlines"]))
    # 视图 y 轴方向不保证（可能朝下）→ 用「中心凸台顶」（对应 z 最大）判断并归一
    if boss_y is not None and len(lev) > 1 and abs(boss_y - lev[0]) < abs(boss_y - lev[-1]):
        lev = sorted(round(lev[0] + lev[-1] - y, 3) for y in lev)
    steps = [round(lev[i + 1] - lev[i], 3) for i in range(len(lev) - 1)]

    # 投影里同一个圆可能被分成多段弧（如中心外弧分上下两段）→ 按几何去重；
    # 凹颈弧单独校核，不参与分组配对
    seen, circ = set(), []
    for c in vt["circles"]:
        if abs(c["r"] - R.TOP["neck_R"]) < 1.0:
            continue
        key = (round(c["r"], 3), round(c["cx"], 3), round(c["cy"], 3))
        if key in seen:
            continue
        seen.add(key)
        circ.append((c["r"], c["cx"], c["cy"]))

    return {
        "len_x": round(max(tx) - min(tx), 3),
        "len_y": round(max(ty) - min(ty), 3),
        "top_circles": circ,
        "neck": sorted(set(c["r"] for c in vt["circles"]
                           if abs(c["r"] - R.TOP["neck_R"]) < 1.0)),
        "height": round(max(fy) - min(fy), 3),
        "steps": steps,
        "boss_w": boss_w,
        "marks": {d["label"]: d["value"] for d in data["dims"]},
    }


# ================= 比对 =================
def compare(cur):
    iss = []

    def add(kind, name, base, now, action=None, note=""):
        iss.append({"kind": kind, "name": name, "base": base, "cur": now,
                    "dev": None if (base is None or now is None) else now - base,
                    "action": action, "note": note})

    # ---- 俯视外接 ----
    if abs(cur["len_x"] - BASE_LEN_X) > R.TOL:
        add("geom", "外接总长", BASE_LEN_X, cur["len_x"],
            ("D_SIDE", BASE_LEN_X / 2.0 - BASE_P["R_SIDE"]),
            "总长 = 2×(D_SIDE + R_SIDE)")
    if abs(cur["len_y"] - BASE_LEN_Y) > R.TOL:
        add("geom", "外接总宽", BASE_LEN_Y, cur["len_y"],
            ("R_OUT_CEN", BASE_P["R_OUT_CEN"]), "总宽 = 2×R_OUT_CEN")

    # ---- 俯视各组圆 ----
    b_cen, b_side = _group(R.TOP["circles"])
    c_cen, c_side = _group(cur["top_circles"])
    for bases, curs, is_cen in ((b_cen, c_cen, True), (b_side, c_side, False)):
        pairs, miss_b, miss_c = best_match(bases, curs)
        names = roles_for(bases, is_cen)
        if miss_b or miss_c:
            add("geom", "%s组圆数量" % ("中心" if is_cen else "侧"), len(bases), len(curs), None,
                "圆数不符 → 配对不可靠，跳过该组半径比对（特征缺失/多余，或两个特征尺寸刚好重合）")
            continue
        for i, (b, c) in enumerate(pairs):
            role = names[i]
            if role is None:
                continue
            pname, k, label = ROLE2PARAM[role]
            if abs(c[0] - b[0]) > R.TOL:
                add("geom", "%s 半径" % label, b[0], c[0],
                    (pname, BASE_P[pname]), "直径标注 %.0f，应为 φ%.0f" % (2 * b[0], 2 * BASE_P[pname] / k))
            if abs(c[1] - b[1]) > R.TOL:
                add("geom", "%s 圆心 x" % label, b[1], c[1],
                    ("D_SIDE", BASE_P["D_SIDE"]), "特征中心位置 = D_SIDE")
        if miss_b or miss_c:
            add("geom", "圆数量", len(bases), len(curs), None,
                "同名组圆数不符（基准 %d / 投影 %d）——可能有特征缺失或多余" % (len(bases), len(curs)))

    # ---- 凹颈 ----
    if not cur["neck"]:
        add("geom", "凹颈 R", R.TOP["neck_R"], None, ("R_NECK", BASE_P["R_NECK"]), "投影里没有该半径的弧")
    elif abs(cur["neck"][0] - R.TOP["neck_R"]) > R.TOL:
        add("geom", "凹颈 R", R.TOP["neck_R"], cur["neck"][0], ("R_NECK", BASE_P["R_NECK"]))

    # ---- 前视高度 ----
    if abs(cur["height"] - BASE_H) > R.TOL:
        add("geom", "总高", BASE_H, cur["height"],
            ("H_CEN", BASE_P["H_CEN"]), "总高 = BASE_T + H_CEN")
    if len(cur["steps"]) == 3:
        rule = [("BASE_T", "底板厚"), ("H_WING", "侧凸台高出底板"), ("H_CEN", "中心凸台高出底板")]
        base_steps = [_Z[1] - _Z[0], _Z[2] - _Z[1], _Z[3] - _Z[2]]
        for i, (bs, cs) in enumerate(zip(base_steps, cur["steps"])):
            if abs(cs - bs) > R.TOL:
                pn, cn = rule[i]
                add("geom", cn, bs, cs, (pn, BASE_P[pn]), "相邻高度层之差")
    elif cur["steps"]:
        add("geom", "高度层数量", 3, len(cur["steps"]), None, "投影里的水平层数与基准不符")

    if cur["boss_w"] is not None and abs(cur["boss_w"] - R.FRONT["boss_width"]) > R.TOL:
        add("geom", "中心凸起宽度", R.FRONT["boss_width"], cur["boss_w"],
            ("R_BOSS", BASE_P["R_BOSS"]), "中心凸台直径 = 该宽度")

    # ---- 图纸标注值 ----
    for label, bv in R.MARKS.items():
        cv = cur["marks"].get(label)
        if cv is None:
            add("mark", label, bv, None, None, "图纸上缺少这个标注")
        elif abs(cv - bv) > R.TOL:
            add("mark", label, bv, cv, None, "标注值与原图不符（形状对但标注错？）")

    return iss


# ================= 报告 =================
def report(iss, cur):
    geom = [x for x in iss if x["kind"] == "geom"]
    mark = [x for x in iss if x["kind"] == "mark"]

    print("\n" + "=" * 74)
    print("【1】几何比对 —— 判断「三维形状」对不对")
    print("-" * 74)
    print("  俯视外接   基准 %.1f × %.1f      当前 %.1f × %.1f"
          % (BASE_LEN_X, BASE_LEN_Y, cur["len_x"], cur["len_y"]))
    print("  前视总高   基准 %.1f            当前 %.1f" % (BASE_H, cur["height"]))
    print("  高度层差   基准 %-18s 当前 %s"
          % (str([_Z[1] - _Z[0], _Z[2] - _Z[1], _Z[3] - _Z[2]]), str(cur["steps"])))
    if geom:
        print("  → 发现 %d 处几何不符：" % len(geom))
        for x in geom:
            d = "" if x["dev"] is None else "   偏差 %+.2f" % x["dev"]
            print("     ! %-16s 基准 %-9s 当前 %-9s%s" % (x["name"], x["base"], x["cur"], d))
            if x["note"]:
                print("       %s" % x["note"])
    else:
        print("  → 投影几何与图纸一致 ✓")

    print("\n【2】标注比对 —— 判断「二维标注」对不对")
    print("-" * 74)
    if mark:
        for x in mark:
            print("     ! %-16s 原图 %-9s 图纸 %-9s  %s" % (x["name"], x["base"], x["cur"], x["note"]))
    else:
        print("  全部 %d 项标注与原图一致 ✓" % len(R.MARKS))

    print("\n【3】结论")
    print("-" * 74)
    if not iss:
        print("  几何与标注全部相符  ⇒  **通过**")
    elif geom:
        print("  ⇒ **三维画错了** —— 投影轮廓与图纸不符，先改 params.py")
        if mark:
            print("     （标注偏差是跟着三维一起错的，修好三维后自然消失）")
    else:
        print("  ⇒ **三维没问题，是二维标注错了** —— 形状对、标注没跟上")


def log(line=""):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_run_header(title, maxit):
    import time
    log()
    log("---")
    log()
    log("## %s" % title)
    log()
    log("- 开始：%s　重试上限：%d 轮" % (time.strftime("%Y-%m-%d %H:%M:%S"), maxit))
    log("- 基准：ref_spec.py（%s，容差 %.1f mm）" % (R.CALIB_NOTE, R.TOL))


def log_round(it, iss, acts, applied):
    geom = [x for x in iss if x["kind"] == "geom"]
    mark = [x for x in iss if x["kind"] == "mark"]
    log()
    log("### 第 %d 轮" % it)
    log()
    if not iss:
        log("- 结果：**通过**（几何与标注全部相符）")
        return
    log("- 几何不符 **%d** 处，标注不符 **%d** 处" % (len(geom), len(mark)))
    for x in iss:
        d = "" if x["dev"] is None else "（偏差 %+.2f）" % x["dev"]
        log("  - `%s` %s：基准 %s / 当前 %s%s" % (x["kind"], x["name"], x["base"], x["cur"], d))
    if applied:
        log("- 已应用修正：`%s`" % applied)
    elif acts:
        log("- 待应用修正：`%s`" % acts)
    else:
        log("- **无法给出参数建议** → 需人工检查标注层")


def log_stop(reason, it):
    log()
    log("### 停止（第 %d 轮后）" % it)
    log()
    log("- 原因：%s" % reason)


def merge_actions(iss):
    """汇总修正建议；过滤掉「与当前值相同」的 no-op 建议"""
    """汇总修正建议；过滤掉「与当前值相同」的 no-op 建议"""
    acts = {}
    for x in iss:
        if x["action"]:
            k, v = x["action"]
            v = round(float(v), 4)
            if abs(getattr(P, k) - v) > 1e-9:
                acts[k] = v
    return acts


def apply_fix(acts):
    txt = open(PARAMS, encoding="utf-8").read()
    done = {}
    for k, v in acts.items():
        txt, n = re.subn(r"^(%s\s*=\s*)[\d.]+" % k,
                         lambda m: m.group(1) + ("%.4f" % v).rstrip("0").rstrip("."),
                         txt, flags=re.M)
        if n != 1:
            raise RuntimeError("参数 %s 在 params.py 里匹配到 %d 处，拒绝修改" % (k, n))
        done[k] = v
    open(PARAMS, "w", encoding="utf-8").write(txt)
    return done


def run_pipeline():
    r = subprocess.run([PY, os.path.join(HERE, "make_all.py")],
                       capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if r.returncode != 0:
        print(r.stdout.decode("utf-8", "replace")[-1500:])
        raise SystemExit("make_all 失败")


def main():
    auto = "--auto" in sys.argv
    norun = "--no-run" in sys.argv
    MAXIT = 6
    for a in sys.argv:
        if a.startswith("--max="):
            MAXIT = int(a.split("=", 1)[1])

    print("基准: ref_spec.py（原图标定 %s = %.4f mm/px，容差 %.1f mm）"
          % (R.CALIB_NOTE, R.MM_PER_PX, R.TOL))
    log_run_header("闭环校核", MAXIT)
    if auto:
        shutil.copyfile(PARAMS, PARAMS + ".bak")
        print("已备份 params.py → params.py.bak")

    prev_n, stop_reason, it = None, None, 0
    for it in range(1, MAXIT + 1):
        print("\n" + "#" * 74)
        print("#  第 %d 轮 / 上限 %d" % (it, MAXIT))
        print("#" * 74)
        if not norun:
            print("重新生成（三维 → 投影）…")
            run_pipeline()

        cur = collect(load())
        iss = compare(cur)
        report(iss, cur)

        if not iss:
            log_round(it, iss, None, None)
            break

        acts = merge_actions(iss)
        applied = None
        if auto and acts and it < MAXIT:
            applied = apply_fix(acts)
            print("\n【已应用修正】%s" % applied)
        log_round(it, iss, acts, applied)

        if acts:
            print("\n【建议修改】")
            for k, v in acts.items():
                print("    %-14s %s → %g" % (k, getattr(P, k), v))
        else:
            print("\n【无参数建议】标注层需要人工检查")
            stop_reason = "无参数级修正建议（需人工改标注层）"
            break

        if prev_n is not None and len(iss) >= prev_n:
            stop_reason = "本轮问题数 %d 未少于上一轮 %d，判定为无进展" % (len(iss), prev_n)
            break
        prev_n = len(iss)

        if not auto:
            print("\n（加 --auto 可自动应用并迭代；--max=N 设上限）")
            break
        if it == MAXIT:
            stop_reason = "已达重试上限 %d 轮，仍未通过" % MAXIT
            break
        print("继续下一轮…")

    if stop_reason:
        print("\n【停止】%s" % stop_reason)
        log_stop(stop_reason, it)
    print("\n完成。　日志：%s" % LOG)


if __name__ == "__main__":
    main()
