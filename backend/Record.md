# 博客生成 Agent - 变更记录

> 记录每次功能变更与修复，按时间倒序。

---

## 2026-09-14（耗时优化 + 明暗主题切换）

### 耗时优化（后端 4 项，端到端缩短约 40~90s）
1. **配图并发获取**（image_agent.py）：ThreadPoolExecutor(max_workers=4) 取代串行 for，
   搜图/AI 生图均受益；3 张 AI 生图从串行 60~180s → 并行 20~60s；并发上限 4 防限流
2. **HTTP Session 复用**（image_agent.py）：模块级 `_image_http = requests.Session()`，
   6 处 requests.get/post 全改用 Session
3. **写手"思路+正文"合并调用**（writer.py + graph.py）：首次写作一次 LLM 调用输出
   `=====写作思路=====` + `=====正文=====`，split_thoughts_and_content 拆分；
   省一次 LLM 调用（约 10~25s）；拆分/调用异常自动回退纯正文；打回重写仍纯正文
4. **审稿硬性约束纯规则前置**（reviewer.py）：标题/字数/配图三条约束改代码精确计算，
   任一不通过直接返回（带 1.2.3... 意见），跳过 qwen-max 精审（省 20~50s）；
   LLM 输出中 hard_constraints 以代码结果覆盖
- 明确不做：正文调研预跑（大纲可编辑）、调研结果缓存（需 Redis）、标题生成/评分合并（同 LLM 自评无意义）

### 明暗主题切换（前端全站）
1. **主题机制**：html.dark（Element Plus 官方暗色）+ data-theme（自定义变量）
   - main.js 引入 element-plus/theme-chalk/dark/css-vars.css
   - App.vue header 新增切换按钮（SvgIcon sun/moon），localStorage 持久化，首次跟随系统偏好
   - index.html 首屏内联脚本预应用主题，刷新不闪白
2. **暗色变量体系**（main.css）：[data-theme='dark'] 全套暗色变量；
   新增 --bg-soft / --panel-gradient / --panel-gray-gradient / --header-bg / --modal-mask；
   覆盖 markdown 代码块/引用/表格/配图标记、滚动条、输入框、卡片、header
3. **硬编码颜色变量化**：6 个视图 + ProgressModal 约 80 处替换为 CSS 变量
   （浅色背景、文字色、边框、浅紫/浅灰渐变）；品牌紫与状态徽章色保留
4. **验证**：跟随系统/手动切换/刷新持久化闭环通过；首页/详情三栏页/标题选择页暗色正常

### 待办（下次继续）
- 数据库自动备份（pg_dump + cron + 异地）
- 后端生产进程（Gunicorn 多 worker，去 --reload）
- 密钥管理（Docker secrets / 阿里云 KMS）
- 外层 Nginx 600s 超时确认

---

## 2026-09-14（生产部署 + 配图链路修复）

### 部署上线
- 注册域名 `lzhshow.top`（阿里云），DNS 云解析，免费 SSL 证书
- 两层 Nginx 架构：
  - 外层：服务器系统 Nginx（443 HTTPS + 80 跳转 + gzip + 安全头，反代 `127.0.0.1:8080`）
  - 内层：前端 prod 容器 Nginx（静态托管 + `/api` `/images` 反代 backend:8000）
- 生产端口收敛：后端 8000 / 数据库 5432 不对外暴露
- 生产部署命令：`docker compose --profile prod up -d --build`

### 504 网关超时处理
- 前端新增 `isTimeoutError()`：超时不弹错、继续轮询、以任务最终状态为准
- 覆盖页面：HomeView / TitlesView / OutlineView / CreateView / BlogDetailView
- 内层 Nginx `/api` 超时 600s；外层 Nginx 待同步

### 配图链路修复（4 个缺陷）
1. 搜图关键词二次转换 → 直接用 `analyze_image_needs` 生成的关键词
2. 重试"抽象化"偏离主题 → 生成保留核心语义的关键词变体
3. 只取第一张无校验 → 取 5 张候选按描述重合度选最相关
4. AI 生图 prompt 带编号 → `_clean_image_prompt` 清洗成流畅单段

### Bug 修复
- 新文章复用旧文章图片（文件名 `process_{i+1}` 写死 + persist_image 幂等）
  → 文件名唯一化 `task{task_id}_{run_id}_{序号}`
- 图片文件误提交 git → `.gitignore` 忽略 `backend/data/images/` + `git rm --cached` 移除 9 个文件

### 待办（下次继续）
- 数据库自动备份（pg_dump + cron + 异地）
- 后端生产进程（Gunicorn 多 worker，去 --reload）
- 密钥管理（Docker secrets / 阿里云 KMS）
- 外层 Nginx 600s 超时确认

---

## 早期记录
1. 优化各个 agent 的 prompt，初步通过 prompt 实现伪 ReAct，通过 Few-shot 规范输出结果。
2. OutlinerAgent
