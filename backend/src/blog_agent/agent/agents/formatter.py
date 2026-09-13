import re


def format_markdown(content: str) -> str:
    """
    纯规则格式化 Markdown 文章，不调用 LLM。
    保持内容不变，只优化格式。
    """
    if not content:
        return content

    # 1. 统一换行符
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # 2. 去掉残留的配图注释 <!-- 配图：... -->
    content = re.sub(r'<!--\s*配图[：:]\s*.+?\s*-->\s*', '', content)

    # 3. 去掉行尾空格
    lines = [line.rstrip() for line in content.split("\n")]

    # 4. 统一标题格式（# 后面必须有空格）
    lines = [re.sub(r'^(#{1,6})([^#\s])', r'\1 \2', line) for line in lines]

    # 5. 统一无序列表格式（* 和 + 改成 -）
    lines = [re.sub(r'^(\s*)[*+]\s+', r'\1- ', line) for line in lines]

    # 6. 统一有序列表格式（确保数字后面是 . 加空格）
    lines = [re.sub(r'^(\s*)(\d+)[、.．]\s*', r'\1\2. ', line) for line in lines]

    # 7. 代码块加上语言标识（如果没有的话）
    in_code_block = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            if not in_code_block:
                # 开始代码块
                if line.strip() == "```":
                    lines[i] = "```text"
                in_code_block = True
            else:
                # 结束代码块
                in_code_block = False

    # 8. 合并连续空行（最多一个空行）
    result = []
    prev_empty = False
    for line in lines:
        if line.strip() == "":
            if not prev_empty:
                result.append("")
            prev_empty = True
        else:
            result.append(line)
            prev_empty = False

    # 9. 确保标题前后有空行（标题前面空行，标题后面不需要强制）
    final = []
    for i, line in enumerate(result):
        if re.match(r'^#{1,6}\s+', line):
            # 标题前面如果不是空行且不是第一行，插入空行
            if final and final[-1].strip() != "":
                final.append("")
        final.append(line)

    return "\n".join(final).strip()
