import json, urllib.request, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
key = "sk-6cKBzXPp2wBlrbr9qzAddTMPOqUbQMv51RfyrKAWfEkoEK7L"
base = "https://api.hcnsec.cn/v1"
def describe_image(b64_path, label, model="auto"):
    with open(b64_path) as f:
        b64 = f.read().strip()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": f"这是一个软件界面的截图，标注为「{label}」。请详细描述：1.界面上所有可见元素（按钮/输入框/列表/标签/文本）2.整体布局 3.如果有多条数据，逐条列出内容。中文回答，尽量完整。"}
        ]}],
        "max_tokens": 3000
    }
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=150)
    data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]

out = open(r"D:\sandbox\prompt-preset\docs\img_analysis.txt", "w", encoding="utf-8")
for path, label in [
    (r"D:\sandbox\prompt-preset\docs\prompt.png", "prompt插件当前状态截图"),
    (r"D:\sandbox\prompt-preset\docs\酒馆预设.png", "SillyTavern酒馆预设界面截图"),
    (r"D:\sandbox\prompt-preset\docs\livingmemory前端.png", "LivingMemory AstrBot Pages面板截图"),
]:
    try:
        out.write(f"======== {label} ========\n")
        out.write(describe_image(path, label))
        out.write("\n\n")
        out.flush()
    except Exception as e:
        out.write(f"ERROR: {e}\n\n")
out.write("ALL_DONE")
out.close()
