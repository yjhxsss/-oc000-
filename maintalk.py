import streamlit as st
import openai
import json
import os
from pathlib import Path
import importlib
import pkgutil
import skills

# ---------- 62进制工具 ----------
CHARS62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CHAR_TO_INT = {c: i for i, c in enumerate(CHARS62)}

def decode_62(s: str) -> int:
    """将62进制字符串解码为十进制整数"""
    num = 0
    for ch in s:
        if ch not in CHAR_TO_INT:
            raise ValueError(f"非法字符 '{ch}'，允许的字符：{CHARS62}")
        num = num * 62 + CHAR_TO_INT[ch]
    return num

def encode_62(n: int) -> str:
    """将十进制整数编码为62进制字符串"""
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
    """根据十进制编号加载 OC 设定"""
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

# ---------- 页面配置 ----------
st.set_page_config(page_title="OC 聊天助手", page_icon="🎭")
st.title("🎭 OC 聊天助手")

# ---------- Session State 初始化 ----------
defaults = {
    "messages": [],
    "oc_id": None,            # 十进制文件编号
    "oc_password": "",
    "oc_name": "",
    "oc_base_prompt": "",
    "oc_forced_rules": [],
    "oc_material": None,
    "oc_password_error": "",
    "prev_oc_id": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------- 顶部密码输入与清空 ----------
col1, col2 = st.columns([4, 1])
with col1:
    password = st.text_input(
        "🔐 输入 OC 密码（62进制）",
        value=st.session_state.oc_password,
        placeholder="例如：1LWf",
        help=f"密码由数字、大写字母、小写字母组成（共62个字符）"
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
        # 清空密码时重置 OC
        st.session_state.oc_id = None
        st.session_state.oc_name = ""
        st.session_state.oc_base_prompt = ""
        st.session_state.oc_forced_rules = []
        st.session_state.oc_material = None
        st.session_state.oc_password_error = ""
        st.session_state.messages = []
    else:
        try:
            # 62进制解码 -> 十进制文件编号
            oc_id = decode_62(password)
            profile = load_oc_profile(oc_id)
            if profile:
                st.session_state.oc_id = oc_id
                st.session_state.oc_name = profile.get("name", "未命名")
                st.session_state.oc_base_prompt = profile.get("base_prompt", "")
                st.session_state.oc_forced_rules = profile.get("forced_rules", [])
                st.session_state.oc_material = profile.get("material", None)
                st.session_state.oc_password_error = ""
                # 切换 OC 时清空历史
                if st.session_state.prev_oc_id != oc_id:
                    st.session_state.messages = []
                st.session_state.prev_oc_id = oc_id
            else:
                st.session_state.oc_id = None
                st.session_state.oc_password_error = f"未找到 OC 文件 {oc_id}.json"
        except ValueError as e:
            st.session_state.oc_id = None
            st.session_state.oc_password_error = str(e)

# 显示密码错误或当前 OC
if st.session_state.oc_password_error:
    st.error(st.session_state.oc_password_error)
elif st.session_state.oc_id is not None:
    st.caption(f"当前角色：{st.session_state.oc_name} (编号: {st.session_state.oc_id})")

# ---------- 构建 System Prompt（含素材）----------
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

        # 加载素材
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
            message_placeholder.markdown(full_response)

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
                message_placeholder2.markdown(final_response)
                full_response = final_response
                st.session_state.messages.append({"role": "assistant", "content": final_response})
        else:
            if full_response:
                st.session_state.messages.append({"role": "assistant", "content": full_response})
