import streamlit as st
import openai
import json
import os
import time
import random
import re
from pathlib import Path
from datetime import datetime
import importlib
import pkgutil
import skills

# ---------- 62进制工具 ----------
CHARS62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CHAR_TO_INT = {c: i for i, c in enumerate(CHARS62)}

def decode_62(s: str) -> int:
    num = 0
    for ch in s:
        if ch not in CHAR_TO_INT:
            raise ValueError(f"非法字符 '{ch}'，允许的字符：{CHARS62}")
        num = num * 62 + CHAR_TO_INT[ch]
    return num

def encode_62(n: int) -> str:
    if n == 0:
        return CHARS62[0]
    res = []
    while n > 0:
        n, rem = divmod(n, 62)
        res.append(CHARS62[rem])
    return ''.join(reversed(res))

# ---------- OC 文件操作 ----------
OC_PROFILES_DIR = Path("oc_profiles")
OC_PROFILES_DIR.mkdir(exist_ok=True)

def load_oc_profile(oc_id):
    file_path = OC_PROFILES_DIR / f"{oc_id}.json"
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

# ---------- 技能动态加载 ----------
@st.cache_resource
def load_skills():
    tools = []
    execute_map = {}
    for _, modname, _ in pkgutil.iter_modules(skills.__path__):
        if modname.startswith("_"):
            continue
        module = importlib.import_module(f"skills.{modname}")
        if hasattr(module, "TOOL_DEF"):
            tools.append(module.TOOL_DEF)
            func_name = module.TOOL_DEF.get("function", {}).get("name")
            if func_name and hasattr(module, "execute"):
                execute_map[func_name] = module.execute
    return tools, execute_map

# ---------- API Key ----------
def get_api_key():
    try:
        return st.secrets["DEEPSEEK_API_KEY"]
    except (KeyError, FileNotFoundError):
        return os.environ.get("DEEPSEEK_API_KEY", None)

# ---------- 默认错别字库 ----------
DEFAULT_TYPO_DICT = {
    "是": "系", "我": "窝", "你": "泥", "很": "狠", "的": "哒",
    "了": "啦", "吗": "嘛", "什么": "啥", "怎么": "咋", "没有": "木有",
    "喜欢": "稀饭", "吃": "恰", "不": "卜", "知道": "造", "可爱": "可耐",
    "非常": "灰常", "大家": "大嘎", "同学": "童鞋", "朋友": "盆友",
    "晚安": "晚安鸭", "开心": "开森", "今天": "今颠", "突然": "突兰",
    "为什么": "为森么", "觉得": "觉滴", "真的": "尊嘟", "可是": "可素",
    "这里": "介里", "那里": "辣里", "这个": "介个", "那个": "辣个",
    "好": "吼", "哈哈": "嘎嘎", "哪里": "哪尼", "不要": "表",
    "人家": "伦家", "不好意思": "八好意思", "男朋友": "男票", "女朋友": "女票",
    "这样": "酱紫", "那样": "酿紫", "出来": "粗来", "回去": "回切",
    "回家": "回嘎", "吃饭": "恰饭", "睡觉": "碎觉", "电话": "电发",
    "电脑": "电闹", "手机": "手鸡", "厉害": "腻害", "漂亮": "漂酿",
    "东西": "东东", "事情": "四情", "对不起": "对卜起", "没关系": "木关系",
    "怎么样": "肿么样", "这么": "介么", "那么": "辣么"
}

# 颜文字库
KAOMOJI_LIST = [
    "(◕ᴗ◕✿)", "(≧◡≦)", "(◍•ᴗ•◍)", "(｡•̀ᴗ-)✧", "(◔‿◔)",
    "(๑•̀ㅂ•́)و✧", "( •̀ ω •́ )✧", "(*/ω＼*)", "(´• ω •`)",
    "(╹ڡ╹ )", "(人 •͈ᴗ•͈)", "(☆▽☆)", "(✯ᴗ✯)",
    "ヾ(⌐■_■)ノ♪", "~(˘▾˘~)", "✧(｡•̀ᴗ-)✧",
    "(づ｡◕‿‿◕｡)づ", "(*^▽^*)", "(≧∇≦)ﾉ", "(⌒‿⌒)"
]

