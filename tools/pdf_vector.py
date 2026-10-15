# -*- coding: utf-8 -*-
r"""pdf_vector —— **矢量 PDF 读图**（与 tools/dwg_parser 的栅格读图并行）

为什么要有它
------------
`tools/dwg_parser` 走的是栅格路线（PNG → 霍夫圆/线 → 连通域 + tesseract OCR）。
栅格路线的三个硬伤（`验证报告/真实图纸解析验证.md` 实测）：
  1. **标定错 1.89 倍**（`line_vote` 投票法）
  2. **标注只读出 4/16 条**（字形分类 + OCR 失败）
  3. **没有线型概念**（分不出实线/虚线）
若原图是 **CAD 打印出来的矢量 PDF**，这三条**全部消失**：
  * 坐标就是物理尺寸（pt → mm），标定只需一个比例系数
  * 文字是 PDF 文本对象，带 `/ToUnicode` CMap → **直接解码，不需要 OCR**
  * AutoCAD 的图层会作为 PDF **OCG（可选内容组）** 保留 → 图层名即语义
     （粗实线层/细实线层/中心线层/尺寸线层/剖面线层）

本模块 = 「纯标准库」的最小 PDF 解释器 + 读图语义提取。不依赖任何 PDF 库。

产出契约
--------
与 `steps/s0b_dwgread.py::_pick()` **同形**（下游 s0_plan / s5b_dimchain 零改动）：
    {mm_per_px, scale_method, summary{circles,annotations,matched,match_rate},
     circles[{cx,cy,r_px,r_mm,d_mm}], dims[...]}
坐标单位统一为 **PDF 设备点（pt）**，"px" 即 pt，`mm_per_px` = 每 pt 对应多少 mm。
另有附加字段（下游可忽略）：`geometry{lines,arcs,circles_raw}`、`layers`、`texts`。

标定（mm_per_px 从哪来）
------------------------
三档，按可靠性降序：
  1. `known_scale={"mm":..,"pt":..}` 人给定 → `scale_method="given"`
  2. **标注反推**：尺寸线层里轴平行线段的长度 ≡ 被测量长度；用图上解出的
     标注值集合去拟合比例 k（实测外罩图 k=1.370，6 条标注命中，误差<0.6%）
     → `scale_method="label_backsolve"`
  3. 兜底：`/Measure` 视口的 X 换算系数（本机样例 `/U` 为空，不可靠）
     → `scale_method="pdf_measure"`；再不行 `scale_method="none"`
⚠️ **不要相信标题栏写的比例**：实测该图标题栏写 `2:1`，真实是 A4 1:1 被
   "布满图纸"缩放到 Letter（0.727×），必须靠标注反推。

隔离约定
--------
* 纯标准库（re / zlib / math / collections），**不 import build123d / FreeCAD / cv2**
* 不 import 项目其它模块（可独立单测）
* 只读文件，不写文件（写文件由调用方 s0b_dwgread 负责）

已知表达力缺口
--------------
* PDF 里 DIMENSION 被**展平**成线 + 文字（不像 DXF 有 defpoint2/3），
  所以"标注重接"只能靠**几何贴近 + 长度匹配**，比 DXF 弱一档
* 圆弧/圆若是贝塞尔（`c`）绘制，本版只按**离散点**收集，不还原圆心半径；
  闭合折线（AutoCAD 常把圆打成多段折线）可以还原
* 线型（dash）若已在打印时展平为实线段，则只能靠**图层名**辨语义
"""
import collections
import math
import re
import zlib

# ---------------------------------------------------------------- PDF 底层

_TOK = re.compile(
    rb"\[[^\]]*\]|<[0-9A-Fa-f]*>|\((?:\\.|[^()\\])*\)|/[^\s/\[\]<>()]+|-?\d*\.?\d+|[A-Za-z'\"*]+")


def _obj_bodies(data):
    """对象号 → 对象体（到 endobj 为止）。"""
    out = {}
    for m in re.finditer(rb"(?:^|\n)(\d+)\s+0\s+obj\b(.*?)endobj", data, re.S):
        out[int(m.group(1))] = m.group(2)
    return out


