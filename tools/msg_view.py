#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把消息总线（_msg/*.in.json + *_msg/*.out.json）渲染成自包含 HTML 查看器。

用法：
    python tools/msg_view.py                       # 三处消息总线（垫片/铰链支座/L形支座）
    python tools/msg_view.py --part parts/bracket  # 只看铰链支座
    python tools/msg_view.py --out docs/message_line.html

每步一张卡片，展开看「入参消息(.in.json)」与「出参消息(.out.json)」原始内容。
"""
import json
import os
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 步骤代码 -> 中文命名（代码在前、命名在后，如 s1_build 建模）
STEP_NAMES = {
    "s0_plan": "规划（读图/方案/失误定位）",
    "s1_build": "建模",
    "s2_drawing": "出图",
    "s3_render": "渲染",
    "s4_table": "尺寸表",
    "s5_collect": "采集",
    "s6_compare": "比对",
    "s7_decide": "判定",
    "s8_apply": "写回",
    "s9_record": "记录",
}


def label(stage):
    n = STEP_NAMES.get(stage)
    return f"{stage} · {n}" if n else stage


def short(s, n=46):
    s = str(s).strip()
    return s if len(s) <= n else s[:n] + "…"


def load_trace_jsonl(msg_dir):
    tp = os.path.join(msg_dir, "trace.jsonl")
    if not os.path.exists(tp):
        return None
    recs = []
    with open(tp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    return recs


def round_view(msg_dir):
    """读 trace.jsonl，按轮次归组步骤；出现回边时标注。返回 HTML 或 None。"""
    recs = load_trace_jsonl(msg_dir)
    if not recs:
        return None
    # 还原轮次：与 trace_view.walk 同口径——第 2 次「规划」起算第 1 轮
    steps, round_no, plan_count = [], 0, 0
    for r in recs:
        if r.get("kind") != "step":
            continue
        if r.get("stage") == "s0_plan":
            plan_count += 1
            if plan_count >= 2:
                round_no += 1
        steps.append((round_no, r))
    if not steps:
        return None

    groups = {}
    for rn, r in steps:
        groups.setdefault(rn, []).append(r)

    def dsum(d):
        if not isinstance(d, dict):
            return ""
        return "   ".join(f"{k}={short(v, 22)}" for k, v in list(d.items())[:6])

    blocks = []
    for rn in sorted(groups):
        title = "准备（主链初跑）" if rn == 0 else f"第 {rn} 轮（闭环）"
        chips = []
        for r in groups[rn]:
            st = r.get("stage")
            act = r.get("action") or "?"
            badge = {"run": "run", "cache": "缓存", "fail": "fail"}.get(act, act)
            cls = {"run": "c-run", "cache": "c-cache", "fail": "c-fail"}.get(act, "")
            chips.append(f'<span class="chip {cls}" title="{esc(dsum(r.get("data")))}">'
                         f'{esc(label(st))}<em>{esc(badge)}</em></span>')
        blocks.append(f'<div class="rblock"><div class="rtitle">{esc(title)}</div>'
                      f'<div class="rchips">{"".join(chips)}</div></div>')

    # 是否出现回边：后续轮次首步回到 建模/规划，或中间出现 写回
    has_back = any(rn > 0 and r.get("stage") in ("s1_build", "s0_plan") for rn, r in steps) \
        or any(r.get("stage") == "s8_apply" for _, r in steps)
    note = ('<div class="backedge">↩ 回边：判定未通过 → 重新 建模→出图→采集→比对→判定，'
            '进入下一轮</div>') if has_back else \
           '<div class="backedge noback">（本次 1 轮即 pass，未触发回边迭代）</div>'
    return '<div class="roundview"><div class="rvh">轮次结构（来自 trace.jsonl）</div>' \
           + "".join(blocks) + note + "</div>"


# (标签, _msg 目录)
PARTS = [
    ("垫片 (root)", "_msg"),
    ("铰链支座 (bracket)", "parts/bracket/_msg"),
    ("L 形支座 (lbracket)", "parts/lbracket/_msg"),
]


def step_order(name):
    # s0_plan / s1_build ... -> 按数字 N 排序
    base = name[:-len(".in.json")] if name.endswith(".in.json") else name[:-len(".out.json")]
    digits = "".join(ch for ch in base if ch.isdigit())
    return (int(digits) if digits else 999, base)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def fmt_json(d):
    try:
        return json.dumps(d, ensure_ascii=False, indent=2)
    except Exception:
        return repr(d)


def part_section(part_label, msg_dir):
    path = os.path.join(ROOT, msg_dir)
    if not os.path.isdir(path):
        return f'<details open><summary>{esc(label)} — 目录不存在</summary></details>'
    files = [f for f in os.listdir(path) if f.endswith(".json")]
    ins = sorted([f for f in files if f.endswith(".in.json")], key=step_order)
    outs = set(f for f in files if f.endswith(".out.json"))

    cards = []
    for inf in ins:
        step = inf[:-len(".in.json")]
        outf = step + ".out.json"
        try:
            ind = json.load(open(os.path.join(path, inf), encoding="utf-8"))
        except Exception as e:
            ind = {"_error": str(e)}
        outd = None
        if outf in outs:
            try:
                outd = json.load(open(os.path.join(path, outf), encoding="utf-8"))
            except Exception as e:
                outd = {"_error": str(e)}

        status = (outd or {}).get("status", "?")
        stage = (outd or {}).get("stage", step)
        started = (outd or {}).get("started", "")
        finished = (outd or {}).get("finished", "")
        stcolor = {"ok": "#1a7f37", "fail": "#cf222e"}.get(status, "#666")

        body = f'<div class="stephead"><b>{esc(label(stage))}</b> '
        body += f'<span class="st" style="color:{stcolor}">[{esc(status)}]</span>'
        body += f'<span class="meta">{esc(started)} → {esc(finished)}</span></div>'

        body += '<div class="two">'
        body += '<div class="col"><div class="h">入参消息 .in.json</div><pre>'
        body += esc(fmt_json(ind)) + "</pre></div>"
        if outd is not None:
            body += '<div class="col"><div class="h">出参消息 .out.json</div><pre>'
            body += esc(fmt_json(outd)) + "</pre></div>"
        else:
            body += '<div class="col"><div class="h">出参消息</div><pre>(无 .out.json)</pre></div>'
        body += "</div>"

        cards.append(f'<details class="card"><summary>{esc(label(stage))} '
                    f'<span class="st" style="color:{stcolor}">[{esc(status)}]</span></summary>'
                    f'<div class="cardbody">{body}</div></details>')

    n = len(ins)
    rv = round_view(os.path.join(ROOT, msg_dir))
    rv_html = rv or '<div class="roundview none">（本零件 _msg 无 trace.jsonl，运行 `python pipe.py --part <零件> --loop --trace` 可启用轮次视图）</div>'
    return (f'<details open><summary class="part">{esc(part_label)} '
            f'<span class="meta">— {n} 步消息</span></summary>'
            + rv_html + "".join(cards) + "</details>")


def main():
    args = sys.argv[1:]
    out = None
    only = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--out":
            out = args[i + 1]; i += 2
        elif a == "--part":
            only = args[i + 1]; i += 2
        else:
            i += 1

    sections = []
    for label, d in PARTS:
        if only and only not in d:
            continue
        sections.append(part_section(label, d))

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>消息线查看器</title><style>
body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;background:#f6f8fa;color:#1f2328}}
header{{padding:14px 20px;background:#24292f;color:#fff}}
header h1{{margin:0;font-size:18px}}
header .sub{{opacity:.7;font-size:12px;margin-top:4px}}
.wrap{{padding:16px 20px}}
.part{{font-size:15px;font-weight:600;margin:14px 0 6px;background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:10px 12px;cursor:pointer}}
.card{{border:1px solid #d0d7de;border-radius:6px;margin:6px 0;background:#fff}}
.card>summary{{padding:8px 12px;cursor:pointer;font-size:13px}}
.cardbody{{padding:0 12px 12px}}
.stephead{{margin:6px 0 4px}}
.st{{font-weight:600}}
.meta{{color:#656d76;font-size:12px;margin-left:8px}}
.two{{display:flex;gap:12px;flex-wrap:wrap}}
.col{{flex:1;min-width:320px;border:1px solid #eaeef2;border-radius:6px;overflow:hidden}}
.col .h{{background:#f0f3f6;padding:5px 10px;font-size:12px;font-weight:600;color:#444}}
pre{{margin:0;padding:10px;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word;max-height:360px;overflow:auto;background:#fafbfc}}
.roundview{{border:1px solid #c8e1ff;background:#f3f9ff;border-radius:6px;padding:10px 12px;margin:6px 0 12px}}
.roundview.none{{border-color:#e1e4e8;background:#f6f8fa;color:#656d76;font-size:12px}}
.rvh{{font-size:12px;font-weight:600;color:#0C447C;margin-bottom:8px}}
.rblock{{display:flex;align-items:flex-start;gap:10px;padding:6px 0;border-bottom:1px dashed #d6e7fb}}
.rblock:last-of-type{{border-bottom:0}}
.rtitle{{width:120px;flex:none;font-size:12px;color:#444;font-weight:600;padding-top:3px}}
.rchips{{flex:1;display:flex;flex-wrap:wrap;gap:6px}}
.chip{{font-size:12px;padding:3px 9px;border-radius:14px;background:#eef1f4;color:#333;border:1px solid #d7dbe0;cursor:help}}
.chip em{{font-style:normal;color:#888;margin-left:5px;font-size:11px}}
.c-run{{background:#E6F1FB;color:#0C447C;border-color:#b9d6f2}}
.c-cache{{background:#F1EFE8;color:#5F5E5A;border-color:#e0ddcf}}
.c-fail{{background:#FCEBEB;color:#A32D2D;border-color:#f0c9c9}}
.backedge{{margin-top:8px;font-size:12px;color:#0C447C;background:#e1f0ff;padding:5px 9px;border-radius:5px}}
.backedge.noback{{color:#656d76;background:#eef1f4}}
</style></head><body>
<header><h1>消息线查看器（_msg 总线）</h1>
<div class="sub">生成时间 {now} · 每个步骤的「入参消息→出参消息」即步骤间唯一通信 · 展开看原始 JSON</div></header>
<div class="wrap">{''.join(sections)}</div></body></html>"""

    if not out:
        out = os.path.join(ROOT, "docs", "message_line.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", out)


if __name__ == "__main__":
    main()
