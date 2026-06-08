import requests
import json

url = "https://cdn.sta1n.cn/v1/chat/completions"
key = "sk-62JmqwdDKaekwh6KjmcuVOBtaKfAetzk5rGK2giL8X0rrMnm"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {key}"
}

payload = {
    "model": "[AN]gemini-3.5-flash-thinking",
    "messages": [{"role": "user", "content": "你好，说一句话测试"}]
}

try:
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print(f"HTTP {r.status_code}")
    print(r.text)
except Exception as e:
    print(f"Error: {e}")
