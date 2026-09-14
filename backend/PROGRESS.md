# 博客生成 Agent - 后端项目进度

> 最后更新：2026-09-14

## 一、项目概述

基于 FastAPI + SQLAlchemy + LangGraph + 阿里云百炼大模型的多 Agent 博客生成系统。

用户输入主题 → 多 Agent 协作（调研→标题→大纲→正文→审稿→配图→格式化）→ 生成带配图的完整博客文章。

---

## 二、技术栈

| 层级 | 技术 |
|------|------|
| Web 框架 | FastAPI 0.141.1 |
| ASGI 服务器 | Uvicorn 0.52.4 |
| ORM | SQLAlchemy 2.0.52 |
| 数据库 | **PostgreSQL 16（Docker 容器）** |
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
    ├── .env.example              # 后端环境变量模板（20项全覆盖，无真实密钥）
    ├── requirements.txt          # 依赖清单（含 psycopg2-binary）
    ├── PROGRESS.md               # 本文档
    ├── Dockerfile                # 后端镜像（apt/pip 阿里云换源）
    ├── data/images/              # 配图持久化目录（挂载 /app/data/images）
    │
    ├── config/
    │   └── settings.py           # 配置管理（含 image_save_dir）
    │
    ├── scripts/
    │   └── init_db.py            # 建表脚本
    │
    └── src/blog_agent/
        ├── main.py               # FastAPI 入口（含 /images 静态文件挂载）
        │
        ├── db/                   # 数据库层
        │   ├── session.py        # 数据库会话（PostgreSQL 连接池配置）
        │   ├── models.py         # 数据模型（BlogTask 表，27列，16状态）
        │   └── repositories/
        │       └── task_repo.py  # 任务 CRUD（含删除）
        │
        ├── clients/              # 客户端层
        │   └── llm_client.py     # LLM 客户端（支持联网搜索，max_tokens/timeout）
        │
        ├── schemas/              # Schema 层
        │   ├── task_schema.py    # 任务请求/响应格式（含文章风格、配图配置）
        │   └── blog_schema.py    # 博客内容格式（含审稿记录、配图URL、写作思路）
        │
        ├── service/              # 业务层
        │   └── task_service.py   # 任务服务（含删除、三次调研保存、配置保存）
        │
        ├── api/                  # 接口层
        │   ├── deps.py           # 依赖注入
        │   └── v1/
        │       └── blog.py       # 博客 API 路由（10个接口）
        │
        └── agent/                # Agent 层（核心）
            ├── state.py          # LangGraph 状态定义（含 content_research、review_result）
            ├── graph.py          # LangGraph 工作流编排（三阶段+审稿循环+调研重跑）
            └── agents/           # 6个 Agent 类 + 1个纯规则格式化函数
                ├── base_agent.py     # Agent 基类（支持 enable_search）
                ├── researcher.py     # 调研员（任务路由：标题/大纲/正文，都联网，补充/重新调研模式）
                ├── title_agent.py    # 标题策划（依据调研结果创作，不预设博客类型）
                ├── outliner.py       # 大纲师（严格遵守标题/配图/风格，配图注释统一格式）
                ├── writer.py         # 写手（5条硬约束，严格依据大纲+调研+审稿意见）
                ├── reviewer.py       # 审稿（硬性约束3条+5维度审核，综合90分通过，打回最多3次）
                ├── image_agent.py    # 配图设计师（批量分析配图位置，专业英文关键词/prompt，本地持久化）
                └── formatter.py      # 纯规则格式化函数（非Agent，不调用LLM）

front/
├── Dockerfile                   # 生产镜像：多阶段构建（node build → nginx）
├── Dockerfile.dev               # 开发镜像：vite dev server（热更新）
├── nginx.conf                   # 生产配置：静态托管 + /api、/images 反代
└── src/
    ├── views/
    │   ├── HomeView.vue         # 首页（输入主题）
    │   ├── TitlesView.vue       # 标题选择页（文章风格配置、是否配图）
    │   ├── OutlineView.vue      # 大纲确认页（配图方式、字数、水平、额外要求）
    │   ├── GeneratingView.vue   # 生成中（实时进度）
    │   └── BlogDetailView.vue   # 文章详情（三栏布局：配置/正文/调研+审稿）
    └── components/
        └── MarkdownRender.vue   # Markdown渲染（含KaTeX公式）
