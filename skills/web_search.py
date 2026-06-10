import requests

TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "在互联网上搜索给定关键词，返回相关摘要和链接。适合查询最新信息、事实、新闻等。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，例如 'Python 教程'"
                }
            },
            "required": ["query"]
        }
    }
}

def execute(args):
    query = args.get("query", "")
    if not query:
        return "未提供搜索关键词"
    try:
        # 使用 DuckDuckGo 的免费 API（无需密钥）
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        results = []
        # 摘要
        if data.get("AbstractText"):
            results.append(f"摘要：{data['AbstractText']}")
        if data.get("AbstractURL"):
            results.append(f"链接：{data['AbstractURL']}")
        # 相关话题
        for topic in data.get("RelatedTopics", [])[:3]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(f"• {topic['Text']}")
                if topic.get("FirstURL"):
                    results.append(f"  链接：{topic['FirstURL']}")
        if not results:
            return f"未找到与 '{query}' 相关的结果"
        return "\n".join(results)
    except Exception as e:
        return f"搜索时出错：{str(e)}"
