# -*- coding: utf-8 -*-
r"""pipe.py —— 消息驱动器（全零件通用）

**只做调度与投递，不做任何业务计算。** 每个步骤是独立进程，
靠 _msg/<stage>.in.json → .out.json 通信（协议见 MSG.md）。

用法
----
    python pipe.py                              跑根零件（垫片）
    python pipe.py --part parts/bracket         跑铰链支座
    python pipe.py --part parts/bracket --loop  全链 + 闭环（只报不改）
    python pipe.py --part parts/bracket --loop --auto
                                                闭环自动改参数并迭代
    python pipe.py --only s2_drawing            只跑某一段（调试）
    python pipe.py --no-guard                   跳过隔离检查（不推荐）
    python pipe.py --no-cache                   忽略指纹缓存，强制重跑
    python pipe.py --trace                      每步入参/出参/耗时/判定写成 _msg/trace.jsonl

链路由 10 步组成（s0 与 s9 是所有零件共用的「思考 + 记录」步骤）：

    s0_plan    循环前读图：把图纸基准 / 尺寸关系 / 历史错误拼成本轮方案
    s1_build   build123d 建模 → STEP / STL
    s2_drawing FreeCAD 无界面出图 → FCStd + 投影数据
    s3_render  A3 矢量 PDF / PNG
    s4_table   尺寸对照表（参数值 vs 图纸实测值）
    s5_collect 从投影里提炼特征（不判断）
    s6_compare 当前投影 vs 原图基准 → 差异清单
    s7_decide  差异 → 判定 + 修正建议（不动文件）
    s8_apply   唯一被允许改 params.py 的步骤
    s9_record  把本轮思路与错误写进 notes/

性能相关的两个开关（默认开启）：
    * 指纹缓存：入参 sha256 + 入参 data + 步骤脚本 sha256 都没变 → 直接复用上次
      结果，不再起进程。改了某个步骤脚本，只有它自己和下游会重跑。
    * 延迟出图：闭环中间轮只跑 s1+s2（几何相关），s3/s4 等最后一轮结束再补跑一次，
      每轮省下约 3 秒的渲染与制表开销。

路径通过环境变量覆盖，脚本本身不含业务路径：
    MPIPE_PY   venv 的 python.exe
    MPIPE_FC   FreeCAD 的 freecadcmd.exe
    MPIPE_TD   FreeCAD 的 A3 图框模板 A3_Landscape_TD.svg
"""
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import msgio                                                     # noqa: E402
from msgio import PROTOCOL, read_json, write_json, ref_file, sha256   # noqa: E402


# ---------------- 命令行 ----------------
def parse_argv(argv):
    opt = dict(part=".", auto=False, loop=False, only=None, max_it=6,
               guard=True, cache=True, trace=False)
    for i, a in enumerate(argv):
        if a == "--part" and i + 1 < len(argv):
            opt["part"] = argv[i + 1]
        elif a.startswith("--part="):
            opt["part"] = a.split("=", 1)[1]
        elif a == "--only" and i + 1 < len(argv):
            opt["only"] = argv[i + 1]
        elif a.startswith("--only="):
            opt["only"] = a.split("=", 1)[1]
        elif a.startswith("--max="):
            opt["max_it"] = int(a.split("=", 1)[1])
        elif a == "--auto":
            opt["auto"] = True
        elif a == "--loop":
            opt["loop"] = True
        elif a == "--no-guard":
            opt["guard"] = False
        elif a == "--no-cache":
            opt["cache"] = False
        elif a == "--trace":
            opt["trace"] = True
    opt["loop"] = opt["loop"] or opt["auto"]
    return opt


# ---------------- 环境配置（可用环境变量覆盖，不必改脚本） ----------------
PY = os.environ.get("MPIPE_PY", r"D:\3d\build123d\.venv\Scripts\python.exe")
FC = os.environ.get("MPIPE_FC", "D:/3d/\u65b0\u5efa\u6587\u4ef6\u5939/FreeCAD 1.1/bin/freecadcmd.exe")
TD = os.environ.get("MPIPE_TD",
                    "D:/3d/\u65b0\u5efa\u6587\u4ef6\u5939/FreeCAD 1.1/data/Mod/TechDraw/"
                    "Templates/ISO/A3_Landscape_TD.svg")