```

---

## 四、已完成功能

### ✅ 4.1 基础架构
- [x] 虚拟环境搭建（Python 3.12 + .venv）
- [x] 配置管理（pydantic-settings 读 .env）
- [x] 数据库层（SQLAlchemy + PostgreSQL 连接池配置）
- [x] 数据库建表（BlogTask 表，27列，16个状态枚举）
- [x] 依赖清单（requirements.txt）
- [x] Docker 容器化（Dockerfile + docker-compose）

### ✅ 4.2 大模型对接
- [x] LLM 客户端封装（OpenAI 兼容协议，max_tokens/timeout）
- [x] 阿里云百炼对接（已验证可用）
- [x] 各 Agent 可独立配置模型
- [x] 千问自带联网搜索支持（`enable_search=True`，已验证）

### ✅ 4.3 多 Agent 架构（LangGraph）
- [x] Agent 基类（统一角色设定、模型配置、联网开关）
- [x] **6个专业 Agent + 1个纯规则格式化函数**：
  - 调研员（**任务路由**：标题调研/大纲调研/正文调研三套提示词，只启动匹配任务；**补充/重新调研模式**）
  - 标题策划（生成3个标题，依据调研结果创作，不预设博客类型）
  - 大纲师（生成博客风格大纲，严格遵守标题/配图/风格配置，配图注释统一 `<!-- 配图：描述 -->`）
  - 写手（5条硬约束：禁改标题/严格守大纲/严格结合调研/严格守配置/认真对待审稿意见）
  - 审稿（硬性约束3条+5维度审核，综合90分通过，打回最多3次，流量预测）
  - 配图设计师（批量分析配图位置上下文，专业英文搜图关键词/AI生图prompt，本地持久化）
  - 格式化（**纯规则函数，非Agent，不调用LLM**：统一标题/列表/空行/代码块格式）

### ✅ 4.4 工作流编排（LangGraph StateGraph）
- [x] 阶段1：标题调研（联网）→ 生成标题 → 标题评分
- [x] 阶段2：大纲调研（联网）→ 生成大纲
- [x] 阶段3：正文调研（联网）→ 写正文 → 审稿循环（条件分支，最多3次）
  - 审稿不通过 → 判断是否需要重新调研 → 补充调研（追加）/重新调研（覆盖）→ 重写正文
  - 审稿通过 → 配图（如需要）→ 格式化
- [x] 三个人工介入点（选标题+风格配置、确认大纲+配图方式+字数配置、查看成品）

### ✅ 4.5 联网搜索与调研
- [x] 千问自带联网搜索（三次调研节点全部强制开启）
- [x] 调研员提示词强化：
  - **标题调研**：提取关键信息→搜索同类标题→总结标题类型/角度/重复度
  - **大纲调研**：标题深度分析→按风格搜索同类文章结构→输出结构分析+大纲制定建议
  - **正文调研**：逐章节分析大纲内容需求→列调研清单→严格按清单搜索→按清单整理标注来源时间→"有就是有没有就是没有不许乱编"
- [x] **补充/重新调研模式**：
  - 补充调研（supplement）：只针对审稿意见方向搜索，新结果追加到旧结果后面
  - 重新调研（redo）：完整重新调研，直接覆盖旧结果
- [x] 调研结果保存到数据库（title_research / outline_research / content_research）
- [x] 调研过程清洗：不输出【思考】【行动】【观察】过程，直接输出最终结论
- [x] 5处token黑洞修复（ReAct循环、重复内容等）

### ✅ 4.6 配图功能（含持久化+智能分析）
- [x] 大纲中标注配图位置（`<!-- 配图：配图内容建议 -->`，描述主体/场景/风格，20-50字）
- [x] **配图方式在大纲确认页选择**（标题页只保留是否配图开关）
- [x] Pexels API 搜索图片（已验证可用）
- [x] Unsplash API 搜索图片（备选）
- [x] 百炼通义万相 AI 生成图片（qwen-image-3.0-pro）
- [x] **批量分析配图位置**：一次LLM调用分析多个配图位置的上下文和描述
- [x] **专业搜图关键词**：简洁明了且专业的英文关键词+搜图描述
- [x] **专业AI生图prompt**：50-100词，含9要素（主体/场景/风格/光线/构图/色调/细节/质量/负面提示）
- [x] 智能重试：搜不到时 LLM 优化描述，最多重试2次
- [x] 失败降级：多次搜不到自动改成纯文本过渡句
- [x] 图片自动插入正文对应章节
- [x] **图片本地持久化**：AI生图/API搜图生成后立即下载到 `backend/data/images/`，
      数据库存 `/images/xxx` 本地路径，后端 `/images` 静态服务 + 前端代理提供访问，
      彻底解决百炼 OSS 临时链接过期问题

### ✅ 4.7 审稿系统（重新设计）
- [x] **硬性约束3条**（违反任何一条直接不通过）：
  1. 标题一个字都不能错
  2. 字数只允许多（超200字内）不允许少
  3. 配图一张都不能少（标记数量检查）
- [x] **5维度审核**：
  1. 大纲符合程度 ≥80%
  2. 内容扣题程度 ≥80%
  3. 风格匹配度 ≥75%
  4. 调研素材引用程度 ≥70%
  5. 逻辑流畅性 ≥85分
- [x] **综合评分 ≥90分**才能通过，不能胡乱给高分
- [x] **审稿意见**：条理清晰（1.2.3...），每点含 where/why/expected
- [x] **重新调研判断**：明确"重新调研"或"补充调研"，给出详细调研列表
- [x] **通过理由**：分点列出通过的理由
- [x] **流量预测**：一般/中等/高/火/爆火（带颜色标识）
- [x] 打回最多3次（settings.max_review_rounds）
- [x] Python预计算实际字数和配图数量，确保硬性约束检查准确
- [x] **移除配图符合度维度**（审稿时图片还没生成，检查了没意义，方案C）

### ✅ 4.8 API 接口（10个）
- [x] 创建任务 `POST /api/v1/task`
- [x] 生成标题 `POST /api/v1/task/{id}/generate-titles`
- [x] 提交标题配置 `POST /api/v1/task/{id}/submit-title-config`（标题+是否配图+文章风格+大纲额外要求）
- [x] 重新生成大纲 `POST /api/v1/task/{id}/regenerate-outline`
- [x] 确认大纲 `POST /api/v1/task/{id}/confirm-outline`（大纲+配图方式+字数+水平+正文额外要求）
- [x] 生成正文 `POST /api/v1/task/{id}/generate-content`
- [x] 获取任务详情 `GET /api/v1/task/{id}`
- [x] 任务列表 `GET /api/v1/task`
- [x] 博客详情 `GET /api/v1/blog/{id}`（含审稿记录、配图URL、写作思路、三次调研结果、配置信息）
- [x] 删除任务 `DELETE /api/v1/task/{id}`

### ✅ 4.9 实时进度
- [x] progress 字段实时更新
- [x] 前端可通过 `GET /task/{id}` 轮询获取进度（轮询时序已修复）
- [x] 16个状态枚举（含 researching_content、reviewing、generating_images、formatting）
- [x] 标题选择页"重新生成"进度提示修复

### ✅ 4.10 前端（Vue 3 + Element Plus）
- [x] 5个页面：首页、标题选择、大纲确认、生成中、文章详情
- [x] 实时进度展示（进度条+Agent时间线）
- [x] 大纲可编辑
- [x] 文章删除功能
- [x] 标题选择页两栏底部对齐（CSS 修复）
- [x] 调研过程 Markdown 渲染修复
- [x] 首页输入框样式（恢复原样，去除多余图标，发送按钮垂直居中）
- [x] **文章风格配置**（标题选择页：科普/技术/论文/散文/笔记/自定义）
- [x] **配图方式移到大纲确认页**（标题页只保留是否配图）
- [x] **字数/水平移到大纲确认页**，新增正文额外要求输入框
- [x] **标题页额外要求只传给大纲师**，大纲页额外要求只传给写手

### ✅ 4.11 文章详情页三栏布局
- [x] **后端字段扩展**：返回 title_research / outline_research / content_research / writing_thoughts / target_word_count / level / extra_requirements / need_image / article_style / article_style_custom
- [x] **写手思路能力**（writer.generate_thoughts + blog_task.writing_thoughts 列 + graph 写手节点首次生成思路存库）
- [x] **前端三栏布局**（BlogDetailView.vue，以整个浏览器窗口为容器）：
  - 左栏：用户选择的标题 / 大纲配置（字数/水平/额外要求/配图方式）/ 文章风格 / 大纲结构（折叠）
  - 中栏：正文（保持原 820px 宽度不变，高度控制+上下滚动）
  - 右栏：**审稿记录（最上边，默认展开）** / 写手思路 / 标题调研 / 大纲调研 / 正文调研（默认折叠，超长截断+展开，超出20行上下滚动）
  - 侧栏内容支持 Markdown + KaTeX 公式渲染
  - 审稿记录展示：综合评分 + 通过理由 + 流量预测
  - 响应式：≤1280px 右栏下移、≤900px 单栏堆叠

### ✅ 4.12 生产化改造
- [x] **数据库切换 SQLite → PostgreSQL（Docker）**
  - postgres:16-alpine 容器 + healthcheck + `postgres_data` 持久化卷
  - 密码 `lisiyao`，连接串 `postgresql+psycopg2://blog:lisiyao@postgres:5432/blog_agent`
  - requirements.txt 增加 psycopg2-binary
  - **数据迁移**：5 条历史任务完整迁移（含枚举 name 兼容、布尔列转换、自增序列重置）
  - 旧 sqlite 卷已删除
