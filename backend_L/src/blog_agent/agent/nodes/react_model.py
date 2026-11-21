"""
ReAct 循环 · 机制节点（三个子图共用的模板）

react_model 是「思考」节点：把调研指令 + 对话历史交给绑定了工具的 LLM，
产出下一轮消息（可能带 tool_calls，也可能直接给最终答复）。

用法（子图构造时闭包绑定，实现机制复用）：
    research_model_node = make_react_model_node(
        system_prompt=RESEARCH_SYSTEM,
        task_builder=build_title_research_plan,   # 根据 state 拼 PLAN 指令
        tools=[web_search],                        # 绑定给模型的工具
        model_role="researcher",
    )

state.messages 约定（与 state.py 一致）：[{role, content, ...}] 字典列表
- 首轮由本节点惰性注入 system + task，之后循环累积 assistant / tool 消息
- dict 与 langchain BaseMessage 的互转在本模块实现
"""
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

from src.blog_agent.agent.state import AgentState
from src.blog_agent.agent.agents.prompt_utils import editorial_brief
from src.blog_agent.clients.llm_client import get_chat_model

# ============================================================
# 消息互转（dict 列表 <-> langchain BaseMessage）
# ============================================================


def message_to_dict(msg: BaseMessage) -> Dict[str, Any]:
    """BaseMessage -> state.messages 里的 dict"""
    d: Dict[str, Any] = {"role": _role_of(msg), "content": msg.content}
    if isinstance(msg, AIMessage) and msg.tool_calls:
        # 保留工具调用信息，供 react_tools 节点执行、条件边判断
        d["tool_calls"] = [
            {"name": tc["name"], "args": tc["args"], "id": tc["id"]}
            for tc in msg.tool_calls
        ]
    if isinstance(msg, ToolMessage):
        d["tool_call_id"] = msg.tool_call_id
    return d


def _role_of(msg: BaseMessage) -> str:
    if isinstance(msg, SystemMessage):
        return "system"
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, AIMessage):
        return "assistant"
    if isinstance(msg, ToolMessage):
        return "tool"
    return "assistant"


def dict_to_message(d: Dict[str, Any]) -> BaseMessage:
    """state.messages 里的 dict -> BaseMessage"""
    role = d.get("role", "assistant")
    content = d.get("content", "")
    if role == "system":
        return SystemMessage(content=content)
    if role == "user":
        return HumanMessage(content=content)
    if role == "tool":
        return ToolMessage(
            content=content,
            tool_call_id=d.get("tool_call_id") or d.get("id") or "tool_call_id",
        )
    # assistant
    tool_calls = d.get("tool_calls")
    if tool_calls:
        return AIMessage(
            content=content,
            tool_calls=[
                {"name": tc["name"], "args": tc["args"], "id": tc["id"]}
                for tc in tool_calls
            ],
        )
    return AIMessage(content=content)


# ============================================================
# 机制节点工厂
# ============================================================


def make_react_model_node(
    system_prompt: str,
    task_builder: Callable[[AgentState], str],
    tools: Optional[List[BaseTool]] = None,
    model_role: str = "researcher",
    temperature: Optional[float] = None,
):
    """
    生成一个 ReAct「思考」节点。

    - system_prompt: 模型人设（如 RESEARCH_SYSTEM）
    - task_builder: 根据当前 state 拼接任务指令的函数（如 PLAN 指令模板 + state 字段）
    - tools: 绑定给模型的工具列表（模型据此输出 tool_calls）
    - model_role / temperature: 透传给 get_chat_model

    首轮自动注入 [system, user(task)]，此后直接以累积历史调用模型。
    """
    model = get_chat_model(role=model_role, temperature=temperature)
    if tools:
        model = model.bind_tools(tools)

    def react_model_node(state: AgentState) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = state.get("messages") or []
        if not messages:
            # 第一轮：注入 system + 任务指令
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task_builder(state) + editorial_brief(state)},
            ]
        resp = model.invoke([dict_to_message(m) for m in messages])
        return {"messages": [*messages, message_to_dict(resp)]}

    return react_model_node