# ---------------- 拓扑：谁读什么、写到哪 ----------------
#   in_files : [(role, 来源)]  来源 = "文件名"（零件目录里的输入）或 "@步名"（取该步产物）
#              来源前加 "?" 表示可选（文件不存在就跳过这一条）
#   in_data  : [(key, 值)]      额外的内联入参
#   in_data_from: 步名          把该步 out.data 整体并入本步入参 data
#   out_dir  : 产物目录（相对零件目录）
STEPS = [
    dict(name="s0_plan", runner="py", out_dir="notes", head=True,
         in_files=[("params", "params.py"), ("dims_spec", "dims_spec.py"),
                   ("ref_spec", "ref_spec.py"), ("plan_src", "notes/plan_src.md"),
                   ("errors_md", "?notes/errors.md"),
                   ("skill_advice", "?notes/skill_advice.md")],
         in_data_from="s7_decide"),
    dict(name="s1_build", runner="py", out_dir="models",
         in_files=[("params", "params.py")]),
    dict(name="s2_drawing", runner="fc", out_dir=".",
         in_files=[("params", "params.py"), ("model_step", "@s1_build")],
         in_data=[("template", TD)]),
    dict(name="s3_render", runner="py", out_dir=".", output=True,
         in_files=[("drawing_json", "@s2_drawing")]),
    dict(name="s4_table", runner="py", out_dir=".", output=True,
         in_files=[("params", "params.py"), ("dims_spec", "dims_spec.py"),
                   ("drawing_json", "@s2_drawing")]),
    # ---- 闭环 ----
    dict(name="s5_collect", runner="py", out_dir=".", loop=True,
         in_files=[("drawing_json", "@s2_drawing")]),
    dict(name="s6_compare", runner="py", out_dir=".", loop=True,
         in_files=[("ref_spec", "ref_spec.py")], in_data_from="s5_collect"),
    dict(name="s7_decide", runner="py", out_dir=".", loop=True,
         in_files=[("params", "params.py")], in_data_from="s6_compare"),
    dict(name="s8_apply", runner="py", out_dir=".", loop=True, optional=True,
         in_files=[("params", "params.py")], in_data_from="s7_decide"),
    dict(name="s9_record", runner="py", out_dir="notes", loop=True, tail=True,
         in_files=[("params", "params.py"), ("dims_spec", "dims_spec.py"),
                   ("plan_md", "@s0_plan"),
                   ("skill_feedback", "?notes/skill_feedback.md")],
         in_data_from="s7_decide"),
]
BY_NAME = {s["name"]: s for s in STEPS}
CHAIN = [s["name"] for s in STEPS if not s.get("loop")]          # s0,s1,s2,s3,s4
# s5,s6,s7（s8 按需单独执行；s9 是每轮结尾的记录员，单独放 LOOP_TAIL）
LOOP = [s["name"] for s in STEPS
        if s.get("loop") and not s.get("optional") and not s.get("tail")]
LOOP_TAIL = [s["name"] for s in STEPS if s.get("tail")]          # s9_record
# 闭环中间轮只需要几何相关步骤；出图/制表延迟到最后补跑
QUICK_CHAIN = ["s1_build", "s2_drawing"]
DEFERRED = [s["name"] for s in STEPS if s.get("output")]         # s3,s4


