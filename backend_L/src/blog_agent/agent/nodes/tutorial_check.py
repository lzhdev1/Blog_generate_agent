"""Check concrete Python tutorial inputs without executing generated code or opening its paths."""
import ast
import re
from pathlib import PurePath


_FENCE = re.compile(
    r"^ {0,3}(?P<fence>`{3,}|~{3,})[ \t]*(?P<lang>[^\n]*)\n(?P<code>.*?)"
    r"^ {0,3}(?P=fence)[ \t]*\r?$", re.M | re.S)
_PYTHON = {"py", "py3", "python", "python3"}
_READERS = {"read_csv", "read_table", "read_json", "read_excel", "read_parquet", "read_pickle"}
_WRITERS = {"to_csv", "to_json", "to_excel", "to_parquet", "to_pickle"}
_PREPARATION = re.compile(
    r"保存为|另存为|命名为|另存成|保存成|准备(?:好|文件|一份|一个)|内容(?:如[下图]|为)|"
    r"创建|新建|下载|写入|存入|已有|给定|"
    r"save(?:d)?(?:\s+\w+){0,2}\s+as|create|download|already\s+have", re.I)
_SHELL_SETUP = re.compile(r"(?:>>?|\btee\b)\s*['\"]?([^\s'\";|]+)")
_MULTI_ROW_OUTPUT = re.compile(
    r"(?:输出(?:为|如下)?|打印(?:出)?)[^。！？\n]{0,30}\[[^\]\n]+\]"
    r"[`\s]*(?:及|和|以及|、|换行后|随后|下一行)[^。！？\n]{0,15}\[[^\]\n]+\]")


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _file_access(call):
    """Return (path, creates_file) for commonplace, unambiguous literal-path calls."""
    fn = call.func
    kwargs = {kw.arg: kw.value for kw in call.keywords}
    arg = call.args[0] if call.args else None
    if isinstance(fn, ast.Name) and fn.id == "open":
        path = _literal(arg or kwargs.get("file"))
        mode = call.args[1] if len(call.args) > 1 else kwargs.get("mode")
        mode = "r" if mode is None else _literal(mode)
        if mode is not None:
            return path, any(letter in mode for letter in "wxa")
    if isinstance(fn, ast.Attribute):
        if fn.attr in _READERS | _WRITERS:
            return _literal(arg or kwargs.get("filepath_or_buffer") or kwargs.get("path_or_buf")), fn.attr in _WRITERS
        path_call = fn.value
        if (isinstance(path_call, ast.Call) and isinstance(path_call.func, ast.Name)
                and path_call.func.id == "Path" and path_call.args):
            if fn.attr in {"read_text", "read_bytes", "write_text", "write_bytes"}:
                return _literal(path_call.args[0]), fn.attr.startswith("write")
            if fn.attr == "open":
                mode = arg or kwargs.get("mode")
                mode = "r" if mode is None else _literal(mode)
                if mode is not None:
                    return _literal(path_call.args[0]), any(letter in mode for letter in "wxa")
    return None, False


def _prints_one_csv_row(tree):
    """Recognize a straight-line script that prints only the row returned by one next()."""
    nodes = list(ast.walk(tree))
    if any(isinstance(n, (ast.For, ast.While, ast.If, ast.Try, ast.FunctionDef, ast.comprehension)) for n in nodes):
        return False
    bindings = {}
    for node in nodes:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in bindings:
                return False
            bindings[name] = node.value

    def bound(value):
        return bindings.get(value.id) if isinstance(value, ast.Name) else value

    prints = [n for n in nodes if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"]
    if len(prints) != 1 or len(prints[0].args) != 1 or prints[0].keywords:
        return False
    item = bound(prints[0].args[0])
    if not (isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "next" and item.args):
        return False
    reader = bound(item.args[0])
    return (isinstance(reader, ast.Call) and isinstance(reader.func, ast.Attribute)
            and isinstance(reader.func.value, ast.Name) and reader.func.value.id == "csv" and reader.func.attr == "reader")


def tutorial_input_issues(state):
    if state.get("article_style") != "technical":
        return []
    content = state.get("content") or ""
    prepared = set()
    brief = "\n".join(str(state.get(k) or "") for k in
                      ("topic", "purpose", "extra_requirements", "content_extra_requirements"))
    setup_lines = []
    problems = []
    output_issues = []
    previous = 0
    for block in _FENCE.finditer(content):
        lead = content[previous:block.start()]
        setup_lines.extend(line for line in lead.splitlines() if _PREPARATION.search(line))
        previous = block.end()
        code = block["code"]
        if block["lang"].strip().lower() not in _PYTHON:
            if block["lang"].strip().lower() in {"sh", "shell", "bash", "zsh"}:
                prepared.update(_SHELL_SETUP.findall(code))
            elif code.strip() and lead.strip():
                setup_lines.append(lead.strip().splitlines()[-1])
            # A fence such as ```csv orders.csv explicitly names the example's input.
            setup_lines.append(block["lang"])
            continue
        if re.search(r"反例|错误(?:写法|示例|演示)|故意(?:省略|遗漏)|预期报错|broken example", lead.strip().split("\n")[-1], re.I):
            continue
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError, RecursionError):
            continue  # Partial or pseudo-code belongs with the semantic reviewer.
        following = content[block.end():].strip().split("\n\n")[0]
        if _prints_one_csv_row(tree) and _MULTI_ROW_OUTPUT.search(following):
            output_issues.append(("教程输出", "示例只读取并打印一行，却声称会依次输出两行",
                                  "让示例实际读取并打印所列各行，或如实给出这段代码的单行输出"))
        calls = sorted((node for node in ast.walk(tree) if isinstance(node, ast.Call)),
                       key=lambda node: (node.lineno, node.col_offset))
        for call in calls:
            path, creates = _file_access(call)
            if not path or "://" in path or "\n" in path or not PurePath(path).suffix:
                continue
            if creates:
                prepared.add(path)
            elif path not in prepared and path not in problems:
                name = re.compile(r"(?<![\w./-])" + re.escape(path) + r"(?![\w./-])", re.ASCII)
                if not name.search(brief) and not any(name.search(line) for line in setup_lines):
                    problems.append(path)
    return ([("教程输入", f"Python 示例读取 {path!r}，前文没有给出或创建这个输入文件",
              "给出可复现的最小输入和准备方法，或让示例在内存中直接处理同一份数据") for path in problems[:3]]
            + output_issues[:1])
