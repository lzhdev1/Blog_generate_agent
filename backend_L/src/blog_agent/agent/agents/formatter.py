"""排版 Markdown 文章，保留代码块原文与显式换行。"""
import re


def format_markdown(content: str) -> str:
    if not content:
        return content

    result = []
    fence = None
    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if fence:
            result.append(line)
            if re.fullmatch(r" {0,3}" + fence[0] + "{" + str(len(fence)) + r",}\s*", line):
                fence = None
            continue
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if opening:
            fence = opening.group(1)
            result.append(line)
            continue
        if line.startswith(("    ", "\t")):
            result.append(line)
            continue

        line = re.sub(r"<!--\s*配图[：:]\s*.*?-->", "", line)
        if not line.strip():
            if result and result[-1]:
                result.append("")
            continue

        line = re.sub(r"^(#{1,6})([^#\s])", r"\1 \2", line)
        line = re.sub(r"^(\s*)[*+]\s+", r"\1- ", line)
        line = re.sub(r"^(\s*)(\d+)[、．]\s*", r"\1\2. ", line)
        if re.match(r"^#{1,6}\s+", line) and result and result[-1]:
            result.append("")
        result.append(line)

    return "\n".join(result).strip("\n")
