# -*- coding: utf-8 -*-
r"""s3_render —— 图纸渲染（**共享层通用实现**，2026-10-15 从零件层下沉到这里）

## 为什么要下沉

原来每个零件各有一份 `steps/s3_render.py`（bracket / lbracket / ybracket 各 60~70 行），
内容分成两半：

* **通用骨架**（20 行）：读消息 → 取 `_drawing.json` → 调 `lib.drawing_render.render`
  → 写产物消息。三个零件一模一样。
* **零件数据**（30~40 行）：`PLACE` / `VIEW_ORDER` / `LABELS` / `TITLE` / `DIMS`。
  这五样**全是数据、没有逻辑**，却因为写在 `.py` 里而成了"产品层的代码"。

下沉后：零件目录**不再有 s3_render.py**，只剩一个 `draw_spec.py` 数据文件。
架构 `lib/drawing_render.render` 的签名变化**不再波及任何零件** —— 这是
`MSG.md §〇 接口演进纪律` 想要的效果。

## 零件怎么表达自己

`parts/<name>/draw_spec.py` 提供五样（schema 见该文件头部注释）：
`PLACE` / `VIEW_ORDER` / `LABELS` / `TITLE` / `DIMS`。

其中两处是本层提供的**声明式能力**，替代原来散在零件里的 Python：

1. `label_from="meas:L"` —— 标注数值取 `_drawing.json` 里 FreeCAD **实测值**。
   改 `params.py` 后图上数字自动跟随（bracket 之前是硬编码字符串，
   见 `docs/遗留事项与下一步.md` §二-1 —— 本层顺带修掉了）。
2. `when=dict(kind="circles_near", ...)` —— 条件标注。
   lbracket 的 pitch 原来靠 6 行 Python 判断"是否找到两个 φ8 圆"，现在声明式表达。

## 缺 draw_spec.py 时的行为

**直接报错退出**，不做静默回退（与 `pipe.py` 对 s1~s8 的策略一致）：
悄悄拿别的零件的图纸来顶替，会在很远的地方炸、报错还指向下游。
`pipe.py` 会把这条回退打在耗时排行汇总里，不再是静默发生。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPIPE_ROOT") or os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from msgio import boot, finish, ref_path, ref_data      # noqa: E402
from lib.drawing_render import render                   # noqa: E402


# ------------------------------------------------------------------ draw_spec

def _load_draw_spec():
    """定位并加载零件的 draw_spec.py（只允许在零件目录根下）。"""
    part_dir = os.environ.get("MPIPE_HERE") or os.getcwd()
    path = os.path.join(part_dir, "draw_spec.py")
    if not os.path.exists(path):
        raise FileNotFoundError(
            "缺少 %s\n"
            "  s3_render 已下沉到共享层，零件不再自带 steps/s3_render.py。\n"
            "  请在零件目录建 draw_spec.py，声明 PLACE / VIEW_ORDER / LABELS / TITLE / DIMS\n"
            "  （格式见 %s 头部注释，或参考 parts/lbracket/draw_spec.py）。"
            % (path, path))
    import importlib.util
    spec = importlib.util.spec_from_file_location("_draw_spec", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for k in ("PLACE", "VIEW_ORDER", "LABELS", "TITLE", "DIMS"):
        if not hasattr(mod, k):
            raise AttributeError("%s 缺少 %s" % (path, k))
    return mod


# ------------------------------------------------------------------ when 求值

def _eval_when(when, data):
    """求值一条标注的 `when` 条件；返回 (是否成立, 附加数据)。

    支持的谓词（2026-10-15 只这两种，覆盖当前四个零件）：

    * `dict(kind="circles_near", view=V, r=R, tol=T, n=N)`
      —— 视图 V 里半径≈R（|r-R|<tol）的圆**不少于 N 个**才成立。
      成立时返回 `("circles", [圆心按 y 排序])`，供 `span="circles"` 取端点。
    * `dict(kind="always")` —— 恒真（等价于不写 when）。
    """
    if not when:
        return True, None
    kind = when.get("kind")
    views = {v["name"]: v for v in data["views"]}
    if kind == "always":
        return True, None
    if kind == "circles_near":
        v = views.get(when["view"])
        if not v:
            return False, None
        r0 = float(when["r"])
        tol = float(when.get("tol", 0.3))
        hit = [c for c in v.get("circles", []) if abs(c["r"] - r0) < tol]
        if len(hit) < int(when.get("n", 2)):
            return False, None
        hit.sort(key=lambda c: c["cy"])
        return True, ("circles", hit)
    raise ValueError("未知的 when.kind：%r（s3_render 只支持 always / circles_near）" % (kind,))


# ------------------------------------------------------------------ DIMS 编译

def _fmt(v):
    """按原行为格式化：整数值不带小数点。"""
    f = float(v)
    return "%d" % round(f) if abs(f - round(f)) < 1e-6 else ("%.2f" % f).rstrip("0")


def _compile_dims(dims, data, meas):
    """把 draw_spec 的声明式 DIMS 编译成 `lib.drawing_render` 要的 dict 列表。

    三件事在这里做：
    1. `label_from="meas:X"` → label 取 FreeCAD 实测值（改参数自动跟随）
    2. `label_wrap="2-φ%d"` → 实测值套进格式模板（直径/半径类标注）
    3. `when` + `span="circles"` → 条件成立时把两个端点圆心填进 `wa`/`wb`
    """
    out = []
    for d in dims:
        ok, extra = _eval_when(d.get("when"), data)
        if not ok:
            continue
        item = {k: v for k, v in d.items()
                if k not in ("when", "span", "label_from", "label_wrap")}
        if "label_from" in d:
            src = d["label_from"]
            if src.startswith("meas:"):
                key = src.split(":", 1)[1]
                if key not in meas:
                    # 没有这个实测值就不标这条（宁可少标，不要标错）
                    continue
                tmpl = d.get("label_wrap")
                item["label"] = (tmpl % round(float(meas[key]))) if tmpl \
                    else _fmt(meas[key])
            else:
                item["label"] = src
        if d.get("span") == "circles" and extra:
            _tag, hit = extra
            item["wa"] = hit[0]["cy"]
            item["wb"] = hit[-1]["cy"]
        out.append(item)
    return out


# ------------------------------------------------------------------ handler

def handler(in_msg):
    spec = _load_draw_spec()
    out_dir = ref_data(in_msg, "out_dir")
    data = json.load(open(ref_path(in_msg, "drawing_json"), encoding="utf-8"))
    meas = {d["label"]: d["value"] for d in data.get("dims", [])}

    dims = _compile_dims(spec.DIMS, data, meas)
    pdf, png, dx, dy = render(data, out_dir, spec.PLACE, spec.VIEW_ORDER,
                              spec.TITLE, dims, spec.LABELS,
                              label_style=getattr(spec, "LABEL_STYLE", "right"),
                              meas=meas)

    skipped = len(spec.DIMS) - len(dims)
    if skipped:
        print("[s3_render] %d 条标注因 when 条件不成立被跳过" % skipped)
    return [("drawing_pdf", pdf), ("drawing_png", png)], {
        "pdf_bytes": os.path.getsize(pdf),
        "png_bytes": os.path.getsize(png),
        "n_dims_declared": len(spec.DIMS),
        "n_dims_drawn": len(dims),
        "shift_dx": round(dx, 2),
        "shift_dy": round(dy, 2),
    }


if __name__ == "__main__":
    from msgio import run_stage
    run_stage("s3_render", handler)