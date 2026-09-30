# -*- coding: utf-8 -*-
r"""s9_record —— 每轮结束的「记录员」：建模思路 + 错误思路入库

闭环真正的资产不是某一版模型，而是**踩过的坑**。这一步把本轮的
判定、差异、改了什么、以及 s0 给出的方案摘要，追加进两个文件：

    notes/model_notes.md   建模思路时间线（每轮一行结论，可回溯）
    notes/errors.md        错误库（按分类去重累积，记次数，供 s0 下轮提示）
    notes/skill_feedback.md 反馈给 mech-projection-analysis 技能的条目
                                 （证伪/补正/确认。下次跑技能时把本文件当额外上下文）

入参消息
    refs: params（当前参数值）、dims_spec（分类映射）、plan_md（s0 产出的本轮方案，可选）
          skill_feedback（已有的 notes/skill_feedback.md，可选）
    data: out_dir（notes 目录）、round（轮次）
          以及驱动器注入的 s7_decide 判定（verdict/items/fixes/diagnosis）

产出
    refs: model_notes、errors_md、skill_feedback_md
    data: {round, verdict, n_new_error, n_error_total}

只有这一步和 s8_apply 会写文件：s8 改 params.py，s9 写 notes/。
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msgio import run_stage, ref_path, ref_data, exec_module      # noqa: E402


def parse_errors(text):
    out = []
    for ln in text.splitlines():
        m = re.match(r"^-\s+\[([^\]]+)\]\s*(.*?)\s*(?:\(×(\d+)\))?\s*$", ln.strip())
        if m and m.group(2):
            out.append({"cat": m.group(1).strip(),
                        "text": m.group(2).strip(),
                        "n": int(m.group(3) or 1)})
    return out


def dump_errors(errs):
    L = ["# 错误库（s9_record 自动累积，s0_plan 每轮读取）", "",
         "格式：`- [分类] 描述 (×出现次数)`。改完记得看一眼，人工补充「敢不敢改」的结论。", ""]
    for e in sorted(errs, key=lambda x: (x["cat"], x["text"])):
        L.append("- [%s] %s (×%d)" % (e["cat"], e["text"], e["n"]))
    return "\n".join(L) + "\n"


def has_role(msg, role):
    return any(r["role"] == role for r in msg.get("in", {}).get("refs", []))


def handler(in_msg):
    out_dir = ref_data(in_msg, "out_dir")
    rd = int(ref_data(in_msg, "round", 1) or 1)
    DS = exec_module(ref_path(in_msg, "dims_spec"), "part_dims_spec")
    dims = getattr(DS, "DIMS", []) or []

    verdict = ref_data(in_msg, "verdict", "unknown")
    items = ref_data(in_msg, "items") or []
    fixes = ref_data(in_msg, "fixes") or {}
    diag = ref_data(in_msg, "diagnosis", "")
    reason = ref_data(in_msg, "reason", "")

    os.makedirs(out_dir, exist_ok=True)
    notes_path = os.path.join(out_dir, "model_notes.md")
    err_path = os.path.join(out_dir, "errors.md")

    def cat_of(name):
        d = next((d for d in dims if d.get("label") and d["label"] == name), None)
        if d is None:
            d = next((d for d in dims if d.get("cat") and d["cat"] in str(name)), None)
        return (d.get("cat") if d else None) or "未分类"

    # ---- ① 建模思路时间线 ----
    if not os.path.exists(notes_path):
        open(notes_path, "w", encoding="utf-8").write(
            "# 建模思路记录（s9_record 自动追加）\n\n"
            "每轮闭环结束追加一段：本轮怎么判的、改了什么、下一轮要注意什么。\n")
    L = []
    L.append("\n## 第 %d 轮 · %s · 判定=%s\n" % (rd, time.strftime("%Y-%m-%d %H:%M:%S"), verdict))
    if diag:
        L.append("- 诊断：%s" % diag)
    if reason:
        L.append("- 理由：%s" % reason)
    if items:
        L.append("- 差异 %d 项：" % len(items))
        for x in items:
            L.append("  - `%s` 基准 %s / 当前 %s（%s）"
                     % (x.get("name"), x.get("base"), x.get("cur"), cat_of(x.get("name"))))
    else:
        L.append("- 差异：无")
    if fixes:
        L.append("- 应用修正：%s" % ", ".join("%s → %s" % (k, v) for k, v in fixes.items()))
    if has_role(in_msg, "plan_md"):
        ptxt = open(ref_path(in_msg, "plan_md"), encoding="utf-8").read()
        n_st = len(re.findall(r"^\s*\d+\.\s+\*\*", ptxt, re.M))
        L.append("- 本轮方案：notes/plan.md（构造 %d 阶段）" % n_st)
    with open(notes_path, "a", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    # ---- ② 错误库去重累积 ----
    errs = parse_errors(open(err_path, encoding="utf-8").read()) if os.path.exists(err_path) else []
    idx = {(e["cat"], e["text"]): i for i, e in enumerate(errs)}
    n_new = 0
    for x in items:
        name = str(x.get("name", ""))
        cat = cat_of(name)
        txt = "%s：图上 %s，建模得 %s" % (name, x.get("base"), x.get("cur"))
        if x.get("cur") is None:
            txt = "%s：图上 %s，建模里没有这个特征" % (name, x.get("base"))
        k = (cat, txt)
        if k in idx:
            errs[idx[k]]["n"] += 1
        else:
            idx[k] = len(errs)
            errs.append({"cat": cat, "text": txt, "n": 1})
            n_new += 1
    open(err_path, "w", encoding="utf-8").write(dump_errors(errs))

    # ---- ③ 给 mech-projection-analysis 技能写反馈 ----
    fb_path = os.path.join(out_dir, "skill_feedback.md")
    if not os.path.exists(fb_path):
        open(fb_path, "w", encoding="utf-8").write(
            "# 技能反馈（s9_record 自动追加）\n\n"
            "下次跑 `mech-projection-analysis` 技能时，把本文件当额外上下文："
            "「上一版分析在实际建模里被证伪/补正/确认了哪些条目」。\n\n"
            "格式：\n\n```\n## <日期> · 第 N 轮 · 判定=<verdict>\n"
            "- 差异 N 项：\n  - <差异名> 基准 X / 当前 Y（cat=...）\n"
            "  - 反馈类型：<证伪分析 / 补正分析 / 确认分析>\n"
            "  - 根因：<一句话>\n- 应用修正：<参数改动>\n```\n\n---")
    fb_type = {"pass": "确认分析", "fix": "补正分析",
               "manual": "证伪分析", "stuck": "证伪分析",
               "suggest": "待分析"}.get(verdict, "待分析")
    fb_L = []
    fb_L.append("\n## %s · 第 %d 轮 · 判定=%s" % (
        time.strftime("%Y-%m-%d"), rd, verdict))
    if items:
        fb_L.append("- 差异 %d 项：" % len(items))
        for x in items:
            fb_L.append("  - `%s` 基准 %s / 当前 %s（cat=%s）"
                        % (x.get("name"), x.get("base"), x.get("cur"),
                           cat_of(x.get("name"))))
    fb_L.append("- 反馈类型：%s" % fb_type)
    if fixes:
        fb_L.append("- 应用修正：%s" % ", ".join("%s → %s" % (k, v) for k, v in fixes.items()))
    if reason:
        fb_L.append("- 根因（自动判断）：%s" % reason[:120])
    with open(fb_path, "a", encoding="utf-8") as f:
        f.write("\n".join(fb_L) + "\n")

    print("[s9_record] 第 %d 轮：判定=%s，新增错误条目 %d，错误库共 %d 条，技能反馈 +1"
          % (rd, verdict, n_new, len(errs)))

    return [("model_notes", notes_path), ("errors_md", err_path),
            ("skill_feedback_md", fb_path)], {
        "round": rd, "verdict": verdict,
        "n_new_error": n_new, "n_error_total": len(errs),
        "n_item": len(items),
    }


if __name__ == "__main__":
    run_stage("s9_record", handler)
