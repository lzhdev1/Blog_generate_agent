# 博客生成 Agent - 后端项目进度

> 最后更新：2026-09-09

## 一、项目概述

基于 FastAPI + SQLAlchemy + LangGraph + 阿里云百炼大模型的多 Agent 博客生成系统。

用户输入主题 → 多 Agent 协作（调研→标题→大纲→正文→审稿→配图→排版）→ 生成带配图的完整博客文章。

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
| 大模型 | 阿里云百炼（OpenAI 兼容协议，千问系列） |
| Agent 框架 | LangGraph 1.2.11 |
| HTTP 客户端 | Requests 2.34.2 |
| 联网搜索 | 千问自带联网搜索（enable_search） |
| 配图 | Pexels API（搜索）/ 百炼通义万相（AI生成） |
| 容器化 | Docker + Docker Compose |

---

## 三、项目结构

```
backend/
├── .env                          # 环境变量配置
├── requirements.txt              # 依赖清单
├── PROGRESS.md                   # 本文档
├── Dockerfile                    # Docker 镜像构建
├── .dockerignore
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
    │   ├── models.py             # 数据模型（BlogTask 表，21字段，13状态）
    │   └── repositories/
    │       └── task_repo.py      # 任务 CRUD（含删除）
    │
    ├── clients/                  # 客户端层
    │   └── llm_client.py         # LLM 客户端（支持联网搜索）
    │
    ├── schemas/                  # Schema 层
    │   ├── task_schema.py        # 任务请求/响应格式
    │   └── blog_schema.py        # 博客内容格式（含审稿记录、配图URL）
    │
    ├── service/                  # 业务层
    │   └── task_service.py       # 任务服务（含删除、三次调研保存）
    │
    ├── api/                      # 接口层
    │   ├── deps.py               # 依赖注入
    │   └── v1/
    │       └── blog.py           # 博客 API 路由（10个接口）
    │
    └── agent/                    # Agent 层（核心）
        ├── state.py              # LangGraph 状态定义（含 content_research）
        ├── graph.py              # LangGraph 工作流编排（三阶段）
        └── agents/               # 7个 Agent 类
            ├── base_agent.py     # Agent 基类（支持 enable_search）
            ├── researcher.py     # 研究员（三次调研：标题/大纲/正文，都联网）
            ├── title_agent.py    # 标题策划
            ├── outliner.py       # 大纲师（博客风格，支持配图标注）
            ├── writer.py         # 写手（支持调研结果+审稿意见修改）
            ├── reviewer.py       # 审稿（含配图质量审查，70分通过）
            ├── formatter.py      # 排版师（清理配图注释）
            └── image_agent.py    # 配图设计师（智能重试+失败改纯文本）
```

---

## 四、已完成功能

### ✅ 4.1 基础架构
- [x] 虚拟环境搭建（Python 3.12 + .venv）
- [x] 配置管理（pydantic-settings 读 .env）
- [x] 数据库层（SQLite + SQLAlchemy + 连接池）
- [x] 数据库建表（BlogTask 表，21个字段，13个状态枚举）
- [x] 依赖清单（requirements.txt）
- [x] Docker 容器化（Dockerfile + docker-compose）

### ✅ 4.2 大模型对接
- [x] LLM 客户端封装（OpenAI 兼容协议）
- [x] 阿里云百炼对接（已验证可用，千问3.7-plus）
- [x] 各 Agent 可独立配置模型
- [x] 千问自带联网搜索支持（`enable_search=True`，已验证）

### ✅ 4.3 多 Agent 架构（LangGraph）
- [x] Agent 基类（统一角色设定、模型配置、联网开关）
- [x] 7个专业 Agent：
  - 研究员（**三次调研**：标题调研 + 大纲调研 + 正文调研，全部联网）
  - 标题策划（生成3个标题）
  - 大纲师（生成博客风格大纲，支持配图标注）
  - 写手（生成正文，支持调研结果+审稿意见修改）
  - 审稿（结构化审稿，**含配图质量审查**，70分通过，最多2轮）
  - 排版师（格式化文章，清理配图注释）
  - 配图设计师（智能搜索+重试+失败改纯文本）

