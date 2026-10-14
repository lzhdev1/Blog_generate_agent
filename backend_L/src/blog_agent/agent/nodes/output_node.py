"""
输出/总结节点（三个子图共用的模板）

两种用途，由子图构造时指定：
1. 调研总结：ReAct 循环结束后，把搜索结果汇总交给模型，产出结构化调研结论，
   写入 state（title_research / outline_research / content_research）
2. 生成段：用生成指令（含调研结果/用户配置）产出业务产物，
   写入 state（titles / outline / content），可用结构化输出（Pydantic schema）

配套工具函数：
- collect_search_results(state)：把 ReAct 循环里所有工具搜索结果拼接成文本
- collect_full_conversation(state)：拼接完整对话历史（供生成段参考全部上下文）
"""
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

from src.blog_agent.agent.state import AgentState
from src.blog_agent.clients.llm_client import bind_structured_output, get_chat_model


def collect_search_results(state: AgentState, max_chars: int = 6000) -> str:
    """把 ReAct 循环中所有工具（web_search 等）的返回内容拼接为文本。

    供调研总结任务使用：模型基于真实搜索结果输出结论，而不是凭记忆。
    """
    messages: List[Dict[str, Any]] = state.get("messages") or []
    parts = [
        str(m.get("content", "")).strip()
        for m in messages
        if m.get("role") == "tool" and str(m.get("content", "")).strip()
    ]
    joined = "\n\n---\n\n".join(parts)
    return joined[:max_chars]


def collect_full_conversation(state: AgentState, max_chars: int = 12000) -> str:
    """拼接 ReAct 循环完整对话（含搜索结果），供生成段参考上下文。"""
    messages: List[Dict[str, Any]] = state.get("messages") or []
    parts = [
        f"[{m.get('role')}]\n{str(m.get('content', '')).strip()}"
        for m in messages
        if str(m.get("content", "")).strip()
    ]
    joined = "\n\n".join(parts)
    return joined[:max_chars]


def make_output_node(
    system_prompt: str,
    task_builder: Callable[[AgentState], str],
    output_key: str,
    model_role: str = "researcher",
    temperature: Optional[float] = None,
    structured_schema: Optional[Type[BaseModel]] = None,
    extractor: Optional[Callable[[BaseModel], Any]] = None,
    enable_thinking: Optional[bool] = None,
):
    """
    生成一个输出/总结节点。

    - system_prompt: 模型人设
    - task_builder: 根据 state 拼接任务指令（调研总结 → SUMMARY + 搜索结果；
                    生成段 → 生成指令 + 调研结果 + 用户配置）
    - output_key: 结果写入 state 的字段名（title_research / titles / outline / content ...）
    - structured_schema: 需要结构化输出时传入 Pydantic 模型
    - extractor: 把结构化对象转成要写入 state 的值（如 TitleList → .titles 列表）；
                 缺省时写入 model_dump() 结果
    - enable_thinking: None 按角色白名单（reviewer 开思考等）；True/False 强制
    """
    if structured_schema is not None:
        model = bind_structured_output(
            structured_schema, role=model_role, enable_thinking=enable_thinking
        )
        use_text = False
    else:
        model = get_chat_model(
            role=model_role, temperature=temperature, enable_thinking=enable_thinking
        )
        use_text = True

    def output_node(state: AgentState) -> Dict[str, Any]:
        task = task_builder(state)
        if use_text:
            resp = model.invoke(task)
            value: Any = str(resp.content)
        else:
            obj = model.invoke(task)
            value = extractor(obj) if extractor is not None else obj.model_dump()
        return {output_key: value}

    return output_node
