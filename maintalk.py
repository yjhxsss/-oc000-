import streamlit as st
import openai
import json
import os
import time
import random
import re
from pathlib import Path
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

# ---------- 错别字替换库 ----------
TYPO_DICT = {
    "是": "系",
    "我": "窝",
    "你": "泥",
    "很": "狠",
    "的": "哒",
    "了": "啦",
    "吗": "嘛",
    "什么": "啥",
    "怎么": "咋",
    "没有": "木有",
    "喜欢": "稀饭",
    "吃": "恰",
    "不": "卜",
    "知道": "造",
    "可爱": "可耐",
    "非常": "灰常",
    "大家": "大嘎",
    "同学": "童鞋",
    "朋友": "盆友",
    "晚安": "晚安鸭",
    "开心": "开森",
    "今天": "今颠",
    "突然": "突兰",
    "为什么": "为森么"
}

# 颜文字库
KAOMOJI_LIST = [
    "(◕ᴗ◕✿)",
    "(≧◡≦)",
    "(◍•ᴗ•◍)",
    "(｡•̀ᴗ-)✧",
    "(◔‿◔)",
    "(๑•̀ㅂ•́)و✧",
    "( •̀ ω •́ )✧",
    "(*/ω＼*)",
    "(´• ω •`)",
    "(╹ڡ╹ )",
    "(人 •͈ᴗ•͈)",
    "(☆▽☆)",
    "(✯ᴗ✯)",
    "ヾ(⌐■_■)ノ♪",
    "~(˘▾˘~)",
    "✧(｡•̀ᴗ-)✧",
    "(づ｡◕‿‿◕｡)づ",
    "(*^▽^*)",
    "(≧∇≦)ﾉ",
    "(⌒‿⌒)"
]

# 特殊标点替换映射
PUNCT_MAP = {
    ".": "～",
    ",": "，",
    "!": "！",
    "?": "？",
    ";": "…",
    ":": "：",
    "。": "～",
    "！": "！！",
    "？": "？？"
}

# ---------- 文本后处理（错别字、颜文字、特殊标点）----------
def apply_oc_text_effects(text, typo_rate, emoji_rate, special_punct):
    if not text:
        return text

    # 特殊标点替换（在文字替换前处理，避免干扰）
    if special_punct:
        new_text = ""
        for ch in text:
            # 以一定概率替换为活泼符号
            if ch in PUNCT_MAP and random.random() < 0.5:
                new_text += random.choice(["～", "！", "？", "…", "❤️"])
            else:
                new_text += ch
        text = new_text

    # 错别字替换（按字概率）
    if typo_rate and typo_rate > 0:
        words = list(text)  # 逐字处理
        for i, ch in enumerate(words):
            if ch in TYPO_DICT and random.random() < typo_rate:
                # 替换为谐音字
                words[i] = TYPO_DICT[ch]
            # 也支持双字词，简单处理：如果当前字是双字词的首字，检查后面字
        text = "".join(words)
        # 再做简单的二字词替换（避免单字替换破坏词）
        for k, v in TYPO_DICT.items():
            if len(k) == 2 and k in text:
                if random.random() < typo_rate:
                    text = text.replace(k, v, 1)  # 只替换一次避免循环

    # 颜文字插入（按句子概率）
    if emoji_rate and emoji_rate > 0:
        sentences = re.split(r'(?<=[。！？.!?…])', text)
        new_sentences = []
        for sent in sentences:
            if sent and random.random() < emoji_rate:
                kaomoji = random.choice(KAOMOJI_LIST)
                # 随机插在句首或句尾
                if random.random() < 0.5:
                    sent = kaomoji + sent
                else:
                    sent = sent + kaomoji
            new_sentences.append(sent)
        text = "".join(new_sentences)

    return text

