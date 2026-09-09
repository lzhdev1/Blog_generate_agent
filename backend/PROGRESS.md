# 博客生成 Agent - 后端项目进度

> 最后更新：2026-09-09

## 一、项目概述

基于 FastAPI + SQLAlchemy + LangGraph + 阿里云百炼大模型的多 Agent 博客生成系统。

用户输入主题 → 多 Agent 协作 → 生成带配图的完整博客文章。

---

## 二、技术栈

| 层级 | 技术 |
|------|------|
| Web 框架 | FastAPI 0.141.1 |
| ASGI 服务器 | Uvicorn 0.52.4 |
| ORM | SQLAlchemy 2.0.52 |
| 数据库 | SQLite（开发）/ 可切换 MySQL/PostgreSQL |
| 数据验证 | Pydantic 2.13.5 |
| 配置管理 | pydantic-settings 2.15.0 |
| 大模型 | 阿里云百炼（OpenAI 兼容协议） |
| Agent 框架 | LangGraph 1.2.11 |
| HTTP 客户端 | Requests 2.34.2 |
| 配图 | Pexels API（搜索）/ 百炼通义万相（AI生成） |

---

## 三、项目结构

```
backend/
├── .env                          # 环境变量配置
├── requirements.txt              # 依赖清单
├── PROGRESS.md                   # 本文档
├── blog_agent.db                 # SQLite 数据库
│
├── config/
│   └── settings.py               # 配置管理
│
├── scripts/
│   ├── init_db.py                # 建表脚本
│   └── check_db.py               # 数据库查看脚本
│
└── src/blog_agent/
    ├── main.py                   # FastAPI 入口
    │
    ├── db/                       # 数据库层
    │   ├── session.py            # 数据库会话（连接池）
    │   ├── models.py             # 数据模型（BlogTask 表）
    │   └── repositories/
    │       └── task_repo.py      # 任务 CRUD
    │
    ├── clients/                  # 客户端层
    │   └── llm_client.py         # LLM 客户端
    │
    ├── schemas/                  # Schema 层
    │   ├── task_schema.py        # 任务请求/响应格式
    │   └── blog_schema.py        # 博客内容格式
    │
    ├── service/                  # 业务层
    │   └── task_service.py       # 任务服务
    │
    ├── api/                      # 接口层
    │   ├── deps.py               # 依赖注入
    │   └── v1/
    │       └── blog.py           # 博客 API 路由
    │
    └── agent/                    # Agent 层（核心）
        ├── state.py              # LangGraph 状态定义
        ├── graph.py              # LangGraph 工作流编排
        └── agents/               # 7个 Agent 类
            ├── base_agent.py     # Agent 基类
            ├── researcher.py     # 研究员
            ├── title_agent.py    # 标题策划
            ├── outliner.py       # 大纲师
            ├── writer.py         # 写手
            ├── reviewer.py       # 审稿
            ├── formatter.py      # 排版师
            └── image_agent.py    # 配图设计师
```

---

## 四、已完成功能

### ✅ 4.1 基础架构
- [x] 虚拟环境搭建（Python 3.12 + .venv）
- [x] 配置管理（pydantic-settings 读 .env）
- [x] 数据库层（SQLite + SQLAlchemy + 连接池）
- [x] 数据库建表（BlogTask 表，20个字段，12个状态枚举）
- [x] 依赖清单（requirements.txt）

### ✅ 4.2 大模型对接
- [x] LLM 客户端封装（OpenAI 兼容协议）
- [x] 阿里云百炼对接（已验证可用）
- [x] 各 Agent 可独立配置模型

### ✅ 4.3 多 Agent 架构（LangGraph）
- [x] Agent 基类（统一角色设定、模型配置）
- [x] 7个专业 Agent：
  - 研究员（标题调研 + 大纲调研）
  - 标题策划（生成3个标题）
  - 大纲师（生成大纲，支持配图标注）
  - 写手（生成正文，支持审稿意见修改）
  - 审稿（结构化审稿，通过/不通过）
  - 排版师（格式化文章）
  - 配图设计师（搜索/生成图片，插入正文）

### ✅ 4.4 工作流编排（LangGraph StateGraph）
- [x] 阶段1：标题调研 → 生成标题
- [x] 阶段2：大纲调研 → 生成大纲
- [x] 阶段3：写正文 → 审稿循环（条件分支，最多3次）→ 配图（如需要）→ 格式化
- [x] 两个人工介入点（选标题+配图配置、确认大纲）

### ✅ 4.5 配图功能
- [x] 大纲中标注配图位置（`<!-- 配图：描述 -->`）
- [x] Pexels API 搜索图片（已验证可用）
- [x] Unsplash API 搜索图片（预留）
- [x] 百炼通义万相 AI 生成图片（预留）
- [x] 图片自动插入正文对应章节

### ✅ 4.6 API 接口（9个）
- [x] 创建任务 `POST /api/v1/task`
- [x] 生成标题 `POST /api/v1/task/{id}/generate-titles`
- [x] 提交标题配置 `POST /api/v1/task/{id}/submit-title-config`
- [x] 重新生成大纲 `POST /api/v1/task/{id}/regenerate-outline`
- [x] 确认大纲 `POST /api/v1/task/{id}/confirm-outline`
- [x] 生成正文 `POST /api/v1/task/{id}/generate-content`
- [x] 获取任务详情 `GET /api/v1/task/{id}`
- [x] 任务列表 `GET /api/v1/task`
- [x] 博客详情 `GET /api/v1/blog/{id}`

