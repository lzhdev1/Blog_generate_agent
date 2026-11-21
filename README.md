# 稿间 · Blog Agent

稿间是一个中文优先、支持中英文界面的博客创作工作台。作者输入主题，选择标题、调整大纲和写作要求，随后由 Agent 调研、撰写、审稿并输出 Markdown。作者可以私藏成稿、公开分享，或设置下载价格。开发环境支持模拟注册与充值，正式环境支持 SMTP 邮箱验证。

## 从选题到成稿

| 阶段 | Agent 的工作 | 作者的操作 |
| --- | --- | --- |
| 选题 | 结合主题、读者、篇幅和文风调研并拟定候选标题 | 可在开始时写明创作目的，选择或改写标题，调整文风和大纲要求 |
| 大纲 | 结合已选标题与要求编排章节，审核结构 | 编辑 Markdown 大纲，确认篇幅、读者水平、配图来源和正文要求 |
| 正文 | 调研、写作、审稿。需要修改时带回当前稿件和意见，需要补充资料时再次调研 | 在进度页查看当前节点，离开后可从「我的稿件」继续 |
| 交付 | 处理配图、排版并保存成稿和引用来源 | 阅读文章、查看评审意见，复制或下载 Markdown，确认当前版本的发布权限 |
| 私有修订 | 审核保存的修订稿，保留作者编辑的正文 | 局部修改、按需补查资料，审阅通过后采用并重新确认发布 |

标题和大纲由作者最终确认。自动审核达到重试上限后，界面会提示作者检查可用产物。正文审核耗尽时任务进入失败状态，保留草稿和反馈。作者可以重试当前阶段，也可以返回大纲调整写作要求。只有交付步骤完成才将新任务标记为 `completed`。是否执行模型评审由 `enable_review` 控制，标题、字数和配图等正文硬性校验仍然生效。

文章广场展示公开文章和示例。「我的稿件」汇总作者的任务、点赞、收藏、购买和下载记录。购买和下载历史可打开当时保存的版本。

技术、科普、论文以及明确要求实证的稿件须有来自检索工具的来源记录。作者可按正文中的 `[S1]` 等编号核对摘录。系统检查可识别的外部断言、数字和引用，审稿人收到原始摘录并评估论断是否恰当。对个人笔记和散文，只在使用外部事实时要求对应证据。检索不可用时，缺少必要依据的稿件保存在作者工作区。

发布与购买都携带已显示给用户的 `expected_revision`，购买还需提交 `expected_price`。版本或报价变化后返回 HTTP 409，由用户查看新内容再确认。已有公开文章可以继续阅读。仅有旧审核记录或跳过模型评审的私稿，须在修订页复审后公开。修订期间保留原版的可见性，作者采用修订后同一文章地址转为私有，再由作者确认发布。

## 代码入口

| 路径 | 内容 |
| --- | --- |
| `front_L/src/views` | 创作工作台、标题、大纲、生成进度、阅读、稿件库、账户页面 |
| `front_L/src/utils/taskWorkflow.js` | 从任务状态恢复到对应页面 |
| `backend_L/src/blog_agent/api/v1` | FastAPI 任务、进度、文章、历史记录、账户接口 |
| `backend_L/src/blog_agent/service/agent_service.py` | 用户工作流各阶段的后台执行与结果落库 |
| `backend_L/src/blog_agent/agent` | LangGraph 图、角色提示词、工具和审核节点 |
| `backend_L/config/settings.py` | 模型、搜索、配图、审核次数和并发等配置 |

前端使用 Vue 3、Vite、Pinia 和 Element Plus。后端使用 FastAPI、LangGraph、SQLAlchemy 和 PostgreSQL。前端用 SSE 接收进度，断线时通过任务查询恢复。标题、大纲、正文的生成请求进入 PostgreSQL 持久队列。每个阶段由独立子进程执行，页面关闭后仍然继续。

## 开发启动

使用仓库现有的 PostgreSQL 实例和 Docker 网络 `shared-db`。首次配置时，将 `backend_L/.env.example` 复制为 `backend_L/.env`，填写 `db_url`、`llm_base_url`、`llm_api_key` 和 `jwt_secret`。调研检索和可选配图依赖各自的服务凭据，具体配置见 `settings.py`。后端启动时使用 SQLAlchemy 创建缺少的表。

```powershell
docker compose -f docker-compose.dev.yml up -d --build
```

开发编排默认在本机 5175 提供前端，8001 提供 API，接口文档在 `/docs`。如果前端端口已被其他项目使用，可单独运行后端，然后从宿主机启动 Vite。

