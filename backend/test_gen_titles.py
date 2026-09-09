import sys
sys.path.insert(0, '/app')
import urllib.request, json

# 1. 创建任务
print("1. 创建任务...")
create_data = json.dumps({"topic": "测试评分字段"}).encode()
req = urllib.request.Request(
    "http://localhost:8000/api/v1/task",
    data=create_data,
    headers={"Content-Type": "application/json"},
    method="POST"
)
with urllib.request.urlopen(req) as resp:
    task = json.loads(resp.read().decode())
    task_id = task['id']
    print(f"   任务ID: {task_id}")

# 2. 生成标题（同步执行，需要等待）
print("2. 生成标题（可能需要30-60秒）...")
req2 = urllib.request.Request(
    f"http://localhost:8000/api/v1/task/{task_id}/generate-titles",
    method="POST"
)
with urllib.request.urlopen(req2, timeout=120) as resp2:
    result = json.loads(resp2.read().decode())
    print(f"   状态码: {resp2.status}")
    print(f"   返回字段列表: {list(result.keys())}")
    print(f"   status: {result.get('status')}")
    print(f"   titles数量: {len(result.get('titles', []))}")
    print(f"   title_scores存在: {'title_scores' in result}")
    print(f"   title_scores类型: {type(result.get('title_scores')).__name__}")
    print(f"   title_scores数量: {len(result.get('title_scores', []))}")
    if result.get('title_scores'):
        print(f"   第一个评分: {json.dumps(result['title_scores'][0], ensure_ascii=False)[:150]}")

print("\n3. 结论:")
if 'title_scores' in result and result['title_scores']:
    print("   ✅ generate-titles 接口返回了 title_scores，后端schema正常")
else:
    print("   ❌ generate-titles 接口没有返回 title_scores，需要检查后端")
