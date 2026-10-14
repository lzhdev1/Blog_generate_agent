"""
共享 AgentState：全流程 LangGraph 状态定义

所有子图（标题/大纲/正文）与主图（supervisor）共用这一个 State，
节点函数从 state 读输入、把结果写回 state，实现跨阶段数据贯通。

LangGraph 状态语义：
- 普通字段：节点返回时【覆盖】旧值（默认行为）
- Annotated 字段 + reducer：节点返回时【累积追加】新值（如对话消息、工具轨迹）
"""
from operator import add
from typing import Annotated, Any, Dict, List, Optional, TypedDict


def add_list(left: List, right: List) -> List:
    """累积型 reducer：把新列表追加到旧列表后面（用于 messages / tool_traces）。

    约定：返回【空列表】表示清空信号（子图入口重置当前 ReAct 循环时使用），
    其余情况为追加累积。
    """
    if not right:
        return []
    return left + right


class AgentState(TypedDict, total=False):
    """
    共享工作流状态
    字段分组：任务信息 / 用户输入与配置 / 标题阶段 / 大纲阶段 / 正文阶段 /
             审稿与质量门 / ReAct 循环与工具轨迹 / 流程控制
    """

    # ==================== 任务信息 ====================
    task_id: int
    """任务 ID：用于同步数据库、前端轮询"""
    status: str
    """任务状态：对应 TaskStatus 枚举值（researching_title / generating_content ...）"""
    progress: str
    """当前进度提示：写入数据库，前端展示用"""

    # ==================== 用户输入与配置 ====================
    topic: str
    """用户最初输入的主题"""
    article_style: str
    """文章风格：popular_science / technical / essay / prose / note / custom（标题选择页）"""
    article_style_custom: str
    """自定义风格内容（风格为 custom 时用户输入）"""
    need_image: bool
    """是否配图（标题选择页配置，传大纲子图）"""
    image_source: str
    """配图方式：api(搜图) / ai(AI生图)（大纲确认页配置，正文子图后配图工具用）"""
    extra_requirements: str
    """对大纲的额外要求（标题选择页填写，只给大纲子图）"""
    word_count: int
    """目标字数（大纲确认页填写，给正文子图）"""
    level: str
    """专业水平（大纲确认页填写，给正文子图）"""
    content_extra_requirements: str
    """对正文的额外要求（大纲确认页填写，只给正文子图）"""

    # ==================== 标题阶段 ====================
    title_research: str
    """标题调研结果（含资料来源/时间，标题子图输出，主图评审可见）"""
    titles: List[str]
    """生成的候选标题列表"""
    title_scores: List[Dict[str, Any]]
    """标题评分列表"""
    selected_title: str
    """用户选择的标题（用户确认后写入，供后续子图使用）"""

    # ==================== 大纲阶段 ====================
    outline_research: str
    """大纲调研结果（同类文章结构分析，大纲子图输出）"""
    outline: str
    """生成的大纲（含配图标记，正文子图输入）"""
    outline_confirmed: bool
    """大纲是否已确认（用户确认后为 True）"""

    # ==================== 正文阶段 ====================
    content_research: str
    """正文调研结果（素材 + 来源 + 发布时间，正文子图输出）"""
    content: str
    """正文 markdown（含配图标记）"""
    writing_thoughts: str
    """写手写作思路（写库后前端右侧栏展示）"""
    image_urls: List[str]
    """配图 URL 列表（配图工具产出）"""
    image_prompts: List[Dict[str, Any]]
    """配图提示词（搜图关键词 / AI 生图 prompt）"""
    formatted_content: str
    """格式化后的正文（排版工具产出，最终展示用）"""

    # ==================== 审稿与质量门（主 Agent） ====================
    review_result: Dict[str, Any]
    """最近一次评审结果：passed / score / 各维度评分 / 意见 / 是否需重新调研"""
    review_count: int
    """打回次数（防死循环，与 max_review_rounds 配合）"""
    max_review_rounds: int
    """打回上限（默认 3，从 settings 注入）"""
    review_feedback: str
    """给子 Agent 的审稿意见（逐条列出，子 Agent 重跑时携带）"""
    research_suggestions: str
    """审稿给出的调研建议（打回后重新调研/补充调研的方向清单）"""

    # ==================== ReAct 循环与工具轨迹 ====================
    messages: Annotated[List[Dict[str, Any]], add_list]
    """当前子图 ReAct 循环的对话历史：{role, content} 字典列表。
    子图入口重置为空列表，循环中累积「模型消息 + 工具结果」，支持条件边判断与断点恢复。"""
    tool_traces: Annotated[List[Dict[str, Any]], add_list]
    """全流程工具调用轨迹：[{tool, args, result_summary, timestamp}]。
    全流程累积不清空，写库后前端可展示「调研/工具调用过程」。"""

    # ==================== 流程控制 ====================
    stage: str
    """当前阶段标识：titles / outline / content / done（主图路由用）"""
    error: Optional[str]
    """错误信息（异常时写入）"""