```powershell
docker compose -f docker-compose.dev.yml up -d backendl
cd front_L
npm ci
npm run dev -- --host 127.0.0.1 --port 5187
```

宿主机 Vite 默认把 `/api` 和 `/images` 代理到 `http://127.0.0.1:8001`。开发容器通过 `BLOG_AGENT_API_TARGET` 指向 Compose 后端。生产编排使用 Nginx 提供静态页面和同源 API 代理。

从旧版本升级时，先让旧实例停止接收新的写作请求，等待队列中的作业结束，再替换所有共享该数据库的 API 和工作进程。旧工作进程无法区分私有修订复审与正文重写。新版启动会在数据库锁保护下补齐字段和修订表；就绪检查通过后再开放新版前端。回滚前也需等待已接纳的复审作业结束。

## 额度与排队

所有普通账户使用免费计划。新建草稿每天最多 20 篇，启动标题和大纲各用 1 点，启动正文用 3 点。私有修订保存免费，单独提交复审用 1 点。默认每个账户每天 10 点，全站每天 100 点，于 UTC 00:00（北京时间 08:00）重置。点数是阶段预算，实际供应商账单取决于模型、token 和配图。

额度、队列作业和任务状态在一次数据库事务内提交。队列满、同稿重复提交、配额不足都会保留稿件与余额。作业在开始执行前中断时，会优先使用原作业和原额度重新领取。如果所有启动机会都用尽，系统将本版本记录的预留点数退回原扣款日的用户和全站额度。已开始执行的阶段遇到超时或限流会保留该次扣点，作者主动重新生成时计入新的阶段费用。生成接口支持 `Idempotency-Key`，修订送审要求携带此键。请求发出后遇到断线，应复用原键与原始参数查询本次操作结果。

| 默认策略 | 配置 |
| --- | --- |
| 每日账户／全站点数 10／100 | `FREE_DAILY_UNITS`、`SITE_DAILY_UNITS` |
| 每账户最多 1 个已排队或运行中的阶段 | `FREE_MAX_ACTIVE_JOBS` |
| 整个数据库最多同时执行 4 个阶段，最多接纳 64 个待执行及运行中的阶段 | `AGENT_MAX_WORKERS`、`AGENT_MAX_QUEUED_JOBS` |
| 作业租约默认 90 秒，执行前的领取最多尝试 2 次 | `AGENT_JOB_LEASE_SECONDS`、`AGENT_JOB_MAX_ATTEMPTS` |
| 每阶段最多 24 次模型请求、40 次工具请求、3 张配图 | `MODEL_LIMIT_MODEL_CALLS`、`MODEL_LIMIT_TOOL_REQUESTS`、`MODEL_LIMIT_IMAGES` |
| 单次请求输入上限 192,000 字节，输出上限 8,192 tokens，默认无 SDK 网络重试 | `MODEL_LIMIT_INPUT_BYTES`、`MODEL_LIMIT_OUTPUT_TOKENS`、`MODEL_LIMIT_SDK_RETRIES` |
| 供应商阶段预算 600 秒，单次请求超时上限 90 秒，作业进程硬上限 1,800 秒 | `MODEL_LIMIT_STAGE_SECONDS`、`MODEL_LIMIT_REQUEST_SECONDS`、`AGENT_JOB_MAX_RUNTIME_SECONDS` |

暂停外部调用可将 `MODEL_LIMIT_ENABLED=false` 配置到所有实例并重启。只停用 AI 生图使用 `MODEL_LIMIT_AI_IMAGES_ENABLED=false`。当前显式检索工具也计入预算，接入服务商时保持 `llm_enable_search=false`。

调度器通过短事务和租约协调各实例。尚未开始执行的作业可在租约到期后重新领取；已经开始调用供应商的阶段中断后标记失败，作者可以检查稿件再重试。旧进程失去租约后无法覆盖新结果。SSE 在单个 API 进程内每账号最多 3 条连接，断线可以重新查询。滚动升级到队列版本时，先停止全部旧版服务。如有无作业记录且仍显示运行中的旧稿，可运行 `python -m src.blog_agent.service.job_worker recover-legacy` 查看数量，确认后使用 `--apply` 将其转为可重试状态。

正文阶段会保存已取得的调研资料和写手已返回的草稿。若审稿中断，作者可以在失败页查看正文与写作思路。对已有稿件发起重写时，系统会在同一事务保留一份恢复副本。重写失败后，作者可以免费恢复上一版，连同当时的标题、大纲、正文和创作设置一起恢复为私密稿。恢复后的公开和下载权限由作者重新设置。重写成功后，系统会清除本次替换使用的恢复副本。

