from typing import Optional

from openai import OpenAI

from config.settings import settings


class LlmClient:
    def __init__(self):
        self.client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key
        )

    def chat_completion(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        传入prompt，返回大模型输出文本
        支持指定模型、系统提示词、温度
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = self.client.chat.completions.create(
            model=model or settings.llm_model,
            messages=messages,
            temperature=temperature if temperature is not None else settings.llm_temperature
        )
        return resp.choices[0].message.content.strip()


# 全局单例，整个项目共用这一个客户端实例
llm_client = LlmClient()