- [x] **配置变量化**：POSTGRES_USER/PASSWORD/DB/HOST/PORT 抽到根目录 `.env`
      （compose `${VAR}` 引用，密码不再进仓库），新增 `.env.example` 部署模板
- [x] **backend Dockerfile 换源**：apt/pip 全部指向阿里云镜像（服务器部署必需）
- [x] **前端 dev/prod 双模式**（docker compose profiles）
  - 开发：`frontend`（Dockerfile.dev + vite 热更新），本地 `docker compose up` 照旧
  - 生产：`frontend-prod`（多阶段构建 + nginx），服务器 `docker compose --profile prod up -d --build`
  - nginx.conf：静态托管 + Vue Router 回退 + `/api`、`/images` 反代 backend + 接口超时 600s
  - 端口可用 `${FRONTEND_PORT:-80}` 覆盖
- [x] **.env.example 补全**：20项全覆盖模板（与 settings.py 核对无缺失无多余，无密钥泄漏）
- [x] **.env 清理**：移除已废弃的 `llm_model_formatter`（排版降级为纯规则），db_url 加注释说明 docker 环境下自动覆盖

### ✅ 4.13 内容质量修复
- [x] **写手提示词重构**（writer.py）：去掉"技术博客写手"身份预设 → 通用文章写手，文风由大纲与调研决定
- [x] **禁自编标题**：正文不输出任何标题行、不加大纲外的"引子/前言"，标题由页面顶部展示 selected_title
- [x] **代码/公式约束**：除非大纲或调研明确要求（教程/API 文档类）否则不插代码块；公式用 LaTeX `$...$` / `$$...$$`
- [x] **前端 KaTeX 渲染**（MarkdownRender.vue + katex 依赖）：行内/块级公式真实渲染
- [x] **标题字段修正**（BlogDetailView.vue）：`blog.title`（API 无此字段）→ `blog.selected_title`
- [x] **标题调研 topic 插入 bug 修复**（调研节点说没接收到用户主题的问题）
- [x] **各节点数据流确认**：标题/大纲/正文生成节点都正确接收到上游数据和调研结果

