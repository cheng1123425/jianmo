# -*- coding: utf-8 -*-
r"""tools/trace_view.py —— 把一次运行的 trace 画成"高亮路径图"（直观调试）

读 `_msg/trace.jsonl`（`pipe.py --trace` 产生），生成一份**自包含 HTML 报告**：
  * 顶部：本次运行的命令 / 结局 / 轮数 / 耗时 / 缓存命中
  * 中间：**本次实际走过的路径高亮**的拓扑图（没走的边留灰，走过的加粗）
         节点按 运行/缓存/失败 上色，标注轮次与耗时
  * 底部：逐轮时间线（每一步的顺序、耗时、缓存与否）+ 每轮判定

用法
----
    python tools/trace_view.py                       # 根零件（垫片）
    python tools/trace_view.py --part parts/lbracket  # 指定零件
    python tools/trace_view.py --part parts/lbracket --open   # 顺带打印文件路径
"""
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import pipe  # noqa: E402

CN = {
    "s0_plan": "规划", "s1_build": "建模", "s2_drawing": "出图",
    "s3_render": "渲染", "s4_table": "尺寸表", "s5_collect": "采集",
    "s6_compare": "比对", "s7_decide": "判定", "s8_apply": "写回",
    "s9_record": "记录",
}
# 固定的节点位置（viewBox 980x400 内）——拓扑是固定的，手排比自动布局更好看
POS = {
    "s0_plan": (30, 64), "s1_build": (178, 64), "s2_drawing": (326, 64),
    "s3_render": (474, 64), "s4_table": (622, 64), "FIN": (790, 64),
    "s5_collect": (178, 180), "s6_compare": (326, 180),
    "s7_decide": (474, 180), "s9_record": (622, 180),
    "s8_apply": (326, 300), "OK": (560, 300), "STOP": (740, 300),
}
W, H = 118, 50
VIRTUAL = {"FIN": "成品", "OK": "通过", "STOP": "停"}
# 拓扑边（与 pipe.py 一致；END 边是虚拟终点）
EDGES = [
    ("s0_plan", "s1_build"), ("s1_build", "s2_drawing"), ("s2_drawing", "s3_render"),
    ("s3_render", "s4_table"), ("s4_table", "FIN"),
    ("s0_plan", "s5_collect"), ("s5_collect", "s6_compare"), ("s6_compare", "s7_decide"),
    ("s7_decide", "s9_record"),
    ("s9_record", "OK"), ("s9_record", "STOP"), ("s9_record", "s8_apply"),
    ("s8_apply", "s1_build"), ("s2_drawing", "s0_plan"),
]


def load_trace(part):
    path = os.path.join(ROOT, part, "_msg", "trace.jsonl")
    if not os.path.exists(path):
        raise SystemExit("没找到 %s\n先跑：python pipe.py --part %s --loop --trace"
                         % (os.path.relpath(path, ROOT), part))
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return path, recs


def walk(recs):
    """把 trace 还原成：走过的事件序列 + 每轮分组 + 走过的边

    注意：pipe.py 先跑主链（含一次「规划」），再进闭环；闭环每轮又从「规划」开始。
    所以第 1 次「规划」属于"准备"（第 0 轮），第 2 次起才是第 1、2…轮。
    """
    steps, verdicts, meta = [], [], {}
    round_no = 0
    plan_count = 0
    for r in recs:
        k = r.get("kind")
        if k == "run_start":
            meta["argv"] = r.get("argv")
            meta["part"] = r.get("part")
        elif k == "run_end":
            meta["outcome"] = r.get("outcome")
            meta["dur"] = r.get("dur")
        elif k == "verdict":
            verdicts.append(r)
        elif k == "step":
            if r["stage"] == "s0_plan":
                plan_count += 1
                if plan_count >= 2:
                    round_no += 1
            steps.append(dict(r, round=round_no))
    # 走过的边：相邻两步即成一条边（这就是"路径走向"）
    taken = set()
    for a, b in zip(steps, steps[1:]):
        if a["stage"] == "s2_drawing" and b["stage"] == "s0_plan":
            taken.add(("s2_drawing", "s0_plan"))
        else:
            taken.add((a["stage"], b["stage"]))
    # 最后一个 step → 虚拟终点
    if steps:
        last = steps[-1]["stage"]
        if last == "s4_table":
            taken.add(("s4_table", "FIN"))
    return steps, verdicts, meta, taken


