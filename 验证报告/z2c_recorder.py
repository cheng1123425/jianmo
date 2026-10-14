# -*- coding: utf-8 -*-
"""录制代理验证：执行 CadQuery 代码，把所有链式调用录制下来。
不真装 cadquery —— 用一个假模块顶替 sys.modules['cadquery']。
对应交接文档 §5.4 的「执行+录制」方案。
"""
import sys, types, json

# ---------------- 录制代理 ----------------
RECORDS = []          # 全局录制流水

class Rec:
    """假的 Workplane / Shape：每个实例有唯一 oid，所有方法都记账并返回新 Rec。"""
    _counter = [0]
    def __init__(self, oid=None, path=None):
        if oid is None:
            Rec._counter[0] += 1
            oid = "W%d" % Rec._counter[0]
        self._oid = oid
        self._path = path or []        # 累积的调用链，形如 [("rect",(60,40))]

    def __getattr__(self, name):
        # 任何方法调用都返回一个「调用器」
        def caller(*args, **kwargs):
            # 只保留可直接序列化的实参（求值后的数值）
            cargs = [_plain(a) for a in args]
            ckw = {k: _plain(v) for k, v in kwargs.items()}
            # 特殊情况：布尔运算的目标与参数
            extra = {}
            if name in ("union", "cut", "intersect"):
                # args[0] 通常是一个 Rec（另一条链的结果）
                if args and isinstance(args[0], Rec):
                    cargs = ["<ref:%s>" % args[0]._oid]
                    extra = {"target": self._oid, "arg": args[0]._oid,
                             "arg_chain": args[0]._path}
            rec = {
                "op": name,
                "on": self._oid,
                "args": cargs,
                "kwargs": ckw,
            }
            rec.update(extra)
            RECORDS.append(rec)
            # 返回一个新 Rec，继承调用链
            newpath = self._path + [(name, tuple(cargs))]
            return Rec(path=newpath)
        return caller

def _plain(v):
    if isinstance(v, Rec):
        return "<ref:%s>" % v._oid
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v

# ---------------- 假 cadquery 模块 ----------------
def _make_fake_cq():
    m = types.ModuleType("cadquery")
    m.Workplane = lambda *a, **k: (_record_ctor("Workplane", a, k))
    return m

def _record_ctor(name, args, kwargs):
    RECORDS.append({"op": "ctor:" + name, "on": None,
                    "args": [_plain(a) for a in args],
                    "kwargs": {k: _plain(v) for k, v in kwargs.items()}})
    return Rec()

# ---------------- 运行 ----------------
def run(path):
    RECORDS.clear()
    Rec._counter[0] = 0
    sys.modules["cadquery"] = _make_fake_cq()
    src = open(path, encoding="utf-8").read()
    g = {"__name__": "__main__", "print": lambda *a, **k: None}
    exec(compile(src, path, "exec"), g)
    return RECORDS

if __name__ == "__main__":
    recs = run("/tmp/z2c_sample.py")
    print("=== 执行+录制：共录制 %d 条操作 ===" % len(recs))
    for i, r in enumerate(recs, 1):
        line = "[%2d] %-18s on=%-6s args=%s" % (i, r["op"], r["on"], r["args"])
        if r.get("target"):
            line += "  (布尔: %s ← %s)" % (r["target"], r["arg"])
        print(line)