# ---------- 打字机效果显示 ----------
def typewriter_effect(placeholder, full_text, speed):
    """逐字显示文本，模拟打字效果"""
    displayed = ""
    for ch in full_text:
        displayed += ch
        placeholder.markdown(displayed + "▌")
        time.sleep(speed)
    placeholder.markdown(full_text)

# ---------- 页面配置 ----------
st.set_page_config(page_title="OC 聊天助手", page_icon="🎭")

# ---------- Session State 初始化 ----------
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

# ---------- 顶部密码输入与清空 ----------
col1, col2 = st.columns([4, 1])
with col1:
    password = st.text_input(
        "🔐 输入 OC 密码（62进制）",
        value=st.session_state.oc_password,
        placeholder="例如：1lLW1",
        help=f"密码由数字、大写字母、小写字母组成"
    )
with col2:
    st.write("")
    if st.button("🗑️ 清空对话"):
        st.session_state.messages = []
        st.rerun()

# 处理密码输入变化
if password != st.session_state.oc_password:
    st.session_state.oc_password = password
    if password.strip() == "":
        st.session_state.oc_id = None
        st.session_state.oc_name = ""
        st.session_state.oc_base_prompt = ""
        st.session_state.oc_forced_rules = []
        st.session_state.oc_material = None
        st.session_state.oc_typing_speed = 0.05
        st.session_state.oc_typo_rate = 0.0
        st.session_state.oc_emoji_rate = 0.0
        st.session_state.oc_special_punct = False
        st.session_state.oc_password_error = ""
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
                st.session_state.oc_password_error = ""
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
elif st.session_state.oc_id is not None:
    st.caption(f"当前角色：{st.session_state.oc_name} (编号: {st.session_state.oc_id})")

# ---------- 构建 System Prompt ----------
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

# ---------- 显示历史消息 ----------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------- 聊天输入 ----------
if prompt := st.chat_input("输入消息..."):
    api_key = get_api_key()
    if not api_key:
        st.error("未检测到 API Key，请在 `.streamlit/secrets.toml` 或环境变量中设置 `DEEPSEEK_API_KEY`")
        st.stop()
    if st.session_state.oc_id is None:
        st.error("请先输入有效的 OC 密码")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    tools, execute_map = load_skills()
    tools = tools if tools else None

    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    system_content = build_system_content()
    messages_for_api = []
    if system_content:
        messages_for_api.append({"role": "system", "content": system_content})
    messages_for_api.extend(st.session_state.messages)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
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
                # 流式时不应用效果，先显示纯文本（避免闪烁），最终再处理
                message_placeholder.markdown(stream_content + "▌")
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

        # 工具调用处理（如有）
        if tool_calls:
            assistant_tool_msg = {"role": "assistant", "tool_calls": tool_calls, "content": None}
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
                    "content": result
                })
                with st.chat_message("tool"):
                    st.caption(f"🔧 {func_name} → {result}")

            # 第二次请求获取最终回答
            messages_for_api = []
            if system_content:
                messages_for_api.append({"role": "system", "content": system_content})
            messages_for_api.extend(st.session_state.messages)

            with st.chat_message("assistant"):
                message_placeholder2 = st.empty()
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
                        message_placeholder2.markdown(final_response + "▌")
                full_response = final_response
                message_placeholder = message_placeholder2  # 复用后面的打字机效果

        # 应用 OC 特效并播放打字机效果
        if full_response:
            # 取出当前 OC 的效果参数
            typo = st.session_state.oc_typo_rate
            emoji = st.session_state.oc_emoji_rate
            punct = st.session_state.oc_special_punct
            speed = st.session_state.oc_typing_speed

            processed_text = apply_oc_text_effects(full_response, typo, emoji, punct)

            # 显示处理后的文本（打字机效果）
            typewriter_effect(message_placeholder, processed_text, speed)

            # 将最终的加工后文本存入历史（让下次请求也能看到效果后的内容）
            st.session_state.messages.append({"role": "assistant", "content": processed_text})
        else:
            # 无文字内容（极少情况）
            pass