### ✅ 4.14 Bug 修复
- [x] `image_source` 未定义错误（run_generate_outline 中 initial_state 引用了已移除的参数）
- [x] `need_image` 为 NULL 导致响应校验失败（重置数据时操作不当）
- [x] 标题选择页"重新生成"无进度提示
- [x] 调研过程不显示（ReAct 过程标识清洗）
- [x] 正文调研重复内容（token黑洞，5处修复）
- [x] 三栏布局太紧凑（改为以浏览器窗口为容器，中间栏保持原宽度）
- [x] 侧栏展开内容显示不全（超出20行上下滚动）
- [x] 正文展示高度控制（超出上下滚动）

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
- [ ] 配图生成后质量审核（当前审稿时图片还没生成）

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

### 后端 `backend/.env`（完整 20 项模板见 `.env.example`）
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
# （llm_model_formatter 已移除，排版降级为纯规则，不调用LLM）

# ========== 审稿配置 ==========
enable_review=true
max_review_rounds=3

# ========== 配图配置 ==========
pexels_api_key=你的Pexels_API_Key
unsplash_access_key=你的Unsplash_API_Key
image_gen_model=qwen-image-3.0-pro
image_api_key=配图专用API_Key（不填则用llm_api_key）
dashscope_workspace_id=百炼业务空间ID
image_save_dir=/app/data/images    # 配图持久化目录（本地直接运行改 ./data/images）

