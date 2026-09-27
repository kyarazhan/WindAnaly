"""i18n 审计（B5）：扫描 ui/ 与 app.py 中未经 tr() 的中文文案。

规则：
  - 统计 AST 层面的字符串常量（含 f-string 片段）中含 CJK 的节点；
  - 包裹在 tr(...) 调用内的字符串视为已国际化，不计；
  - 模块/类/函数的 docstring、注释不计（注释本就不进 AST 字符串）；
  - `tools/i18n_audit_allowlist.txt` 每行一个子串，命中的发现视为已接受
    （内部日志、异常细节等非界面文案）。

用法:
    python tools/i18n_audit.py            # 全量报告；非白名单 >0 时退出码 1
    python tools/i18n_audit.py --list     # 只列出发现，不改退出码
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

ALLOWLIST_FILE = os.path.join('tools', 'i18n_audit_allowlist.txt')
SCAN_TARGETS = ['app.py', 'ui']


def has_cjk(s: str) -> bool:
    return any('\u4e00' <= ch <= '\u9fff' for ch in s)


def load_allowlist() -> list[str]:
    if not os.path.exists(ALLOWLIST_FILE):
        return []
    return [l.rstrip('\n') for l in open(ALLOWLIST_FILE, encoding='utf-8')
            if l.strip() and not l.startswith('#')]


class Scanner(ast.NodeVisitor):
    def __init__(self):
        self.findings = []
        self.tr_depth = 0
        self._docstrings = set()

    def _mark_docstring(self, node):
        body = getattr(node, 'body', None)
        if body:
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                self._docstrings.add(id(first))

    def visit_Module(self, node):
        self._mark_docstring(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._mark_docstring(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._mark_docstring(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == 'tr':
            self.tr_depth += 1
            self.generic_visit(node)
            self.tr_depth -= 1
        else:
            self.generic_visit(node)

    def _check_str(self, node, text):
        if self.tr_depth == 0 and id(node) not in self._docstrings \
                and has_cjk(text):
            self.findings.append((node.lineno, text))

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            self._check_str(node, node.value)

    def visit_JoinedStr(self, node):
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                self._check_str(v, v.value)
        self.generic_visit(node)


def scan_file(path: str) -> list:
    src = open(path, encoding='utf-8').read()
    scanner = Scanner()
    scanner.visit(ast.parse(src))
    return [(path, ln, text) for ln, text in scanner.findings]


def main() -> int:
    list_only = '--list' in sys.argv
    allow = load_allowlist()
    findings = []
    targets = ['app.py']
    for r, d, fs in os.walk('ui'):
        d[:] = [x for x in d if x != '__pycache__']
        targets += [os.path.join(r, f) for f in fs if f.endswith('.py')]
    for path in targets:
        findings += scan_file(path)

    remaining = []
    allow_norm = [''.join(a.split()) for a in allow if a.strip()]
    for path, ln, text in findings:
        norm = ''.join(text.split())
        if not any(a in norm for a in allow_norm):
            remaining.append((path, ln, text))

    for path, ln, text in sorted(remaining):
        print(f'{path}:{ln}: {text[:80]}')
    print(f'\n硬编码中文文案：{len(findings)} 处，'
          f'白名单接受 {len(findings) - len(remaining)} 处，'
          f'待处理 {len(remaining)} 处')

    if list_only:
        return 0
    return 1 if remaining else 0


if __name__ == '__main__':
    sys.exit(main())
