# -*- coding: utf-8 -*-
r"""pdf_anno.py —— 从矢量 PDF 图纸里捞出「图纸说了什么」（L2 锚点）

定位：这是「锚点驱动」方案（方案④）的第 2 刀。**纯读图，不看三维**。
输出与 census 的 L0 面表对账，用于度量「图纸标注 vs 真值几何」差多少。

★ 纪律：本文件的规则**一次写定、之后冻结**。对账结果只许度量错多少，
  不许回头改这里去迎合真值 —— 那是把答案抄进学习（用户 10-16 明确的方法论边界）。
  若必须改，改后 test 池作废，只能在 train 池上重报。

用法
----
    python pdf_anno.py --json <输出目录> <文件.pdf> [...]
    python pdf_anno.py <文件.pdf>            # 打印摘要

产出（每件）
    {"part":..., "title":{零件名,图号,材料,比例}, "diameter":[…], "radius":[…],
     "thread":[…], "angle":[…], "through_holes":…, "sample":[…], "linear_bare":[…],
     "roughness":[…], "gdt":[…], "excluded":…}
"""
import json
import os
import re
import sys
import warnings

# ---------------------------------------------------------------- 剔除清单
# 标题栏 / 技术要求 / 图上印刷模板 —— 不是尺寸，混进来会污染统计
BOILER = [
    "标记处数", "更改文件名", "签", "字", "日", "期", "图", "样", "标", "记", "重", "量", "比", "例",
    "第张共", "设计", "审核", "工艺", "标准化", "批准", "智新", "其余", "技术要求",
    "锐角倒钝", "去除毛刺飞边", "未注公差原则", "GB/T4249", "的要求",
    "通孔（镶嵌ST2.5×0.45×1D钢丝螺套）",
]
# 表面粗糙度Ra 的常见序列
# ★ 表面粗糙度 Ra 序列。**必须剔除 25 / 50 / 100**：
#   它们与常用尺寸值撞车 —— 实测顶部垫片图上真有 "50" 这个尺寸，
#   被当粗糙度吃掉后标定直接崩（最大标注变成 7075 或 34，比例算成 0.027）。
#   只保留辨识度高的小值段。
RA = {"0.012", "0.025", "0.05", "0.1", "0.2", "0.4", "0.8", "1.6", "3.2", "6.3", "12.5"}

RE_DIA = re.compile(r"[Ø⌀Φφ]\s*(\d+(?:\.\d+)?)")
RE_RAD = re.compile(r"(?<![A-Za-z])R\s*(\d+(?:\.\d+)?)(?!\d)")
RE_THREAD = re.compile(r"(?<![A-Za-z0-9])M\s*(\d+(?:\.\d+)?)")
RE_ANG = re.compile(r"(\d+(?:\.\d+)?)\s*°")
RE_CNT = re.compile(r"(\d+)\s*[×xX]\s*")
RE_TOL = re.compile(r"[±]\s*(\d+(?:\.\d+)?)")
RE_TOL2 = re.compile(r"([+＋]\s*\d+(?:\.\d+)?)")
RE_TOL3 = re.compile(r"([-－]\s*\d+(?:\.\d+)?)")
RE_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
RE_SCALE = re.compile(r"^(\d+)\s*:\s*(\d+)$")
RE_GDT = re.compile(r"^[a-zA-Z]\s*\d+(?:\.\d+)?\s*[A-Z]$")      # 如 r 0.025A / f 0.042B
RE_FRAME = re.compile(r"^（?\d+×[Ø⌀Φφ]\d+(?:\.\d+)?[^）]*）?$")


def is_boiler(tok):
    t = tok.strip()
    if not t:
        return True
    if any(b == t or (len(b) > 1 and b in t) for b in BOILER):
        return True
    # ★ 编号条款（技术要求里的 "3.未注倒角均为0.5×45°。" 之类）
    #   实测：技术要求段是**倒序**落进文本流的（条款在前、"技术要求"标题在后），
    #   所以不能按标题截断，只能逐条剔除。
    #   注意 `\D` 保证不会误伤 `48.5±0.1` / `3.2` / `1.6` 这类真尺寸。
    if re.match(r"^\d+\.\D", t):
        return True
    if "未注" in t or "其余" in t or "全部" in t:
        return True
    return False


