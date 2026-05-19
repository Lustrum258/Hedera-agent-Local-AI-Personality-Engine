"""示例插件 — 简单的 ping/pong 响应"""

from hedera.plugin.base import PluginBase


class PingPlugin(PluginBase):
    name = "ping"
    description = "响应 ping 命令，返回 pong"
    keywords = []
    commands = ["/ping"]

    def process(self, message: str, context: dict = None) -> str | None:
        if message.strip() == "/ping":
            return "pong 🏓"
        return None
