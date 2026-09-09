from typing import TypedDict, List, Optional, Dict


class AgentState(TypedDict):
    """
    LangGraph 工作流状态：在各个 Agent 节点之间传递的数据
    每个节点读取需要的字段，处理后更新字段，返回给下一个节点
    """
    # 任务ID（用于更新数据库）
    task_id: int

    # 用户输入
    topic: str

    # 调研结果
    title_research: str
    outline_research: str

    # 节点1：标题
    titles: List[str]
    selected_title: str

    # 配图配置
    need_image: bool
    image_source: str

    # 节点2：大纲
    outline: str
    outline_confirmed: bool

    # 节点3：正文
    content: str

    # 审稿
    review_result: Dict
    review_count: int          # 审稿次数，控制循环上限
    review_feedback: str

    # 格式化
    formatted_content: str

    # 当前进度
    progress: str

    # 错误信息
    error: Optional[str]
