# -*- coding: utf-8 -*-
r"""lib/pdf_marks.py —— 闭环校验「交付 PDF 上印的字」与「模型实测值」是否一致

## 为什么需要这个模块（遗留事项与下一步 §二-2）

`s6_compare` 原本只比 `_drawing.json` 里 FreeCAD 的**标注值**，
**从不看交付 PDF 上到底印了什么字**。后果是：
bracket 曾把 13 条标注写成**硬编码字符串**（`"28"` / `"16"` / `"8"`…），
改 `params.py` 后 PDF 上的数字**不变**，而闭环一路 pass —— **检测缺口**。

## 两道检查（从便宜到贵）

**① 硬编码扫描（静态，不用读 PDF）** —— `check_draw_spec`
`draw_spec.py` 的 `DIMS` 里，**任何没有 `label_from="meas:X"` 却带字面量 `label=`的条目，
都是硬编码**（bracket 就是这么出事的）。这类问题在数据文件里就能看出来，
比读 PDF 更早、更确定，所以先查它。

**② PDF 文字核对（读交付物）** —— `check_pdf_marks`
把 `draw_spec` 声明要画的那些标注，逐条到**交付 PDF 的文字层**里核对数值在不在。
读PDF 而不是问 s3「你打算印什么」，是因为要验的是**最终产物**——
用户真正拿到手的那张图。

## ⚠️ 关键坑1：必须按**坐标**排除标题栏（2026-10-15 实测踩到）

第一版实现把整页文字拼起来找数字，结果**抓不到硬编码**——因为
标题栏的「外接 56 × 40 × 39」里就含 `56`/`40`/`39`，恰好与 L/W/H_total 的实测值
相同。把 L 硬编码成 99 之后，PDF 里仍然搜得到 56，校验全绿。

修法：用 `extract_text(visitor_text=...)` 取每个文本块的**坐标**，
把**标题栏矩形**整块排除。矩形由 `lib/drawing_render.py` 的常量算出
（`TITLE_W` / `TITLE_H` / `A3W` / `A3H` / `M_FRAME`），**与渲染同一套坐标系**，
不靠猜阈值。实测（lbracket，A3 横向 1190.6×841.9 pt）：

```
标题栏矩形: x 686.0~1167.9   y 22.7~147.4     (pt)
标题栏实块: y 31.9~119.5     x 694.5~1012.0   → 全部落在矩形内 ✓
标注实块:   y 238.4~666.5    x 80.1~635.7     → 全部落在矩形外 ✓
```

## ⚠️ 关键坑2：只校验 `draw_spec` **声明要画**的那些，不校验全集

`s2_drawing` 生成的是标注**全集**（FreeCAD 里每个尺寸对象都有），
而 `draw_spec.DIMS` 只声明图上**画哪些** —— 机械图不必标每个内部尺寸
（ybracket 的 arm_t / opening / base_h / cbore_depth 就是故意不标的）。

第一版按全集校验，于是 ybracket 报了 5 条「对不上」，全是误报。
**语义应是「图上印的数对不对」，不是「模型有的数图上都要有」。**

## 跳过直径/半径的原因

`_drawing.json` 里 `dia` 类存**实测直径**（如 `8.1771`），而图上印的是
「φ8」的**名义值**（来自 params）。两者本就不同，强行比对会全线误报。

## 依赖

需要 `pypdf`（纯 Python）：`python -m pip install pypdf`

**pypdf 缺失时② 只跳过、不报错** —— 不能因为缺个增强依赖就让整条闭环挂掉。
① 是纯文本分析，不需要任何依赖，永远可用。
"""
import os
import re

#: 图上会印成「裸数字」的标注类型。dia/rad 不在其中（印的是 φ8 / R10 名义值）
LINEAR_KINDS = ("extentH", "extentV", "extentX", "distX", "distY")

_HERE = os.path.dirname(os.path.abspath(__file__))


# ================================================================ ① 硬编码扫描