def _streams(data):
    """对象号 → 解压后的流内容（Flate）。向前找最近的 `N 0 obj` 定对象号。"""
    out = {}
    for m in re.finditer(rb"stream\r?\n", data):
        s = m.end()
        e = data.find(b"endstream", s)
        if e < 0:
            continue
        head = data[max(0, m.start() - 500):m.start()]
        nums = re.findall(rb"(\d+)\s+0\s+obj", head)
        if not nums:
            continue
        try:
            out[int(nums[-1])] = zlib.decompress(data[s:e].rstrip(b"\r\n"))
        except Exception:
            pass
    return out


def _hex2text(v):
    """PDF 十六进制串 → python str（自动判 UTF-16BE / UTF-8）。"""
    if v[:1] == b"<":
        v = v[1:-1]
    try:
        b = bytes.fromhex(v.decode("ascii"))
    except Exception:
        return ""
    if b[:2] == b"\xfe\xff":
        return b.decode("utf-16-be", "replace")
    return b.decode("utf-8", "replace")


def _cmap_of(blob):
    """解析 ToUnicode CMap → (码→字符, 码长字节数)。

    **关键**：CMap 里的十六进制串长度决定码长 —— AutoCAD 常写 `<0013>`，
    那是 **2 字节码**（4 个 hex 字符）。误按 1 字节读会全解成 `?`。
    """
    mp = {}
    clen = [None]

    def note(h):
        if clen[0] is None:
            clen[0] = len(h) // 2

    for blk in re.findall(rb"beginbfrange(.*?)endbfrange", blob, re.S):
        for lo, hi, rest in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[.*?\]|<[0-9A-Fa-f]+>)", blk, re.S):
            note(lo)
            l, h = int(lo, 16), int(hi, 16)
            us = re.findall(rb"<([0-9A-Fa-f]+)>", rest)
            if len(us) == 1:
                base = int(us[0], 16)
                for i in range(min(h - l + 1, 8192)):
                    mp[l + i] = chr(base + i)
            else:
                for i, u in enumerate(us):
                    if l + i <= h:
                        mp[l + i] = chr(int(u, 16))
    for blk in re.findall(rb"beginbfchar(.*?)endbfchar", blob, re.S):
        for a, b in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            note(a)
            mp[int(a, 16)] = chr(int(b, 16))
    return mp, (clen[0] or 1)


# ---------------------------------------------------------------- 内容流解释

class _GState:
    __slots__ = ("ctm", "w", "rgb", "font", "tsize", "tmode", "layer")

    def __init__(self):
        self.ctm = (1, 0, 0, 1, 0, 0)
        self.w = 1.0
        self.rgb = (0, 0, 0)
        self.font = None
        self.tsize = 1.0
        self.tmode = 0
        self.layer = None

    def copy(self):
        g = _GState()
        for s in self.__slots__:
            setattr(g, s, getattr(self, s))
        return g


