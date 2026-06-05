import streamlit as st
import openai
import json
import os
import time
import random
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import importlib
import pkgutil
import skills

# ===================== 62进制工具 =====================
CHARS62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CHAR_TO_INT = {c: i for i, c in enumerate(CHARS62)}

def decode_62(s):
    num = 0
    for ch in s:
        if ch not in CHAR_TO_INT:
            raise ValueError(f"非法字符 '{ch}'")
        num = num * 62 + CHAR_TO_INT[ch]
    return num

def encode_62(n):
    if n == 0:
        return CHARS62[0]
    res = []
    while n > 0:
        n, rem = divmod(n, 62)
        res.append(CHARS62[rem])
    return ''.join(reversed(res))

# ===================== OC 文件操作 =====================
OC_PROFILES_DIR = Path("oc_profiles")
OC_PROFILES_DIR.mkdir(exist_ok=True)

def load_oc_profile(oc_id):
    file_path = OC_PROFILES_DIR / f"{oc_id}.json"
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

# ===================== 技能动态加载 =====================
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

# ===================== API Key =====================
def get_api_key():
    try:
        return st.secrets["DEEPSEEK_API_KEY"]
    except (KeyError, FileNotFoundError):
        return os.environ.get("DEEPSEEK_API_KEY", None)

# ===================== 错别字风格库 =====================
TYPO_STYLES = {
    "cute": {"是":"系","我":"窝","你":"泥","很":"狠","的":"哒","了":"啦","吗":"嘛","什么":"啥","怎么":"咋","没有":"木有","喜欢":"稀饭","吃":"恰","不":"卜","知道":"造"},
    "cool": {"什么":"啥","怎么":"怎","没有":"无","知道":"知","不要":"别"},
    "classical": {"我":"吾","你":"汝","很":"甚","的":"之","是":"乃","吗":"乎"},
    "dialect": {"什么":"啥子","怎么":"咋个","没有":"冇","你":"恁","我":"俺"},
    "lazy": {"这样":"酱","那样":"酿","不要":"表","什么":"啥","知道":"造"}
}
DEFAULT_TYPO_DICT = {"什么":"啥","怎么":"咋","没有":"没","知道":"知","不要":"别"}

def get_typo_dict():
    custom = st.session_state.get("oc_custom_typo_dict")
    if custom:
        return custom
    style = st.session_state.get("oc_typo_style")
    if style == "random":
        styles = [s for s in TYPO_STYLES.keys() if s != "random"]
        return TYPO_STYLES[random.choice(styles)]
    if style in TYPO_STYLES:
        return TYPO_STYLES[style]
    return DEFAULT_TYPO_DICT

# ===================== 颜文字库 =====================
KAOMOJI_LIST = [
    "(◕ᴗ◕✿)","(≧◡≦)","(◍•ᴗ•◍)","(｡•̀ᴗ-)✧","(◔‿◔)",
    "(๑•̀ㅂ•́)و✧","( •̀ ω •́ )✧","(*/ω＼*)","(´• ω •`)",
    "(╹ڡ╹ )","(人 •͈ᴗ•͈)","(☆▽☆)","(✯ᴗ✯)",
    "ヾ(⌐■_■)ノ♪","~(˘▾˘~)","✧(｡•̀ᴗ-)✧",
    "(づ｡◕‿‿◕｡)づ","(*^▽^*)","(≧∇≦)ﾉ","(⌒‿⌒)"
]

# ===================== 文本特效 =====================
def apply_oc_text_effects(text, typo_rate, emoji_rate, special_punct):
    if not text:
        return text
    typo_dict = get_typo_dict()
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

# ===================== 打字机效果 =====================
def typewriter_effect(placeholder, full_text, speed):
    displayed = ""
    for ch in full_text:
        displayed += ch
        placeholder.markdown(displayed + "▌")
        time.sleep(speed)
    placeholder.markdown(full_text)

