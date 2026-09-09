from typing import Optional

from src.blog_agent.clients.llm_client import llm_client
from config.settings import settings


class BaseAgent:
    """Agent 基类：所有 Agent 都继承这个类"""

    # 子类需要定义
    name: str = "base"
    role: str = ""
    system_prompt: str = ""
    model_config_key: str = ""  # 对应 settings 里的模型配置字段名

    def get_model(self) -> str:
        """获取该 Agent 使用的模型，优先用专属配置，没有则用默认模型"""
        model = getattr(settings, self.model_config_key, None)
        return model or settings.llm_model

    def chat(self, prompt: str, temperature: Optional[float] = None) -> str:
        """调用大模型，自动带上该 Agent 的角色设定和模型"""
        return llm_client.chat_completion(
            prompt=prompt,
            model=self.get_model(),
            system_prompt=self.system_prompt,
            temperature=temperature,
        )