def check_draw_spec(draw_spec_path, add):
    """扫 `draw_spec.DIMS`，找出**硬编码**的标注值。

    判据：一条 DIMS 带了字面量 `label=`，但**没有** `label_from="meas:..."`
    ⇒ 它的值不来自 FreeCAD 实测 ⇒ 改 params 后图上数字不会变 ⇒ 问题。

    返回 (从 meas 取值的 label 集合, 硬编码条数)。
    """
    import importlib.util
    if not draw_spec_path or not os.path.exists(draw_spec_path):
        return set(), 0
    try:
        spec = importlib.util.spec_from_file_location("_ds_probe", draw_spec_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        dims = getattr(mod, "DIMS", [])
    except Exception as e:
        add("issue", "draw_spec", None, None, None,
            "draw_spec.py 读不出来，无法检查标注是否硬编码：%s" % e)
        return set(), 0

    meas, hard = set(), 0
    for d in dims:
        lf = d.get("label_from")
        if isinstance(lf, str) and lf.startswith("meas:"):
            meas.add(lf.split(":", 1)[1])
            continue
        if d.get("label") is not None:
            hard += 1
            add("issue", "硬编码标注", d.get("label"), None, None,
                "这条标注的值是写死的字面量（%r），不是取自 FreeCAD 实测值 —— "
                "改 params.py 后图上数字**不会变**。请改成 label_from=\"meas:<label>\""
                % (d.get("label"),))
    return meas, hard


# ================================================================ ② PDF 文字核对

def _frame_consts():
    """从 `lib/drawing_render.py` 读 A3 尺寸 / 标题栏尺寸（**不 import 它**）。

    不 import 是因为 drawing_render 依赖 matplotlib，而本模块要在纯采集环节用；
    正则取常量还能保证「与渲染用同一份数字」，不会两边各写一套而漂移。
    """
    try:
        src = open(os.path.join(_HERE, "drawing_render.py"), encoding="utf-8").read()
    except Exception:
        src = ""

    def g(pat, dflt):
        m = re.search(pat, src)
        return float(m.group(1)) if m else dflt

    return {
        "A3W": g(r"A3W\s*,\s*A3H\s*=\s*([\d.]+)", 420.0),
        "A3H": g(r"A3W\s*,\s*A3H\s*=\s*[\d.]+\s*,\s*([\d.]+)", 297.0),
        "M_FRAME": g(r"M_FRAME\s*=\s*([\d.]+)", 8.0),
        "TITLE_W": g(r"TITLE_W\s*,\s*TITLE_H\s*=\s*([\d.]+)", 170.0),
        "TITLE_H": g(r"TITLE_W\s*,\s*TITLE_H\s*=\s*[\d.]+\s*,\s*([\d.]+)", 44.0),
    }


def title_block_rect():
    """标题栏矩形（单位 pt，PDF 坐标系原点左下），外扩余量 3mm。

    matplotlib 的 `set_ylim(0, A3H)` 让 **y 轴原点在左下**，与 PDF 一致，
    所以 mm → pt 直接乘 72/25.4，不需要翻转 y。
    """
    c = _frame_consts()
    k = 72.0 / 25.4
    x0 = (c["A3W"] - c["M_FRAME"] - c["TITLE_W"]) * k
    y0 = c["M_FRAME"] * k
    x1 = (c["A3W"] - c["M_FRAME"]) * k
    y1 = (c["M_FRAME"] + c["TITLE_H"]) * k
    m = 3.0 * k
    return (x0 - m, y0 - m, x1 + m, y1 + m)


def extract_pdf_items(pdf_path):
    """提取 PDF 文本块 `[(x, y, size, text)]`（pt）；失败返回 None。"""
    try:
        from pypdf import PdfReader
    except Exception:
        return None
    items = []

    def visitor(text, cm, tm, font_dict, font_size):
        t = (text or "").strip()
        if not t:
            return
        # 实际位置 = tm × cm（PDF 规范：先 tm 后 cm）。
        # matplotlib 把整页放进一个 cm 变换里，只看 tm 会拿到全 0 的 y。
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        items.append((x, y, float(font_size or 0), t))

    try:
        reader = PdfReader(pdf_path)
        for pg in reader.pages:
            pg.extract_text(visitor_text=visitor)
    except Exception:
        return None
    return items


def _fmt_candidates(v):
    """一个数值在图上可能的印法：`56` / `56.0` / `56.00`。

    matplotlib 的格式化（`%.0f` / `%.2f`）与 FreeCAD 的实测精度不完全一致，
    所以把常见印法都列出来逐个找。
    """
    f = float(v)
    out = set()
    if abs(f - round(f)) < 1e-9:
        out.add("%d" % round(f))
        out.add("%.1f" % f)
        out.add("%.2f" % f)
    else:
        out.add("%.1f" % f)
        out.add("%.2f" % f)
        out.add("%.3f" % f)
    return out


def _norm(s):
    """归一化：去千分位逗号、不换行空格 → 空格、压掉多余空白与换行。"""
    s = s.replace(",", "").replace("\u00a0", " ")
    return re.sub(r"[ \t\r\n]+", " ", s)


def check_pdf_marks(pdf_path, marks, marks_kind, add, only=None):
    """核对交付 PDF **图面区**上是否印出了 `only` 里那些标注的实测值。

    `only` 是要校验的 label 集合（来自 `draw_spec` 的声明）。传 None 表示
    校验 `marks` 里全部线性尺寸（给没有 draw_spec 的老实现用）。

    返回 (检查了几条, 报了几条问题, 状态)：
      状态 ∈ "ok" / "issues" / "skipped"（pypdf 缺失或 PDF 不可读）。
    """
    items = extract_pdf_items(pdf_path)
    if items is None:
        return 0, 0, "skipped"

    x0, y0, x1, y1 = title_block_rect()
    body = [t for (x, y, _s, t) in items
            if not (x0 <= x <= x1 and y0 <= y <= y1)]
    norm = _norm(" ".join(body))

    want = [lb for lb in marks
            if (marks_kind or {}).get(lb) in LINEAR_KINDS
            and (only is None or lb in only)]
    if not want:
        return 0, 0, "ok"

    bad = 0
    for label in sorted(want):
        val = marks[label]
        if any(c in norm for c in _fmt_candidates(val)):
            continue
        bad += 1
        add("issue", "PDF字:%s" % label, val, None, None,
            "draw_spec 声明要标 %s（模型实测 %.4g），但交付 PDF 图面区找不到这个数字"
            " —— 图上印的字与模型不符" % (label, float(val)))
    return len(want), bad, ("issues" if bad else "ok")