### ✅ 4.7 实时进度
- [x] progress 字段实时更新
- [x] 前端可通过 `GET /task/{id}` 轮询获取进度

---

## 五、待做事项

### 🔲 5.1 基础完善（优先级：高）
- [ ] 全局异常处理（统一错误响应格式）
- [ ] 接口参数校验完善
- [ ] 日志系统（logging 配置）
- [ ] 数据库迁移工具（Alembic，替代删库重建）
- [ ] 单元测试（pytest）

### 🔲 5.2 功能扩展（优先级：中）
- [ ] 联网搜索（现在调研是纯 LLM 分析，没有真正联网搜索）
- [ ] 向量数据库/RAG（知识库，参考已有文章）
- [ ] 一键发布到博客平台（WordPress/知乎/公众号等）
- [ ] 图片下载到本地（现在用的是远程URL，可能过期）
- [ ] 用户系统/多用户支持
- [ ] 文章历史版本管理
- [ ] 标题/大纲/正文的手动编辑功能

### 🔲 5.3 性能优化（优先级：中）
- [ ] 异步任务（Celery + Redis，现在是同步阻塞，生成正文时接口会超时）
- [ ] 流式输出（SSE/WebSocket，替代轮询）
- [ ] 断点续跑（LangGraph checkpoint，服务重启后恢复任务）
- [ ] 数据库从 SQLite 切换到 MySQL/PostgreSQL（生产环境）
- [ ] 大模型调用重试机制和超时处理

### 🔲 5.4 前端（优先级：高）
- [ ] 前端页面开发（任务创建、标题选择、大纲确认、文章展示）
- [ ] 实时进度展示
- [ ] 文章预览和编辑
- [ ] 配图预览和替换

### 🔲 5.5 部署（优先级：低）
- [ ] Docker 容器化
- [ ] 生产环境配置（Gunicorn + Nginx）
- [ ] CI/CD 流水线

---

## 六、环境变量说明

```env
# ========== LLM 基础配置 ==========
llm_base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
llm_api_key=你的百炼API_Key
llm_model=qwen-plus
llm_temperature=0.7

# ========== 各 Agent 模型配置（可选，不填则用默认 llm_model）==========
llm_model_researcher=qwen-turbo      # 研究员：快、便宜
llm_model_outliner=qwen-plus         # 大纲师：平衡
llm_model_writer=qwen-plus           # 写手：质量
llm_model_reviewer=qwen-max          # 审稿：最强
llm_model_formatter=qwen-turbo       # 排版师：简单

# ========== 审稿配置 ==========
max_review_rounds=3

# ========== 配图配置 ==========
# 方式A：图片网站API
pexels_api_key=你的Pexels_API_Key     # 推荐
# unsplash_access_key=你的Unsplash_Key # 备选

# 方式B：AI生成图片（和LLM共用api_key）
image_gen_model=wanx2.1-t2i-turbo

# ========== Database ==========
db_url=sqlite:///./blog_agent.db

# ========== Celery Redis（暂未使用，预留）==========
redis_broker_url=redis://127.0.0.1:6379/0
redis_result_backend=redis://127.0.0.1:6379/0

# ========== Agent ==========
agent_timeout=120
```

---

## 七、启动方式

```bash
# 1. 创建虚拟环境
python -m venv .venv

# 2. 激活虚拟环境
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置 .env 文件（复制 .env.example 或直接修改）

# 5. 初始化数据库
python scripts/init_db.py

# 6. 启动服务
uvicorn src.blog_agent.main:app --reload

# 7. 访问接口文档
# http://127.0.0.1:8000/docs
```

---

## 八、完整使用流程

1. **创建任务**：`POST /api/v1/task`，传入主题
2. **生成标题**：`POST /api/v1/task/{id}/generate-titles`
   - 研究员自动调研 → 标题策划生成3个标题
3. **提交标题配置**：`POST /api/v1/task/{id}/submit-title-config`
   - 传入选择的标题、是否需要配图、配图方式
   - 研究员自动调研 → 大纲师生成大纲（标注配图位置）
4. **确认大纲**：`POST /api/v1/task/{id}/confirm-outline`
   - 可重新生成大纲
5. **生成正文**：`POST /api/v1/task/{id}/generate-content`
   - 写手写正文 → 审稿审稿（不通过则循环修改，最多3次）→ 配图设计师配图 → 排版师格式化
6. **查看成品**：`GET /api/v1/blog/{id}`

---

## 九、已知问题和注意事项

1. **生成正文接口同步阻塞**：生成正文可能需要1-3分钟，期间接口会一直等待，生产环境需要改成异步任务
2. **SQLite 不支持高并发**：开发用没问题，生产环境建议切换 MySQL/PostgreSQL
3. **图片URL可能过期**：Pexels/Unsplash 的图片URL有有效期，建议下载到本地存储
4. **调研节点没有真正联网**：现在是纯 LLM 分析，后续可以加联网搜索提升质量
5. **改模型后需要删库重建**：SQLAlchemy create_all() 不会更新已存在的表，后续用 Alembic 迁移

---

## 十、代码量统计

| 模块 | 文件数 | 代码行数 |
|------|--------|---------|
| Agent 层 | 10个 | ~750行 |
| 业务层 | 1个 | ~185行 |
| 接口层 | 3个 | ~170行 |
| 数据库层 | 3个 | ~100行 |
| Schema 层 | 2个 | ~90行 |
| 配置+客户端 | 2个 | ~60行 |
| **合计** | **21个核心文件** | **~1350行** |
