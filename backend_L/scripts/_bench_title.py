"""标题链路逐节点计时：定位 2 分钟花在哪。"""
import time
from src.blog_agent.agent.graphs.title_graph import build_title_graph

t0 = time.time()
graph = build_title_graph()
state = {"topic": "2026年AI Agent发展趋势", "max_review_rounds": 2}

# 用 stream 逐节点观测耗时
node_times = {}
last = time.time()
from src.blog_agent.clients.provider_budget import provider_run

with provider_run():
    for chunk in graph.stream(state, stream_mode="updates"):
        for node_name, _ in chunk.items():
            now = time.time()
            node_times[node_name] = now - last
            print(f"[+{now-t0:6.2f}s] node done: {node_name} ({now-last:.2f}s)")
            last = now

print(f"\n=== total: {time.time()-t0:.2f}s ===")
print("=== node times ===")
for k, v in node_times.items():
    print(f"  {k}: {v:.2f}s")