# ===================== 分段连续回复（新：独立气泡） =====================
def render_segments(final_text, base_speed, panic_mode):
    """
    将文本分段，每段用独立聊天气泡展示。
    返回 True 表示已分段处理（已添加消息到历史），主流程不再重复添加。
    """
    if not final_text or panic_mode.get("segment_interval", 0) == 0:
        return False  # 不需要分段

    max_len = panic_mode.get("max_segment_length", 30)
    interval = panic_mode.get("segment_interval", 1.5)
    speed = base_speed * panic_mode.get("speed_multiplier", 1.0)

    # 切分段落
    segments = []
    remaining = final_text
    while remaining:
        if len(remaining) <= max_len:
            segments.append(remaining)
            break
        chunk = remaining[:max_len]
        cut = -1
        for punct in ["。", "！", "？", "!", "?", ".", " "]:
            pos = chunk.rfind(punct)
            if pos > cut:
                cut = pos
        if cut == -1:
            cut = max_len - 1
        segments.append(remaining[:cut+1])
        remaining = remaining[cut+1:].lstrip()

    # 逐个气泡输出并存入历史
    for i, seg in enumerate(segments):
        with st.chat_message("assistant"):
            placeholder = st.empty()
            typewriter_effect(placeholder, seg, speed)
        # 存入历史记录
        st.session_state.messages.append({
            "role": "assistant",
            "content": seg,
            "timestamp": now_beijing_timestamp()
        })
        if i != len(segments) - 1:
            time.sleep(interval)
    return True  # 已处理

# ===================== 聊天气泡CSS =====================
def inject_css():
    st.markdown("""
        <style>
        .stChatMessageContainer {
            display: flex;
            flex-direction: column;
        }
        div[data-testid="stChatMessage"][aria-label*="user"] {
            align-self: flex-end;
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
            border: 2px solid #42a5f5;
            border-radius: 20px;
            padding: 10px 16px;
            margin: 8px 0;
            max-width: 80%;
            box-shadow: 0 4px 12px rgba(66, 165, 245, 0.2);
            word-wrap: break-word;
        }
        div[data-testid="stChatMessage"][aria-label*="assistant"] {
            align-self: flex-start;
            background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
            border: 2px solid #ffa726;
            border-radius: 20px;
            padding: 10px 16px;
            margin: 8px 0;
            max-width: 80%;
            box-shadow: 0 4px 12px rgba(255, 167, 38, 0.2);
            word-wrap: break-word;
        }
        .read-status {
            font-size: 0.8em;
            color: #666;
            margin-top: 4px;
            text-align: right;
        }
        .time-divider {
            text-align: center;
            color: #999;
            font-size: 0.85em;
            margin: 16px 0 8px 0;
        }
        </style>
    """, unsafe_allow_html=True)

# ===================== 页面配置 =====================
st.set_page_config(page_title="OC 聊天助手", page_icon="🎭")
inject_css()

# ===================== Session State =====================
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
    "oc_typo_style": None,
    "oc_unread_probability": 0.08,
    "oc_consecutive_multiplier": 1.0,
    "consecutive_unread_count": 0,
    "oc_ignore_keywords": [],
    "oc_urgency_threshold": 0.7,
    "oc_panic_mode": {},
    "oc_auto_prob": 0.0,
    "oc_auto_delay_min": 30,
    "oc_auto_delay_max": 120,
    "oc_auto_prompt": "你可以偶尔主动和对方说点有趣的事情。",
    "auto_timer_end": None,
    "auto_timer_active": False,
    "auto_timer_trigger_handled": False,
    "oc_password_error": "",
    "prev_oc_id": None,
    "pending_reply": False,
    "last_user_prompt": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

def now_beijing_timestamp():
    return datetime.now(ZoneInfo("Asia/Shanghai")).timestamp()

# ===================== 动态标题 =====================
if st.session_state.oc_name:
    st.title(f"🎭 {st.session_state.oc_name}")
else:
    st.title("🎭 OC 聊天助手")

# ===================== 密码与清空 =====================
col1, col2 = st.columns([4, 1])
with col1:
    password = st.text_input("🔐 OC 密码", value=st.session_state.oc_password)
with col2:
    st.write("")
    if st.button("🗑️ 清空对话"):
        for key in defaults:
            if key in st.session_state:
                st.session_state[key] = defaults[key]
        st.rerun()