def _mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _ap(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


_PAINT = ("S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n")
_FILL = ("f", "F", "f*", "B", "B*", "b", "b*")
_STROKE = ("S", "s", "B", "B*", "b", "b*")


def _interpret(streams_in_order, props, ocg_names):
    """按顺序解释若干内容流（**图形状态跨流共享** —— PDF 把 /Contents 数组
    的多段拼成一条逻辑流，`cm` 常只写在第一段）。

    返回 dict: segs / loops / texts / layer_count
    """
    gs = _GState()
    stack = []
    segs = []        # (p0, p1, layer)  设备 pt
    loops = []       # ([pts...], layer) 闭合子路径
    texts = []       # (pos, text, layer, font, tmode)
    layer_count = collections.Counter()

    for dec in streams_in_order:
        nums, names, strs = [], [], []
        path, subs = [], []
        tm = tlm = (1, 0, 0, 1, 0, 0)
        for m in _TOK.finditer(dec):
            t = m.group(0).decode("latin1")
            if re.fullmatch(r"-?\d*\.?\d+", t):
                nums.append(float(t))
                continue
            if t.startswith("/"):
                names.append(t[1:])
                if len(names) > 4:
                    names.pop(0)
                continue
            if t[:1] in "<[(":
                strs.append(m.group(0))
                if len(strs) > 8:
                    strs.pop(0)
                continue
            if t == "BDC":
                for nm in reversed(names):
                    if nm in props:
                        gs.layer = ocg_names.get(props[nm])
                        break
            elif t in ("E", "EMC"):
                gs.layer = None
            elif t == "cm" and len(nums) >= 6:
                gs.ctm = _mul(tuple(nums[-6:]), gs.ctm)
            elif t == "w" and nums:
                gs.w = nums[-1]
            elif t in ("RG", "rg") and len(nums) >= 3:
                gs.rgb = tuple(int(max(0.0, min(1.0, v)) * 255) for v in nums[-3:])
            elif t == "Tr" and nums:
                gs.tmode = int(nums[-1])
            elif t == "Tf":
                gs.font = names[-1] if names else None
                if nums:
                    gs.tsize = nums[-1]
            elif t == "Tm" and len(nums) >= 6:
                tm = tlm = tuple(nums[-6:])
            elif t in ("Td", "TD") and len(nums) >= 2:
                tm = tlm = _mul((1, 0, 0, 1, nums[-2], nums[-1]), tlm)
            elif t == "T*":
                tm = tlm = _mul((1, 0, 0, 1, 0, -gs.tsize * 1.2), tlm)
            elif t == "m" and len(nums) >= 2:
                if path:
                    subs.append(path)
                path = [(nums[-2], nums[-1])]
            elif t in ("l", "v", "y") and len(nums) >= 2:
                if path:
                    path.append((nums[-2], nums[-1]))
            elif t == "c" and len(nums) >= 6:
                # 三次贝塞尔 → 采样展开（圆/圆弧常以此绘制；只取终点会让点太稀，
                # 圆就识别不出来了）
                if path:
                    p0 = path[-1]
                    c1 = (nums[-6], nums[-5])
                    c2 = (nums[-4], nums[-3])
                    p3 = (nums[-2], nums[-1])
                    for i in range(1, 9):
                        u = i / 8.0
                        v = 1.0 - u
                        path.append((
                            v * v * v * p0[0] + 3 * v * v * u * c1[0]
                            + 3 * v * u * u * c2[0] + u * u * u * p3[0],
                            v * v * v * p0[1] + 3 * v * v * u * c1[1]
                            + 3 * v * u * u * c2[1] + u * u * u * p3[1]))
            elif t == "h":
                if path:
                    path.append(path[0])
            elif t == "re" and len(nums) >= 4:
                x, y, w_, h_ = nums[-4:]
                subs.append([(x, y), (x + w_, y), (x + w_, y + h_),
                             (x, y + h_), (x, y)])
            elif t in _PAINT:
                if path:
                    subs.append(path)
                path = []
                M = gs.ctm
                for pl in subs:
                    dev = [_ap(M, p[0], p[1]) for p in pl]
                    if len(dev) >= 2 and t in _STROKE:
                        for i in range(len(dev) - 1):
                            segs.append((dev[i], dev[i + 1], gs.layer))
                    if len(dev) >= 4 and math.dist(dev[0], dev[-1]) < 1e-6:
                        loops.append((dev, gs.layer))
                subs = []
                layer_count[gs.layer] += 1
            elif t in ("Tj", "TJ", "'", '"'):
                M = _mul(tm, gs.ctm)
                s = _decode_str(strs[-1], fonts_cache.get(gs.font)) if strs else ""
                if s.strip():
                    texts.append((_ap(M, 0, 0), s, gs.layer, gs.font, gs.tmode))
                strs = []
            elif t == "q":
                stack.append(gs.copy())
            elif t == "Q":
                if stack:
                    gs = stack.pop()
            if t != "cm":
                nums = []
    return dict(segs=segs, loops=loops, texts=texts, layer_count=layer_count)


fonts_cache = {}


def _decode_str(tok, font):
    if not font:
        return ""
    cm, clen = font
    step = clen * 2
    s = ""
    for hx in re.findall(rb"<([0-9A-Fa-f]+)>", tok):
        h = hx.decode()
        for i in range(0, len(h) - step + 1, step):
            s += cm.get(int(h[i:i + step], 16), "?")
    for lit in re.findall(rb"\((?:\\.|[^()\\])*\)", tok):
        s += lit[1:-1].decode("latin1", "replace")
    return s


# ---------------------------------------------------------------- 语义层

_LAYER_KIND = [
    ("粗实线", "visible"), ("细实线", "thin"), ("中心线", "center"),
    ("点划线", "center"), ("虚线", "hidden"), ("剖面线", "hatch"),
    ("尺寸线", "dim"), ("标注", "dim"), ("文本", "text"), ("文字", "text"),
    ("图框", "frame"), ("标号", "label"),
]


def _layer_semantic(name):
    if not name:
        return "unknown"
    for k, v in _LAYER_KIND:
        if k in name:
            return v
    return "other"


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _label_values(texts):
    """从尺寸线层的文字里抽候选标注值。"""
    vals = {}
    for pos, s, layer, fname, tmode in texts:
        if _layer_semantic(layer) not in ("dim", "text", "other", "unknown"):
            continue
        for mk in re.findall(r"[ØΦ⌀]?\s*(\d+(?:\.\d+)?)", s):
            try:
                v = float(mk)
            except ValueError:
                continue
            if 1.0 <= v <= 400.0:
                vals.setdefault(round(v, 3), s.strip())
    return vals


def _dim_segments(segs):
    """尺寸线层里的**轴平行**线段 = 线性尺寸线（长度 ≡ 被测量长度）。"""
    out = []
    for p0, p1, layer in segs:
        if _layer_semantic(layer) != "dim":
            continue
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        L = math.hypot(dx, dy)
        if L < 2.0:
            continue
        if abs(dy) < 0.2:
            out.append((p0, p1, L, "distX"))
        elif abs(dx) < 0.2:
            out.append((p0, p1, L, "distY"))
    return out


def _fit_scale(dim_segs, texts):
    """拟合比例 k（实物mm = k × 纸面mm）。

    **判据用"邻近 + 长度匹配"两个约束**（只有长度匹配会被小 k 骗到：
    k 越小，越长的线都被压进小数值区间，误命中反而更多）。

    对每个候选 k：统计有多少条标注文字，能在**它附近**（< 60pt）找到一条
    长度换算后与它数值相符的尺寸线。取命中最多者。
    """
    items = []
    for pos, s, layer, fname, tmode in texts:
        if _layer_semantic(layer) not in ("dim", "text", "other", "unknown"):
            continue
        nums = [float(x) for x in _NUM.findall(s) if 1.0 <= float(x) <= 400.0]
        if nums:
            items.append((pos, nums[0]))
    if not items or not dim_segs:
        return None, 0, []
    best = (0, None)
    for k1000 in range(300, 3001, 5):
        k = k1000 / 1000.0
        hit = 0
        for pos, v in items:
            for p0, p1, L, kind in dim_segs:
                mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
                if math.dist(mid, pos) > 60.0:
                    continue
                real = L * 25.4 / 72.0 * k
                if abs(real - v) <= max(0.15, v * 0.02):
                    hit += 1
                    break
        if hit > best[0]:
            best = (hit, k)
    if not best[1]:
        return None, 0, []
    k = best[1]
    detail = []
    for pos, v in items:
        got = None
        for p0, p1, L, kind in dim_segs:
            mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
            if math.dist(mid, pos) > 60.0:
                continue
            real = L * 25.4 / 72.0 * k
            if abs(real - v) <= max(0.15, v * 0.02):
                got = round(real, 2)
                break
        detail.append((v, got))
    return k, best[0], detail


def _circles_from_loops(loops):
    """闭合折线 → 圆。判据：包围盒近方 + 各点到质心半径一致。"""
    out = []
    for pts, layer in loops:
        if len(pts) < 6:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if w < 0.5 or h < 0.5:
            continue
        if abs(w - h) > 0.06 * max(w, h):
            continue
        cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
        rr = [math.dist((cx, cy), p) for p in pts]
        r = sum(rr) / len(rr)
        if r < 0.25 or (max(rr) - min(rr)) > 0.10 * r:
            continue
        out.append(dict(cx=cx, cy=cy, r_pt=r, layer=layer))
    # 去重（同心同半径）
    uniq = []
    for c in sorted(out, key=lambda c: -c["r_pt"]):
        if not any(abs(c["cx"] - u["cx"]) < 1.0 and abs(c["cy"] - u["cy"]) < 1.0
                   and abs(c["r_pt"] - u["r_pt"]) < 1.0 for u in uniq):
            uniq.append(c)
    return uniq


def parse(pdf_path, known_scale=None, verbose=False):
    """读一张矢量工程图 PDF → 与 s0b_dwgread 同形的语义 dict。"""
    data = open(pdf_path, "rb").read()
    bodies = _obj_bodies(data)
    S = _streams(data)

    # ---- 图层（OCG）----
    ocg_names = {}
    for num, body in bodies.items():
        m = re.search(rb"/Name\s*(<[0-9A-Fa-f]+>|\([^)]*\))", body)
        if m and b"/Type" in body and b"/OCG" in body:
            ocg_names[num] = _hex2text(m.group(1))
    props = {}
    page = None
    for body in bodies.values():
        pm = re.search(rb"/Properties\s*<<(.*?)>>", body, re.S)
        if pm:
            for nm, num in re.findall(rb"/(\w+)\s+(\d+)\s+0\s+R", pm.group(1)):
                props[nm.decode()] = int(num)
        if b"/MediaBox" in body and page is None:
            page = body

    # ---- 字体 → CMap ----
    fonts_cache.clear()
    for nm, num in re.findall(rb"/(F\d+)\s+(\d+)\s+0\s+R", page or b""):
        body = bodies.get(int(num))
        if not body:
            continue
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", body)
        if not tu:
            continue
        blob = S.get(int(tu.group(1)))
        if blob is None:
            tb = bodies.get(int(tu.group(1)), b"")
            i, j = tb.find(b"stream"), tb.find(b"endstream")
            raw = tb[i + 6:j].lstrip(b"\r\n")
            try:
                blob = zlib.decompress(raw)
            except Exception:
                blob = raw
        fonts_cache[nm.decode()] = _cmap_of(blob)

    # ---- 内容流（按 /Contents 顺序）----
    contents = []
    if page:
        cm = re.search(rb"/Contents\s*\[(.*?)\]", page, re.S)
        if cm:
            contents = [int(x) for x in re.findall(rb"(\d+)\s+0\s+R", cm.group(1))]
        else:
            cm = re.search(rb"/Contents\s+(\d+)\s+0\s+R", page)
            if cm:
                contents = [int(cm.group(1))]
    streams_in_order = [S[n] for n in contents if n in S]

    R = _interpret(streams_in_order, props, ocg_names)
    segs, loops, texts = R["segs"], R["loops"], R["texts"]

    # ---- 标定 ----
    label_vals = _label_values(texts)
    dim_segs = _dim_segments(segs)
    k = None
    method = "none"
    detail = []
    if known_scale and known_scale.get("pt"):
        k = float(known_scale["mm"]) / float(known_scale["pt"]) / (25.4 / 72.0)
        method = "given"
    else:
        k, hits, detail = _fit_scale(dim_segs, texts)
        if k:
            method = "label_backsolve"
    mm_per_pt = (k * 25.4 / 72.0) if k else 0.0

    # ---- 圆 ----
    circ = _circles_from_loops(loops)
    circles = [dict(cx=c["cx"], cy=c["cy"], r_px=c["r_pt"],
                    r_mm=round(c["r_pt"] * mm_per_pt, 3),
                    d_mm=round(2 * c["r_pt"] * mm_per_pt, 3),
                    layer=c["layer"]) for c in circ]

    # ---- 标注：文字 + 几何贴近接地 ----
    dims = []
    n_ground = 0
    for pos, s, layer, fname, tmode in texts:
        sv = _layer_semantic(layer)
        if sv not in ("dim", "text", "other", "unknown"):
            continue
        nums = [float(x) for x in _NUM.findall(s) if 1.0 <= float(x) <= 400.0]
        if not nums:
            continue
        rec = dict(text=s.strip(), type=("dia" if re.search(r"[ØΦ⌀]", s) else "linear"),
                   values=nums, box_px=[], center_px=[round(pos[0], 2), round(pos[1], 2)],
                   grounded=False, kind=None, cx=None, cy=None, r_px=None,
                   d_mm=None, measured_mm=None, method=None, confidence=None,
                   note=None, p1=None, p2=None, len_mm=None, ends=None,
                   layer=layer)
        v = nums[0]
        if mm_per_pt:
            if re.search(r"[ØΦ⌀]", s):
                near = [c for c in circles
                        if abs(c["d_mm"] - v) <= max(0.15, v * 0.02)
                        and math.dist((c["cx"], c["cy"]), pos) < 160.0]
                if near:
                    c = min(near, key=lambda c: math.dist((c["cx"], c["cy"]), pos))
                    rec.update(grounded=True, kind="dia", cx=round(c["cx"], 2),
                               cy=round(c["cy"], 2), r_px=round(c["r_px"], 3),
                               d_mm=c["d_mm"], measured_mm=c["d_mm"],
                               method="circle_match", confidence=0.9)
            else:
                best = None
                for p0, p1, L, kind in dim_segs:
                    mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                    real = L * 25.4 / 72.0 * (k or 0.0)
                    if abs(real - v) <= max(0.15, v * 0.02):
                        d = math.dist(mid, pos)
                        if best is None or d < best[0]:
                            best = (d, p0, p1, L, kind, real)
                if best and best[0] < 160.0:
                    _, p0, p1, L, kind, real = best
                    rec.update(grounded=True, kind=kind, measured_mm=round(real, 3),
                               p1=[round(p0[0], 2), round(p0[1], 2)],
                               p2=[round(p1[0], 2), round(p1[1], 2)],
                               len_mm=round(L * 25.4 / 72.0, 3),
                               method="dimline_len", confidence=0.85)
        n_ground += 1 if rec["grounded"] else 0
        dims.append(rec)

    layers = collections.Counter()
    for _, _, layer in segs:
        layers[layer or "(未标层)"] += 1

    sem = {
        "mm_per_px": round(mm_per_pt, 6),
        "scale_method": method,
        "summary": {
            "circles": len(circles),
            "annotations": len(dims),
            "matched": n_ground,
            "match_rate": round(n_ground / len(dims), 4) if dims else 0.0,
            "source": "vector_pdf",
            "n_lines": len(segs),
            "n_texts": len(texts),
            "n_labels": len(label_vals),
            "calib_k": round(k, 4) if k else None,
            "calib_hits": len([d for d in detail if d[1] is not None]),
        },
        "circles": circles,
        "dims": dims,
        "layers": dict(layers),
        "geometry": {
            "lines": [{"x1": round(p0[0], 3), "y1": round(p0[1], 3),
                       "x2": round(p1[0], 3), "y2": round(p1[1], 3),
                       "semantic": _layer_semantic(layer), "layer": layer}
                      for p0, p1, layer in segs],
        },
    }
    if verbose:
        print("[pdf_vector] 流 %d 段｜线段 %d｜闭合环 %d｜文字 %d"
              % (len(streams_in_order), len(segs), len(loops), len(texts)))
        print("[pdf_vector] 图层: %s" % dict(layers))
        print("[pdf_vector] 标定: %s  mm/pt=%.5f  k=%s  命中=%s/%s"
              % (method, mm_per_pt, k and round(k, 4),
                 len([d for d in detail if d[1] is not None]), len(detail)))
        for v, got in detail:
            if got is not None:
                print("            标注 %-8s ← 尺寸线实测 %.2f mm" % (v, got))
    return sem
