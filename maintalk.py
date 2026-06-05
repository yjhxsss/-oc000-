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

# ===================== 按段落分段发送（总是执行） =====================
def render_paragraphs(text, speed, segment_interval=0.8):
    """将文本按换行符分割成段落，每个段落一个聊天气泡，依次输出。"""
    paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
    if not paragraphs:
        return
    for i, para in enumerate(paragraphs):
        with st.chat_message("assistant"):
            placeholder = st.empty()
            typewriter_effect(placeholder, para, speed)
        # 存入历史记录
        st.session_state.messages.append({
            "role": "assistant",
            "content": para,
            "timestamp": now_beijing_timestamp()
        })
        if i != len(paragraphs) - 1:
            time.sleep(segment_interval)

# ===================== CSS 布局 =====================
def inject_css():
    st.markdown("""
        <style>
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) {
            display: flex !important;
            justify-content: flex-end !important;
            flex-direction: row-reverse !important;
        }
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-assistant"]) {
            display: flex !important;
            justify-content: flex-start !important;
        }
        div[data-testid="stChatMessage"] [data-testid="stChatMessageContent"] {
            max-width: 80%;
            border-radius: 20px;
            padding: 10px 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] {
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
            border: 2px solid #42a5f5;
            border-radius: 20px 6px 20px 20px;
            margin-right: 0;
            margin-left: 8px;
        }
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-assistant"]) [data-testid="stChatMessageContent"] {
            background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
            border: 2px solid #ffa726;
            border-radius: 6px 20px 20px 20px;
            margin-left: 0;
            margin-right: 8px;
        }
        .time-divider { text-align:center; color:#999; font-size:0.85em; margin:16px 0 8px 0; }
        .typing-indicator { text-align:left; color:#888; font-style:italic; margin:8px 0; }
        </style>
    """, unsafe_allow_html=True)

# ===================== 页面配置 =====================
st.set_page_config(page_title="OC 聊天助手", page_icon="🎭")
inject_css()

# ===================== Session State 增加字段 =====================
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
    "pending_auto_content": None,        # 已经生成好的主动消息内容
    "auto_message_ready": False,         # 是否有准备好的主动消息
    "ai_output_in_progress": False,      # AI 是否正在输出（打字机进行中）
    "pending_user_input": None,          # 用户在 AI 输出时发送的消息暂存
    "oc_password_error": "",
    "prev_oc_id": None,
    "pending_reply": False,
    "last_user_prompt": None,
    "oc_use_ai_urgency": False,
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

# 密码处理（省略，保持之前完整代码的逻辑不变）
# ...（复制之前的密码处理部分，确保加载所有字段）...
# 由于篇幅，此处省略，请使用前一个完整版中的密码处理代码，并添加新字段加载：
# st.session_state.pending_auto_content = None
# st.session_state.auto_message_ready = False
# st.session_state.ai_output_in_progress = False
# st.session_state.pending_user_input = None
# st.session_state.oc_auto_prob = profile.get("auto_message_probability", 0.0) 等

# 注意：实际部署时需补全完整的密码处理部分，这里假设用户会替换为之前的密码处理块，并加上新字段。

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
            with st.chat_message("user"):
                st.markdown(msg["content"])
                st.caption("已读" if is_read else "未读")
        else:
            with st.chat_message("assistant"):
                st.markdown(msg["content"])

# ===================== 主动消息提示按钮 =====================
def show_auto_message_prompt():
    if st.session_state.get("auto_message_ready") and not st.session_state.get("ai_output_in_progress"):
        col_btn, col_empty = st.columns([1, 3])
        with col_btn:
            if st.button("💬 对方想跟你说话", key="auto_btn"):
                # 发送主动消息
                content = st.session_state.pending_auto_content
                if content:
                    typo = st.session_state.oc_typo_rate
                    emoji = st.session_state.oc_emoji_rate
                    punct = st.session_state.oc_special_punct
                    speed = st.session_state.oc_typing_speed
                    processed = apply_oc_text_effects(content, typo, emoji, punct)
                    # 段落发送
                    render_paragraphs(processed, speed)
                st.session_state.auto_message_ready = False
                st.session_state.pending_auto_content = None
                st.rerun()

