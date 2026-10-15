# -*- coding: utf-8 -*-
r"""lib —— 系统层骨架（零件无关的通用实现）

本目录的模块**不含任何零件几何**，可被任意零件步骤调用。
与 `steps/` 的区别：
  * `steps/` 是**消息流水线的入口**（每个文件对应一步，负责 boot/run_stage 与协议）
  * `lib/`  是**入口调用的工具实现**（纯函数、可单测、无副作用）

当前成员：
  collect.py  从投影数据提取几何特征（s5_collect 的实现）
  ir.py       零件的唯一真值表示（IR / feature graph；build123d 与 PartDesign 的共同源）
  drawing_fc.py   出图骨架（TechDraw 视图 + 标注，零件声明分离）
  drawing_render.py  出图渲染骨架（投影 JSON → A3 图纸）
"""