def svg(steps, taken):
    status = {}
    for s in steps:
        status[s["stage"]] = s["action"]
    dur_by_stage = {}
    for s in steps:
        dur_by_stage[s["stage"]] = dur_by_stage.get(s["stage"], 0) + s.get("dur", 0)

    def center(n):
        x, y = POS[n]
        return x + W / 2.0, y + H / 2.0

    out = ['<svg viewBox="0 0 980 400" width="100%" role="img">',
           '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" '
           'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           '<path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" '
           'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>']

    # ---- 边 ----
    for a, b in EDGES:
        if a not in POS or b not in POS:
            continue
        ax, ay = center(a)
        bx, by = center(b)
        is_taken = (a, b) in taken
        color = "#185FA5" if is_taken else "#D3D1C7"
        width = 2.4 if is_taken else 1.0
        dash = "" if is_taken else ' stroke-dasharray="4 3"'
        if (a, b) == ("s8_apply", "s1_build"):        # 回边画弯
            d = "M%g %g C%g %g %g %g %g %g" % (
                ax, ay - H / 2.0, ax, 20, bx, 20, bx, by - H / 2.0)
            out.append('<path d="%s" fill="none" stroke="%s" stroke-width="%s"%s '
                       'marker-end="url(#ar)"/>' % (d, color, width, dash))
        else:
            out.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" '
                       'stroke-width="%s"%s marker-end="url(#ar)"/>'
                       % (ax, ay, bx, by, color, width, dash))

    # ---- 节点 ----
    palette = {
        "run": ("#E6F1FB", "#185FA5", "#0C447C"),
        "cache": ("#F1EFE8", "#888780", "#444441"),
        "fail": ("#FCEBEB", "#E24B4A", "#791F1F"),
        None: ("#FFFFFF", "#D3D1C7", "#B4B2A9"),
    }
    for name, (x, y) in POS.items():
        st = status.get(name)
        fill, stroke, txt = palette[st if name not in VIRTUAL else "run"]
        if name in VIRTUAL:
            fill, stroke, txt = "#E1F5EE", "#0F6E56", "#085041"
        label = VIRTUAL.get(name) or CN.get(name, name)
        sub = ""
        if name in status and status[name] != "cache":
            sub = "%d 轮 · %.1fs" % (len([s for s in steps if s["stage"] == name]),
                                    dur_by_stage.get(name, 0))
        elif status.get(name) == "cache":
            sub = "缓存"
        out.append('<rect x="%g" y="%g" width="%g" height="%g" rx="9" fill="%s" '
                   'stroke="%s" stroke-width="1.2"/>' % (x, y, W, H, fill, stroke))
        out.append('<text x="%g" y="%g" text-anchor="middle" font-size="14" '
                   'fill="%s">%s</text>' % (x + W / 2.0, y + (21 if sub else 30), txt,
                                            html.escape(label)))
        if sub:
            out.append('<text x="%g" y="%g" text-anchor="middle" font-size="11" '
                       'fill="%s">%s</text>' % (x + W / 2.0, y + 38, txt, html.escape(sub)))
    out.append("</svg>")
    return "\n".join(out)


def timeline(steps, verdicts):
    rounds = {}
    for s in steps:
        rounds.setdefault(s["round"], []).append(s)
    vd = {}
    for v in verdicts:
        vd[v.get("round")] = v
    rows = []
    for rno in sorted(rounds):
        chips = []
        for s in rounds[rno]:
            act = s["action"]
            cls = {"run": "c-run", "cache": "c-cache", "fail": "c-fail"}.get(act, "")
            extra = "缓存" if act == "cache" else "%.1fs" % s.get("dur", 0)
            chips.append('<span class="chip %s">%s<em>%s</em></span>'
                         % (cls, html.escape(CN.get(s["stage"], s["stage"])), extra))
        v = vd.get(rno, {})
        verdict = v.get("verdict", "—")
        vcls = {"pass": "v-pass", "fix": "v-fix", "manual": "v-stop",
                "stuck": "v-stop"}.get(verdict, "v-none")
        vtxt = "→ 通过" if verdict == "pass" else ("→ 要改 %d 项" % v.get("n_items", 0)
                                                  if verdict == "fix" else "→ %s" % verdict)
        label = "准备（主链初跑）" if rno == 0 else "第 %d 轮" % rno
        rows.append('<div class="row"><div class="rno">%s</div>'
                    '<div class="chips">%s</div>'
                    '<div class="vd %s">%s</div></div>'
                    % (label, "".join(chips), vcls, html.escape(str(vtxt))))
    return "\n".join(rows)


