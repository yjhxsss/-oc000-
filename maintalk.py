import streamlit as st
import openai
import json
import os
from pathlib import Path
import importlib
import pkgutil
import skills

# ---------- OC 文件操作 ----------
OC_PROFILES_DIR = Path("oc_profiles")
OC_PROFILES_DIR.mkdir(exist_ok=True)

def load_oc_profile(oc_id):
    """根据密码（即文件名，不含扩展名）加载 OC 设定"""
    file_path = OC_PROFILES_DIR / f"{oc_id}.json"
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_oc_profile(oc_id, data):
    """保存 OC 设定到对应文件（oc_id 为密码/文件名）"""
    file_path = OC_PROFILES_DIR / f"{oc_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
    "oc_id": None,
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
        "🔐 输入 OC 密码（十进制数字，对应 oc_profiles/ 下的文件名）",
        value=st.session_state.oc_password,
        placeholder="例如：26060501",
        help="密码即为 OC 配置文件的名称（不含 .json）"
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
        # 直接使用密码作为文件名加载 OC
        profile = load_oc_profile(password)
        if profile:
            st.session_state.oc_id = password
            st.session_state.oc_name = profile.get("name", "未命名")
            st.session_state.oc_base_prompt = profile.get("base_prompt", "")
            st.session_state.oc_forced_rules = profile.get("forced_rules", [])
            st.session_state.oc_material = profile.get("material", None)
            st.session_state.oc_password_error = ""
            # 切换 OC 时清空历史
            if st.session_state.prev_oc_id != password:
                st.session_state.messages = []
            st.session_state.prev_oc_id = password
        else:
            st.session_state.oc_id = None
            st.session_state.oc_password_error = f"未找到 OC 文件 {password}.json"

# 显示密码错误或当前 OC
if st.session_state.oc_password_error:
    st.error(st.session_state.oc_password_error)
elif st.session_state.oc_id is not None:
    st.caption(f"当前角色：{st.session_state.oc_name} (ID: {st.session_state.oc_id})")

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

        # 加载素材（如果 OC 指定了 material 字段）
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
    # 检查必要条件
    api_key = get_api_key()
    if not api_key:
        st.error("未检测到 API Key，请在 `.streamlit/secrets.toml` 或环境变量中设置 `DEEPSEEK_API_KEY`")
        st.stop()
    if st.session_state.oc_id is None:
        st.error("请先输入有效的 OC 密码")
        st.stop()

    # 用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 技能加载
    tools, execute_map = load_skills()
    tools = tools if tools else None

    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    system_content = build_system_content()
    messages_for_api = []
    if system_content:
        messages_for_api.append({"role": "system", "content": system_content})
    messages_for_api.extend(st.session_state.messages)

    # 第一次请求（流式 + 工具调用收集）
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

        # 处理工具调用
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

            # 第二次请求，生成最终回答
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
