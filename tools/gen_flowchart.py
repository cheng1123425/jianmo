# -*- coding: utf-8 -*-
r"""tools/gen_flowchart.py —— 从 pipe.py 的 STEPS 自动生成流程图

为什么需要它：`MSG.md` 里的拓扑图/逐步输入输出表是**手写**的，
改 `pipe.py` 的 STEPS 后容易忘了同步。这里直接从代码生成 Mermaid 流程图，
保证图 = 代码。

用法
----
    python tools/gen_flowchart.py            # 生成 docs/flowchart.md
    python tools/gen_flowchart.py --svg      # 顺便打印一份纯文本版

生成物：`docs/flowchart.md`（GitHub / VS Code 可直接渲染 Mermaid）。
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import pipe  # noqa: E402  —— 只 import，不执行 main()

OUT_MD = os.path.join(ROOT, "docs", "flowchart.md")

# 步骤代号 → 中文名（与用户可见口径一致：不用 s0/s1 代号）
CN = {
    "s0_plan": ("规划", "读图 · 出方案 · 定位失误"),
    "s1_build": ("建模", "build123d → STEP / STL"),
    "s2_drawing": ("出图", "FreeCAD 无界面投影"),
    "s3_render": ("渲染", "A3 矢量图纸"),
    "s4_table": ("尺寸表", "参数值 vs 实测值"),
    "s5_collect": ("采集", "从投影提炼特征"),
    "s6_compare": ("比对", "对照原图基准出差异"),
    "s7_decide": ("判定", "通过 / 要改 / 待人工"),
    "s8_apply": ("写回", "唯一允许改参数"),
    "s9_record": ("记录", "思路 · 错误库 · 技能反馈"),
}


def node(stage):
    """Mermaid 节点：代号 + 中文名 + 副标题"""
    if stage in CN:
        name, sub = CN[stage]
        return '%s["%s<br/>%s"]' % (stage, name, sub)
    return '%s["%s"]' % (stage, stage)


def gen_mermaid():
    """按 pipe.py 的真实拓扑生成 Mermaid（只支持 mermaid 的 %% 注释，不写非法边）"""
    L = ["```mermaid", "graph TD", ""]
    for s in pipe.STEPS:
        L.append("    %s" % node(s["name"]))
    L.append("")

    L.append("    %% ===== 主链：每次都跑 =====")
    L.append("    %s" % (" --> ".join(pipe.CHAIN)))
    L.append('    %s --> FIN(["成品<br/>图纸 + 尺寸表"])' % pipe.CHAIN[-1])
    L.append("")

    L.append("    %% ===== 闭环：每轮都从「规划」重新开始 =====")
    L.append("    s0_plan --> s5_collect --> s6_compare --> s7_decide")
    L.append("    s7_decide -- 判定结果 --> s9_record")
    L.append("")

    L.append("    %% ===== 记录之后按判定结果分流 =====")
    L.append('    s9_record -- "通过" --> OK(["闭环结局 pass<br/>退出码 0，收工"])')
    L.append('    s9_record -- "要改 + --auto" --> s8_apply')
    L.append('    s9_record -- "无进展 / 待人工 / 仅建议" --> STOP(["停：stuck / manual / suggest<br/>退出码 2，交给人"])')
    L.append("")
    L.append("    %% ===== 写回 → 只重出几何 → 下一轮 =====")
    L.append("    s8_apply --> s1_build")
    L.append('    s2_drawing -- "下一轮（超过上限 → maxit）" --> s0_plan')
    L.append("")

    if pipe.DEFERRED:
        L.append("    %% ===== 迭代期间出图/制表延后，循环结束后补跑 =====")
        L.append('    s7_decide -. "延后" .-> %s' % pipe.DEFERRED[0])

    L.append("```")
    return "\n".join(L)


def gen_text():
    out = []
    out.append("步骤清单（来自 pipe.py 的 STEPS，共 %d 步）" % len(pipe.STEPS))
    out.append("-" * 52)
    for s in pipe.STEPS:
        tag = []
        if s.get("head"):
            tag.append("每轮开头")
        if s.get("tail"):
            tag.append("每轮结尾")
        if s.get("loop"):
            tag.append("仅 --loop")
        if s.get("optional"):
            tag.append("按需")
        if s.get("output"):
            tag.append("延迟出图")
        name, sub = CN.get(s["name"], (s["name"], ""))
        out.append("%-12s %-6s %-30s %s" % (s["name"], name, sub, "/".join(tag)))
    out.append("")
    out.append("主链（每次都跑）: %s" % " → ".join(pipe.CHAIN))
    out.append("闭环（--loop）  : 规划 → %s → 记录" % " → ".join(pipe.LOOP))
    out.append("延迟出图        : %s" % " / ".join(pipe.DEFERRED))
    out.append("迭代时只重跑    : %s" % " → ".join(pipe.QUICK_CHAIN))
    out.append("轮次上限        : 默认 %d（--max=N 可调）" % pipe.parse_argv([])["max_it"])
    return "\n".join(out)


def main():
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    body = gen_mermaid()
    text = gen_text()
    md = (
        "# 流程图（自动生成，勿手改）\n\n"
        "> 本文件由 `tools/gen_flowchart.py` 从 `pipe.py` 的 `STEPS` 生成，**不要手改**。\n"
        "> 改了流水线拓扑后跑：`python tools/gen_flowchart.py`\n\n"
        + body
        + "\n\n---\n\n## 步骤清单与运行参数\n\n```\n"
        + text
        + "\n```\n"
    )
    with io.open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(md)
    print("已生成：%s" % os.path.relpath(OUT_MD, ROOT).replace("\\", "/"))
    if "--svg" in sys.argv or "--text" in sys.argv:
        print()
        print(text)


if __name__ == "__main__":
    main()