# ========== Database（PostgreSQL）==========
# Docker 环境下由 docker-compose.yml 的 environment 自动覆盖，无需修改这里
# 本地调试如需直连 postgres 容器，可改为：
# db_url=postgresql+psycopg2://blog:lisiyao@localhost:5432/blog_agent
db_url=postgresql+psycopg2://blog:lisiyao@postgres:5432/blog_agent

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
# 本地开发（dev 模式，vite 热更新）
docker compose up -d
# 前端：http://localhost:5173
# 后端API：http://localhost:8000
# 接口文档：http://localhost:8000/docs

# 服务器生产部署（nginx 托管构建产物）
docker compose --profile prod up -d --build
# 前端：http://服务器IP（80端口，可用 FRONTEND_PORT=8080 覆盖）
```

### 本地直接运行方式（不使用 Docker，需先本地安装 PostgreSQL）
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# 配置 .env（db_url 指向本地 PostgreSQL，image_save_dir 改 ./data/images）
python scripts/init_db.py
uvicorn src.blog_agent.main:app --reload
```

---

## 八、完整使用流程

1. **创建任务**：输入博客主题
2. **生成标题**：调研员联网调研同类文章标题 → 标题策划依据调研结果生成3个标题 → 标题评分
3. **选择标题+配置**（标题选择页）：
   - 选择标题
   - 配置**文章风格**（科普/技术/论文/散文/笔记/自定义）
   - 选择**是否配图**（配图方式在下一步选择）
   - 填写**对大纲的额外要求**（只传给大纲师）
4. **生成大纲**：调研员联网调研同类文章大纲结构（按标题+风格）→ 大纲师依据调研结果+用户配置生成大纲（标注配图位置）
5. **确认/修改大纲**（大纲确认页）：
   - 可编辑大纲
   - 选择**配图方式**（Pexels搜索/AI生成）
   - 配置**目标字数**、**专业水平**
   - 填写**对正文的额外要求**（只传给写手）
6. **生成正文**：
   - 调研员逐章节分析大纲需求→列调研清单→联网调研最新资料（标注来源时间，不许乱编）
   - 写手基于大纲+调研结果生成正文（5条硬约束）
   - 审稿审查（硬性约束3条+5维度审核，综合90分通过，不通过则打回修改，最多3次）
     - 打回时判断是否需要重新调研→补充调研（追加到旧结果）/重新调研（覆盖）→重写
   - 配图设计师配图（批量分析配图位置，专业英文关键词/prompt，本地持久化，搜不到改纯文本）
   - 纯规则格式化（统一标题/列表/空行/代码块格式，不调用LLM）
7. **查看成品**：文章详情页（三栏布局），含配图、审稿记录、调研结果、写手思路

---

## 九、已知问题和注意事项

1. **生成正文接口同步阻塞**：生成正文可能需要2-5分钟，期间接口会一直等待，生产环境需要改成异步任务（Celery+Redis）
2. **历史 AI 生图任务图片已失效**：2026-09-10 之前生成的 AI 配图用的是百炼 OSS 临时链接（约1天过期），
   修复持久化前的历史任务图片无法恢复，需重新生成任务才会走本地转存逻辑
3. **改模型后需要手动加字段**：SQLAlchemy create_all() 不会更新已存在的表，新增字段需手动 ALTER TABLE，后续用 Alembic 迁移
4. **联网搜索用千问自带能力**：搜索过程不透明，后续可考虑接独立搜索引擎 API
5. **postgres 密码改动注意**：`POSTGRES_*` 只在数据卷首次初始化时生效，改密码需 `ALTER USER` 或重建卷
6. **本地 80 端口可能被系统占用**（Windows http.sys），验证生产前端用 `FRONTEND_PORT=8080`
7. **审稿时图片还没生成**：配图agent在审稿通过后才执行，所以审稿只检查配图标记数量，不检查实际图片质量（已移除配图符合度维度）
8. **frontend-prod 容器默认不启动**：它有 `profiles: ["prod"]` 标记，只有加 `--profile prod` 才启动；本地开发不需要它

---

## 十、代码量统计

| 模块 | 文件数 | 代码行数 |
|------|--------|---------|
| Agent 层 | 9个（6个Agent+1个格式化函数+state+graph） | ~1200行 |
| 业务层 | 1个 | ~250行 |
| 接口层 | 3个 | ~220行 |
| 数据库层 | 3个 | ~130行 |
| Schema 层 | 2个 | ~150行 |
| 配置+客户端 | 2个 | ~100行 |
| 脚本 | 3个 | ~200行 |
| **后端合计** | **23个核心文件** | **~2250行** |
| 前端（Vue） | ~15个 | ~3500行 |
| **项目总计** | **~38个核心文件** | **~5750行** |
