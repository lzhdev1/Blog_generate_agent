# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-agent blog generation system. User inputs a topic, 7 specialized agents collaborate (Researcher → Title Planner → Outliner → Writer → Reviewer → Image Designer → Formatter) to produce a complete blog article with images.

## Development Commands

### Backend (FastAPI + LangGraph)

```bash
cd backend

# Activate virtual environment
.\.venv\Scripts\Activate.ps1  # Windows PowerShell

# Install dependencies
pip install -r requirements.txt

# Initialize database (SQLite)
python scripts/init_db.py

# Run development server
uvicorn src.blog_agent.main:app --reload

# API docs: http://127.0.0.1:8000/docs
```

### Frontend (Vue 3 + Element Plus)

```bash
cd front

# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build
```

### Docker (Full Stack)

```bash
# Start both frontend and backend
docker compose up -d

# Frontend: http://localhost:5173
# Backend API: http://localhost:8000
```

## Architecture

### Backend Layers

```
backend/src/blog_agent/
├── main.py              # FastAPI entry point, CORS config
├── api/v1/blog.py       # 10 REST endpoints, state machine transitions
├── service/task_service.py  # Business logic, DB operations via repository
├── db/
│   ├── models.py        # SQLAlchemy models, TaskStatus enum (13 states)
│   └── repositories/    # Data access layer
├── clients/llm_client.py    # OpenAI-compatible client for Alibaba DashScope
└── agent/               # Core multi-agent system
    ├── state.py         # AgentState TypedDict (shared workflow state)
    ├── graph.py         # LangGraph StateGraph orchestration (3 phases)
    └── agents/          # 7 agent classes inheriting BaseAgent
```

### Multi-Agent Workflow (LangGraph)

The system uses LangGraph StateGraph with conditional edges and loops:

**Phase 1: Title Generation**
- `research_node` → `generate_titles_node` → `score_titles_node`
- Researcher agent does web search (enable_search=True), analyzes competitor titles
- Title agent generates 3 options, researcher scores them

**Phase 2: Outline Generation**
- `research_node` → `generate_outline_node`
- Triggered by `submit-title-config` endpoint (human selects title + image config)
- Outliner generates blog-style outline, marks image insertion points with `<!-- 配图：描述 -->`

**Phase 3: Content Generation**
- `research_content_node` → `write_node` → `review_node` (conditional loop) → `image_node` (if needed) → `format_node`
- Review loop: Reviewer checks quality (70-point threshold), rejects with feedback if failed, max 2 rounds
- Image agent: Extracts markers, searches Pexels/Unsplash or generates via AI, fails gracefully to text transitions
- Formatter: Cleans up image comments, finalizes markdown

### Key Design Patterns

**Agent Base Class**: All agents inherit `BaseAgent`, which provides:
- `chat()` method with automatic model selection (per-agent config or default)
- `enable_search` parameter: None=use global config, True/False=override
- System prompt injection for role definition

**State Management**: `AgentState` TypedDict flows through the graph, each node reads/writes specific fields. Database updates happen inside node functions via `TaskService`.

**LLM Client**: Single global instance (`llm_client`), OpenAI-compatible protocol for Alibaba DashScope. Qwen models support built-in web search via `extra_body={"enable_search": True}`.

**Image Fallback**: If image search fails after retries, converts to pure text transition sentences instead of blocking.

### Frontend Structure

```
front/src/
├── views/               # 6 pages matching workflow stages
│   ├── HomeView.vue     # Task list
│   ├── CreateView.vue   # Create task
│   ├── TitlesView.vue   # Select title + configure images
│   ├── OutlineView.vue  # Confirm/edit outline
│   ├── GeneratingView.vue   # Real-time progress (polling)
│   └── BlogDetailView.vue   # Final article with images
├── api/task.js          # Axios API client
├── stores/task.js       # Pinia state management
└── router/index.js      # Vue Router, 6 routes
```

Vite proxies `/api` to `http://backend:8000` in Docker, or configure `VITE_API_URL` env var.

## Environment Variables

Backend requires `.env` in `backend/` directory:

```env
# Required
llm_base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
llm_api_key=your_dashscope_api_key
llm_model=qwen-plus

# Optional: Per-agent model overrides
llm_model_researcher=qwen-turbo
llm_model_reviewer=qwen-max

# Optional: Image sources
pexels_api_key=your_pexels_key
image_gen_model=wanx2.1-t2i-turbo

# Review behavior
enable_review=true
max_review_rounds=2

# Database
db_url=sqlite:///./blog_agent.db
```

## Database Schema

Single `blog_task` table with 21 columns tracking the entire workflow. JSON fields store arrays (titles, image_urls, title_scores). Status field uses `TaskStatus` enum with 13 states for real-time progress tracking.

## API Endpoints

All endpoints under `/api/v1`:
- `POST /task` - Create task
- `POST /task/{id}/generate-titles` - Phase 1 (auto-research + generate)
- `POST /task/{id}/submit-title-config` - Human intervention 1 (select title + image config, triggers Phase 2)
- `POST /task/{id}/regenerate-outline` - Retry outline generation
- `POST /task/{id}/confirm-outline` - Human intervention 2 (confirm/edit outline)
- `POST /task/{id}/generate-content` - Phase 3 (research + write + review + image + format)
- `GET /task/{id}` - Poll task status and progress
- `GET /blog/{id}` - Get final article

## Known Limitations

- **Synchronous blocking**: `generate-content` endpoint blocks for 2-5 minutes during Phase 3. Production needs Celery + Redis (currently stubbed in requirements.txt).
- **SQLite**: Not suitable for concurrent writes. Switch to MySQL/PostgreSQL for production.
- **Image URLs expire**: Pexels/Unsplash URLs have TTL. Download to local storage for permanence.
- **No schema migrations**: `create_all()` doesn't update existing tables. Manual `ALTER TABLE` needed when adding columns, or integrate Alembic.

## Code Style

- Backend: Python 3.12+, type hints, docstrings in Chinese for business logic
- Frontend: Vue 3 Composition API, Element Plus components, purple gradient theme
- No linting/formatting tools configured yet (pytest, black, ruff in requirements.txt but commented out)
