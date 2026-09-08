import json, urllib.request, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
key = "sk-6cKBzXPp2wBlrbr9qzAddTMPOqUbQMv51RfyrKAWfEkoEK7L"
base = "https://api.hcnsec.cn/v1"
with open(r"D:\sandbox\prompt-preset\docs\prompt.png") as f:
    b64 = f.read().strip()
body = {
    "model": "auto",
    "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        {"type": "text", "text": "这是 AstrBot 插件配置页面的截图。请详细描述：1.每个配置项的名称、类型（输入框/下拉框/JSON编辑器等）2.当前值 3.用户可交互部分。中文回答。"}
    ]}],
    "max_tokens": 3000
}
req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
resp = urllib.request.urlopen(req, timeout=150)
data = json.loads(resp.read())
out = open(r"D:\sandbox\prompt-preset\docs\prompt_analysis.txt", "w", encoding="utf-8")
out.write(data["choices"][0]["message"]["content"])
out.close()
print("done")
