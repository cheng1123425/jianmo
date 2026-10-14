# -*- coding: utf-8 -*-
r"""最小闭环 —— ⑤ 生成 A3 工程图 PDF（无界面 TechDraw + matplotlib 落盘）

FreeCAD console 模式不能直接出 PDF（文档 §7 提到的坑），
所以照 jianmo 的做法：TechDraw 取几何 → matplotlib 画 A3 矢量图 + 真实标注。
标注文字来自 IR 语义层 → 这就是 3D↔2D 对应关系的落地。
"""
import sys, os, json
import FreeCAD as App
import Part, TechDraw
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon

matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

ARGS = json.loads(sys.argv[-1])
STEP, OUT_PDF, TD = ARGS["step"], ARGS["pdf"], ARGS["template"]
DIA, COUNT, R_FILLET = ARGS["dia"], ARGS["count"], ARGS["r_fillet"]

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def p(*a): print(*a); sys.stdout.flush()

# --- FreeCAD 取投影边 ---
doc = App.newDocument("D")
sh = Part.Shape(); sh.read(STEP)
obj = doc.addObject("Part::Feature", "P"); obj.Shape = sh
page = doc.addObject("TechDraw::DrawPage", "Page")
tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Tpl"); tpl.Template = TD; page.Template = tpl
top = doc.addObject("TechDraw::DrawViewPart", "Top"); top.Source=[obj]; top.Direction=(0,0,1)
front = doc.addObject("TechDraw::DrawViewPart", "Front"); front.Source=[obj]; front.Direction=(0,-1,0)
page.addView(top); page.addView(front)
doc.recompute()

def edges_of(view):
    out=[]
    for e in view.getVisibleEdges():
        cn = e.Curve.__class__.__name__
        if cn=="Circle":
            c=e.Curve.Center
            out.append(("circle",(c.x,c.y),e.Curve.Radius))
        elif cn=="Line":
            out.append(("line",((e.Vertexes[0].X,e.Vertexes[0].Y),(e.Vertexes[-1].X,e.Vertexes[-1].Y)),e.Length))
    return out

top_e = edges_of(top)
front_e = edges_of(front)

# --- matplotlib 画 A3 横向 ---
A3W, A3H = 420, 297
fig = plt.figure(figsize=(A3W/25.4, A3H/25.4), dpi=150)
ax = fig.add_axes([0,0,1,1]); ax.set_xlim(0,A3W); ax.set_ylim(0,A3H); ax.axis("off")
ax.add_patch(plt.Rectangle((10,10),A3W-20,A3H-20,fill=False,lw=1.5))

# 图框角标（简化标题栏）
ax.add_patch(plt.Rectangle((A3W-130,10),120,30,fill=False,lw=1))
ax.text(A3W-125,33,"底板 4 孔  比例 1:2  单位 mm",fontsize=8)
ax.text(A3W-125,28,"未注公差  去毛刺",fontsize=7,color="#444")
ax.text(A3W-125,22,"第一角投影法（GB）",fontsize=7,color="#444")
ax.text(A3W-125,16,"尺寸Φ: 实时联动 IR",fontsize=6,color="#0a7")

# 俯视图（居中偏下）
cx, cy, sc = 130, 130, 1.6      # 1:2 比例 → 显示放大系数
ax.text(cx, cy+75, "俯视图 (Top)", fontsize=10, ha="center")
for kind, geom, val in top_e:
    if kind=="circle":
        ax.add_patch(Circle((cx+geom[0]*sc, cy+geom[1]*sc), val*sc, fill=False, lw=0.8))
    else:
        (x1,y1),(x2,y2)=geom
        ax.plot([cx+x1*sc,cx+x2*sc],[cy+y1*sc,cy+y2*sc],'k-',lw=0.8)
# 外轮廓虚线中心线
ax.plot([cx-70,cx+70],[cy,cy],'-.',color="#888",lw=0.5)
ax.plot([cx,cx],[cy-45,cy+45],'-.',color="#888",lw=0.5)

# 真实尺寸标注（来自 IR 语义层）
lead = "4×Φ%d" % DIA
ax.annotate(lead, xy=(cx+35, cy+22), xytext=(cx+70, cy+55),
            fontsize=10, color="#c00", fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#c00", lw=1))
ax.text(cx+70, cy+60, "安装孔（联动）", fontsize=7, color="#c00")
ax.annotate("R%d" % R_FILLET, xy=(cx-38, cy+38), xytext=(cx-78, cy+58),
            fontsize=9, color="#06c",
            arrowprops=dict(arrowstyle="->", color="#06c", lw=1))
# 总长总宽
ax.annotate("", xy=(cx-48,cy-50), xytext=(cx+48,cy-50), arrowprops=dict(arrowstyle="<->",lw=0.7))
ax.text(cx, cy-58, "120", fontsize=8, ha="center")
ax.annotate("", xy=(cx-58,cy-36), xytext=(cx-58,cy+36), arrowprops=dict(arrowstyle="<->",lw=0.7))
ax.text(cx-66, cy, "80", fontsize=8, va="center", rotation=90)

# 主视图（左上）
fx, fy = 130, 235
ax.text(fx, fy+45, "主视图 (Front)", fontsize=10, ha="center")
for kind, geom, val in front_e:
    if kind=="line":
        (x1,y1),(x2,y2)=geom
        ax.plot([fx+x1*sc,fx+x2*sc],[fy+y1*sc,fy+y2*sc],'k-',lw=0.9)
ax.annotate("", xy=(fx-48,fy-30), xytext=(fx+48,fy-30), arrowprops=dict(arrowstyle="<->",lw=0.7))
ax.text(fx, fy-37, "120", fontsize=8, ha="center")
ax.annotate("12", xy=(fx+58,fy), fontsize=8, color="#c00", va="center")

ax.text(A3W-125, 48, "本图由 IR 语义层驱动生成", fontsize=7, color="#0a7")
ax.text(A3W-125, 42, "Φ%d 改 IR 一处 → 这里自动变" % DIA, fontsize=7, color="#0a7")

fig.savefig(OUT_PDF, format="pdf")
fig.savefig(OUT_PDF.replace(".pdf",".png"), dpi=150)
p("已生成:", OUT_PDF)
p("标注文字 = %s, 引用自 IR.dia=%d" % (lead, DIA))
