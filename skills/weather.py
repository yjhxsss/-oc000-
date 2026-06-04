import requests

TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取指定城市的实时天气情况",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，例如 Beijing、上海、Tokyo"
                }
            },
            "required": ["city"]
        }
    }
}

def execute(args):
    city = args.get("city", "北京")
    try:
        # 使用 wttr.in 免费天气 API，返回简洁格式
        url = f"https://wttr.in/{city}?format=%C+%t+%h+%w&lang=zh"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return f"{city}天气：{resp.text.strip()}"
        else:
            return f"获取{city}天气失败（状态码：{resp.status_code}）"
    except Exception as e:
        return f"天气查询出错：{str(e)}"