# 密码处理（保持不变）
if password != st.session_state.oc_password:
    st.session_state.oc_password = password
    if password.strip() == "":
        for key in ["oc_id","oc_name","oc_base_prompt","oc_forced_rules",
                    "oc_material","oc_custom_typo_dict","oc_typo_style","oc_password_error"]:
            st.session_state[key] = None if key != "oc_forced_rules" else []
        st.session_state.oc_typing_speed = 0.05
        st.session_state.oc_typo_rate = 0.0
        st.session_state.oc_emoji_rate = 0.0
        st.session_state.oc_special_punct = False
        st.session_state.oc_unread_probability = 0.08
        st.session_state.oc_consecutive_multiplier = 1.0
        st.session_state.consecutive_unread_count = 0
        st.session_state.oc_ignore_keywords = []
        st.session_state.oc_urgency_threshold = 0.7
        st.session_state.oc_panic_mode = {}
        st.session_state.oc_auto_prob = 0.0
        st.session_state.auto_timer_active = False
        st.session_state.auto_timer_end = None
        st.session_state.messages = []
        st.session_state.pending_reply = False
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
                st.session_state.oc_typo_style = profile.get("typo_style", None)
                if "unread_probability" in profile:
                    st.session_state.oc_unread_probability = profile["unread_probability"]
                elif "reply_probability" in profile:
                    st.session_state.oc_unread_probability = 1.0 - profile["reply_probability"]
                else:
                    st.session_state.oc_unread_probability = 0.08
                st.session_state.oc_consecutive_multiplier = profile.get("consecutive_unread_multiplier", 1.0)
                st.session_state.oc_ignore_keywords = profile.get("ignore_keywords", [])
                st.session_state.oc_urgency_threshold = profile.get("urgency_threshold", 0.7)
                st.session_state.oc_panic_mode = profile.get("panic_mode", {})
                st.session_state.oc_auto_prob = profile.get("auto_message_probability", 0.0)
                st.session_state.oc_auto_delay_min = profile.get("auto_message_delay_min", 30)
                st.session_state.oc_auto_delay_max = profile.get("auto_message_delay_max", 120)
                st.session_state.oc_auto_prompt = profile.get("auto_message_prompt", "你可以偶尔主动和对方说点有趣的事情。")
                st.session_state.oc_password_error = ""
                st.session_state.consecutive_unread_count = 0
                if st.session_state.prev_oc_id != oc_id:
                    st.session_state.messages = []
                    st.session_state.auto_timer_active = False
                    st.session_state.auto_timer_end = None
                    st.session_state.pending_reply = False
                st.session_state.prev_oc_id = oc_id
            else:
                st.session_state.oc_id = None
                st.session_state.oc_password_error = f"未找到 OC 文件 {oc_id}.json"
        except ValueError as e:
            st.session_state.oc_id = None
            st.session_state.oc_password_error = str(e)

if st.session_state.oc_password_error:
    st.error("❌ 密码无效")
elif st.session_state.oc_id is not None:
    st.success("✅ 密码有效")

# ===================== System Prompt =====================
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

# ===================== 消息格式转换 =====================
def prepare_messages_for_api(session_messages):
    api_messages = []
    for msg in session_messages:
        if msg.get("silent"):
            continue
        new_msg = {"role": msg["role"]}
        if "content" in msg and msg["content"] is not None:
            new_msg["content"] = msg["content"]
        if "tool_calls" in msg:
            new_msg["tool_calls"] = msg["tool_calls"]
        if "tool_call_id" in msg:
            new_msg["tool_call_id"] = msg["tool_call_id"]
        api_messages.append(new_msg)
    return api_messages