def extract(text):
    """★ 抽取规则一次写定、之后冻结（见文件头纪律）。

    注：2026-10-16 试过用**版面分区**（标题栏/技术要求按坐标剔除）替代词表法，
    **实测是回归，已回退**：外罩 Ø 从 7 个掉到 4 个、比例 `2:1` 全丢
    （它本来就在标题栏区域里，而比例是当元数据用的）。
    根因：分区边界（尤其标题栏的 y 分界）还不够可信，直接拿去过滤会误杀标注。
    ⇒ 分区目前只作**诊断信息**用（view_map.py），不参与标注过滤。
    """
    raw = [t.strip() for t in text.split() if t.strip()]
    toks = [t for t in raw if not is_boiler(t)]
    out = {"diameter": [], "radius": [], "thread": [], "angle": [],
           "through_holes": [], "sample": [], "linear_bare": [],
           "roughness": [], "gdt": [], "tolerance": [], "scale": None,
           "title": {}, "excluded": len(raw) - len(toks)}

    # 比例 2:1
    for t in toks:
        m = RE_SCALE.match(t)
        if m:
            out["scale"] = t
            break

    # 标题栏：零件名 / 图号 / 材料
    m = re.search(r"\bsj-\d{3}\b", text, re.I)
    if m:
        out["title"]["图号"] = m.group(0)
    # ★ 材料：候选表要覆盖本项目实际用到的牌号。
    #   2026-10-16 补 TC4（钛合金；底部垫片/合金管垫片/定心垫片三件都用它）——
    #   原先表里只有钢/铝牌号，导致这三件材料识别为 "?"。
    MATS = ("TC4", "TA2", "Ti6Al4V", "7075", "6061", "2024", "Q235", "Q345", "45",
            "40Cr", "20CrMnTi", "GCr15", "304", "316", "304L", "316L",
            "1Cr18Ni9Ti", "HT200", "ZL104")
    for mat in MATS:
        if re.search(r"(?<![0-9A-Za-z])%s(?![0-9A-Za-z])" % re.escape(mat), text):
            out["title"]["材料"] = mat
            break

    for t in toks:
        # ---- 直径（可带 n× 前缀）----
        for m in RE_DIA.finditer(t):
            n = 1
            c = RE_CNT.search(t[:m.start()])
            if c:
                n = int(c.group(1))
            out["diameter"].append({
                "d": float(m.group(1)), "n": n, "tok": t,
                "through": "通孔" in t, "uniform": "均布" in t})

        # ---- 半径 ----
        for m in RE_RAD.finditer(t):
            out["radius"].append({"r": float(m.group(1)), "tok": t})

        # ---- 螺纹 ----
        for m in RE_THREAD.finditer(t):
            n = 1
            c = RE_CNT.search(t[:m.start()])
            if c:
                n = int(c.group(1))
            out["thread"].append({"M": float(m.group(1)), "n": n, "tok": t})

        # ---- 角度 ----
        for m in RE_ANG.finditer(t):
            out["angle"].append({"deg": float(m.group(1)), "tok": t})

        # ---- 形位公差框 ----
        if RE_GDT.match(t):
            out["gdt"].append(t)

        # ---- 公差 ----
        for rx in (RE_TOL, RE_TOL2, RE_TOL3):
            for m in rx.finditer(t):
                out["tolerance"].append(m.group(0).replace(" ", ""))

        # ---- 光洁度 ----
        #   ★ 粗糙度值（0.1/1.6/3.2…）**不能同时进 linear_bare**。
        #   踩过的坑：它们混进裸数字后会污染标定 —— 曾让 solve_scale 选出
        #   117.9 pt/mm 的荒谬比例（188.6pt 除下来正好 =1.6，撞上粗糙度值），
        #   结果厚度算成 0.1mm、体积 0.256。
        if t in RA:
            out["roughness"].append(float(t))
            continue
        elif re.match(r"^c\s*\d", t):
            out["roughness"].append(t)

        # ---- 裸数字（歧义最大，单列）----
        #   ★ 材料牌号（7075 / 304 / TC4 …）形状上也是数字/字母，会混进来。
        #     实测 7075 进了裸数字 ⇒ 成为"最大标注" ⇒ 标定算成 0.027 pt/mm。
        if RE_NUM.match(t) and t != out["title"].get("材料"):
            out["linear_bare"].append(t)
        elif re.match(r"^\d+(?:\.\d+)?[±]", t) or RE_TOL.search(t):
            out["sample"].append(t)

    # 通孔汇总
    for d in out["diameter"]:
        if d["through"]:
            out["through_holes"].append({"d": d["d"], "n": d["n"], "uniform": d["uniform"]})
    for th in out["thread"]:
        if "通孔" in th["tok"]:
            out["through_holes"].append({"thread": th["M"], "n": th["n"]})
    return out


def anno_of(pdf_path):
    warnings.filterwarnings("ignore")
    from pypdf import PdfReader
    text = PdfReader(pdf_path).pages[0].extract_text() or ""
    d = extract(text)
    d["part"] = os.path.splitext(os.path.basename(pdf_path))[0]
    d["source"] = os.path.abspath(pdf_path)
    return d


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    as_json = argv[0] == "--json"
    outdir = argv[1] if as_json else None
    files = argv[2:] if as_json else argv
    if as_json:
        os.makedirs(outdir, exist_ok=True)

    print("%-26s %6s %6s %6s %6s  %s" % ("part", "Ø数", "R数", "角度", "通孔", "图号/材料/比例"))
    print("-" * 84)
    for p in files:
        try:
            d = anno_of(p)
        except Exception as e:
            print("%-26s  FAIL %s" % (os.path.basename(p)[:26], str(e)[:30]))
            continue
        t = d["title"]
        print("%-26s %6d %6d %6d %6d  %s/%s/%s"
              % (d["part"][:26], len(d["diameter"]), len(d["radius"]),
                 len(d["angle"]), len(d["through_holes"]),
                 t.get("图号", "?"), t.get("材料", "?"), d["scale"] or "?"))
        if as_json:
            with open(os.path.join(outdir, d["part"] + ".anno.json"), "w",
                      encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