class Driver(object):
    def __init__(self, part_rel):
        self.part = os.path.normpath(os.path.join(HERE, part_rel))
        if not os.path.isdir(self.part):
            raise SystemExit("零件目录不存在：%s" % self.part)
        self.params = os.path.join(self.part, "params.py")
        self.steps_dir = os.path.join(self.part, "steps")
        self.msg_dir = os.path.join(self.part, "_msg")
        self.cache_path = os.path.join(self.msg_dir, ".cache.json")
        # msgio 的「相对路径基准」指向零件目录，消息里的 path 都相对它
        msgio.PATH_BASE = self.part
        msgio.MSG_DIR = self.msg_dir
        os.makedirs(self.msg_dir, exist_ok=True)
        self.timing = {}          # 步名 → 累计秒
        self.hits = {}            # 步名 → 缓存命中次数
        # trace：把每一步的入参/出参/耗时/判定写成 JSONL（--trace 打开）
        self.trace_on = False
        self.trace_path = os.path.join(self.msg_dir, "trace.jsonl")
        self.t_start = time.time()
        self._trace_opened = False

    # -------- 工具 --------
    def _abs(self, p):
        return p if os.path.isabs(p) else os.path.join(self.part, p)

    def _rel(self, p):
        try:
            return os.path.relpath(p, HERE).replace("\\", "/")
        except Exception:
            return p

    @staticmethod
    def _brief(v, n=70):
        """把出参 data 压成一行摘要（列表/字典只报长度，长串截断）"""
        if isinstance(v, (list, tuple)):
            return "[%d 项]" % len(v)
        if isinstance(v, dict):
            return "{%d 键}" % len(v)
        s = str(v)
        return s if len(s) <= n else s[:n] + "…"

    def trace(self, **rec):
        """写一条 trace（--trace 未开则空转）。首次写会重建文件，避免历史累积。"""
        if not self.trace_on:
            return
        rec["t"] = round(time.time() - self.t_start, 2)
        rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        mode = "a" if self._trace_opened else "w"
        try:
            with open(self.trace_path, mode, encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._trace_opened = True
        except OSError:
            pass

    def script_of(self, name):
        """零件自己的 steps/ 优先，没有就用根目录的通用 steps/（s0/s9 是共用的）"""
        local = os.path.join(self.steps_dir, name + ".py")
        if os.path.exists(local):
            return local
        shared = os.path.join(HERE, "steps", name + ".py")
        if os.path.exists(shared):
            return shared
        raise SystemExit("找不到步骤脚本：%s（%s 或 %s）" % (name, local, shared))

    def load_cache(self):
        if os.path.exists(self.cache_path):
            try:
                return read_json(self.cache_path)
            except Exception:
                return {}
        return {}

    def save_cache(self, cache):
        write_json(self.cache_path, cache)

    # -------- 消息构造 --------
    def build_in_msg(self, step, seq, produced, extra=None):
        refs = []
        for item in step.get("in_files", []):
            role, src = item[0], item[1]
            optional = item[2] if len(item) > 2 else False
            if src.startswith("@"):
                path = produced.get(src[1:], {}).get(role)
                if not path:
                    if optional:
                        continue
                    raise RuntimeError("步骤 %s 需要 %s.%s，但上一步没有产出它"
                                       % (step["name"], src[1:], role))
            else:
                if src.startswith("?"):
                    src, optional = src[1:], True
                path = self._abs(src)
                if not os.path.exists(path):
                    if optional:
                        continue
                    raise FileNotFoundError("步骤 %s 的入参不存在：%s"
                                            % (step["name"], path))
            refs.append(ref_file(path, role))

        data = dict(step.get("in_data") or {})
        data["out_dir"] = self._abs(step["out_dir"])
        src_stage = step.get("in_data_from")
        if src_stage:
            data.update(produced.get(src_stage + ".data", {}) or {})
        if extra:
            data.update(extra)

        return {"protocol": PROTOCOL, "stage": step["name"], "seq": seq,
                "status": "request", "in": {"refs": refs, "data": data},
                "out": {"refs": [], "data": {}}, "error": None}

    @staticmethod
    def fingerprint(msg, script):
        h = hashlib.sha256()
        for r in sorted(msg["in"]["refs"], key=lambda x: x["role"]):
            h.update(r["role"].encode("utf-8"))
            h.update(r["sha256"].encode("utf-8"))
        h.update(json.dumps(msg["in"]["data"], sort_keys=True,
                            ensure_ascii=False).encode("utf-8"))
        h.update(sha256(script).encode("utf-8"))
        return h.hexdigest()

    # -------- 执行一步 --------
    def run_step(self, step, seq, produced, extra=None, cache=None, verbose=True):
        name = step["name"]
        in_path = os.path.join(self.msg_dir, name + ".in.json")
        out_path = os.path.join(self.msg_dir, name + ".out.json")
        script = self.script_of(name)

        msg = self.build_in_msg(step, seq, produced, extra)
        write_json(in_path, msg)
        fp = self.fingerprint(msg, script)

        # ---- 指纹缓存：入参、入参数据、步骤脚本都没变 → 直接复用上次结果 ----
        if cache is not None:
            if cache.get(name) == fp and os.path.exists(out_path):
                old = read_json(out_path)
                if old.get("status") == "ok":
                    produced[name] = {x["role"]: self._abs(x["path"])
                                      for x in old["out"]["refs"]}
                    produced[name + ".data"] = old["out"]["data"]
                    self.hits[name] = self.hits.get(name, 0) + 1
                    print("    %-12s %5.1fs  (缓存命中，未起进程)" % (name, 0.0))
                    self.trace(kind="step", seq=seq, stage=name, action="cache",
                               dur=0.0, status="ok",
                               out=[x["role"] for x in old["out"]["refs"]],
                               files=[self._rel(self._abs(x["path"]))
                                      for x in old["out"]["refs"]],
                               data={k: self._brief(v)
                                     for k, v in (old["out"]["data"] or {}).items()})
                    return old, ""
            cache.pop(name, None)

        cmd = ([PY] if step["runner"] == "py" else [FC]) + [script]
        # 参数一律走环境变量（FreeCAD 命令行不透传自定义参数，py 也一样用，统一干净）
        env = dict(os.environ, PYTHONIOENCODING="utf-8",
                   MPIPE_MSG=in_path, MPIPE_SEQ=str(seq),
                   MPIPE_ROOT=HERE, MPIPE_HERE=self.part,
                   MPIPE_MSG_DIR=self.msg_dir)
        t0 = time.time()
        h_before = sha256(self.params) if os.path.exists(self.params) else None
        r = subprocess.run(cmd, capture_output=True, env=env)
        # 运行时强制：只有 s8_apply 允许改 params.py
        h_after = sha256(self.params) if os.path.exists(self.params) else None
        if h_before != h_after and name != "s8_apply":
            raise RuntimeError("步骤 %s 擅自改动了 params.py —— 只有 s8_apply 允许（隔离违例）"
                               % name)
        dt = time.time() - t0
        self.timing[name] = self.timing.get(name, 0.0) + dt
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
            self.trace(kind="step", seq=seq, stage=name, action="fail", dur=dt,
                       status="no_out_msg", exit_code=r.returncode,
                       error=(out[-400:] or "").strip())
            return None, out

        res = read_json(out_path)
        if res.get("seq") != seq or res.get("status") != "ok":
            print("\n!!! %s 执行失败（seq=%s status=%s）" % (name, res.get("seq"), res.get("status")))
            print((res.get("error") or "")[-2500:] or out[-2500:])
            self.trace(kind="step", seq=seq, stage=name, action="fail", dur=dt,
                       status=str(res.get("status")),
                       error=((res.get("error") or "")[-400:] or out[-400:]).strip())
            return None, out

        produced[name] = {x["role"]: self._abs(x["path"]) for x in res["out"]["refs"]}
        produced[name + ".data"] = res["out"]["data"]
        if cache is not None:
            cache[name] = fp
            self.save_cache(cache)
        print("    %-12s %5.1fs" % (name, dt))
        self.trace(kind="step", seq=seq, stage=name, action="run", dur=round(dt, 2),
                   status="ok", out=[x["role"] for x in res["out"]["refs"]],
                   files=[self._rel(self._abs(x["path"])) for x in res["out"]["refs"]],
                   data={k: self._brief(v)
                         for k, v in (res["out"]["data"] or {}).items()})
        return res, out

    # -------- 闭环 --------
    def run_loop(self, seq, opt, produced, cache):
        prev_n = None
        deferred = False
        for it in range(1, opt["max_it"] + 1):
            print("\n" + "#" * 70)
            print("#  闭环第 %d 轮 / 上限 %d" % (it, opt["max_it"]))
            print("#" * 70)

            # ① 循环前：读图 → 本轮建模方案 + 失误定位
            print("\n>>> s0_plan（读图 / 方案 / 失误定位）")
            res, _ = self.run_step(BY_NAME["s0_plan"], seq, produced,
                                   extra={"round": it}, cache=cache)
            if res is None:
                return "fail", it, deferred
            pl = produced.get("s0_plan.data", {})
            print("    构造 %d 阶段｜参数预检不符 %d 项｜疑似失误 %d 处｜历史错误提示 %d 条"
                  % (pl.get("n_stages", 0), pl.get("n_bad", 0),
                     pl.get("n_suspect", 0), pl.get("n_risk", 0)))
            if pl.get("n_skill_steps") or pl.get("n_skill_risks"):
                print("    技能建议 %d 步｜技能风险 %d 条（来自 mech-projection-analysis）"
                      % (pl.get("n_skill_steps", 0), pl.get("n_skill_risks", 0)))
            for s in pl.get("suspects", []):
                if s.get("stage"):
                    print("      → 阶段 %d「%s」← %s" % (s["stage"], s["stage_title"], s["name"]))
            for x in pl.get("precheck", []):
                if not x["ok"] and x.get("action"):
                    print("      → 参数级建议：%s = %s（图上 %s，现在 %s）"
                          % (x["action"][0], x["action"][1], x["base"], x["cur"]))

            # ② 采集 → 比对 → 判定
            # s0 预检里「标注 == 参数本身」的恒等项可以直接反解出建议值，
            # 交给 s7 兜底（s6 的投影比对推不出建议时用得上）
            s0_fix = {}
            for x in pl.get("precheck", []):
                if (not x["ok"]) and x.get("action"):
                    s0_fix[x["action"][0]] = x["action"][1]

            for name in LOOP:
                print("\n>>> %s" % name)
                res, _ = self.run_step(BY_NAME[name], seq, produced,
                                       extra={"s0_fix": s0_fix}, cache=cache)
                if res is None:
                    return "fail", it, deferred

            # ③ 记录本轮思路与错误（无论成败都记）
            for name in LOOP_TAIL:
                print("\n>>> %s" % name)
                res, _ = self.run_step(BY_NAME[name], seq, produced,
                                       extra={"round": it}, cache=cache)
                if res is None:
                    return "fail", it, deferred

            dec = produced.get("s7_decide.data", {})
            verdict = dec.get("verdict")
            if verdict == "pass":
                print("\n  ⇒ 通过：几何与标注全部相符")
                self.trace(kind="verdict", seq=seq, round=it, verdict="pass", items=[])
                return "pass", it, deferred
            if dec.get("diagnosis"):
                print("\n  ⇒ %s" % dec["diagnosis"])
            for x in dec.get("items", []):
                print("     ! %-22s 基准 %-9s 当前 %s" % (x["name"], x["base"], x["cur"]))
            fixes = dec.get("fixes") or {}
            n = len(dec.get("items", []))
            self.trace(kind="verdict", seq=seq, round=it, verdict=verdict, n_items=n,
                       items=[{"name": x.get("name"), "base": x.get("base"),
                               "cur": x.get("cur")} for x in dec.get("items", [])],
                       fixes=fixes, diagnosis=dec.get("diagnosis"))

            if verdict == "manual":
                print("\n  【停】%s" % dec.get("reason"))
                return "manual", it, deferred
            if not opt["auto"]:
                print("\n  【建议修改】%s" % fixes)
                print("  （加 --auto 可自动应用并迭代）")
                return "suggest", it, deferred
            if prev_n is not None and n >= prev_n:
                print("\n  【停】本轮问题数 %d 未少于上一轮 %d，判定无进展" % (n, prev_n))
                return "stuck", it, deferred
            prev_n = n

            # ④ 应用修正（s8 是唯一被允许改 params.py 的步骤），然后只重出几何
            print("\n  应用修正 → 重出三维与投影…（出图/制表延后到最后）")
            res, _ = self.run_step(BY_NAME["s8_apply"], seq, produced, cache=cache)
            if res is None:
                return "fail", it, deferred
            seq += 1
            for name in QUICK_CHAIN:
                res, _ = self.run_step(BY_NAME[name], seq, produced, cache=cache)
                if res is None:
                    return "fail", it, deferred
            deferred = True

        return "maxit", opt["max_it"], deferred

    # -------- 隔离检查 --------
    def run_guard(self):
        print("=" * 70)
        print(">>> 隔离检查（guard.py）")
        print("=" * 70)
        dirs, seen = [], set()
        for d in (self.steps_dir, os.path.join(HERE, "steps")):
            k = os.path.normcase(os.path.realpath(d))
            if k not in seen and os.path.isdir(d):
                seen.add(k)
                dirs.append(d)
        cmd = [PY, os.path.join(HERE, "guard.py")]
        for d in dirs:
            cmd += ["--steps", d]
        g = subprocess.run(cmd, capture_output=True,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        print((g.stdout or b"").decode("utf-8", "replace").rstrip())
        if g.returncode != 0:
            print("\n隔离检查未通过，拒绝运行。")
            sys.exit(3)

    # -------- 耗时排行 --------
    def report_timing(self):
        if not self.timing:
            return
        print("\n耗时排行（仅统计真实执行的步骤）：")
        tot = sum(self.timing.values())
        for name, dt in sorted(self.timing.items(), key=lambda kv: -kv[1]):
            bar = "█" * max(1, int(round(dt / max(tot, 1e-9) * 28)))
            print("    %-12s %5.1fs %5.0f%%  %s" % (name, dt, dt / tot * 100, bar))
        if self.hits:
            print("    缓存命中：%s"
                  % ", ".join("%s×%d" % (k, v) for k, v in sorted(self.hits.items())))


def main():
    opt = parse_argv(sys.argv[1:])
    drv = Driver(opt["part"])
    print("零件目录：%s" % os.path.relpath(drv.part, HERE).replace("\\", "/") or ".")
    drv.trace_on = bool(opt.get("trace"))
    drv.trace(kind="run_start", part=drv._rel(drv.part),
              argv=sys.argv[1:], opt=opt)

    if opt["guard"]:
        drv.run_guard()

    cache = drv.load_cache() if opt["cache"] else None
    t0 = time.time()
    produced, seq = {}, 1

    if opt["only"]:
        name = opt["only"]
        if name not in BY_NAME:
            raise SystemExit("未知步骤 %s；可用：%s" % (name, ", ".join(BY_NAME)))
        print("\n" + "=" * 70)
        print(">>> %s（单步）" % name)
        print("=" * 70)
        res, _ = drv.run_step(BY_NAME[name], seq, produced, cache=cache)
        if res is None:
            print("\n失败。")
            drv.trace(kind="run_end", outcome="fail", dur=round(time.time() - t0, 2))
            sys.exit(1)
        drv.report_timing()
        drv.trace(kind="run_end", outcome="only", dur=round(time.time() - t0, 2))
        if drv.trace_on:
            print("    trace：", drv._rel(drv.trace_path))
        return

    for name in CHAIN:
        print("\n" + "=" * 70)
        print(">>> %s" % name)
        print("=" * 70)
        res, _ = drv.run_step(BY_NAME[name], seq, produced, cache=cache)
        if res is None:
            print("\n失败，已中止。")
            sys.exit(1)

    outcome = None
    if opt["loop"]:
        outcome, it, deferred = drv.run_loop(seq, opt, produced, cache)
        print("\n闭环结局：%s（%d 轮）" % (outcome, it))
        # 中间轮跳过的出图/制表，这里补跑一次（用最新一版的投影数据）
        if deferred:
            print("\n>>> 补跑出图与尺寸表（s3_render / s4_table）")
            for name in DEFERRED:
                res, _ = drv.run_step(BY_NAME[name], seq, produced, cache=cache)
                if res is None:
                    print("\n补跑失败。")
                    sys.exit(1)

    print("\n" + "=" * 70)
    print("完成，用时 %.1f 秒" % (time.time() - t0))
    for r in (produced.get("s3_render", {}).get("drawing_pdf"),
              produced.get("s4_table", {}).get("dims_table_pdf")):
        if r:
            print("   ", r)
    print("    消息目录：", drv.msg_dir)
    print("    方案/记录：", os.path.join(drv.part, "notes"))
    drv.report_timing()
    drv.trace(kind="run_end", outcome=outcome, dur=round(time.time() - t0, 2))
    if drv.trace_on:
        print("    trace：", drv._rel(drv.trace_path))
    if outcome in ("manual", "stuck", "maxit", "fail"):
        sys.exit(2)


if __name__ == "__main__":
    main()