# ===================== 消息时间分隔渲染 =====================
def render_messages_with_time():
    prev_time = None
    for i, msg in enumerate(st.session_state.messages):
        if msg["role"] == "tool" or msg.get("silent"):
            continue
        if msg["role"] == "assistant" and not msg.get("content"):
            continue

        is_read = False
        if msg["role"] == "user":
            if msg.get("read"):
                is_read = True
            else:
                for j in range(i + 1, len(st.session_state.messages)):
                    nxt = st.session_state.messages[j]
                    if nxt["role"] in ("assistant", "tool"):
                        is_read = True
                        break
                    if nxt["role"] == "user":
                        break

        show_time = False
        if prev_time is None:
            show_time = True
        else:
            diff = msg["timestamp"] - prev_time
            if diff >= 1200:
                show_time = True
        if show_time:
            dt = datetime.fromtimestamp(msg["timestamp"], tz=ZoneInfo("Asia/Shanghai"))
            time_str = dt.strftime("%m月%d日 %H:%M")
            st.markdown(f'<div class="time-divider">📅 {time_str}</div>', unsafe_allow_html=True)
            prev_time = msg["timestamp"]

        if msg["role"] == "user":
            read_text = "已读" if is_read else "未读"
            bubble_html = f"""
            <div class="user-bubble">{msg["content"]}<br>
            <span class="read-status">{read_text}</span></div>
            """
            st.markdown(bubble_html, unsafe_allow_html=True)
        else:
            bubble_html = f"""
            <div class="assistant-bubble">{msg["content"]}</div>
            """
            st.markdown(bubble_html, unsafe_allow_html=True)

# ===================== 主动消息定时器（前端JS） =====================
def inject_auto_timer_js():
    if not st.session_state.get("auto_timer_active") or st.session_state.auto_timer_trigger_handled:
        return
    timer_end = st.session_state.auto_timer_end
    if timer_end is None:
        return
    remaining = max(0, int(timer_end - time.time()))
    st.text_input("", key="auto_timer_trigger", label_visibility="collapsed")
    js_code = f"""
    <script>
    setTimeout(() => {{
        const input = window.parent.document.querySelector('input[aria-label=""]');
        if (input) {{
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(input, 'trigger_' + Date.now());
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}
    }}, {remaining * 1000});
    </script>
    """
    st.components.v1.html(js_code, height=0)

inject_auto_timer_js()

# 检测定时器触发
if st.session_state.get("auto_timer_trigger") and not st.session_state.auto_timer_trigger_handled:
    trigger_val = st.session_state.auto_timer_trigger
    if trigger_val.startswith("trigger_"):
        if st.session_state.auto_timer_active and st.session_state.auto_timer_end and time.time() >= st.session_state.auto_timer_end:
            st.session_state.auto_timer_active = False
            st.session_state.auto_timer_end = None
            api_key = get_api_key()
            if api_key:
                client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
                system = build_system_content()
                recent = st.session_state.messages[-6:]
                msgs = []
                if system:
                    msgs.append({"role":"system","content":system})
                msgs.extend(prepare_messages_for_api(recent))
                msgs.append({"role":"user","content":f"[内部指令] {st.session_state.oc_auto_prompt} 请直接说出一句主动发起的话题，简短自然。"})
                try:
                    resp = client.chat.completions.create(model="deepseek-chat", messages=msgs, temperature=1.1, max_tokens=100)
                    content = resp.choices[0].message.content
                except:
                    content = "（突然想找你聊聊天…）"
                if content:
                    typo = st.session_state.oc_typo_rate
                    emoji = st.session_state.oc_emoji_rate
                    punct = st.session_state.oc_special_punct
                    processed = apply_oc_text_effects(content, typo, emoji, punct)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": processed,
                        "timestamp": now_beijing_timestamp()
                    })
        st.session_state.auto_timer_trigger_handled = True
        st.rerun()

# ===================== 提前标记已读 =====================
if st.session_state.pending_reply:
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        st.session_state.messages[-1]["read"] = True

# 渲染历史消息
render_messages_with_time()

# ===================== 聊天输入处理 =====================
if prompt := st.chat_input("输入消息..."):
    api_key = get_api_key()
    if not api_key:
        st.error("未配置 API Key")
        st.stop()
    if st.session_state.oc_id is None:
        st.error("请先输入有效的 OC 密码")
        st.stop()

    # 取消定时器
    st.session_state.auto_timer_active = False
    st.session_state.auto_timer_end = None
    st.session_state.auto_timer_trigger_handled = False

    user_msg = {"role": "user", "content": prompt, "read": False, "timestamp": now_beijing_timestamp()}
    st.session_state.messages.append(user_msg)
    st.session_state.last_user_prompt = prompt
    st.session_state.pending_reply = True
    st.rerun()

