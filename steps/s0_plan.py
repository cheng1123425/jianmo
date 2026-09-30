# -*- coding: utf-8 -*-
r"""s0_plan —— 每轮循环前的「读图 → 建模方案 → 失误定位」

这一步不建模、不出图，只做**思考**：把图纸基准、尺寸关系、历史错误
和上一轮的判定拼成一份「本轮该怎么画」的方案，交给人和后面的步骤看。

入参消息
    refs: params      (params.py —— 人的输入，当前参数值)
          dims_spec   (dims_spec.py —— 标注 ↔ 实体关系表)
          ref_spec    (ref_spec.py —— 原图基准 / 真值)
          plan_src    (notes/plan_src.md —— 人工维护的建模方案源：读图/构造/易错)
          errors_md   (notes/errors.md —— 历史错误库，可选)
          skill_advice (notes/skill_advice.md —— 来自 mech-projection-analysis 技能的视图映射/有序步骤/风险，可选)
    data: out_dir（notes 目录）、round（轮次）
          以及驱动器注入的上一轮 s7_decide 判定（verdict/items/fixes）

产出
    refs: plan_md   (notes/plan.md —— 本轮方案)
    data: {read, stages, precheck, suspects, risks, round, n_bad, n_suspect}

为什么放在循环最前面
    闭环最容易出现的浪费是「不看图纸就改参数」。s0 先把
    ① 图上标了什么  ② 每个标注对应实体的哪一段  ③ 上一轮栽在哪一步
    摆出来，后面的 s5~s8 就有据可依，少走回头路。
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msgio import run_stage, ref_path, ref_data, exec_module      # noqa: E402


# ---------------- notes/plan_src.md 解析 ----------------
def parse_sections(text):
    """## 段名 → 行列表"""
    secs, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            cur = s[3:].strip()
            secs.setdefault(cur, [])
        elif cur is not None:
            secs[cur].append(line.rstrip())
    return secs


def parse_stages(lines):
    """解析「构造」段：
        1. 底板 | cat=底板 | params=L,W,T | how=Rectangle + extrude(T)
    """
    stages = []
    for ln in lines:
        m = re.match(r"^\s*(\d+)\.\s+(.+)$", ln)
        if not m:
            continue
        rest, meta = m.group(2).strip(), {}
        title = rest
        if "|" in rest:
            ps = [x.strip() for x in rest.split("|")]
            title = ps[0]
            for p in ps[1:]:
                if "=" in p:
                    k, v = p.split("=", 1)
                    meta[k.strip()] = v.strip()
        stages.append(dict(
            no=int(m.group(1)), title=title,
            cats=[x.strip() for x in meta.get("cat", "").split(",") if x.strip()],
            params=[x.strip() for x in meta.get("params", "").split(",") if x.strip()],
            how=meta.get("how", "")))
    return stages


def parse_errors(text):
    """解析错误库： - [分类] 描述 (×N)"""
    out = []
    for ln in text.splitlines():
        m = re.match(r"^-\s+\[([^\]]+)\]\s*(.*?)\s*(?:\(×(\d+)\))?\s*$", ln.strip())
        if m and m.group(2):
            out.append({"cat": m.group(1).strip(),
                        "text": m.group(2).strip(),
                        "n": int(m.group(3) or 1)})
    return out


# ---------------- notes/skill_advice.md 解析 ----------------
def parse_skill_steps(lines):
    """技能模板「## 5. 高效作画 / 建模步骤」段的编号列表；紧随其后的「理由：…」也并入。"""
    steps, last = [], None
    for ln in lines:
        m = re.match(r"^\s*(\d+)\.\s+(.+)$", ln)
        if m:
            if last is not None:
                steps.append(last)
            last = dict(no=int(m.group(1)), title=m.group(2).strip(), reason="")
        elif last is not None and ln.strip():
            r = re.search(r"理由[：:]\s*(.+)$", ln)
            last["reason"] = (r.group(1).strip() if r else (last["reason"] + " " + ln.strip())).strip()
    if last is not None:
        steps.append(last)
    return steps


def parse_skill_risks(lines):
    """技能模板「## 6. 风险与待确认」的 markdown 表行。
    支持 4 列「项/问题/影响/建议」和 5 列「#/项/问题/影响/建议」两种表头。
    跳过表头（首格是 # 或空）和分隔行（任何格只含 - 字符）。"""
    out = []
    for ln in lines:
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(c) < 4 or not c[0] or c[0] == "#":
            continue
        if any((not x) or set(x) <= set("-") for x in c):
            continue                                # 表头/分隔行
        if len(c) >= 5:
            out.append(dict(num=c[0], item=c[1], issue=c[2], impact=c[3], advice=c[4]))
        else:
            out.append(dict(num="", item=c[0], issue=c[1], impact=c[2], advice=c[3]))
    return out


