# -*- coding: utf-8 -*-
r"""s5b_dimchain —— 尺寸链校验（独立隔离步骤）

**为什么要单独一步、而且要隔离**

尺寸链校验是"图纸自洽性"检验，和"模型 vs 图纸"比对（s6_compare）是两件事：
  * s6_compare 回答「模型做得对不对」
  * 本步回答    「图纸本身说得通吗」—— Σ各段 = 总尺寸吗？有没有漏标/重标？

后者不依赖模型，只依赖标注集合，因此必须能在模型还没建好之前就跑；
而且它的结论（"这条链不闭合"）会影响后续所有判断，所以不能和 s6 搅在一起。
合在一起会让"图纸错"和"模型错"混为一谈，出了偏差查不出是哪边的责任。

隔离约定
--------
* 只通过消息通信：所有入参走 refs，sha256 不符即报错
* 不 import params / ref_spec / dims_spec —— 用 exec_module 按消息声明的路径加载
* 不 import 其他 s*_ 步骤
* 不改任何文件（驱动器运行时强制，只有 s8_apply 能改 params.py）
* 产出只写自己的 out.json

算法见 tools/dimchain.py：
  构链（并查集，端点重合即同链）→ 逐链闭合校验 → 径向链（半径/直径参与）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

from msgio import run_stage, ref_path, ref_data, exec_module   # noqa: E402
import dimchain                                                # noqa: E402


def _load_json_opt(in_msg, *roles):
    """按 role 取可选入参（JSON 文件），支持多个候选 role 依序回落。
    `@步名` 优先，文件形式（_file 后缀）兜底 —— 单步调试时也能跑。"""
    import json
    refs = in_msg.get("in", {}).get("refs", [])
    for role in roles:
        for r in refs:
            if r["role"] == role and os.path.exists(r["path"]):
                with open(r["path"], encoding="utf-8") as f:
                    return json.load(f)
    return None


def _dims_from_sem(sem):
    """把 dwg_semantics 的 dims 转成 dimchain 认的格式（补 value_mm）"""
    out = []
    for d in sem.get("dims", []):
        v = d.get("values")
        val = None
        if isinstance(v, (list, tuple)) and v:
            val = v[0]
        if d.get("type") == "radius" and val is not None:
            pass                                   # 半径单独按 diameter 处理
        item = dict(d)
        item["value_mm"] = val if val is not None else d.get("measured_mm")
        if d.get("type") in ("diameter", "pattern_dia") and val is not None:
            item["value_mm"] = val
        out.append(item)
    return out


def _dims_from_drawing(dw):
    """把 _drawing.json 的 dims（当前模型的标注）转成 dimchain 格式。
    模型侧**只有数值、没有像素端点**，因此不造假 p1/p2 —— 端点重合构链
    只属于原图侧；模型侧走按 (view, axis) 分组的数值闭合（见 handler）。"""
    out = []
    for d in dw.get("dims", []):
        out.append({
            "label": d.get("label"), "text": d.get("label"),
            "type": "dia" if d["kind"] == "dia" else
                    ("radius" if d["kind"] == "rad" else "linear"),
            "value_mm": d.get("value"),
            "view": d.get("view"),
            "kind": d.get("kind"),
        })
    return out


def _view_extent_mm(v):
    """视图包围盒（_drawing.json 的 edges 坐标单位是 mm）"""
    pts = [q for e in v["edges"] for q in e]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {"x": (min(xs), max(xs)), "y": (min(ys), max(ys))}


def check_value_groups(mdims, ext, tol_ratio=0.02, min_tol_mm=0.5):
    """模型侧数值闭合：按 (view, axis) 分组，Σ该组段值 vs 该视图该方向跨度。

    抓两类问题：
      * closure   段值之和装不进投影（重复标注 / 数值与几何矛盾）
      * under_dim 段值之和小於跨度（有未标注的凸出）
    dia/rad 不参与线性闭合（它们是径向量，归径向链管）。
    """
    issues = []
    groups = {}
    for d in mdims:
        if d.get("kind") not in ("distX", "distY"):
            continue
        ax = "x" if d["kind"] == "distX" else "y"
        groups.setdefault((d.get("view"), ax), []).append(d)
    for (view, ax), segs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        e = ext.get(view)
        if not e:
            continue
        span = e[ax][1] - e[ax][0]
        if span <= 0:
            continue
        s = sum(float(d.get("value_mm") or 0.0) for d in segs)
        tol = max(min_tol_mm, tol_ratio * span)
        names = "+".join(str(d.get("text")) for d in segs)
        if s > span + tol:
            issues.append({
                "kind": "closure", "severity": "error",
                "msg": "模型侧 %s 视图 %s 向尺寸链装不进投影：Σ%s = %.3f > 跨度 %.3f"
                       "（差 %+.3f）—— 重复标注或数值与几何矛盾"
                       % (view, ax, names, s, span, s - span),
                "view": view, "axis": ax, "sum": round(s, 3),
                "span": round(span, 3), "err": round(s - span, 3),
                "chain": {"axis": ax, "segments": [
                    {"text": d.get("text"), "value_mm": d.get("value_mm")}
                    for d in segs]},
            })
        elif s < span - tol:
            issues.append({
                "kind": "under_dim", "severity": "warn",
                "msg": "模型侧 %s 视图 %s 向尺寸链未覆盖全跨度：Σ%s = %.3f < 跨度 %.3f"
                       "（差 %+.3f）—— 有未标注的凸出"
                       % (view, ax, names, s, span, s - span),
                "view": view, "axis": ax, "sum": round(s, 3),
                "span": round(span, 3), "err": round(s - span, 3),
            })
    return issues


def handler(in_msg):
    verbose = bool(ref_data(in_msg, "verbose", False))

    sem = _load_json_opt(in_msg, "dwg_semantics", "dwg_semantics_file")
    dw = _load_json_opt(in_msg, "drawing_json", "drawing_json_file")
    params = None
    try:
        params = exec_module(ref_path(in_msg, "params"), "params_for_chain")
    except KeyError:
        params = None

    # ---- 原图侧：图纸自身自洽吗 ----
    issues, chains, radial, fixes = [], [], [], {}
    if sem and not sem.get("no_drawing"):
        mp = sem.get("mm_per_px") or 0.0
        dims = _dims_from_sem(sem)
        circles = sem.get("circles", [])
        chains, issues, radial = dimchain.check_all(dims, mp, circles=circles)
        # 链给出的建议值：接地位可疑的距离标注 → 用链值覆盖
        for it in issues:
            if it.get("kind") == "pitch_vs_dim" and it.get("chain_part_mm"):
                fixes.setdefault("pitch_from_chain", []).append({
                    "text": it.get("text"),
                    "dim_mm": it.get("dim_mm"),
                    "chain_mm": it.get("chain_part_mm"),
                    "measured_mm": it.get("seg_mm"),
                })
    elif sem and sem.get("no_drawing"):
        issues.append({"kind": "no_drawing", "severity": "info",
                       "msg": "本零件无二维图纸 → 跳过原图侧尺寸链校验（只验模型侧）"})
    else:
        issues.append({"kind": "no_input", "severity": "warn",
                       "msg": "没有图纸语义输入（dwg_semantics），跳过尺寸链校验"})

    # ---- 模型侧：当前参数/投影说得通吗 ----
    # 模型侧只有数值没有像素端点 → 不做端点重合构链（那是原图侧的特权），
    # 改为按 (view, axis) 分组的数值闭合：Σ段值 vs 视图跨度。
    model_issues = []
    if dw:
        mdims = _dims_from_drawing(dw)
        ext = {}
        for v in dw.get("views", []):
            if v["name"] == "Iso":
                continue
            e = _view_extent_mm(v)
            if e:
                ext[v["name"]] = e
        model_issues = check_value_groups(mdims, ext)

    n_err = sum(1 for it in issues + model_issues if it.get("severity") == "error")
    n_warn = sum(1 for it in issues + model_issues if it.get("severity") == "warn")

    print("[尺寸链] 原图侧：线性链 %d 条，径向链 %d 条，问题 %d 个"
          % (len(chains), len(radial), len(issues)))
    for ch in chains:
        print("     链[%s] %s" % (ch["axis"],
              " + ".join("%s=%.1f" % (s["text"], s["value_mm"])
                         for s in ch["segments"])))
    for ch in radial:
        print("     径向链[%s] %.2fmm = %s"
              % (ch["axis"], ch["span_mm"],
                 " + ".join("%.1f" % p for p in ch["parts"])))
    if dw:
        print("[尺寸链] 模型侧：数值分组闭合，问题 %d 个" % len(model_issues))
    for it in issues + model_issues:
        print("     ! [%s] %s" % (it.get("severity"), it.get("msg")))

    return [], {
        # 命名空间隔离：out.data 会按 in_data_from 平铺进下游的入参 data，
        # 因此键名必须全局唯一 —— 本步全部产出收在 "dimchain" 一个键下，
        # 避免与 s6_compare 的 issues 等同名键冲突（那会让 s7 拿错清单）。
        "dimchain": {
            "n_chains": len(chains), "n_radial": len(radial),
            "n_issues": len(issues) + len(model_issues),
            "n_error": n_err, "n_warn": n_warn,
            "chains": [{"axis": c["axis"], "span_px": round(c["span"], 2),
                        "segments": [{"text": s["text"], "value_mm": s["value_mm"],
                                      "measured_mm": s.get("measured_mm")}
                                     for s in c["segments"]]}
                       for c in chains],
            "radial": [{"axis": c["axis"], "span_mm": c["span_mm"],
                        "parts": c["parts"]} for c in radial],
            "issues": issues + model_issues,
            "fixes": fixes,
        },
    }


if __name__ == "__main__":
    run_stage("s5b_dimchain", handler)
