"""配图 Agent：确定性管线 + LLM 分析（接入任务流程的配图阶段）

流程（与旧版行为一致，图片 I/O 复用新版 image_client）：
1. 从正文提取配图标记 <!-- 配图：描述 --> + 前后文
2. LLM 逐个分析配图位置上下文 → 生成专业搜图关键词 / AI 生图 prompt
3. 并发获取图片 + 持久化到本地（image_client.fetch_all，文件名带 run_id 不复用旧图）
4. 把配图标记替换为图片 markdown
5. 配图失败的位置降级为纯文本过渡句
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

from src.blog_agent.agent.agents.image_prompts import (
    ANALYZE_IMAGE_NEEDS_AI,
    ANALYZE_IMAGE_NEEDS_API,
    FALLBACK_TRANSITION_TASK,
)
from src.blog_agent.clients.image_client import image_client
from src.blog_agent.clients.llm_client import chat

logger = logging.getLogger(__name__)

# 无效占位描述（模型照抄格式示例时产生），命中则跳过分析，避免浪费搜索/生图调用
INVALID_IMAGE_MARKERS = {
    "搜索关键词", "具体搜索关键词", "图片搜索关键词", "配图关键词",
    "画面描述", "配图描述", "图片描述", "配图位置和搜索关键词",
    "关键词", "描述", "search keywords", "image description",
}

# 配图标记正则：<!-- 配图：描述 -->
_MARKER_PATTERN = r'<!--\s*配图[：:]\s*(.+?)\s*-->'


def extract_markers_with_context(content: str, context_chars: int = 200) -> List[Dict]:
    """从正文中提取配图标记，并附带每个标记的上下文（前后各 context_chars 字）"""
    markers = []
    for i, match in enumerate(re.finditer(_MARKER_PATTERN, content)):
        description = match.group(1).strip()
        start, end = match.start(), match.end()
        context_before = content[max(0, start - context_chars):start].strip()
        context_after = content[end:min(len(content), end + context_chars)].strip()

        before_text = content[:start]
        title_matches = list(re.finditer(r'^#{1,4}\s+(.+)$', before_text, re.MULTILINE))
        position_title = title_matches[-1].group(1).strip() if title_matches else f"第{i+1}个配图位置"

        markers.append({
            "index": i,
            "description": description,
            "context_before": context_before,
            "context_after": context_after,
            "position_title": position_title,
            "start": start,
            "end": end,
        })
    return markers


def analyze_image_needs(markers_with_context: List[Dict], image_source: str) -> List[Dict]:
    """
    LLM 逐个分析每个配图位置的上下文，生成专业的搜图关键词 / AI 生图 prompt。
    image_source: "api"（搜图）或 "ai"（AI 生图）
    返回：[{"index", "query_or_prompt", "description_cn"}, ...]
    """
    if not markers_with_context:
        return []

    results = []
    for marker in markers_with_context:
        idx = marker["index"]
        description = marker["description"]
        stripped = (description or "").strip()
        # 无效占位描述直接跳过
        if not stripped or stripped in INVALID_IMAGE_MARKERS or len(stripped) < 3:
            logger.info("配图位置%d描述无效（占位词或过短），跳过分析: %r", idx + 1, stripped[:30])
            results.append({"index": idx, "query_or_prompt": "", "description_cn": ""})
            continue

        try:
            if image_source == "api":
                prompt = ANALYZE_IMAGE_NEEDS_API.format(
                    position_title=marker["position_title"],
                    context_before=marker["context_before"][:300],
                    context_after=marker["context_after"][:300],
                    description=description,
                )
                analysis = chat(prompt, role="image", temperature=0.3)
                query, desc_cn = "", ""
                for line in analysis.split("\n"):
                    line = line.strip()
                    if line.lower().startswith("关键词:") or line.lower().startswith("keyword:"):
                        query = line.split(":", 1)[1].strip()
                    elif line.startswith("描述:") or line.lower().startswith("description:"):
                        desc_cn = line.split(":", 1)[1].strip()
                if not query:  # 解析失败：整段作为关键词
                    query = analysis.strip()[:100]
                results.append({"index": idx, "query_or_prompt": query, "description_cn": desc_cn})
                logger.info("配图位置%d搜图关键词: %s", idx + 1, query)
            else:
                prompt = ANALYZE_IMAGE_NEEDS_AI.format(
                    position_title=marker["position_title"],
                    context_before=marker["context_before"][:300],
                    context_after=marker["context_after"][:300],
                    description=description,
                )
                analysis = chat(prompt, role="image", temperature=0.7)
                clean = _clean_image_prompt(analysis)
                results.append({"index": idx, "query_or_prompt": clean, "description_cn": description})
                logger.info("配图位置%d AI生图prompt生成完成（%d字符）", idx + 1, len(clean))
        except Exception as e:  # noqa: BLE001
            logger.warning("配图位置%d分析失败，回退原描述: %s", idx + 1, e)
            results.append({"index": idx, "query_or_prompt": description, "description_cn": description})
    return results


def _clean_image_prompt(raw: str) -> str:
    """清洗 AI 绘画提示词：去编号/标签前缀、列表符号，合并成单段英文"""
    if not raw:
        return raw
    parts = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        line = re.sub(r'^\d+[.、)）:：\s]+', '', line)          # 去编号前缀
        line = re.sub(r'^[-*•]\s*', '', line)                   # 去列表符号
        line = re.sub(
            r'^(主体|场景|风格|色调|构图|光线|画质|氛围|细节|subject|scene|style|color'
            r'|colour|composition|lighting|quality|atmosphere|detail)\s*[：:]\s*',
            '', line, flags=re.IGNORECASE
        )
        line = line.strip().strip('"\'`"')
        if line:
            parts.append(line)
    merged = " ".join(parts)
    return merged if merged else raw


def insert_images_by_markers(
    content: str,
    image_markers: List[Dict],
    image_urls: List[Optional[str]],
) -> Tuple[str, List[str]]:
    """把正文中的配图标记替换成图片 markdown；从后往前替换避免位置偏移"""
    result = content
    inserted_urls = []
    for i in range(len(image_markers) - 1, -1, -1):
        marker = image_markers[i]
        if i >= len(image_urls) or not image_urls[i]:
            result = result[:marker["start"]] + result[marker["end"]:]  # 失败删除标记
            continue
        replacement = f'![配图{i+1}]({image_urls[i]})'
        result = result[:marker["start"]] + replacement + result[marker["end"]:]
        inserted_urls.append(image_urls[i])
    inserted_urls.reverse()
    return result, inserted_urls


def replace_image_with_text(content: str, position: str, description: str) -> str:
    """配图失败时，在对应章节标题后插入 LLM 生成的纯文本过渡句代替图片"""
    try:
        transition = chat(
            FALLBACK_TRANSITION_TASK.format(position=position, description=description),
            role="image", temperature=0.5,
        ).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("生成过渡句失败: %s", e)
        transition = ""
    if not transition:
        return content

    escaped_position = re.escape(position)
    pattern = f'(^#{{1,4}}\\s+{escaped_position}\\s*$)'
    new_content = re.sub(pattern, f'\\1\n\n{transition}\n', content, count=1, flags=re.MULTILINE)
    if new_content == content:  # 找不到标题，在末尾追加
        new_content = content + f'\n\n{transition}\n'
    return new_content


def process_images(content: str, image_source: str, task_id: int = None) -> Tuple[str, List[str]]:
    """配图主入口：提取标记+上下文 → LLM 分析 → 并发获取+持久化 → 替换标记 → 失败降级"""
    markers = extract_markers_with_context(content)
    if not markers:
        logger.info("未找到配图标记，跳过配图")
        return content, []

    logger.info("找到 %d 个配图位置，开始分析...", len(markers))
    analyzed = analyze_image_needs(markers, image_source)
    analyzed_map = {a["index"]: a for a in analyzed}

    # 过滤出有有效关键词/prompt 的位置，交给 image_client 并发获取
    items, positions = [], []
    for marker in markers:
        query = (analyzed_map.get(marker["index"]) or {}).get("query_or_prompt", "")
        if query:
            items.append({"index": marker["index"], "query_or_prompt": query})
            positions.append(marker["index"])

    prefix = f"task{task_id}" if task_id is not None else "img"
    fetched = image_client.fetch_all(items, image_source, max_workers=4, prefix=prefix)

    # 还原为与 markers 等长的列表
    image_urls: List[Optional[str]] = [None] * len(markers)
    for pos_idx, url in zip(positions, fetched):
        image_urls[pos_idx] = url

    # 替换标记
    content_with_images, inserted_urls = insert_images_by_markers(content, markers, image_urls)

    # 失败降级：改为纯文本过渡句
    failed_markers = [markers[i] for i in range(len(markers)) if not image_urls[i]]
    if failed_markers:
        logger.info("有%d处配图未找到，正在调整为文字描述...", len(failed_markers))
        for marker in failed_markers:
            desc_cn = (analyzed_map.get(marker["index"]) or {}).get("description_cn", marker["description"])
            content_with_images = replace_image_with_text(
                content_with_images, marker["position_title"], desc_cn
            )

    success_urls = [u for u in inserted_urls if u]
    logger.info("配图完成：成功%d张，失败%d处", len(success_urls), len(failed_markers))
    return content_with_images, success_urls
