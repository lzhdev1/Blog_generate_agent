"""
LLM 客户端封装（基于 langchain-openai 的 ChatOpenAI）

为什么用 langchain 而不是裸调 openai SDK：
- langgraph 的 ReAct 循环（create_react_agent / StateGraph 节点）接收的是
  langchain_core 的 BaseChatModel，不是 openai 原始 client；
- with_structured_output 提供 Pydantic 结构化输出（output 节点解析 JSON 用）；
- 千问百炼是 OpenAI 兼容协议，ChatOpenAI 配 base_url 即可接入。

对外能力：
- get_chat_model(role, ...)     按角色拿一个 ChatOpenAI 实例（ReAct 子图绑定用）
- bind_structured_output(schema) 绑定 Pydantic 输出结构（output/审稿节点用）
- chat(messages, ...)           简单文本对话（非 ReAct 节点直接用）
"""
from functools import lru_cache
from typing import Any, Dict, List, Optional, Type, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from config.settings import settings

# 角色 -> settings 中的模型配置键
ROLE_MODEL_KEYS: Dict[str, str] = {
    "researcher": "llm_model_researcher",
    "title": "llm_model_title",
    "outliner": "llm_model_outliner",
    "writer": "llm_model_writer",
    "reviewer": "llm_model_reviewer",
    "image": "llm_model_image",
}

Role = str  # researcher / title / outliner / writer / reviewer / image


def _resolve_model_name(role: Optional[str]) -> str:
    """按角色解析模型名；角色未配置时回退到默认 llm_model"""
    if role:
        key = ROLE_MODEL_KEYS.get(role)
        if key:
            named = getattr(settings, key, None)
            if named:
                return named
    return settings.llm_model


def _resolve_thinking(
    role: Optional[str], enable_thinking: Optional[bool]
) -> bool:
    """决定是否开启思考模式：显式传值优先，否则按角色白名单（settings.llm_thinking_roles）"""
    if enable_thinking is not None:
        return enable_thinking
    return bool(role and role in settings.llm_thinking_roles_list)


@lru_cache(maxsize=64)
def _get_chat_model_cached(
    model_name: str,
    temperature: float,
    enable_search: bool,
    timeout: int,
    enable_thinking: bool,
) -> ChatOpenAI:
    """
    缓存模型实例：同一 (model, temperature, search, thinking) 只创建一次连接对象。
    注意：settings 是进程级单例，其值运行期不变，按值缓存是安全的。
    """
    kwargs: Dict[str, Any] = {
        "model": model_name,
        "api_key": settings.llm_api_key,
        "base_url": settings.llm_base_url,
        "temperature": temperature,
        "timeout": timeout,       # LLM 调用超时（秒），防止 API 卡住无限等待
        "max_retries": 2,         # 网络级失败自动重试 2 次
    }
    # 千问百炼 OpenAI 兼容模式：extra_body 携带非标准参数
    extra_body: Dict[str, Any] = {"enable_thinking": enable_thinking}
    if enable_search:
        # 千问自带联网搜索（调研节点用；注意：Chat Completions 不带结构化来源）
        extra_body["enable_search"] = True
    kwargs["extra_body"] = extra_body
    return ChatOpenAI(**kwargs)


def get_chat_model(
    role: Optional[str] = None,
    temperature: Optional[float] = None,
    enable_search: Optional[bool] = None,
    enable_thinking: Optional[bool] = None,
) -> ChatOpenAI:
    """
    获取一个 ChatOpenAI 实例。

    - role: researcher/title/outliner/writer/reviewer/image；None 用默认 llm_model
    - temperature: None 用全局 settings.llm_temperature
    - enable_search: None 用全局 settings.llm_enable_search；
                     True/False 强制开启/关闭千问自带联网搜索
    - enable_thinking: None 按角色白名单（settings.llm_thinking_roles）；
                       True/False 强制开启/关闭思考模式
    """
    model_name = _resolve_model_name(role)
    temp = temperature if temperature is not None else settings.llm_temperature
    search = enable_search if enable_search is not None else settings.llm_enable_search
    thinking = _resolve_thinking(role, enable_thinking)
    return _get_chat_model_cached(
        model_name, temp, search, settings.agent_timeout, thinking
    )


def bind_structured_output(
    schema: Type[Any],
    role: Optional[str] = None,
    temperature: Optional[float] = None,
    enable_search: Optional[bool] = None,
    enable_thinking: Optional[bool] = None,
    method: str = "json_schema",
) -> BaseChatModel:
    """
    绑定 Pydantic 输出结构：模型输出会被强制解析为 schema 对应的对象。
    供 output 节点（标题/大纲/正文结构化产出）与审稿节点使用。

    - method: json_schema（走 response_format=json_schema，字段校验更严）
              或 json_mode（response_format=json_object，兼容性更好）
    """
    model = get_chat_model(
        role=role,
        temperature=temperature,
        enable_search=enable_search,
        enable_thinking=enable_thinking,
    )
    return model.with_structured_output(schema, method=method)


def chat(
    messages: Union[str, List[Dict[str, str]]],
    role: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    enable_search: Optional[bool] = None,
) -> str:
    """
    简单文本对话：返回模型输出文本。
    供非 ReAct 节点（审稿、写作思路、格式化等）直接调用。

    - messages 为字符串时自动作为 user 消息（可带 system_prompt）
    - messages 为列表时直接作为完整对话（[{role, content}, ...]）
    """
    if isinstance(messages, str):
        msgs: List[Dict[str, str]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": messages})
    else:
        msgs = list(messages)
        if system_prompt and not any(m.get("role") == "system" for m in msgs):
            msgs.insert(0, {"role": "system", "content": system_prompt})

    model = get_chat_model(role=role, temperature=temperature, enable_search=enable_search)
    resp = model.invoke(msgs)
    # resp.content 可能是 str（文本）或 list（多模态）；统一转成 str
    return resp.content if isinstance(resp.content, str) else str(resp.content)