if st.session_state.pending_reply:
    api_key = get_api_key()
    if not api_key:
        st.error("未配置 API Key")
        st.stop()

    prompt = st.session_state.last_user_prompt
    should_reply = True
    if st.session_state.oc_ignore_keywords:
        if any(kw in prompt for kw in st.session_state.oc_ignore_keywords):
            should_reply = False

    if should_reply:
        base_unread = st.session_state.oc_unread_probability
        multiplier = st.session_state.oc_consecutive_multiplier
        consecutive = st.session_state.consecutive_unread_count
        effective_unread = base_unread * (multiplier ** consecutive)
        effective_unread = min(1.0, effective_unread)
        if random.random() < effective_unread:
            should_reply = False
            st.session_state.consecutive_unread_count += 1
        else:
            st.session_state.consecutive_unread_count = 0

    if not should_reply:
        st.session_state.pending_reply = False
        st.rerun()

    # ---------- 正常回复流程 ----------
    tools, execute_map = load_skills()
    tools = tools if tools else None

    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    system_content = build_system_content()
    messages_for_api = []
    if system_content:
        messages_for_api.append({"role": "system", "content": system_content})
    messages_for_api.extend(prepare_messages_for_api(st.session_state.messages))

    # 显示“对方正在输入中...”
    with st.chat_message("assistant"):
        typing_placeholder = st.empty()
        typing_placeholder.markdown("对方正在输入中...")

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
        assistant_tool_msg = {"role": "assistant", "content": None, "tool_calls": tool_calls, "timestamp": now_beijing_timestamp()}
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
                "timestamp": now_beijing_timestamp()
            })
            with st.chat_message("tool"):
                st.caption(f"🔧 {func_name} → {result}")

        messages_for_api = []
        if system_content:
            messages_for_api.append({"role": "system", "content": system_content})
        messages_for_api.extend(prepare_messages_for_api(st.session_state.messages))
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
        full_response = final_response if final_response else "（工具调用完成，但需要整理语言...）"

    # 清除“对方正在输入中...”
    typing_placeholder.empty()

    if full_response and full_response.strip():
        urgency = 0.0
        urgency_match = re.search(r"\[URGENCY:(\d+\.?\d*)\]", full_response)
        if urgency_match:
            urgency = float(urgency_match.group(1))
            full_response = re.sub(r"\[URGENCY:\d+\.?\d*\]", "", full_response).strip()

        typo = st.session_state.oc_typo_rate
        emoji = st.session_state.oc_emoji_rate
        punct = st.session_state.oc_special_punct
        speed = st.session_state.oc_typing_speed
        panic_mode = st.session_state.oc_panic_mode

        if urgency >= st.session_state.oc_urgency_threshold and panic_mode:
            typo = typo * panic_mode.get("typo_multiplier", 1.0)
            processed = apply_oc_text_effects(full_response, typo, emoji, punct)
            # 分段输出（内部会添加消息到历史并展示气泡）
            segmented = render_segments(processed, speed, panic_mode)
            if not segmented:
                # 如果不分段，则走普通流程
                with st.chat_message("assistant"):
                    placeholder = st.empty()
                    typewriter_effect(placeholder, processed, speed)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": processed,
                    "timestamp": now_beijing_timestamp()
                })
        else:
            processed = apply_oc_text_effects(full_response, typo, emoji, punct)
            with st.chat_message("assistant"):
                placeholder = st.empty()
                typewriter_effect(placeholder, processed, speed)
            st.session_state.messages.append({
                "role": "assistant",
                "content": processed,
                "timestamp": now_beijing_timestamp()
            })
    else:
        # 空回复不添加气泡
        pass

    # 启动主动消息定时器
    if st.session_state.oc_auto_prob > 0:
        if random.random() < st.session_state.oc_auto_prob:
            delay = random.randint(st.session_state.oc_auto_delay_min, st.session_state.oc_auto_delay_max)
            st.session_state.auto_timer_end = now_beijing_timestamp() + delay
            st.session_state.auto_timer_active = True
        else:
            st.session_state.auto_timer_active = False
            st.session_state.auto_timer_end = None
    else:
        st.session_state.auto_timer_active = False

    st.session_state.pending_reply = False
    st.rerun()
