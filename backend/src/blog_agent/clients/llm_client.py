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
        enable_search: Optional[bool] = None,
    ) -> str:
        """
        传入prompt，返回大模型输出文本
        支持指定模型、系统提示词、温度、联网搜索

        enable_search:
          - None: 使用全局配置 settings.llm_enable_search
          - True: 强制开启千问自带联网搜索
          - False: 强制关闭联网搜索
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 决定是否开启联网搜索
        use_search = enable_search if enable_search is not None else settings.llm_enable_search

        # 构建请求参数
        kwargs = {
            "model": model or settings.llm_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
        }

        # 千问/百炼 OpenAI 兼容模式下，通过 extra_body 开启联网搜索
        if use_search:
            kwargs["extra_body"] = {"enable_search": True}

        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content.strip()


# 全局单例，整个项目共用这一个客户端实例
llm_client = LlmClient()
