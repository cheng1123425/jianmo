# -*- coding: utf-8 -*-
r"""s6b_projection —— 绘图投影原则校验（独立隔离步骤）

**为什么单独一步**

s6_compare 比对的是「模型 vs 原图基准」（零件做得对不对）；
本步校验的是「三视图之间说得通吗」（图画得对不对）—— 这是**图纸规范**问题，
不是几何精度问题。混在一起会让"投影关系错了"和"尺寸做小了"难以分辨。

校验的投影原则（第一角投影，中国国标 GB）
--------------------------------------
1. **长对正**  主视图与俯视图的长度（x）相等，且中心对齐
2. **高平齐**  主视图与左/右视图的高度（y）相等
3. **宽相等**  俯视图的宽度（y）与侧视图的宽度（x）相等
4. **视图齐全** 三视图缺一不可 —— 缺侧视图则 2/3 无法校验，本身即违规
5. **中心共线** 各视图的对称中心落在同一条投影线上
6. **图尺相符** 视图包围盒必须装得下它的尺寸标注（放不下的尺寸是错的）

隔离约定
--------
* 只通过消息通信：入参走 refs，sha256 不符即报错
* 不 import params / ref_spec / dims_spec —— exec_module 按消息路径加载
* 不 import 其他 s*_ 步骤
* 不改任何文件（只有 s8_apply 能改 params.py，驱动器运行时强制）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

from msgio import run_stage, ref_path, ref_data, exec_module   # noqa: E402

# 第一角投影（国标）的视图配置：哪个视图该挨着谁
FIRST_ANGLE = {
    "Front": {"right": "Left", "below": "Top"},     # 左视图放右边，俯视图放下边
}


def _view_extent(v):
    pts = [q for e in v["edges"] for q in e]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {"x": (min(xs), max(xs)), "y": (min(ys), max(ys))}


def _dim_of(dw, label):
    for d in dw.get("dims", []):
        if d.get("label") == label:
            return d
    return None


def check(dw, tol=1e-6):
    """返回 issues 列表"""
    issues = []
    views = {v["name"]: v for v in dw.get("views", []) if v["name"] != "Iso"}
    ext = {n: _view_extent(v) for n, v in views.items()}
    ext = {n: e for n, e in ext.items() if e}

    def add(kind, sev, msg, **kw):
        d = {"kind": kind, "severity": sev, "msg": msg}
        d.update(kw)
        issues.append(d)

    # ---- 4) 视图齐全 ----
    need = ["Front", "Top"]
    side = [n for n in views if n in ("Left", "Right")]
    missing = [n for n in need if n not in ext]
    if missing:
        add("view_missing", "error",
            "缺少基本视图：%s —— 无法构齐三视图" % ", ".join(missing))
    if not side:
        add("view_missing", "error",
            "缺少侧视图（Left/Right）—— 「高平齐」「宽相等」两项投影原则"
            "无从校验；且国标三视图必须主视+俯视+侧视齐全")
    # 缺视图只记录，**不提前返回**：能验的项目照验（长对正、图尺相符、
    # 高度链都不依赖侧视图），否则一次缺视图会连带漏掉真正的几何错误。

    F, T = ext.get("Front"), ext.get("Top")
    S = ext.get(side[0]) if side else None

    # ---- 1) 长对正（只依赖主视 + 俯视）----
    if F and T:
        fL = F["x"][1] - F["x"][0]
        tL = T["x"][1] - T["x"][0]
        if abs(fL - tL) > max(tol, 1e-6 * max(fL, tL)):
            add("length_align", "error",
                "长对正不符：主视图长 %.3f ≠ 俯视图长 %.3f（差 %+.3f）"
                % (fL, tL, tL - fL), front=fL, top=tL, err=round(tL - fL, 4))
        else:
            add("length_align", "ok",
                "长对正：主视/俯视长度均为 %.3f" % fL, front=fL, top=tL)

    # ---- 2) 高平齐（主视 + 侧视）----
    if F and S:
        fH = F["y"][1] - F["y"][0]
        sH = S["y"][1] - S["y"][0]
        if abs(fH - sH) > max(tol, 1e-6 * max(fH, sH)):
            add("height_align", "error",
                "高平齐不符：主视图高 %.3f ≠ %s 高 %.3f（差 %+.3f）"
                % (fH, side[0], sH, sH - fH), front=fH, side=sH,
                err=round(sH - fH, 4))
        else:
            add("height_align", "ok",
                "高平齐：主视/%s 高度均为 %.3f" % (side[0], fH),
                front=fH, side=sH)

    # ---- 3) 宽相等（俯视 + 侧视）----
    if T and S:
        tW = T["y"][1] - T["y"][0]
        sW = S["x"][1] - S["x"][0]
        if abs(tW - sW) > max(tol, 1e-6 * max(tW, sW)):
            add("width_equal", "error",
                "宽相等不符：俯视图宽 %.3f ≠ %s 宽 %.3f（差 %+.3f）"
                % (tW, side[0], sW, sW - tW), top=tW, side=sW,
                err=round(sW - tW, 4))
        else:
            add("width_equal", "ok",
                "宽相等：俯视/%s 宽度均为 %.3f" % (side[0], tW),
                top=tW, side=sW)

    # ---- 5) 中心共线 ----
    bad_center = False
    pairs = [("Front", "Top", "x")]
    if side:
        pairs.append(("Front", side[0], "y"))
    for a, b, ax in pairs:
        if a not in ext or b not in ext:
            continue
        ca = (ext[a][ax][0] + ext[a][ax][1]) / 2.0
        cb = (ext[b][ax][0] + ext[b][ax][1]) / 2.0
        if abs(ca - cb) > max(1e-6, 0.01 * max(abs(ca), abs(cb), 1.0)):
            add("center_align", "error",
                "中心不共线：%s 与 %s 的 %s 中心 %.3f ≠ %.3f"
                % (a, b, ax, ca, cb))
            bad_center = True
    if not bad_center:
        add("center_align", "ok", "各视图中心共线")

    # ---- 6) 图尺相符：包围盒必须装得下尺寸标注 ----
    checks = [("extentH", "Top", "x", "总长"), ("extentV", "Top", "y", "总宽")]
    for label, vname, ax, what in checks:
        d = _dim_of(dw, label)
        if not d or vname not in ext:
            continue
        rng = ext[vname][ax]
        size = rng[1] - rng[0]
        if d["value"] > size + 1e-6:
            add("view_vs_dim", "error",
                "%s 标注 %s=%.3f 超出 %s 视图 %s 向范围 %.3f —— 视图装不下该尺寸"
                % (what, label, d["value"], vname, ax, size),
                dim=d["value"], view=size)
        elif d["value"] < size - max(1e-6, 0.02 * size):
            add("view_vs_dim", "warn",
                "%s 标注 %s=%.3f 小于 %s 视图 %s 向范围 %.3f —— 有未标注的凸出"
                % (what, label, d["value"], vname, ax, size),
                dim=d["value"], view=size)

    # ---- 附加：前视高度链之和必须等于主视图总高 ----
    hs = [d for d in dw.get("dims", [])
          if d.get("kind") == "distY" and d.get("view") == "Front"]
    if hs and "Front" in ext:
        total = ext["Front"]["y"][1] - ext["Front"]["y"][0]
        s = sum(d["value"] for d in hs)
        if abs(s - total) > max(1e-6, 0.02 * total):
            add("height_chain", "error",
                "主视高度尺寸链不闭合：Σ%s = %.3f ≠ 主视图总高 %.3f"
                "（差 %+.3f）—— 投影里放不下这组高度标注"
                % ("+".join("%s" % d["label"] for d in hs), s, total, s - total),
                sum=s, total=total, err=round(s - total, 4))

    return issues, ext


def _load_json_opt(in_msg, *roles):
    """按 role 取入参（JSON 文件），支持多个候选 role 依序回落。

    路径**必须**经 msgio.ref_path 解析：它以 MPIPE_HERE 为基准展开相对路径并校验
    sha256。不能直接 os.path.exists(r["path"]) —— 那是相对子进程 CWD（=项目根），
    所有零件都会误读根目录垫片的 _drawing.json，表现为四件报出相同的假投影错误。
    `@步名` 优先，文件形式（_file 后缀）兜底 —— 单步调试时也能跑。
    """
    import json
    for role in roles:
        try:
            ap = ref_path(in_msg, role)
        except (KeyError, FileNotFoundError):
            continue          # 该 role 未声明 / 文件不在 → 试下一个候选
        with open(ap, encoding="utf-8") as f:
            return json.load(f)
    return None


def handler(in_msg):
    dw = _load_json_opt(in_msg, "drawing_json", "drawing_json_file")
    if dw is None:
        raise FileNotFoundError("拿不到投影数据（role=drawing_json）—— "
                                "本步需要 s2_drawing 的产物")

    issues, ext = check(dw)
    n_err = sum(1 for i in issues if i["severity"] == "error")
    n_ok = sum(1 for i in issues if i["severity"] == "ok")

    print("[投影原则] 视图：%s" % ", ".join(sorted(ext)))
    for i in issues:
        mark = {"ok": "  ", "error": "!!", "warn": " !"}[i["severity"]]
        print("   %s %s" % (mark, i["msg"]))

    return [], {
        # 命名空间隔离：out.data 会平铺进下游入参 data，键名必须全局唯一 ——
        # 收在 "projection" 下，避免覆盖 s6_compare 的 issues（s7 会拿错清单）。
        "projection": {
            "n_issues": len(issues), "n_error": n_err, "n_ok": n_ok,
            "issues": issues,
            "extents": {n: {"x": [round(v, 4) for v in e["x"]],
                            "y": [round(v, 4) for v in e["y"]]}
                        for n, e in ext.items()},
        },
    }


if __name__ == "__main__":
    run_stage("s6b_projection", handler)
