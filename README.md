# 博客生成 Agent

基于多 Agent 架构的智能博客生成系统。用户输入主题，系统通过多个专业 Agent 协作，自动生成带配图的完整博客文章。

## ✨ 特性

- 🤖 **多 Agent 协作**：研究员、标题策划、大纲师、写手、审稿、排版师、配图设计师，7个专业 Agent 各司其职
- 🔄 **审稿循环**：自动审稿，不通过则返回修改，最多循环3次
- 🖼️ **智能配图**：支持图片网站API搜索（Pexels/Unsplash）和 AI 生成图片（百炼通义万相）
- 📊 **实时进度**：每个节点执行状态实时更新，前端可轮询展示
- 👤 **人工介入**：标题选择、大纲确认两个人工介入点，用户可控
- 🧠 **LangGraph 编排**：基于 LangGraph StateGraph，支持条件分支和循环
- 🔌 **OpenAI 兼容**：对接阿里云百炼，也可切换其他 OpenAI 兼容大模型

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI 0.141 |
| 数据库 | SQLite（开发）/ MySQL/PostgreSQL（生产） |
| ORM | SQLAlchemy 2.0 |
| Agent 框架 | LangGraph 1.2 |
| 大模型 | 阿里云百炼（OpenAI 兼容协议） |
| 配图 | Pexels API / 百炼通义万相 |

## 📁 项目结构

```
Blog_generate_agent/
├── backend/                    # 后端
│   ├── .env                    # 环境变量（需自行配置）
│   ├── requirements.txt        # Python 依赖
│   ├── PROGRESS.md             # 项目进度文档
│   ├── config/
│   │   └── settings.py         # 配置管理
│   ├── scripts/
│   │   ├── init_db.py          # 建表脚本
│   │   └── check_db.py         # 数据库查看
│   └── src/blog_agent/
│       ├── main.py             # FastAPI 入口
│       ├── db/                 # 数据库层
│       ├── clients/            # 客户端层（LLM）
│       ├── schemas/            # Schema 层
│       ├── service/            # 业务层
│       ├── api/                # 接口层
│       └── agent/              # Agent 层（核心）
│           ├── state.py        # LangGraph 状态
│           ├── graph.py        # LangGraph 工作流
│           └── agents/         # 7个 Agent 类
├── front/                      # 前端（待开发）
├── .gitignore
└── README.md
```

## 🚀 快速开始

### 1. 环境要求

- Python 3.12+
- 阿里云百炼 API Key
- （可选）Pexels API Key（配图搜索用）

### 2. 后端启动

```bash
# 进入后端目录
cd backend

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat
# macOS/Linux:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 初始化数据库
python scripts/init_db.py

# 启动服务
uvicorn src.blog_agent.main:app --reload
```

### 3. 访问接口文档

打开浏览器访问：`http://127.0.0.1:8000/docs`

## 🤖 多 Agent 架构

```
用户输入主题
    ↓
┌─────────────────────────────────────────┐
│  阶段1：标题生成                          │
│  研究员（标题调研）→ 标题策划（3个标题）  │
└─────────────────────────────────────────┘
    ↓
👤 人工介入点1：选择标题 + 配图配置
    ↓
┌─────────────────────────────────────────┐
│  阶段2：大纲生成                          │
│  研究员（大纲调研）→ 大纲师（生成大纲）   │
│  （如需配图，大纲中标注配图位置）          │
└─────────────────────────────────────────┘
    ↓
👤 人工介入点2：确认大纲
    ↓
┌─────────────────────────────────────────┐
│  阶段3：正文生成                          │
│  写手（写正文）                           │
│    ↓                                     │
│  审稿（审稿）                             │
│    ↓ 不通过（最多3次循环）                │
│  写手（根据意见修改）                      │
│    ↓ 通过/达到上限                        │
│  配图设计师（搜索/生成图片，插入正文）     │
│    ↓                                     │
│  排版师（格式化）                         │
└─────────────────────────────────────────┘
    ↓
✅ 成品文章
```

### Agent 角色说明

| Agent | 角色 | 职责 | 建议模型 |
|-------|------|------|---------|
| Researcher | 研究员 | 标题调研、大纲调研，分析同类文章 | qwen-turbo |
| TitleAgent | 标题策划 | 生成3个吸引人的标题 | qwen-plus |
| Outliner | 大纲师 | 生成文章大纲，标注配图位置 | qwen-plus |
| Writer | 写手 | 撰写正文，根据审稿意见修改 | qwen-plus |
| Reviewer | 审稿 | 结构化审稿，给出修改意见 | qwen-max |
| Formatter | 排版师 | 格式化 Markdown，统一格式 | qwen-turbo |
| ImageAgent | 配图设计师 | 搜索/生成图片，插入正文 | qwen-turbo |

## 🔌 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/task` | 创建任务 |
| POST | `/api/v1/task/{id}/generate-titles` | 生成标题（自动调研） |
| POST | `/api/v1/task/{id}/submit-title-config` | 提交标题+配图配置（自动生成大纲） |
| POST | `/api/v1/task/{id}/regenerate-outline` | 重新生成大纲 |
| POST | `/api/v1/task/{id}/confirm-outline` | 确认大纲 |
| POST | `/api/v1/task/{id}/generate-content` | 生成正文（审稿+配图+格式化） |
| GET | `/api/v1/task/{id}` | 获取任务详情（含进度） |
| GET | `/api/v1/task` | 任务列表 |
| GET | `/api/v1/blog/{id}` | 博客详情（成品文章） |

## ⚙️ 环境变量

```env
# LLM 基础配置
llm_base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
llm_api_key=你的百炼API_Key
llm_model=qwen-plus

# 各 Agent 模型配置（可选，不填则用默认）
llm_model_researcher=qwen-turbo
llm_model_outliner=qwen-plus
llm_model_writer=qwen-plus
llm_model_reviewer=qwen-max
llm_model_formatter=qwen-turbo

# 审稿配置
max_review_rounds=3

# 配图配置
pexels_api_key=你的Pexels_API_Key     # 图片搜索（推荐）
# unsplash_access_key=你的Unsplash_Key # 备选
image_gen_model=wanx2.1-t2i-turbo     # AI生成图片模型

# 数据库
db_url=sqlite:///./blog_agent.db
```

详细说明见 `backend/PROGRESS.md`。

## 📋 使用流程

1. **创建任务**：传入博客主题
2. **生成标题**：系统自动调研，生成3个标题
3. **选择标题+配图配置**：选择一个标题，配置是否需要配图及配图方式
4. **确认大纲**：系统自动调研并生成大纲，可重新生成
5. **生成正文**：系统自动写正文、审稿、配图、格式化
6. **查看成品**：获取完整的带配图博客文章

## 📝 待做事项

### 高优先级
- [ ] 前端页面开发
- [ ] 异步任务（Celery + Redis）
- [ ] 全局异常处理
- [ ] 数据库迁移工具（Alembic）

### 中优先级
- [ ] 联网搜索（提升调研质量）
- [ ] 向量数据库/RAG（知识库）
- [ ] 流式输出（SSE/WebSocket）
- [ ] 图片下载到本地
- [ ] 一键发布到博客平台

### 低优先级
- [ ] Docker 容器化
- [ ] 用户系统/多用户
- [ ] CI/CD 流水线

详细待办清单见 `backend/PROGRESS.md`。

## 📄 许可证

MIT License
