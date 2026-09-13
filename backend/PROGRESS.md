# 博客生成 Agent - 后端项目进度

> 最后更新：2026-09-13

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
| 数据库 | **PostgreSQL 16（Docker，生产）** / SQLite（本地直接运行可选） |
| 数据库驱动 | psycopg2-binary 2.9.10 |
| 数据验证 | Pydantic 2.13.5 |
| 配置管理 | pydantic-settings 2.15.0 |
| 大模型 | 阿里云百炼（OpenAI 兼容协议，千问系列） |
| Agent 框架 | LangGraph 1.2.11 |
| HTTP 客户端 | Requests 2.34.2 |
| 联网搜索 | 千问自带联网搜索（enable_search） |
| 配图 | Pexels API（搜索）/ 百炼通义万相（AI生成）+ **本地持久化** |
| 容器化 | Docker + Docker Compose（dev/prod 双模式 profiles） |
| 前端部署 | **开发：Vite dev server / 生产：Nginx 托管构建产物** |

---

## 三、项目结构

```
Blog_generate_agent/
├── .env                          # 根目录：POSTGRES_* 变量（compose 变量替换，gitignore 忽略）
├── .env.example                  # 根目录：PostgreSQL 配置模板
├── docker-compose.yml            # 编排：postgres + backend + frontend(dev) + frontend-prod(prod)
│
└── backend/
    ├── .env                      # 后端环境变量（密钥，gitignore 忽略）
    ├── .env.example              # 后端环境变量模板（21 项全覆盖，无真实密钥）
    ├── requirements.txt          # 依赖清单（含 psycopg2-binary）
    ├── PROGRESS.md               # 本文档
    ├── Dockerfile                # 后端镜像（apt/pip 阿里云换源）
    ├── data/images/              # 配图持久化目录（挂载 /app/data/images）
    │
    ├── config/
    │   └── settings.py           # 配置管理（含 image_save_dir）
    │
    ├── scripts/
    │   ├── init_db.py            # 建表脚本
    │   ├── check_db.py           # 数据库查看脚本
    │   └── migrate_sqlite_to_postgres.py   # SQLite→PostgreSQL 数据迁移脚本
    │
    └── src/blog_agent/
        ├── main.py               # FastAPI 入口（含 /images 静态文件挂载）
        │
        ├── db/                   # 数据库层
        │   ├── session.py        # 数据库会话（sqlite/postgres 双适配）
        │   ├── models.py         # 数据模型（BlogTask 表，25列，13状态）
        │   └── repositories/
        │       └── task_repo.py  # 任务 CRUD（含删除）
        │
        ├── clients/              # 客户端层
        │   └── llm_client.py     # LLM 客户端（支持联网搜索）
        │
        ├── schemas/              # Schema 层
        │   ├── task_schema.py    # 任务请求/响应格式
        │   └── blog_schema.py    # 博客内容格式（含审稿记录、配图URL）
        │
        ├── service/              # 业务层
        │   └── task_service.py   # 任务服务（含删除、三次调研保存）
        │
        ├── api/                  # 接口层
        │   ├── deps.py           # 依赖注入
        │   └── v1/
        │       └── blog.py       # 博客 API 路由（10个接口）
        │
        └── agent/                # Agent 层（核心）
            ├── state.py          # LangGraph 状态定义（含 content_research）
            ├── graph.py          # LangGraph 工作流编排（三阶段）
            └── agents/           # 7个 Agent 类
                ├── base_agent.py     # Agent 基类（支持 enable_search）
                ├── researcher.py     # 调研员（任务路由：标题/大纲/正文，都联网）
                ├── title_agent.py    # 标题策划
                ├── outliner.py       # 大纲师（支持配图标注）
                ├── writer.py         # 写手（支持调研结果+审稿意见修改）
                ├── reviewer.py       # 审稿（含配图质量审查，70分通过）
                ├── formatter.py      # 排版师（清理配图注释）
                └── image_agent.py    # 配图设计师（智能重试+本地持久化+失败改纯文本）

front/
├── Dockerfile                   # 生产镜像：多阶段构建（node build → nginx）
├── Dockerfile.dev               # 开发镜像：vite dev server（热更新）
├── nginx.conf                   # 生产配置：静态托管 + /api、/images 反代
└── ...
```

