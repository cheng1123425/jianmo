# -*- coding: utf-8 -*-
r"""mpipe/1 消息协议 —— 读写实现

只做协议，不做业务。每个步骤脚本用统一入口运行：

    from msgio import run_stage, ref_path, ref_data
    def handler(in_msg):
        src = ref_path(in_msg, "model_step")     # 只能按消息声明读入参
        ...
        return [("result", out_path)], {"k": v}  # (out.refs, out.data)
    if __name__ == "__main__":
        run_stage("s1_build", handler)

驱动器会把上一步 out.refs 投递成本步 in.refs，并在读取时校验 sha256。
"""
import hashlib
import json
import os
import sys
import time
import traceback

PROTOCOL = "mpipe/1"
ROOT = os.path.dirname(os.path.abspath(__file__))
MSG_DIR = os.path.join(ROOT, "_msg")


# ---------------- 路径与摘要 ----------------
def abspath(path):
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def relpath(path):
    return os.path.relpath(os.path.abspath(path), ROOT).replace("\\", "/")


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(abspath(path), "rb") as f:
        for chunk in iter(lambda: f.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


def ref_file(path, role):
    """把一个已存在的文件登记为消息 ref（自动带 sha256 与大小）"""
    ap = abspath(path)
    if not os.path.exists(ap):
        raise FileNotFoundError("产出文件不存在：%s" % ap)
    return {"role": role, "path": relpath(ap),
            "sha256": sha256(ap), "bytes": os.path.getsize(ap)}


# ---------------- 步骤侧读取 ----------------
def ref_path(msg, role):
    """按 role 取出入参路径，并校验 sha256。不符即报错 —— 防止读到被掉包/过期的文件"""
    refs = msg.get("in", {}).get("refs", [])
    for r in refs:
        if r["role"] == role:
            ap = abspath(r["path"])
            if not os.path.exists(ap):
                raise FileNotFoundError("消息声明的入参不存在：%s" % r["path"])
            got = sha256(ap)
            if got != r["sha256"]:
                raise RuntimeError("入参被改动过（声明 %s，实际 %s）：%s"
                                   % (r["sha256"][:12], got[:12], r["path"]))
            return ap
    raise KeyError("消息里没有 role=%r 的入参；现有 role：%s"
                   % (role, [x["role"] for x in refs]))


def ref_data(msg, key=None, default=None):
    d = msg.get("in", {}).get("data", {}) or {}
    return d if key is None else d.get(key, default)


# ---------------- JSON ----------------
def read_json(path):
    with open(abspath(path), encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    d = os.path.dirname(abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(abspath(path), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def exec_module(path, name):
    """加载消息里声明的「人的输入模块」（params.py / 规格清单等）。

    路径来自消息 refs，不是 import 语句 —— 所以不构成步骤间的隐式依赖。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, abspath(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- 步骤统一入口 ----------------
_CTX = {}


def _parse_argv(argv=None):
    # 优先环境变量（FreeCAD 命令行不透传自定义参数，故由驱动器用 MPIPE_MSG/MPIPE_SEQ 传）
    argv = sys.argv[1:] if argv is None else argv
    in_path, seq = os.environ.get("MPIPE_MSG"), int(os.environ.get("MPIPE_SEQ", "1"))
    for i, a in enumerate(argv):
        if a == "--msg" and i + 1 < len(argv):
            in_path = argv[i + 1]
        elif a.startswith("--msg="):
            in_path = a.split("=", 1)[1]
        elif a.startswith("--seq="):
            seq = int(a.split("=", 1)[1])
    return in_path, seq


def boot(stage):
    """【顶层脚本模式】读入参消息，返回 in_msg。

    适合改造既有的长脚本：只在文件开头加几行，原逻辑一行不用动；
    文件末尾调 finish(...) 交差。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    in_path, seq = _parse_argv()
    in_path = in_path or os.path.join(MSG_DIR, stage + ".in.json")
    msg = read_json(in_path)
    if msg.get("protocol") != PROTOCOL:
        raise SystemExit("协议不符：%r ≠ %r" % (msg.get("protocol"), PROTOCOL))
    _CTX.update(stage=stage, msg=msg, seq=seq, t0=time.strftime("%Y-%m-%dT%H:%M:%S"))
    return msg


def finish(out_refs=None, out_data=None):
    """【顶层脚本模式】写结果消息。out_refs: [(role, path), ...]"""
    stage = _CTX.get("stage")
    if not stage:
        raise RuntimeError("finish() 之前必须先调 boot(stage)")
    refs = [ref_file(p, role) for role, p in (out_refs or [])]
    write_json(os.path.join(MSG_DIR, stage + ".out.json"), {
        "protocol": PROTOCOL, "stage": stage, "seq": _CTX["seq"], "status": "ok",
        "started": _CTX["t0"], "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "in": _CTX["msg"].get("in", {"refs": [], "data": {}}),
        "out": {"refs": refs, "data": out_data or {}},
        "error": None,
    })
    print("[%s] OK   out=%s" % (stage, [r["path"] for r in refs]))
    for k, v in (out_data or {}).items():
        s = v if not isinstance(v, (list, dict)) else "%d 项" % len(v)
        print("      %-14s %s" % (k, s))


def run_stage(stage, handler):
    """【函数模式】读 _msg/<stage>.in.json → handler(in_msg) → 写 _msg/<stage>.out.json"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    in_path, seq = _parse_argv()
    in_path = in_path or os.path.join(MSG_DIR, stage + ".in.json")
    out_path = os.path.join(MSG_DIR, stage + ".out.json")
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S")

    def emit(status, refs=None, data=None, err=None):
        write_json(out_path, {
            "protocol": PROTOCOL, "stage": stage, "seq": seq, "status": status,
            "started": t0, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "in": in_msg.get("in", {"refs": [], "data": {}}),
            "out": {"refs": refs or [], "data": data or {}},
            "error": err,
        })

    in_msg = {}
    try:
        in_msg = read_json(in_path)
        if in_msg.get("protocol") != PROTOCOL:
            raise SystemExit("协议不符：%r ≠ %r" % (in_msg.get("protocol"), PROTOCOL))
        out_refs, out_data = handler(in_msg)
        refs = [ref_file(p, role) for role, p in (out_refs or [])]
        emit("ok", refs, out_data)
        print("[%s] OK   out=%s" % (stage, [r["path"] for r in refs]))
        for k, v in (out_data or {}).items():
            s = v if not isinstance(v, (list, dict)) else "%d 项" % len(v)
            print("      %-14s %s" % (k, s))
        return 0
    except SystemExit:
        raise
    except Exception as e:
        emit("fail", None, None, "%s\n%s" % (e, traceback.format_exc()))
        print("[%s] FAIL %s" % (stage, e))
        sys.exit(1)
