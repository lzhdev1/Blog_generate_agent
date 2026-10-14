# backend_L — BlogAgent 重构版后端（全量 LangGraph 化）

> 并行重构版（Strangler Fig 模式）：旧 `backend/` 保持线上稳定不动，本目录在旁并行开发，验证通过后接管。

## 与旧 backend 的关系

| 项 | 旧 backend | backend_L（本目录） |
|---|---|---|
| 状态 | 线上稳定，保持不动 | 并行重构，逐步替换 Agent 层 |
| API | `/api/v1/*` | **完全兼容同一套路由**（前端零改动） |
| 数据库 | 同一 Postgres | **共用同一 Postgres**（用户/文章/任务/订单数据） |
| Agent 层 | Python 类 + 提示词（单次 LLM 调用） | **全部 LangGraph 子图（ReAct 循环 + 工具调用）** |
| 端口 | 8000 | 8001（本地验证用） |

## 目标架构（全部 Agent 用 LangGraph）

- 主图 `supervisor_graph`：主 Agent 质量门（硬规则 + LLM 评审）+ 路由 + 打回重跑（上限 3 次）
- 三个子图：`title_graph` / `outline_graph` / `content_graph`，统一 ReAct 模板
  `plan → model ⇄ tools（循环≤3轮）→ output（Pydantic 校验）`
- 共享 State：`agent/state.py`（全流程贯通）
- 工具集：`agent/tools/`（search_tool / image_tool / format_tool）
- Checkpointer：PostgresSaver（断点恢复 / 快照）

## 目录结构

```
backend_L/
├── config/            # settings（环境变量）、logging 配置
├── scripts/           # init_db 等脚本
├── tasks/             # 异步任务（如沿用）
├── tests/             # 单元 / 集成测试
└── src/blog_agent/
    ├── main.py        # FastAPI 入口
    ├── api/v1/        # 路由（auth / blog / articles / notifications / webhook）
    ├── agent/
    │   ├── state.py           # 共享 AgentState（TypedDict）
    │   ├── tools/             # search_tool / image_tool / format_tool
    │   ├── graphs/            # supervisor_graph / title_graph / outline_graph / content_graph
    │   ├── nodes/             # react_model / react_tools / output_node / quality_gate
    │   └── agents/            # 各角色 prompt 提供者（researcher / title / outliner / writer / reviewer / image）
    ├── clients/        # llm_client（需支持 tools/tool_calls）、image_client、vector_client
    ├── db/             # session / models / repositories
    ├── exceptions/     # 统一异常
    ├── schemas/        # Pydantic 请求/响应模型
    ├── service/        # auth / blog / publish / task 服务
    └── utils/          # 文件 / markdown / 时间工具
```

## 当前状态

- [ ] 阶段 0：复制骨架、双后端可同时启动（API 全通）
- [ ] 阶段 1：基础设施（llm_client tools 支持 / 共享 State / PostgresSaver / output_node）
- [ ] 阶段 2：search_tool + 调研员 ReAct 化（最小闭环）
- [ ] 阶段 3：标题/大纲/正文子图 + 配图/排版工具化
- [ ] 阶段 4：supervisor_graph 质量门 + 打回 + 断点恢复
- [ ] 阶段 5：切换上线（nginx 切 /api → backend_L，旧 backend 退役）

> 注：所有实现代码由本人按阶段编写，详见 PROGRESS.md。
