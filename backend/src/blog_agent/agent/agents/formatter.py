import re

from src.blog_agent.agent.agents.base_agent import BaseAgent


class FormatterAgent(BaseAgent):
    """排版师 Agent：负责格式化文章、生成目录、调整版式"""

    name = "formatter"
    role = "排版师"
    system_prompt = """你是一个专业的排版编辑，擅长：
1. 统一 markdown 格式（标题层级、列表、代码块、引用）
2. 调整段落间距和空行
3. 检查并修正格式错误
4. 保持内容不变，只优化格式"""
    model_config_key = "llm_model_formatter"

    def format_content(self, content: str) -> str:
        """格式化文章"""
        # 先用规则做基础格式化
        formatted = self._basic_format(content)

        # 再用 LLM 做精细调整（简单任务，温度低）
        prompt = f"""请对以下 markdown 文章做格式优化，保持内容不变：

{formatted}

要求：
1. 统一标题层级（## 一级，### 二级）
2. 段落之间空一行
3. 列表格式统一
4. 代码块加上语言标识
5. 去掉多余的空行
6. 直接输出格式化后的文章，不要其他解释"""

        try:
            result = self.chat(prompt, temperature=0.2)
            return result
        except Exception:
            # LLM 调用失败，返回基础格式化的结果
            return formatted

    def _basic_format(self, content: str) -> str:
        """基础格式化：用规则处理常见格式问题"""
        # 统一换行符
        content = content.replace("\r\n", "\n")

        # 去掉大纲残留的配图注释 <!-- 配图：... -->
        content = re.sub(r'<!--\s*配图[：:]\s*.+?\s*-->\s*', '', content)

        # 去掉行尾空格
        lines = [line.rstrip() for line in content.split("\n")]

        # 合并连续空行（最多一个空行）
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

        return "\n".join(result).strip()
