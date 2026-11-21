"""完整 supervisor_graph 标题阶段计时（含 title_gate 主编评审）。"""
import time
from src.blog_agent.agent.graphs.supervisor_graph import build_supervisor_graph

t0 = time.time()
graph = build_supervisor_graph(max_review_rounds=2)

# 只跑到 title_gate 通过：传一个会立刻通过的 state
# 用 stream 逐节点观测
state = {
    "topic": "2026年AI Agent发展趋势",
    "article_style": "technical",
    "word_count": 1200,
    "level": "advanced",
    "need_image": False,
    "max_review_rounds": 2,
}

node_times = {}
last = time.time()
from src.blog_agent.clients.provider_budget import provider_run

with provider_run():
    for chunk in graph.stream(state, stream_mode="updates"):
        for node_name, _ in chunk.items():
            now = time.time()
            node_times[node_name] = now - last
            print(f"[+{now-t0:6.2f}s] {node_name} ({now-last:.2f}s)")
            last = now
            if node_name == "to_outline":
                # 标题阶段到此结束，停止
                break
        else:
            continue
        break

print(f"\n=== 标题阶段 total: {time.time()-t0:.2f}s ===")
for k, v in node_times.items():
    print(f"  {k}: {v:.2f}s")
