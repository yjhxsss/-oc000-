# skills/get_image.py
import streamlit as st

TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "get_image",
        "description": "获取指定索引的图片 data URL，用于在回复中插入图片",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "图片索引，从 0 开始"}
            },
            "required": ["index"]
        }
    }
}

def execute(args):
    index = args.get("index")
    S = st.session_state
    if 0 <= index < len(S.oc_image_pool):
        return S.oc_image_pool[index]
    else:
        return f"错误：图片索引 {index} 无效，共有 {len(S.oc_image_pool)} 张图片"