# ---------- 文本特效处理 ----------
def apply_oc_text_effects(text, typo_rate, emoji_rate, special_punct, custom_typo_dict):
    if not text:
        return text
    typo_dict = custom_typo_dict if custom_typo_dict else DEFAULT_TYPO_DICT

    if special_punct:
        new_text = ""
        for ch in text:
            if ch in "。，！？；：.!?;:" and random.random() < 0.5:
                new_text += random.choice(["～", "！", "？", "…", "❤️"])
            else:
                new_text += ch
        text = new_text

    if typo_rate and typo_rate > 0 and typo_dict:
        words = list(text)
        for i, ch in enumerate(words):
            if ch in typo_dict and random.random() < typo_rate:
                words[i] = typo_dict[ch]
        text = "".join(words)
        for k, v in typo_dict.items():
            if len(k) == 2 and k in text and random.random() < typo_rate:
                text = text.replace(k, v, 1)

    if emoji_rate and emoji_rate > 0:
        sentences = re.split(r'(?<=[。！？.!?…])', text)
        new_sentences = []
        for sent in sentences:
            if sent and random.random() < emoji_rate:
                kaomoji = random.choice(KAOMOJI_LIST)
                if random.random() < 0.5:
                    sent = kaomoji + sent
                else:
                    sent = sent + kaomoji
            new_sentences.append(sent)
        text = "".join(new_sentences)
    return text

# ---------- 打字机效果 ----------
def typewriter_effect(placeholder, full_text, speed):
    displayed = ""
    for ch in full_text:
        displayed += ch
        placeholder.markdown(displayed + "▌")
        time.sleep(speed)
    placeholder.markdown(full_text)

# ---------- 聊天框美化CSS ----------
def inject_css():
    st.markdown("""
        <style>
        .stChatMessage [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background: #f0f8ff;
            border: 2px solid #a0c4ff;
            border-radius: 18px;
            padding: 8px 12px;
            margin: 8px 0;
            box-shadow: 0 2px 6px rgba(0,0,0,0.05);
        }
        .stChatMessage [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
            background: #fffbf0;
            border: 2px solid #ffd6a5;
            border-radius: 18px;
            padding: 8px 12px;
            margin: 8px 0;
            box-shadow: 0 2px 6px rgba(0,0,0,0.05);
        }
        .time-divider {
            text-align: center;
            color: #888;
            font-size: 0.85em;
            margin: 12px 0 4px 0;
        }
        </style>
    """, unsafe_allow_html=True)

# ---------- 页面配置 ----------
st.set_page_config(page_title="OC 聊天助手", page_icon="🎭")
inject_css()