---

## 四、已完成功能

### ✅ 4.1 基础架构
- [x] 虚拟环境搭建（Python 3.12 + .venv）
- [x] 配置管理（pydantic-settings 读 .env）
- [x] 数据库层（SQLAlchemy + 连接池，sqlite/postgres 双适配）
- [x] 数据库建表（BlogTask 表，25列，13个状态枚举）
- [x] 依赖清单（requirements.txt）
- [x] Docker 容器化（Dockerfile + docker-compose）

### ✅ 4.2 大模型对接
- [x] LLM 客户端封装（OpenAI 兼容协议）
- [x] 阿里云百炼对接（已验证可用）
- [x] 各 Agent 可独立配置模型
- [x] 千问自带联网搜索支持（`enable_search=True`，已验证）

### ✅ 4.3 多 Agent 架构（LangGraph）
- [x] Agent 基类（统一角色设定、模型配置、联网开关）
- [x] 7个专业 Agent：
  - 调研员（**任务路由**：标题调研/大纲调研/正文调研三套提示词，只启动匹配任务）
  - 标题策划（生成3个标题，依据调研结果创作，不预设博客类型）
  - 大纲师（生成博客风格大纲，支持配图标注，严格依据调研结果+用户配置）
  - 写手（生成正文，严格依据大纲+调研结果+审稿意见修改）
  - 审稿（结构化审稿，含配图质量审查，70分通过，最多2轮）
  - 排版师（格式化文章，清理配图注释）
  - 配图设计师（智能搜索+重试+本地持久化+失败改纯文本）

### ✅ 4.4 工作流编排（LangGraph StateGraph）
- [x] 阶段1：标题调研（联网）→ 生成标题
- [x] 阶段2：大纲调研（联网）→ 生成大纲
- [x] 阶段3：正文调研（联网）→ 写正文 → 审稿循环（条件分支，最多2次）→ 配图（如需要）→ 格式化
- [x] 两个人工介入点（选标题+配图配置、确认大纲）

### ✅ 4.5 联网搜索与调研
- [x] 千问自带联网搜索（三次调研节点全部强制开启）
- [x] 调研员提示词强化：任务路由规则 + 明确任务目的 + 时效性把关 + 来源记录
- [x] 调研结果保存到数据库（title_research / outline_research / content_research）

### ✅ 4.6 配图功能（含持久化）
- [x] 大纲中标注配图位置（`<!-- 配图：描述 -->`）
- [x] Pexels API 搜索图片（已验证可用）
- [x] Unsplash API 搜索图片（备选）
- [x] 百炼通义万相 AI 生成图片（备选）
- [x] 智能重试：搜不到时 LLM 优化描述，最多重试2次
- [x] 失败降级：多次搜不到自动改成纯文本过渡句
- [x] 图片自动插入正文对应章节
- [x] 审稿时审查配图质量（不匹配则打回修改）
- [x] **图片本地持久化**：AI生图/API搜图生成后立即下载到 `backend/data/images/`，
      数据库存 `/images/xxx` 本地路径，后端 `/images` 静态服务 + 前端代理提供访问，
      彻底解决百炼 OSS 临时链接过期问题

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
- [x] 删除任务 `DELETE /api/v1/task/{id}`

### ✅ 4.8 实时进度
- [x] progress 字段实时更新
- [x] 前端可通过 `GET /task/{id}` 轮询获取进度（轮询时序已修复）
- [x] 13个状态枚举（含 researching_content）

### ✅ 4.9 前端（Vue 3 + Element Plus）
- [x] 6个页面：首页、创建任务、标题选择、大纲确认、生成中、文章详情
- [x] 实时进度展示（进度条+Agent时间线）
- [x] 大纲可编辑
- [x] 文章删除功能
- [x] 标题选择页两栏底部对齐（CSS 修复）
- [x] 调研过程 Markdown 渲染修复
- [x] 首页输入框样式（恢复原样，去除多余图标）

