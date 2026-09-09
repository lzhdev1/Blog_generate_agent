from typing import Optional

from src.blog_agent.agent.agents.base_agent import BaseAgent
from config.settings import settings


class ResearcherAgent(BaseAgent):
    """研究员 Agent：负责调研、搜索资料、分析同类文章
    采用 ReAct 模式：思考(Thought) → 搜索(Action) → 观察(Observation) → 总结
    """

    name = "researcher"
    role = "研究员"
    system_prompt = """你是一个专业的技术研究员，采用 ReAct（思考-行动-观察）模式工作：
1. 【思考】先分析需要调研哪些方面，确定搜索方向
2. 【行动】联网搜索相关资料（系统已自动开启联网搜索）
3. 【观察】从搜索结果中提取关键信息、数据和来源
4. 【总结】输出结构化的调研结论

你的回答要简洁、有洞察力，包含具体数据和来源，不要泛泛而谈。"""
    model_config_key = "llm_model_researcher"

    def research_for_titles(self, topic: str) -> str:
        """
        标题调研：ReAct 模式分析同类文章标题，避免重复，提供角度建议
        自动开启千问自带联网搜索
        """
        prompt = f"""请用 ReAct 模式对"{topic}"进行博客标题调研。

请按以下格式输出：

【思考】
分析这个主题需要调研哪些方面？同类文章的标题通常有什么规律？

【搜索】
（系统已自动联网搜索，请基于搜索到的真实文章分析）

【观察】
从搜索结果中发现：
1. 常见写作角度有哪些？
2. 标题风格（数字型/疑问型/干货型）分布如何？
3. 热门关键词有哪些？
4. 有哪些标题已经被大量使用，需要避开？

【总结】
给出标题创作建议：
- 推荐的切入角度（2-3个）
- 建议使用的关键词
- 需要避开的雷区
- 独特的差异化方向

控制在400字以内，要具体，不要空话。"""

        # 开启千问自带联网搜索
        return self.chat(prompt, temperature=0.5, enable_search=True)

    def research_for_outline(self, topic: str, selected_title: str) -> str:
        """
        大纲调研：ReAct 模式分析同类文章大纲结构，避免重复
        自动开启千问自带联网搜索
        """
        prompt = f"""请用 ReAct 模式进行博客大纲调研。

主题：{topic}
拟定标题：{selected_title}

请按以下格式输出：

【思考】
这个标题下的文章应该包含哪些核心内容？同类文章的大纲结构有什么规律？

【搜索】
（系统已自动联网搜索，请基于搜索到的真实文章分析）

【观察】
从搜索结果中发现：
1. 同类文章通常包含哪些章节？
2. 常见的大纲结构（章节顺序）是什么样的？
3. 哪些内容是必须包含的（读者期待的）？
4. 哪些内容是大多数文章都有的，容易雷同？

【总结】
给出大纲创作建议：
- 推荐的章节结构
- 必须包含的核心内容
- 可以增加的差异化内容（避免雷同）
- 需要注意的避坑点

控制在400字以内，要具体，不要空话。"""

        # 开启千问自带联网搜索
        return self.chat(prompt, temperature=0.5, enable_search=True)

    def research_for_content(self, topic: str, selected_title: str, outline: str) -> str:
        """
        正文调研：ReAct 模式根据标题和大纲，联网检索最新的支撑内容和可靠数据
        自动开启千问自带联网搜索
        """
        prompt = f"""请用 ReAct 模式进行正文写作前的资料调研。

主题：{topic}
拟定标题：{selected_title}
文章大纲：
{outline}

请按以下格式输出：

【思考】
根据大纲，每个章节需要哪些最新数据、案例和权威资料来支撑？哪些技术点可能已经过时需要核实？

【搜索】
（系统已自动联网搜索，请针对大纲中的关键技术点逐一搜索）

【观察】
从搜索结果中提取：
1. 最新的技术版本号、官方数据（列出具体数字）
2. 权威参考资料（官方文档、知名技术博客的名称和链接）
3. 真实案例、Benchmark 数据、性能对比（列出具体数据）
4. 最新的最佳实践、注意事项和常见坑
5. 近期的行业动态和趋势

【总结】
整理成写作参考资料：
- 关键数据速查（版本号、性能指标等）
- 可引用的权威来源
- 需要在文章中体现的最新实践
- 注意避免的过时信息

控制在500字以内，数据要具体，来源要明确。"""

        # 开启千问自带联网搜索
        return self.chat(prompt, temperature=0.3, enable_search=True)

    def score_titles(self, topic: str, titles: list, research: str) -> list:
        """
        对生成的3个标题进行评分
        评分维度：准确性、独特性、SEO友好度
        返回：[{"title": str, "accuracy": int, "uniqueness": int, "seo": int, "total": float, "pros": [str], "cons": [str]}, ...]
        """
        titles_str = "\n".join([f"{i+1}. {t}" for i, t in enumerate(titles)])

        prompt = f"""请作为专业的标题评审，对以下3个博客标题进行评分。

主题：{topic}

待评分标题：
{titles_str}

调研参考：
{research}

评分维度（每项0-10分）：
1. 准确性：标题是否准确反映文章内容，不夸大、不误导
2. 独特性：标题是否有新意，避免和同类文章雷同
3. SEO友好度：标题是否包含关键词，是否适合搜索引擎收录

请严格按照以下JSON格式输出，不要输出其他内容：
[
  {{
    "title": "标题原文",
    "accuracy": 0-10的整数,
    "uniqueness": 0-10的整数,
    "seo": 0-10的整数,
    "total": 综合分(保留1位小数),
    "pros": ["优点1", "优点2"],
    "cons": ["缺点1", "缺点2"]
  }}
]

注意：
- 综合分 = (准确性 + 独特性 + SEO友好度) / 3
- pros和cons各2条，要具体，不要空话
- 直接输出JSON数组，不要markdown代码块"""

        resp = self.chat(prompt, temperature=0.3)

        # 解析 JSON
        try:
            import json
            # 清理可能的 markdown 代码块
            resp_clean = resp.strip()
            if resp_clean.startswith("```"):
                lines = resp_clean.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                resp_clean = "\n".join(lines)
            scores = json.loads(resp_clean)
            return scores
        except Exception as e:
            print(f"标题评分解析失败: {e}")
            # 解析失败，返回默认评分
            return [
                {
                    "title": t,
                    "accuracy": 7,
                    "uniqueness": 7,
                    "seo": 7,
                    "total": 7.0,
                    "pros": ["标题结构清晰"],
                    "cons": ["评分解析失败，使用默认分"]
                }
                for t in titles
            ]
