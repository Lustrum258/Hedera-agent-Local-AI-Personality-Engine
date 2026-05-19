"""示例插件 — 天气查询（展示如何注册工具）"""

import requests

from hedera.plugin.base import PluginBase


def _weather(query: str) -> dict:
    """通过 wttr.in 查天气"""
    try:
        resp = requests.get(
            f"https://wttr.in/{query}?format=%C+%t+%h+%w",
            timeout=10,
            headers={"User-Agent": "curl/8.0"},
        )
        if resp.status_code == 200:
            text = resp.text.strip()
            return {"success": True, "weather": text}
        return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


class WeatherPlugin(PluginBase):
    name = "weather"
    description = "查询天气，支持城市名"
    keywords = ["天气", "温度", "多少度", "热不热"]

    def process(self, message: str, context: dict = None) -> str | None:
        # 简单的城市提取
        for kw in ["天气", "温度", "多少度"]:
            idx = message.find(kw)
            if idx > 0:
                city = message[:idx].strip()
                if city:
                    result = _weather(city)
                    if result.get("success"):
                        return f"{city} 天气: {result['weather']}"
                    return f"查不到 {city} 的天气"
        return None

    def get_tools(self) -> list[dict]:
        return [{
            "name": "check_weather",
            "description": "查询指定城市的实时天气",
            "fn": _weather,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "城市名，如 沈阳、Beijing、London"}
                },
                "required": ["query"],
            },
        }]