### ✅ 4.10 生产化改造（本轮重点）
- [x] **数据库切换 SQLite → PostgreSQL（Docker）**
  - postgres:16-alpine 容器 + healthcheck + `postgres_data` 持久化卷
  - 密码 `lisiyao`，连接串 `postgresql+psycopg2://blog:lisiyao@postgres:5432/blog_agent`
  - requirements.txt 增加 psycopg2-binary
  - **数据迁移**：5 条历史任务完整迁移（含枚举 name 兼容、布尔列转换、自增序列重置）
  - 旧 sqlite 卷已删除（确认无容器引用后 `docker volume rm`）
- [x] **配置变量化**：POSTGRES_USER/PASSWORD/DB/HOST/PORT 抽到根目录 `.env`
      （compose `${VAR}` 引用，密码不再进仓库），新增 `.env.example` 部署模板
- [x] **backend Dockerfile 换源**：apt/pip 全部指向阿里云镜像（服务器部署必需）
- [x] **前端 dev/prod 双模式**（docker compose profiles）
  - 开发：`frontend`（Dockerfile.dev + vite 热更新），本地 `docker compose up` 照旧
  - 生产：`frontend-prod`（多阶段构建 + nginx），服务器 `docker compose --profile prod up -d --build`
  - nginx.conf：静态托管 + Vue Router 回退 + `/api`、`/images` 反代 backend + 接口超时 600s
  - 端口可用 `${FRONTEND_PORT:-80}` 覆盖
- [x] **.env.example 补全**：21 项全覆盖模板（与 settings.py 核对无缺失无多余，无密钥泄漏）

---

## 五、待做事项

### 🔲 5.1 基础完善（优先级：高）
- [ ] 全局异常处理（统一错误响应格式）
- [ ] 接口参数校验完善
- [ ] 日志系统（logging 配置）
- [ ] 数据库迁移工具（Alembic，替代 create_all）
- [ ] 单元测试（pytest）

### 🔲 5.2 生产加固（优先级：高）
- [ ] **数据库自动备份**：cron + pg_dump，异地存储（防数据丢失）
- [ ] 后端生产启动（uvicorn 去掉 --reload，或 Gunicorn 多 worker）
- [ ] HTTPS（服务器上配置 TLS 证书）
- [ ] CORS 白名单（当前 allow_origins=["*"]）
- [ ] **Agent 评估集**：测试用例 + 期望输出，改 prompt 前跑回归

### 🔲 5.3 功能扩展（优先级：中）
- [ ] 向量数据库/RAG（知识库，参考已有文章）
- [ ] 一键发布到博客平台（WordPress/知乎/公众号等）
- [ ] 用户系统/多用户支持
- [ ] 文章历史版本管理
- [ ] 标题/正文的手动编辑功能（大纲已支持）
- [ ] 独立搜索引擎 API（百度/360，当前用千问自带联网）

### 🔲 5.4 性能优化（优先级：中）
- [ ] 异步任务（Celery + Redis，现在是同步阻塞，生成正文时接口会等待）
- [ ] 流式输出（SSE/WebSocket，替代轮询）
- [ ] 断点续跑（LangGraph checkpoint，服务重启后恢复任务）
- [ ] 大模型调用重试机制和超时处理
- [ ] LLM 成本治理（token 统计、限流、缓存）

### 🔲 5.5 部署进阶（优先级：低）
- [ ] CI/CD 流水线（push 自动构建部署）
- [ ] 可观测性（结构化日志、指标监控、告警）
- [ ] 数据库高可用（主从/连接池 PgBouncer）
- [ ] Kubernetes 迁移（多机集群）

---

## 六、环境变量说明

### 根目录 `.env`（docker-compose 变量替换）
```env
POSTGRES_USER=blog
POSTGRES_PASSWORD=lisiyao
POSTGRES_DB=blog_agent
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
```