## 注册、密钥与隔离

- 开发注册页会在邮箱旁显示测试验证码，默认 `888888`。生产 Compose 强制 `APP_ENV=production`，禁用固定测试码与模拟充值。`REGISTRATION_MODE=auto` 时，配置 `SMTP_HOST`、`SMTP_SENDER` 后启用邮箱注册；也可以显式选择 `closed`，已有用户仍可登录。邮件支持 SSL（默认 465）和 STARTTLS，按服务商填写端口及凭据。
- 正式验证码 10 分钟过期，存储摘要，注册成功后一次性消费。后台按客户端和账户标识限制注册、发码和登录尝试。反向代理部署需要将 `FORWARDED_ALLOW_IPS` 设为实际受信任的代理地址或网段，让 Uvicorn 识别真实客户端；默认按直连对端限流。生产 API 通过站点同源代理提供服务。
- 开发及生产应使用各自的数据库、模型凭据和签名密钥。旧版测试账号的邮箱可能已被标记为已验证，迁入生产前应重新核验。生产服务可通过 `BLOG_PRODUCTION_ENV_FILE` 指向独立配置文件。正式 JWT 密钥至少 32 字节；修改密码后旧会话立即失效。旧版正式登录令牌升级后需要重新登录。
- 私稿、任务进度、额度、历史副本和本地配图均按身份校验。文章转私密后停止匿名读图，已经保存副本的读者仍可读取该副本中的配图。构建镜像时只复制运行代码，密钥文件和用户配图通过运行时配置与挂载提供。
- `GET /api/v1/health` 检查 API 存活，`GET /api/v1/ready` 用于部署就绪检查。服务拥塞和额度错误返回可读原因；有明确重试窗口时返回 `Retry-After`。开发后端与前端端口默认绑定本机回环地址。

## 验证

在 `front_L` 运行 `npm run build` 构建生产包，运行 `npm test` 检查 Markdown、来源链接和前端请求恢复。在本机准备好 Playwright、Chrome 和后端镜像后，运行 `npm run test:browser:revision` 可验证旧稿复审、断线恢复、重新发布和扣点。该测试使用临时数据库和本地模拟模型。

在安装了项目依赖的 `backend_L` 环境运行 `python -m unittest discover -s tests -v`。Agent 测试使用固定模型输出。为 `POSTGRES_TEST_URL` 提供可创建临时 schema 的独立 PostgreSQL 测试数据库，即可同时验证真实行锁下的并发提交。

在仓库根目录运行 `python backend_L/scripts/loadtest/isolated_http.py --users 12 --workers 4` 可复测多人并发创作，Windows 也可使用 `py -3`。本机需有 `postgres:16-alpine` 和本项目的开发后端镜像。脚本创建独立 Docker 内部网络、临时 PostgreSQL 数据库及本地模拟模型服务，启动两个 API 实例，从注册一路执行到成稿。结果包含每户逐阶段扣点、队列和执行峰值、请求受理及成稿耗时。结束后清理本轮容器和数据。[12 用户本地实测结果](backend_L/scripts/loadtest/results-2026-11-21.json)

使用同一入口可复测故障恢复。

- `python backend_L/scripts/loadtest/isolated_http.py --provider-faults --workers 2` 在写手阶段制造响应超时，在审稿阶段返回 429，验证草稿保存、同键重发、主动重试和恢复上一版。[模拟模型故障实测记录](backend_L/scripts/loadtest/results/provider_faults_20261121.json)
- `python backend_L/scripts/loadtest/isolated_http.py --worker-recovery` 在排队、领取以及模型调用途中停止测试进程，检查租约接管、扣点和后续稿件的推进。[后台进程故障实测记录](backend_L/scripts/loadtest/results/worker_recovery_20261121.json)
- `python backend_L/scripts/loadtest/isolated_http.py --mixed-faults --users 10 --workers 3` 在同一批创作中只给指定稿件注入超时或 429，并在另一个稿件调用模型时重启一个后台实例。结束后逐账号核对稿件归属、模型请求、幂等回执、作业记录和额度。[混合故障与逐户对账记录](backend_L/scripts/loadtest/results/mixed_faults_20261121.json)
- `python backend_L/scripts/loadtest/isolated_http.py --survivor-traffic` 使用 2 个执行槽和总容量为 4 的队列，验证单个实例掉线期间新建稿件、满队列拒绝和释放容量后的同键重试。[单实例离线期间的请求记录](backend_L/scripts/loadtest/results/survivor_traffic_20261121.json)