def has_role(msg, role):
    return any(r["role"] == role for r in msg.get("in", {}).get("refs", []))


def bullets(lines):
    return [l.strip().lstrip("-").strip() for l in lines if l.strip().startswith("-")]


# ---------------- 主逻辑 ----------------
def handler(in_msg):
    P = exec_module(ref_path(in_msg, "params"), "part_params")
    DS = exec_module(ref_path(in_msg, "dims_spec"), "part_dims_spec")
    RS = exec_module(ref_path(in_msg, "ref_spec"), "part_ref_spec")
    src_path = ref_path(in_msg, "plan_src")
    out_dir = ref_data(in_msg, "out_dir")
    rd = int(ref_data(in_msg, "round", 1) or 1)

    tol = float(getattr(RS, "TOL", 0.5))
    marks = getattr(RS, "MARKS", {}) or {}
    dims = getattr(DS, "DIMS", []) or []

    text = open(src_path, encoding="utf-8").read()
    secs = parse_sections(text)
    stages = parse_stages(secs.get("构造", []))
    read_lines = [l for l in secs.get("读图", []) if l.strip()]
    pitfalls = bullets(secs.get("易错", []))

    errs = []
    if has_role(in_msg, "errors_md"):
        errs = parse_errors(open(ref_path(in_msg, "errors_md"), encoding="utf-8").read())

    # ---- ①' 技能建议（mech-projection-analysis 的产物） ----
    skill_steps, skill_risks, skill_view_map = [], [], []
    if has_role(in_msg, "skill_advice"):
        sk = parse_sections(open(ref_path(in_msg, "skill_advice"), encoding="utf-8").read())
        for key, lines in sk.items():
            if "视图" in key and ("投影" in key or "辨认" in key or "映射" in key):
                skill_view_map = [l for l in lines if l.strip()]
            elif "步骤" in key or "作画" in key:
                skill_steps = parse_skill_steps(lines)
            elif "风险" in key:
                skill_risks = parse_skill_risks(lines)

    # ---- ① 参数预检：关系式算出来的值 vs 图上标的数 ----
    pre = []
    for d in dims:
        label, key = d.get("label"), d.get("key")
        try:
            cur = float(d["expr"](P))
        except Exception:
            cur = None
        base = marks.get(label)
        if base is None or cur is None:
            continue
        base = float(base)
        ok = abs(cur - base) <= tol
        action = None
        # 只有「标注 == 参数本身」的恒等关系才敢直接反解出建议值
        if (not ok) and key and hasattr(P, key):
            try:
                if abs(float(getattr(P, key)) - cur) < 1e-9:
                    action = [key, round(base, 4)]
            except Exception:
                action = None
        pre.append(dict(label=label, cat=d.get("cat"), key=key, base=base,
                        cur=round(cur, 3), rel=d.get("rel"), ok=ok, action=action))
    n_bad = sum(1 for x in pre if not x["ok"])

    # ---- ② 上一轮差异 → 定位到具体建模阶段 ----
    def locate(name):
        hit = next((d for d in dims if d.get("label") and d["label"] == name), None)
        if hit is None:
            hit = next((d for d in dims if d.get("cat") and d["cat"] in name), None)
        if hit is None:
            hit = next((d for d in dims if d.get("key") and d["key"] in name), None)
        cat = hit.get("cat") if hit else None
        st = next((s for s in stages if cat and cat in s["cats"]), None)
        return cat, st

    suspects = []
    for x in (ref_data(in_msg, "items") or []):
        name = str(x.get("name", ""))
        cat, st = locate(name)
        suspects.append(dict(name=name, base=x.get("base"), cur=x.get("cur"),
                             cat=cat, stage=(st["no"] if st else None),
                             stage_title=(st["title"] if st else None)))

    # ---- ③ 历史错误提示：只挑与本轮相关的分类 ----
    cats = set(s["cat"] for s in suspects if s["cat"]) | \
        set(x["cat"] for x in pre if (not x["ok"]) and x["cat"])
    risks = [e for e in errs if (not cats) or (e["cat"] in cats)]
    if not risks and not cats:
        risks = errs[:5]                      # 首轮没有线索时，列出最常犯的几条

    # ---- ④ 写本轮方案 ----
    os.makedirs(out_dir, exist_ok=True)
    plan_path = os.path.join(out_dir, "plan.md")
    L = []
    w = L.append
    w("# 建模方案（第 %d 轮 · %s）\n" % (rd, time.strftime("%Y-%m-%d %H:%M:%S")))
    if skill_steps or skill_risks or skill_view_map:
        w("## 0. 投影技能建议（mech-projection-analysis）\n")
        if skill_view_map:
            w("视图映射：\n")
            for l in skill_view_map[:8]:
                w("> %s" % l.lstrip("|").strip())
            w("")
        if skill_steps:
            w("### 0.1 推荐作画/建模顺序\n")
            for s in skill_steps:
                w("%d. **%s**" % (s["no"], s["title"]))
                if s["reason"]:
                    w("   - 理由：%s" % s["reason"])
            w("")
        if skill_risks:
            w("### 0.2 技能列出的风险\n")
            w("| # | 项 | 问题 | 影响 | 建议 |")
            w("|---|---|---|---|---|")
            for r in skill_risks:
                w("| %s | %s | %s | %s | %s |" % (
                    r.get("num", ""), r["item"], r["issue"], r["impact"], r["advice"]))
            w("")
    w("## 1. 读图结论\n")
    for l in read_lines:
        w(l)
    if not read_lines:
        w("（notes/plan_src.md 缺少「## 读图」段）\n")
    w("\n## 2. 构造顺序\n")
    if stages:
        for s in stages:
            w("%d. **%s**　分类=%s" % (s["no"], s["title"], ",".join(s["cats"]) or "-"))
            if s["params"]:
                w("   - 参数：%s" % ", ".join(s["params"]))
            if s["how"]:
                w("   - 做法：%s" % s["how"])
    else:
        w("（notes/plan_src.md 缺少「## 构造」段）\n")
    w("\n## 3. 参数预检（图上标的 vs 关系式算的）\n")
    if pre:
        w("| 标注 | 分类 | 图上 | 当前 | 关系 | 判定 |")
        w("|---|---|---|---|---|---|")
        for x in pre:
            w("| %s | %s | %s | %s | %s | %s |" % (
                x["label"], x["cat"] or "-", x["base"], x["cur"],
                x["rel"] or "-", "OK" if x["ok"] else "**不符**"))
    else:
        w("（dims_spec 与 ref_spec.MARKS 没有可对上的项）\n")
    w("\n## 4. 上一轮差异 → 疑似失误的建模阶段\n")
    if suspects:
        for s in suspects:
            w("- `%s`　基准 %s / 当前 %s → 阶段 %s（%s）" % (
                s["name"], s["base"], s["cur"],
                s["stage"] if s["stage"] else "?",
                s["stage_title"] or "未能定位"))
    else:
        w("- 无（首轮或上一轮无差异）\n")
    w("\n## 5. 历史错误提示\n")
    if risks:
        for e in risks:
            w("- [%s] %s（已犯 %d 次）" % (e["cat"], e["text"], e["n"]))
    else:
        w("- 错误库里还没有相关条目\n")
    if pitfalls:
        w("\n## 6. 已知易错点（方案源）\n")
        for p in pitfalls:
            w("- %s" % p)
    open(plan_path, "w", encoding="utf-8").write("\n".join(L) + "\n")

    print("[s0_plan] 第 %d 轮：构造 %d 阶段，预检不符 %d 项，疑似失误 %d 处，历史错误提示 %d 条"
          % (rd, len(stages), n_bad, len(suspects), len(risks)))
    for s in suspects:
        if s["stage"]:
            print("      阶段 %d「%s」← %s" % (s["stage"], s["stage_title"], s["name"]))

    return [("plan_md", plan_path)], {
        "round": rd,
        "n_stages": len(stages),
        "n_bad": n_bad,
        "n_suspect": len(suspects),
        "n_risk": len(risks),
        "n_skill_steps": len(skill_steps),
        "n_skill_risks": len(skill_risks),
        "precheck": pre,
        "suspects": suspects,
        "risks": [e["text"] for e in risks],
        "skill_steps": skill_steps,
        "skill_risks": skill_risks,
        "stages": [{"no": s["no"], "title": s["title"], "cats": s["cats"]} for s in stages],
    }


if __name__ == "__main__":
    run_stage("s0_plan", handler)