CSS = """
body{font-family:-apple-system,'Segoe UI',sans-serif;margin:0;padding:18px 22px;color:#222;background:#fafafa}
h1{font-size:17px;margin:0 0 4px}
.meta{font-size:12px;color:#666;margin-bottom:14px}
.meta code{background:#eee;padding:1px 5px;border-radius:4px}
.card{background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:14px;margin-bottom:14px}
.legend{font-size:12px;color:#555;display:flex;gap:16px;flex-wrap:wrap;margin-top:8px}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.row{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px dashed #eee}
.row:last-child{border-bottom:0}
.rno{width:60px;font-size:12px;color:#666;flex:none}
.chips{flex:1;display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:12px;padding:3px 9px;border-radius:14px;background:#f0f0f0;color:#333}
.chip em{font-style:normal;color:#888;margin-left:5px;font-size:11px}
.c-run{background:#E6F1FB;color:#0C447C}.c-cache{background:#F1EFE8;color:#5F5E5A}
.c-fail{background:#FCEBEB;color:#A32D2D}
.vd{font-size:12px;flex:none;padding:3px 10px;border-radius:12px}
.v-pass{background:#E1F5EE;color:#085041}.v-fix{background:#FAEEDA;color:#633806}
.v-stop{background:#FCEBEB;color:#791F1F}.v-none{background:#f0f0f0;color:#666}
"""


def main():
    part = "."
    for i, a in enumerate(sys.argv):
        if a == "--part" and i + 1 < len(sys.argv):
            part = sys.argv[i + 1]
        elif a.startswith("--part="):
            part = a.split("=", 1)[1]
    path, recs = load_trace(part)
    steps, verdicts, meta, taken = walk(recs)
    if not steps:
        raise SystemExit("trace 里没有 step 记录")

    # 路径文本：按轮分段，用 ｜ 隔开
    seg, cur, buf = [], None, []
    for s in steps:
        if cur is None:
            cur = s["round"]
        if s["round"] != cur:
            seg.append(" → ".join(buf))
            buf, cur = [], s["round"]
        buf.append(CN.get(s["stage"], s["stage"]))
    if buf:
        seg.append(" → ".join(buf))
    path_txt = "　｜　".join(seg)
    out_path = os.path.join(ROOT, "docs", "trace_report.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    total = sum(s.get("dur", 0) for s in steps)
    hits = sum(1 for s in steps if s["action"] == "cache")
    argv = " ".join(meta.get("argv") or [])
    doc = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>trace 报告 — %(part)s</title><style>%(css)s</style></head><body>
<h1>运行路径报告 · %(part)s</h1>
<div class="meta"><code>python pipe.py %(argv)s</code><br>
结局 <b>%(outcome)s</b> ｜ %(nround)d 轮 ｜ 步骤 %(nstep)d 次（其中缓存命中 %(hits)d）｜ 步骤耗时合计 %(dur).1fs</div>
<div class="card">
<div style="font-size:12px;color:#555;margin-bottom:6px">本次实际路径（按执行顺序）：</div>
<div style="font-size:13px;color:#0C447C;font-weight:500">%(pathtxt)s</div>
<div style="margin-top:12px">%(svg)s</div>
<div class="legend">
<span><i class="sw" style="background:#185FA5"></i>走过的边</span>
<span><i class="sw" style="background:#D3D1C7"></i>没走的边</span>
<span><i class="sw" style="background:#E6F1FB;border:1px solid #185FA5"></i>真跑</span>
<span><i class="sw" style="background:#F1EFE8;border:1px solid #888780"></i>缓存命中</span>
<span><i class="sw" style="background:#E1F5EE;border:1px solid #0F6E56"></i>终点</span>
</div></div>
<div class="card"><div style="font-size:13px;font-weight:500;margin-bottom:6px">逐轮时间线</div>
%(timeline)s</div>
</body></html>""" % dict(
        css=CSS, part=html.escape(meta.get("part", part)), argv=html.escape(argv),
        outcome=meta.get("outcome", "?"), nround=max(s["round"] for s in steps),
        nstep=len(steps), hits=hits, dur=total, pathtxt=html.escape(path_txt),
        svg=svg(steps, taken), timeline=timeline(steps, verdicts))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    print("本次路径：%s" % path_txt)
    print("已生成：%s" % os.path.relpath(out_path, ROOT).replace("\\", "/"))


if __name__ == "__main__":
    main()
