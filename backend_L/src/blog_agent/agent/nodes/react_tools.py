"""
ReAct 循环 · 工具执行节点（三个子图共用的模板）

react_tools 是「行动 + 观察」节点：读取最后一条 AIMessage 的 tool_calls，
逐个执行工具，把结果作为 ToolMessage 追加回 state.messages，供模型下一轮观察。

配套条件边 has_tool_calls：
- 最后一条消息带 tool_calls -> 继续走 react_tools（行动）
- 否则 -> 调研完成，走出口（总结/输出节点）

异常处理：单个工具调用失败不中断循环，以 "工具调用失败: ..." 反馈给模型，
让模型自行决定重试或放弃（标准 ReAct 容错方式）。
"""
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from src.blog_agent.agent.state import AgentState
from src.blog_agent.agent.nodes.react_model import message_to_dict


def make_react_tools_node(tools: List[BaseTool]):
    """生成 ReAct「工具执行」节点，tools 与绑定给模型的一致（按名称路由）"""
    tool_map = {t.name: t for t in tools}

    def react_tools_node(state: AgentState) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = state.get("messages") or []
        last = messages[-1]
        tool_calls = last.get("tool_calls") or []

        tool_messages: List[Dict[str, Any]] = []
        for tc in tool_calls:
            tool = tool_map.get(tc.get("name"))
            if tool is None:
                content = f"未知工具: {tc.get('name')}（可用工具：{', '.join(tool_map.keys())}）"
            else:
                try:
                    result = tool.invoke(tc.get("args") or {})
                    content = str(result)
                except Exception as e:  # noqa: BLE001 - 工具异常必须反馈给模型而非中断
                    content = f"工具调用失败: {type(e).__name__}: {e}"
            tool_messages.append(
                message_to_dict(
                    ToolMessage(
                        content=content,
                        tool_call_id=tc.get("id") or "tool_call_id",
                    )
                )
            )
        # 注意：state.messages 是 add_list 累积 reducer，这里只返回【增量】工具消息
        return {"messages": tool_messages}

    return react_tools_node


# ReAct 循环硬性上限：工具调用次数达到该值后强制结束，
# 防止模型无限搜索（token 黑洞）。与各调研 PLAN 的"最多搜索 2 次"一致。
MAX_TOOL_ROUNDS = 2


def has_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    """ReAct 循环条件边：
    - 还有待执行的工具调用且未超过硬上限 -> tools（继续行动）
    - 无工具调用 或 已达硬上限 -> done（调研完成）
    """
    messages: List[Dict[str, Any]] = state.get("messages") or []
    if not messages or not messages[-1].get("tool_calls"):
        return "done"
    tool_count = sum(1 for m in messages if m.get("role") == "tool")
    if tool_count >= MAX_TOOL_ROUNDS:
        return "done"
    return "tools"
