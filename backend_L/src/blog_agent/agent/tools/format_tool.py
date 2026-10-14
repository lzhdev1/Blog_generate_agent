"""
排版 / 格式化工具（纯确定性规则，无 LLM）

- format_markdown：规范化 Markdown 正文（去掉残留配图标记、统一标题/列表/空行）
- to_json：对象 → JSON 字符串（供节点把结构化结果写入 state / 前端展示）

迁移自旧版 backend/agent/agents/formatter.py（生产已验证），改为工具形式。
"""
import json
import re
from typing import Any

from langchain_core.tools import tool


def format_markdown(content: str) -> str:
    """
    纯规则格式化 Markdown 文章，保持内容不变，只优化格式：
    1. 统一换行符（CRLF/CR → LF）
    2. 去掉残留的配图注释 <!-- 配图：... -->
    3. 去掉行尾空格
    4. 标题 # 后必须有空格
    5. 无序列表统一为 "- "
    6. 有序列表统一为 "1. "
    7. 代码块无语言标识时补 "text"
    8. 合并连续空行（最多一个）
    9. 标题前保证空行
    """
    if not content:
        return content

    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # 去掉残留的配图注释（含其后多余空行）
    content = re.sub(r"<!--\s*配图[：:]\s*.+?\s*-->\s*", "", content)

    lines = [line.rstrip() for line in content.split("\n")]
    # 标题 # 后必须有空格
    lines = [re.sub(r"^(#{1,6})([^#\s])", r"\1 \2", line) for line in lines]
    # 无序列表统一 "- "
    lines = [re.sub(r"^(\s*)[*+]\s+", r"\1- ", line) for line in lines]
    # 有序列表统一 "1. "
    lines = [re.sub(r"^(\s*)(\d+)[、.．]\s*", r"\1\2. ", line) for line in lines]

    # 代码块补语言标识
    in_code_block = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            if not in_code_block:
                if line.strip() == "```":
                    lines[i] = "```text"
                in_code_block = True
            else:
                in_code_block = False

    # 合并连续空行（最多一个）
    result: list = []
    prev_empty = False
    for line in lines:
        if line.strip() == "":
            if not prev_empty:
                result.append("")
            prev_empty = True
        else:
            result.append(line)
            prev_empty = False

    # 标题前保证空行
    final: list = []
    for line in result:
        if re.match(r"^#{1,6}\s+", line):
            if final and final[-1].strip() != "":
                final.append("")
        final.append(line)

    return "\n".join(final).strip()


@tool
def format_markdown_tool(content: str) -> str:
    """
    规范化 Markdown 正文格式（纯规则，不改变内容语义）：
    统一换行、清理残留配图标记、规范标题/列表/代码块/空行。

    Args:
        content: 待格式化的 Markdown 文本

    Returns:
        格式化后的 Markdown 文本。
    """
    return format_markdown(content)


@tool
def to_json(data: str) -> str:
    """
    把 JSON 字符串规范化（解析后重新序列化，去掉非法空白/修正格式）。
    若输入不是合法 JSON，原样返回。

    Args:
        data: 待规范化的 JSON 字符串

    Returns:
        规范化后的 JSON 字符串。
    """
    try:
        parsed = json.loads(data)
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return data


def dumps_json(obj: Any, indent: int = 2) -> str:
    """Python 对象 → 美化 JSON 字符串（供节点把结构化结果写入 state / 前端展示）"""
    return json.dumps(obj, ensure_ascii=False, indent=indent)
