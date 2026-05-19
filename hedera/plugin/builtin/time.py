"""内置插件 — 时间/日期查询"""

from datetime import datetime
from hedera.plugin.base import PluginBase


class TimePlugin(PluginBase):
    name = "time"
    description = "查询当前时间、日期"
    keywords = ["几点", "时间", "日期", "今天", "现在"]
    priority = 110

    def process(self, message: str, context: dict = None) -> str | None:
        msg = message.strip()
        now = datetime.now()
        if any(kw in msg for kw in ["几点", "时间", "现在"]):
            return f"{now.strftime('%H:%M')}"
        if "日期" in msg or "几号" in msg or "号了" in msg:
            return f"{now.strftime('%Y-%m-%d')}"
        if "今天" in msg and ("周" in msg or "星期" in msg):
            weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            return weekdays[now.weekday()]
        if "今天" in msg and len(msg) < 10:
            return f"{now.strftime('%Y-%m-%d %H:%M')} {['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]}"
        return None

    def get_system_prompt_modifier(self) -> str:
        return "【可用快捷查询】时间、日期、星期几 — 直接问不用绕弯子"