### ✅ 4.4 工作流编排（LangGraph StateGraph）
- [x] 阶段1：标题调研（联网）→ 生成标题
- [x] 阶段2：大纲调研（联网）→ 生成大纲
- [x] 阶段3：**正文调研（联网）** → 写正文 → 审稿循环（条件分支，最多2次）→ 配图（如需要）→ 格式化
- [x] 两个人工介入点（选标题+配图配置、确认大纲）

### ✅ 4.5 联网搜索
- [x] 千问自带联网搜索（三次调研节点全部强制开启）
- [x] 正文调研：检索最新版本号、性能数据、最佳实践、权威来源
- [x] 调研结果保存到数据库（title_research / outline_research / content_research）

### ✅ 4.6 配图功能（增强版）
- [x] 大纲中标注配图位置（`<!-- 配图：描述 -->`）
- [x] Pexels API 搜索图片（已验证可用）
- [x] Unsplash API 搜索图片（备选）
- [x] 百炼通义万相 AI 生成图片（备选）
- [x] **智能重试**：搜不到时 LLM 优化描述，最多重试2次
- [x] **失败降级**：多次搜不到自动改成纯文本过渡句
- [x] 图片自动插入正文对应章节
- [x] 审稿时审查配图质量（不匹配则打回修改）

### ✅ 4.7 API 接口（10个）
- [x] 创建任务 `POST /api/v1/task`
- [x] 生成标题 `POST /api/v1/task/{id}/generate-titles`
- [x] 提交标题配置 `POST /api/v1/task/{id}/submit-title-config`
- [x] 重新生成大纲 `POST /api/v1/task/{id}/regenerate-outline`
- [x] 确认大纲 `POST /api/v1/task/{id}/confirm-outline`
- [x] 生成正文 `POST /api/v1/task/{id}/generate-content`
- [x] 获取任务详情 `GET /api/v1/task/{id}`
- [x] 任务列表 `GET /api/v1/task`
- [x] 博客详情 `GET /api/v1/blog/{id}`（含审稿记录、配图URL）
- [x] **删除任务** `DELETE /api/v1/task/{id}`

### ✅ 4.8 实时进度
- [x] progress 字段实时更新
- [x] 前端可通过 `GET /task/{id}` 轮询获取进度
- [x] 13个状态枚举（含 researching_content）

### ✅ 4.9 前端（Vue 3 + Element Plus）
- [x] 6个页面：首页、创建任务、标题选择、大纲确认、生成中、文章详情
- [x] 紫色渐变主题 + 自定义 SVG 图标
- [x] 实时进度展示（进度条+Agent时间线）
- [x] 大纲可编辑
- [x] 文章删除功能
- [x] 审稿记录展示（只显示 feedback）
- [x] Docker 容器化开发

---

## 五、待做事项

### 🔲 5.1 基础完善（优先级：高）
- [ ] 全局异常处理（统一错误响应格式）
- [ ] 接口参数校验完善
- [ ] 日志系统（logging 配置）
- [ ] 数据库迁移工具（Alembic，替代删库重建）
- [ ] 单元测试（pytest）

### 🔲 5.2 功能扩展（优先级：中）
- [ ] 向量数据库/RAG（知识库，参考已有文章）
- [ ] 一键发布到博客平台（WordPress/知乎/公众号等）
- [ ] 图片下载到本地（现在用的是远程URL，可能过期）
- [ ] 用户系统/多用户支持
- [ ] 文章历史版本管理
- [ ] 标题/大纲/正文的手动编辑功能（大纲已支持，标题和正文待做）
- [ ] 独立搜索引擎 API（百度/360，当前用千问自带联网）

### 🔲 5.3 性能优化（优先级：中）
- [ ] 异步任务（Celery + Redis，现在是同步阻塞，生成正文时接口会等待）
- [ ] 流式输出（SSE/WebSocket，替代轮询）
- [ ] 断点续跑（LangGraph checkpoint，服务重启后恢复任务）
- [ ] 数据库从 SQLite 切换到 MySQL/PostgreSQL（生产环境）
- [ ] 大模型调用重试机制和超时处理