### 后端 `backend/.env`（完整 21 项模板见 `.env.example`）
```env
# ========== LLM 基础配置 ==========
llm_base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
llm_api_key=你的百炼API_Key
llm_model=qwen-plus
llm_temperature=0.7
llm_enable_search=false

# ========== 各 Agent 模型配置（可选）==========
llm_model_researcher=qwen-flash    # 调研员：快、便宜
llm_model_outliner=qwen-flash      # 大纲师：平衡
llm_model_writer=qwen-plus         # 写手：质量
llm_model_reviewer=qwen-max        # 审稿：最强
llm_model_formatter=qwen-flash     # 排版师：简单

# ========== 审稿配置 ==========
enable_review=true
max_review_rounds=2

# ========== 配图配置 ==========
pexels_api_key=你的Pexels_API_Key
image_gen_model=qwen-image-3.0-pro
image_save_dir=/app/data/images    # 配图持久化目录（本地直接运行改 ./data/images）

# ========== Database ==========
# docker compose 会自动覆盖为 postgres；本地直接运行可保持 sqlite
db_url=sqlite:///./blog_agent.db

# ========== Agent ==========
agent_timeout=120
```

---

## 七、启动方式

### Docker 方式（推荐）

```bash
# 本地开发（dev 模式，vite 热更新）
docker compose up -d
# 前端：http://localhost:5173
# 后端API：http://localhost:8000
# 接口文档：http://localhost:8000/docs

# 服务器生产部署（nginx 托管构建产物）
docker compose --profile prod up -d --build
# 前端：http://服务器IP（80端口，可用 FRONTEND_PORT=8080 覆盖）

# 数据库迁移（已执行过，新服务器不需要；如需重迁先清空 postgres 表）
docker compose run --rm -v blog_generate_agent_backend_data:/app/data backend \
  python scripts/migrate_sqlite_to_postgres.py /app/data/blog_agent.db
```

### 本地直接运行方式（不使用 Docker）
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# 配置 .env（db_url 保持 sqlite 或改 postgres，image_save_dir 改 ./data/images）
python scripts/init_db.py
uvicorn src.blog_agent.main:app --reload
```

---

## 八、完整使用流程

1. **创建任务**：输入博客主题
2. **生成标题**：调研员联网调研同类文章标题 → 标题策划依据调研结果生成3个标题
3. **选择标题+配图配置**：选择标题，选择是否配图及配图方式（Pexels搜索/AI生成）
4. **生成大纲**：调研员联网调研同类大纲 → 大纲师依据调研结果+用户配置生成大纲（标注配图位置）
5. **确认/修改大纲**：可编辑大纲，确认后进入正文生成
6. **生成正文**：
   - 调研员联网调研最新资料（版本号、性能数据、最佳实践）
   - 写手基于大纲+调研结果生成正文
   - 审稿审查（含配图质量，不通过则打回修改，最多2轮）
   - 配图设计师配图（智能重试，图片持久化到本地，搜不到改纯文本）
   - 排版师格式化
7. **查看成品**：文章详情页，含配图、审稿记录

---

## 九、已知问题和注意事项

1. **生成正文接口同步阻塞**：生成正文可能需要2-5分钟，期间接口会一直等待，生产环境需要改成异步任务
2. **历史 AI 生图任务图片已失效**：2026-09-10 之前生成的 AI 配图用的是百炼 OSS 临时链接（约1天过期），
   修复持久化前的历史任务图片无法恢复，需重新生成任务才会走本地转存逻辑
3. **改模型后需要手动加字段**：SQLAlchemy create_all() 不会更新已存在的表，新增字段需手动 ALTER TABLE，后续用 Alembic 迁移
4. **联网搜索用千问自带能力**：搜索过程不透明，后续可考虑接独立搜索引擎 API
5. **postgres 密码改动注意**：`POSTGRES_*` 只在数据卷首次初始化时生效，改密码需 `ALTER USER` 或重建卷
6. **本地 80 端口可能被系统占用**（Windows http.sys），验证生产前端用 `FRONTEND_PORT=8080`

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
