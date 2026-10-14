# -*- coding: utf-8 -*-
"""对照：静态 AST 提取（不做执行）—— 验证文档 §5.4 的对比数据。"""
import ast

SRC = "/tmp/z2c_sample.py"

def extract_ast(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else \
                   (f.id if isinstance(f, ast.Name) else "?")
            args = []
            for a in node.args:
                if isinstance(a, ast.Constant):
                    args.append(a.value)
                elif isinstance(a, ast.Name):
                    args.append("<变量:%s>" % a.id)      # ← 参数不是数值！
                elif isinstance(a, ast.BinOp):
                    args.append("<表达式>")               # ← 算术表达式无法求值
                else:
                    args.append("<%s>" % type(a).__name__)
            calls.append((node.lineno, name, args))
    return calls

if __name__ == "__main__":
    calls = extract_ast(SRC)
    # 打印（按 lineno 排序，静态提取只能这样）
    calls_sorted = sorted(calls, key=lambda c: c[0])
    print("=== 静态 AST 提取：共 %d 条 Call ===" % len(calls_sorted))
    for ln, name, args in calls_sorted:
        print("  L%-3d %-12s %s" % (ln, name, args))
    print()
    # 统计丢失的信息
    names = [n for _, n, _ in calls]
    print("--- 丢失检查 ---")
    print("union 出现次数:", names.count("union"), "（真实 1 处 + for 循环里应展开为 4 次）")
    print("cut   出现次数:", names.count("cut"),   "（真实应 6 次：1 中心孔 + 1 槽 + 4 安装孔）")
    print("有 <变量:...> 的参数个数:", sum(1 for _,_,a in calls for x in a if str(x).startswith("<变量")))
    print("有 <表达式> 的参数个数:", sum(1 for _,_,a in calls for x in a if x=="<表达式>"))
    print("center() 调用:", names.count("center"), "（但 AST 看不到它作用在哪个对象上）")
