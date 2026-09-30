# -*- coding: utf-8 -*-
r"""pipe.py —— 消息驱动器

**只做调度与投递，不做任何业务计算。** 每个步骤是独立进程，
靠 _msg/<stage>.in.json → .out.json 通信（协议见 MSG.md）。

用法
----
    python pipe.py                     全链：s1→s2→s3→s4
    python pipe.py --loop              全链 + 闭环（s5→s8），只报不改
    python pipe.py --loop --auto       闭环自动改参数并迭代
    python pipe.py --only s2_drawing   只跑某一段（调试）
    python pipe.py --no-guard          跳过隔离检查（不推荐）

路径通过环境变量覆盖，脚本本身不含业务路径：
    MPIPE_PY   venv 的 python.exe
    MPIPE_FC   FreeCAD 的 freecadcmd.exe
    MPIPE_TD   FreeCAD 的 A3 图框模板 A3_Landscape_TD.svg
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from msgio import (MSG_DIR, PROTOCOL, read_json, write_json,   # noqa: E402
                   ref_file, sha256)

PARAMS = os.path.join(HERE, "params.py")

# ---------------- 环境配置（可用环境变量覆盖，不必改脚本） ----------------
PY = os.environ.get("MPIPE_PY", r"D:\3d\build123d\.venv\Scripts\python.exe")
FC = os.environ.get("MPIPE_FC", "D:/3d/\u65b0\u5efa\u6587\u4ef6\u5939/FreeCAD 1.1/bin/freecadcmd.exe")
TD = os.environ.get("MPIPE_TD",
                    "D:/3d/\u65b0\u5efa\u6587\u4ef6\u5939/FreeCAD 1.1/data/Mod/TechDraw/"
                    "Templates/ISO/A3_Landscape_TD.svg")

# ---------------- 拓扑：谁读什么、写到哪 ----------------
#   in_files : [(role, 来源)]   来源 = "文件名"（外部输入）或 "@步名"（取该步产物）
#   in_data  : [(key, 值)]      额外的内联入参
#   in_data_from: 步名          把该步 out.data 整体作为本步入参 data
#   out_dir  : 产物目录
STEPS = [
    dict(name="s1_build",   runner="py", out_dir="models",
         in_files=[("params", "params.py")]),
    dict(name="s2_drawing", runner="fc", out_dir=".",
         in_files=[("params", "params.py"), ("model_step", "@s1_build")],
         in_data=[("template", TD)]),
    dict(name="s3_render",  runner="py", out_dir=".",
         in_files=[("drawing_json", "@s2_drawing")]),
    dict(name="s4_table",   runner="py", out_dir=".",
         in_files=[("params", "params.py"), ("dims_spec", "dims_spec.py"),
                   ("drawing_json", "@s2_drawing")]),
    # ---- 闭环 ----
    dict(name="s5_collect", runner="py", out_dir=".", loop=True,
         in_files=[("drawing_json", "@s2_drawing")]),
    dict(name="s6_compare", runner="py", out_dir=".", loop=True,
         in_files=[("ref_spec", "ref_spec.py")], in_data_from="s5_collect"),
    dict(name="s7_decide",  runner="py", out_dir=".", loop=True,
         in_files=[("params", "params.py")], in_data_from="s6_compare"),
    dict(name="s8_apply",   runner="py", out_dir=".", loop=True, optional=True,
         in_files=[("params", "params.py")], in_data_from="s7_decide"),
]
BY_NAME = {s["name"]: s for s in STEPS}
CHAIN = [s["name"] for s in STEPS if not s.get("loop")]
LOOP = [s["name"] for s in STEPS if s.get("loop")]


# ---------------- 投递 ----------------
def _abs(p):
    return p if os.path.isabs(p) else os.path.join(HERE, p)


def build_in_msg(step, seq, produced):
    refs = []
    for role, src in step.get("in_files", []):
        if src.startswith("@"):
            stage = src[1:]
            got = produced.get(stage, {}).get(role)
            if not got:
                raise RuntimeError("步骤 %s 需要 %s.%s，但上一步没有产出它"
                                   % (step["name"], stage, role))
            path = got
        else:
            path = _abs(src)
        refs.append(ref_file(path, role))

    data = {}
    for k, v in step.get("in_data", []):
        data[k] = v
    data["out_dir"] = _abs(step["out_dir"])
    src_stage = step.get("in_data_from")
    if src_stage:
        data.update(produced.get(src_stage + ".data", {}))

    return {"protocol": PROTOCOL, "stage": step["name"], "seq": seq,
            "status": "request", "in": {"refs": refs, "data": data},
            "out": {"refs": [], "data": {}}, "error": None}


def run_step(step, seq, produced, verbose=True):
    name = step["name"]
    in_path = os.path.join(MSG_DIR, name + ".in.json")
    out_path = os.path.join(MSG_DIR, name + ".out.json")
    # 不预删除旧结果：靠 seq 校验识别过期结果（沙箱环境 os.remove 会被安全删除机制拦截）

    msg = build_in_msg(step, seq, produced)
    write_json(in_path, msg)

    cmd = ([PY] if step["runner"] == "py" else [FC]) + [
        os.path.join(HERE, "steps", name + ".py")]
    # 参数一律走环境变量（FreeCAD 命令行不透传自定义参数，py 也一样用，统一干净）
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               MPIPE_MSG=in_path, MPIPE_SEQ=str(seq))
    t0 = time.time()
    h_before = sha256(PARAMS) if os.path.exists(PARAMS) else None
    r = subprocess.run(cmd, capture_output=True, env=env)
    # 运行时强制：只有 s8_apply 允许改 params.py
    h_after = sha256(PARAMS) if os.path.exists(PARAMS) else None
    if h_before != h_after and name != "s8_apply":
        raise RuntimeError("步骤 %s 擅自改动了 params.py —— 只有 s8_apply 允许（隔离违例）" % name)
    out = (r.stdout or b"").decode("utf-8", "replace") + \
          (r.stderr or b"").decode("utf-8", "replace")

    if verbose:
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("[") or s.startswith("      ") or s.startswith(">>>"):
                print("   ", s)

    if not os.path.exists(out_path):
        print("\n!!! %s 没有写出结果消息（进程退出码 %d）" % (name, r.returncode))
        print(out[-2500:])
        return None, out

    res = read_json(out_path)
    if res.get("seq") != seq or res.get("status") != "ok":
        print("\n!!! %s 执行失败（seq=%s status=%s）" % (name, res.get("seq"), res.get("status")))
        print((res.get("error") or "")[-2500:] or out[-2500:])
        return None, out

    produced[name] = {x["role"]: _abs(x["path"]) for x in res["out"]["refs"]}
    produced[name + ".data"] = res["out"]["data"]
    print("    %-12s %5.1fs" % (name, time.time() - t0))
    return res, out


# ---------------- 闭环 ----------------
def run_loop(seq, auto, max_it, produced):
    """返回 (结局, 轮次)"""
    prev_n = None
    for it in range(1, max_it + 1):
        print("\n" + "#" * 70)
        print("#  闭环第 %d 轮 / 上限 %d" % (it, max_it))
        print("#" * 70)

        for name in LOOP:
            if name == "s8_apply":
                continue            # s8 在判定之后按需单独执行（见下）
            res, _ = run_step(BY_NAME[name], seq, produced)
            if res is None:
                return "fail", it

        dec = produced.get("s7_decide.data", {})
        verdict = dec.get("verdict")
        if verdict == "pass":
            print("\n  ⇒ 通过：几何与标注全部相符")
            return "pass", it
        if dec.get("diagnosis"):
            print("\n  ⇒ %s" % dec["diagnosis"])
        for x in dec.get("items", []):
            print("     ! %-14s 基准 %-9s 当前 %s" % (x["name"], x["base"], x["cur"]))
        fixes = dec.get("fixes") or {}
        n = len(dec.get("items", []))

        if verdict == "manual":
            print("\n  【停】%s" % dec.get("reason"))
            return "manual", it
        if not auto:
            print("\n  【建议修改】%s" % fixes)
            print("  （加 --auto 可自动应用并迭代）")
            return "suggest", it
        if prev_n is not None and n >= prev_n:
            print("\n  【停】本轮问题数 %d 未少于上一轮 %d，判定无进展" % (n, prev_n))
            return "stuck", it
        prev_n = n

        # 应用修正（s8 是唯一被允许改 params.py 的步骤），然后重走全链
        print("\n  应用修正 → 重出三维与图纸…")
        res, _ = run_step(BY_NAME["s8_apply"], seq, produced)
        if res is None:
            return "fail", it
        seq += 1
        for name in CHAIN:
            res, _ = run_step(BY_NAME[name], seq, produced)
            if res is None:
                return "fail", it

    return "maxit", max_it


# ---------------- 主流程 ----------------
def main():
    argv = sys.argv[1:]
    auto = "--auto" in argv
    loop = "--loop" in argv or auto
    only = None
    max_it = 6
    for i, a in enumerate(argv):
        if a == "--only" and i + 1 < len(argv):
            only = argv[i + 1]
        elif a.startswith("--max="):
            max_it = int(a.split("=", 1)[1])

    os.makedirs(MSG_DIR, exist_ok=True)

    if "--no-guard" not in argv:
        print("=" * 70)
        print(">>> 隔离检查（guard.py）")
        print("=" * 70)
        g = subprocess.run([PY, os.path.join(HERE, "guard.py")],
                           capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        go = (g.stdout or b"").decode("utf-8", "replace")
        print(go.rstrip())
        if g.returncode != 0:
            print("\n隔离检查未通过，拒绝运行。")
            sys.exit(3)

    t0 = time.time()
    produced = {}
    seq = 1

    todo = [only] if only else CHAIN
    for name in todo:
        print("\n" + "=" * 70)
        print(">>> %s" % name)
        print("=" * 70)
        res, _ = run_step(BY_NAME[name], seq, produced)
        if res is None:
            print("\n失败，已中止。")
            sys.exit(1)

    outcome = None
    if loop and not only:
        outcome, it = run_loop(seq, auto, max_it, produced)
        print("\n闭环结局：%s（%d 轮）" % (outcome, it))

    print("\n" + "=" * 70)
    print("完成，用时 %.1f 秒" % (time.time() - t0))
    for r in (produced.get("s3_render", {}).get("drawing_pdf"),
              produced.get("s4_table", {}).get("dims_table_pdf")):
        if r:
            print("   ", r)
    print("    消息目录：", MSG_DIR)
    if outcome in ("manual", "stuck", "maxit", "fail"):
        sys.exit(2)


if __name__ == "__main__":
    main()