# ===================== 处理暂存的用户输入 =====================
def process_pending_user_input():
    """如果在 AI 输出期间有用户输入，现在处理它（等 AI 输出完成后调用）"""
    if st.session_state.get("pending_user_input"):
        prompt = st.session_state.pending_user_input
        st.session_state.pending_user_input = None
        # 模拟正常用户输入流程，但跳过用户主动消息按钮的渲染（因为已处理）
        # 直接进入 pending_reply 逻辑
        user_msg = {"role": "user", "content": prompt, "read": False, "timestamp": now_beijing_timestamp()}
        st.session_state.messages.append(user_msg)
        st.session_state.last_user_prompt = prompt
        st.session_state.pending_reply = True
        st.rerun()

# ===================== 聊天主逻辑 =====================
# 展示主动消息按钮（如果适用）
show_auto_message_prompt()

# 渲染历史消息
render_messages_with_time()

# 检查是否有待处理的用户输入（来自 AI 输出期间的打断）
# 这需要放在输入处理之前，但为了避免干扰，我们在 rerun 时优先处理
# 通过检查 ai_output_in_progress 和 pending_user_input
if st.session_state.get("pending_user_input") and not st.session_state.get("ai_output_in_progress"):
    process_pending_user_input()

# 用户输入
prompt = st.chat_input("输入消息...")

if prompt:
    api_key = get_api_key()
    if not api_key or st.session_state.oc_id is None:
        st.error("请先输入有效的密码并配置 API Key")
        st.stop()

    # 如果在 AI 输出过程中，用户发送消息，暂存起来
    if st.session_state.get("ai_output_in_progress"):
        st.session_state.pending_user_input = prompt
        st.warning("AI 正在输出中，你的消息将在稍后处理。")
        st.stop()  # 停止本次运行，等待输出完成后的 rerun

    # 正常处理流程：先检查是否有准备好的主动消息，如果有，在用户消息前发送
    if st.session_state.get("auto_message_ready"):
        # 先发送主动消息
        content = st.session_state.pending_auto_content
        if content:
            typo = st.session_state.oc_typo_rate
            emoji = st.session_state.oc_emoji_rate
            punct = st.session_state.oc_special_punct
            speed = st.session_state.oc_typing_speed
            processed = apply_oc_text_effects(content, typo, emoji, punct)
            render_paragraphs(processed, speed)
        st.session_state.auto_message_ready = False
        st.session_state.pending_auto_content = None
        # 然后继续处理用户消息，不要 rerun 以避免重复渲染

    # 添加用户消息
    user_msg = {"role": "user", "content": prompt, "read": False, "timestamp": now_beijing_timestamp()}
    st.session_state.messages.append(user_msg)
    st.session_state.last_user_prompt = prompt
    st.session_state.pending_reply = True
    st.rerun()

if st.session_state.pending_reply and not st.session_state.get("ai_output_in_progress"):
    api_key = get_api_key()
    # ...（正常回复生成流程，但需要修改输出部分使用 render_paragraphs 代替原来的整段输出）...

    # 设置 ai_output_in_progress = True，开始输出
    st.session_state.ai_output_in_progress = True

    # 生成回复
    # ...（省略 API 调用，与之前相同）...

    # 假设 full_response 已获得
    if full_response and full_response.strip():
        # 去除可能的标记
        full_response = re.sub(r"\[URGENCY:\d+\.?\d*\]", "", full_response).strip()
        typo = st.session_state.oc_typo_rate
        emoji = st.session_state.oc_emoji_rate
        punct = st.session_state.oc_special_punct
        speed = st.session_state.oc_typing_speed
        processed = apply_oc_text_effects(full_response, typo, emoji, punct)
        # 总是按段落发送
        render_paragraphs(processed, speed)

    # 输出结束
    st.session_state.ai_output_in_progress = False
    st.session_state.pending_reply = False

    # 主动消息准备：如果抽中，生成内容但不立即显示，设置 auto_message_ready
    if st.session_state.oc_auto_prob > 0:
        if random.random() < st.session_state.oc_auto_prob:
            # 生成主动消息内容（模拟之前的调用）
            # ...（使用 API 生成）...
            auto_content = "这是一条主动消息示例"  # 实际调用API
            st.session_state.pending_auto_content = auto_content
            st.session_state.auto_message_ready = True
        else:
            st.session_state.auto_message_ready = False
    else:
        st.session_state.auto_message_ready = False

    # 如果有暂存的用户输入，触发处理
    if st.session_state.pending_user_input:
        process_pending_user_input()
    else:
        st.rerun()