# ---------- Session State ----------
defaults = {
    "messages": [],
    "oc_id": None,
    "oc_password": "",
    "oc_name": "",
    "oc_base_prompt": "",
    "oc_forced_rules": [],
    "oc_material": None,
    "oc_typing_speed": 0.05,
    "oc_typo_rate": 0.0,
    "oc_emoji_rate": 0.0,
    "oc_special_punct": False,
    "oc_custom_typo_dict": None,
    "oc_unread_probability": 0.08,
    "oc_consecutive_multiplier": 1.0,
    "consecutive_unread_count": 0,
    "oc_ignore_keywords": [],
    "oc_password_error": "",
    "prev_oc_id": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------- 动态标题 ----------
if st.session_state.oc_name:
    st.title(f"🎭 {st.session_state.oc_name}")
else:
    st.title("🎭 OC 聊天助手")

# ---------- 密码与清空 ----------
col1, col2 = st.columns([4, 1])
with col1:
    password = st.text_input(
        "🔐 输入 OC 密码",
        value=st.session_state.oc_password,
        placeholder="请从客服处获取"
    )
with col2:
    st.write("")
    if st.button("🗑️ 清空对话"):
        st.session_state.messages = []
        st.session_state.consecutive_unread_count = 0
        st.rerun()

# 密码处理
if password != st.session_state.oc_password:
    st.session_state.oc_password = password
    if password.strip() == "":
        for key in ["oc_id", "oc_name", "oc_base_prompt", "oc_forced_rules",
                    "oc_material", "oc_custom_typo_dict", "oc_password_error"]:
            st.session_state[key] = None if key != "oc_forced_rules" else []
        st.session_state.oc_typing_speed = 0.05
        st.session_state.oc_typo_rate = 0.0
        st.session_state.oc_emoji_rate = 0.0
        st.session_state.oc_special_punct = False
        st.session_state.oc_unread_probability = 0.08
        st.session_state.oc_consecutive_multiplier = 1.0
        st.session_state.consecutive_unread_count = 0
        st.session_state.oc_ignore_keywords = []
        st.session_state.messages = []
    else:
        try:
            oc_id = decode_62(password)
            profile = load_oc_profile(oc_id)
            if profile:
                st.session_state.oc_id = oc_id
                st.session_state.oc_name = profile.get("name", "未命名")
                st.session_state.oc_base_prompt = profile.get("base_prompt", "")
                st.session_state.oc_forced_rules = profile.get("forced_rules", [])
                st.session_state.oc_material = profile.get("material", None)
                st.session_state.oc_typing_speed = profile.get("typing_speed", 0.05)
                st.session_state.oc_typo_rate = profile.get("typo_rate", 0.0)
                st.session_state.oc_emoji_rate = profile.get("emoji_rate", 0.0)
                st.session_state.oc_special_punct = profile.get("special_punct", False)
                st.session_state.oc_custom_typo_dict = profile.get("custom_typo_dict", None)

                # 未读概率处理：优先用 unread_probability，否则转换 reply_probability
                if "unread_probability" in profile:
                    st.session_state.oc_unread_probability = profile["unread_probability"]
                elif "reply_probability" in profile:
                    st.session_state.oc_unread_probability = 1.0 - profile["reply_probability"]
                else:
                    st.session_state.oc_unread_probability = 0.08  # 默认8%

                st.session_state.oc_consecutive_multiplier = profile.get("consecutive_unread_multiplier", 1.0)
                st.session_state.oc_ignore_keywords = profile.get("ignore_keywords", [])
                st.session_state.oc_password_error = ""
                st.session_state.consecutive_unread_count = 0
                if st.session_state.prev_oc_id != oc_id:
                    st.session_state.messages = []
                st.session_state.prev_oc_id = oc_id
            else:
                st.session_state.oc_id = None
                st.session_state.oc_password_error = f"未找到 OC 文件 {oc_id}.json"
        except ValueError as e:
            st.session_state.oc_id = None
            st.session_state.oc_password_error = str(e)

if st.session_state.oc_password_error:
    st.error(st.session_state.oc_password_error)

# ---------- System Prompt ----------
def build_system_content():
    content = ""
    if st.session_state.oc_id is not None:
        base = st.session_state.oc_base_prompt
        rules = st.session_state.oc_forced_rules
        if rules:
            rules_text = "【强制规则，必须无条件遵守】\n" + "\n".join(f"- {r}" for r in rules)
            content = f"{rules_text}\n\n{base}"
        else:
            content = base

        material_name = st.session_state.oc_material
        if material_name:
            material_path = Path("materials") / f"{material_name}.txt"
            if material_path.exists():
                with open(material_path, "r", encoding="utf-8") as f:
                    material_content = f.read()
                if material_content.strip():
                    content += f"\n\n[附加知识库]\n{material_content}"
    return content

# ---------- 消息时间分隔渲染 ----------
def render_messages_with_time():
    """遍历消息，在适当位置插入时间标签"""
    prev_time = None
    for msg in st.session_state.messages:
        # 跳过工具消息的独立渲染（它们会在自己的 chat_message 里处理）
        if msg["role"] == "tool":
            continue

        # 判断是否需要显示时间标签
        show_time = False
        if prev_time is None:
            show_time = True
        else:
            diff = msg["timestamp"] - prev_time
            if diff >= 1200:  # 20分钟 = 1200秒
                show_time = True

        if show_time:
            dt = datetime.fromtimestamp(msg["timestamp"])
            time_str = dt.strftime("%m月%d日 %H:%M")
            st.markdown(f'<div class="time-divider">📅 {time_str}</div>', unsafe_allow_html=True)
            prev_time = msg["timestamp"]

        # 渲染消息内容
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
                status = "已读" if msg.get("read") else "未读"
                st.caption(status)
        else:
            with st.chat_message("assistant"):
                st.markdown(msg["content"])

# ---------- 显示历史消息 ----------
render_messages_with_time()

# ---------- 聊天输入处理 ----------
if prompt := st.chat_input("输入消息..."):
    api_key = get_api_key()
    if not api_key:
        st.error("未配置 API Key")
        st.stop()
    if st.session_state.oc_id is None:
        st.error("请先输入有效的 OC 密码")
        st.stop()

    # 添加用户消息（含时间戳，未读）
    user_msg = {"role": "user", "content": prompt, "read": False, "timestamp": time.time()}
    st.session_state.messages.append(user_msg)

    # 立即显示用户消息
    with st.chat_message("user"):
        st.markdown(prompt)

    # 判断是否回复（未读概率 + 关键词）
    should_reply = True
    # 关键词拦截
    if st.session_state.oc_ignore_keywords:
        if any(kw in prompt for kw in st.session_state.oc_ignore_keywords):
            should_reply = False

    # 未读概率计算（含连续递增）
    if should_reply:
        base_unread = st.session_state.oc_unread_probability
        multiplier = st.session_state.oc_consecutive_multiplier
        consecutive = st.session_state.consecutive_unread_count
        effective_unread = base_unread * (multiplier ** consecutive)
        effective_unread = min(1.0, effective_unread)  # 上限100%
        if random.random() < effective_unread:
            should_reply = False
            st.session_state.consecutive_unread_count += 1
        else:
            # 本次回复了，重置连续未读计数
            st.session_state.consecutive_unread_count = 0

    # 标记已读
    st.session_state.messages[-1]["read"] = True

    if not should_reply:
        st.rerun()

    # ----- 正常回复流程 -----
    tools, execute_map = load_skills()
    tools = tools if tools else None

    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    system_content = build_system_content()
    messages_for_api = []
    if system_content:
        messages_for_api.append({"role": "system", "content": system_content})
    api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    messages_for_api.extend(api_messages)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("对方正在输入中...")

        full_response = ""
        tool_calls = []

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_for_api,
            tools=tools,
            stream=True
        )

        stream_content = ""
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                stream_content += delta.content
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    if tc_delta.index >= len(tool_calls):
                        tool_calls.append({
                            "id": tc_delta.id,
                            "type": "function",
                            "function": {"name": "", "arguments": ""}
                        })
                    if tc_delta.id:
                        tool_calls[tc_delta.index]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls[tc_delta.index]["function"]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls[tc_delta.index]["function"]["arguments"] += tc_delta.function.arguments

        if stream_content:
            full_response = stream_content

        if tool_calls:
            assistant_tool_msg = {"role": "assistant", "tool_calls": tool_calls, "content": None, "timestamp": time.time()}
            st.session_state.messages.append(assistant_tool_msg)

            for tc in tool_calls:
                func_name = tc["function"]["name"]
                func_args = json.loads(tc["function"]["arguments"])
                func = execute_map.get(func_name)
                if func:
                    result = func(func_args)
                else:
                    result = f"技能 {func_name} 未找到"
                st.session_state.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                    "timestamp": time.time()
                })
                with st.chat_message("tool"):
                    st.caption(f"🔧 {func_name} → {result}")

            messages_for_api = []
            if system_content:
                messages_for_api.append({"role": "system", "content": system_content})
            api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
            messages_for_api.extend(api_messages)

            final_response = ""
            response2 = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages_for_api,
                stream=True
            )
            for chunk in response2:
                delta = chunk.choices[0].delta
                if delta.content:
                    final_response += delta.content
            full_response = final_response

        # 应用特效并打字机输出
        if full_response:
            typo = st.session_state.oc_typo_rate
            emoji = st.session_state.oc_emoji_rate
            punct = st.session_state.oc_special_punct
            custom_dict = st.session_state.oc_custom_typo_dict
            speed = st.session_state.oc_typing_speed

            processed = apply_oc_text_effects(full_response, typo, emoji, punct, custom_dict)
            typewriter_effect(message_placeholder, processed, speed)
            st.session_state.messages.append({
                "role": "assistant",
                "content": processed,
                "timestamp": time.time()
            })
        else:
            st.session_state.messages.append({
                "role": "assistant",
                "content": "",
                "timestamp": time.time()
            })
            message_placeholder.empty()