### 🔲 5.4 部署（优先级：低）
- [ ] 生产环境配置（Gunicorn + Nginx）
- [ ] CI/CD 流水线

---

## 六、环境变量说明

```env
# ========== LLM 基础配置 ==========
llm_base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
llm_api_key=你的百炼API_Key
llm_model=qwen3.7-plus-2026-05-26
llm_temperature=0.7
# 千问自带联网搜索（全局开关，researcher 节点会强制开启）
llm_enable_search=false

# ========== 各 Agent 模型配置（可选，不填则用默认 llm_model）==========
llm_model_researcher=qwen3.6-flash    # 研究员：快、便宜
llm_model_outliner=qwen3.7-flash       # 大纲师：平衡
llm_model_writer=qwen3.7-plus          # 写手：质量
llm_model_reviewer=qwen3.7-max         # 审稿：最强
llm_model_formatter=qwen3.6-flash      # 排版师：简单

# ========== 审稿配置 ==========
enable_review=true                     # 是否启用审稿循环
max_review_rounds=2                    # 最多审稿修改次数

# ========== 配图配置 ==========
# 方式A：图片网站API
pexels_api_key=你的Pexels_API_Key      # 推荐
# unsplash_access_key=你的Unsplash_Key  # 备选

# 方式B：AI生成图片（和LLM共用api_key）
image_gen_model=qwen-image-3.0

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

### Docker 方式（推荐）
```bash
# 在项目根目录启动前后端
docker compose up -d

# 前端：http://localhost:5173
# 后端API：http://localhost:8000
# 接口文档：http://localhost:8000/docs
```

### 本地开发方式
```bash
# 1. 创建虚拟环境
python -m venv .venv

# 2. 激活虚拟环境
.\.venv\Scripts\Activate.ps1  # PowerShell

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置 .env 文件

# 5. 初始化数据库
python scripts/init_db.py

# 6. 启动服务
uvicorn src.blog_agent.main:app --reload
```

---

## 八、完整使用流程

1. **创建任务**：输入博客主题
2. **生成标题**：研究员联网调研同类文章标题 → 标题策划生成3个标题
3. **选择标题+配图配置**：选择标题，选择是否配图及配图方式（Pexels搜索/AI生成）
4. **生成大纲**：研究员联网调研同类大纲 → 大纲师生成博客风格大纲（标注配图位置）
5. **确认/修改大纲**：可编辑大纲，确认后进入正文生成
6. **生成正文**：
   - 研究员联网调研最新资料（版本号、性能数据、最佳实践）
   - 写手基于大纲+调研结果生成正文
   - 审稿审查（含配图质量，不通过则打回修改，最多2轮）
   - 配图设计师配图（智能重试，搜不到改纯文本）
   - 排版师格式化
7. **查看成品**：文章详情页，含配图、审稿记录

---

## 九、已知问题和注意事项

1. **生成正文接口同步阻塞**：生成正文可能需要2-5分钟，期间接口会一直等待，生产环境需要改成异步任务
2. **SQLite 不支持高并发**：开发用没问题，生产环境建议切换 MySQL/PostgreSQL
3. **图片URL可能过期**：Pexels/Unsplash 的图片URL有有效期，建议下载到本地存储
4. **改模型后需要手动加字段**：SQLAlchemy create_all() 不会更新已存在的表，新增字段需手动 ALTER TABLE，后续用 Alembic 迁移
5. **联网搜索用千问自带能力**：搜索过程不透明，后续可考虑接独立搜索引擎 API（百度/360）

---

## 十、代码量统计

| 模块 | 文件数 | 代码行数 |
|------|--------|---------|
| Agent 层 | 10个 | ~950行 |
| 业务层 | 1个 | ~210行 |
| 接口层 | 3个 | ~190行 |
| 数据库层 | 3个 | ~110行 |
| Schema 层 | 2个 | ~100行 |
| 配置+客户端 | 2个 | ~80行 |
| **合计** | **21个核心文件** | **~1640行** |
