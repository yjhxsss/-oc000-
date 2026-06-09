import streamlit as st
import openai
import json
import os
import time
import random
import re
import base64
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import importlib
import pkgutil
import skills

# ---------- 密码转换（数字循环偏移）----------
SHIFT = 1   # 偏移量，可修改

def encode_numeric(n_str, shift=SHIFT):
    res = []
    for ch in n_str:
        if '0' <= ch <= '9':
            res.append(str((int(ch) + shift) % 10))
        else:
            res.append(ch)
    return ''.join(res)

def decode_numeric(pw_str, shift=SHIFT):
    res = []
    for ch in pw_str:
        if '0' <= ch <= '9':
            res.append(str((int(ch) - shift) % 10))
        else:
            res.append(ch)
    return ''.join(res)

# ---------- OC 文件 ----------
OC_DIR = Path("oc_profiles")
OC_DIR.mkdir(exist_ok=True)

def load_oc(oc_id):
    f = OC_DIR / f"{oc_id}.json"
    if f.exists():
        with open(f, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return None

# ---------- 技能加载 ----------
@st.cache_resource
def load_skills():
    tools = []
    execs = {}
    for _, mod, _ in pkgutil.iter_modules(skills.__path__):
        if mod.startswith("_"):
            continue
        m = importlib.import_module(f"skills.{mod}")
        if hasattr(m, "TOOL_DEF"):
            tools.append(m.TOOL_DEF)
            name = m.TOOL_DEF["function"]["name"]
            if hasattr(m, "execute"):
                execs[name] = m.execute
    return tools, execs

# ---------- API Key ----------
def get_key():
    return st.secrets.get("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY")

# ---------- 错别字风格 ----------
TYPO_STYLES = {
    "cute": {"是":"系","我":"窝","你":"泥","很":"狠","的":"哒","了":"啦","吗":"嘛","什么":"啥","怎么":"咋","没有":"木有","喜欢":"稀饭","吃":"恰","不":"卜","知道":"造"},
    "cool": {"什么":"啥","怎么":"怎","没有":"无","知道":"知","不要":"别"},
    "classical": {"我":"吾","你":"汝","很":"甚","的":"之","是":"乃","吗":"乎"},
    "dialect": {"什么":"啥子","怎么":"咋个","没有":"冇","你":"恁","我":"俺"},
    "lazy": {"这样":"酱","那样":"酿","不要":"表","什么":"啥","知道":"造"}
}
BASE_TYPO = {"什么":"啥","怎么":"咋","没有":"没","知道":"知","不要":"别"}

def get_typo_dict():
    custom = st.session_state.get("oc_custom_typo_dict")
    if custom:
        return custom
    style = st.session_state.get("oc_typo_style")
    if style == "random":
        styles = list(TYPO_STYLES.keys())
        return TYPO_STYLES[random.choice(styles)] if styles else BASE_TYPO
    return TYPO_STYLES.get(style, BASE_TYPO)

# ---------- 颜文字 ----------
KAOMOJI = ["(◕ᴗ◕✿)","(≧◡≦)","(๑•̀ㅂ•́)و✧","(*/ω＼*)","(´• ω •`)"]

# ---------- 特效 ----------
def apply_effects(text, typo_rate, emoji_rate, special_punct):
    if not text:
        return text
    d = get_typo_dict()
    if special_punct:
        new = ""
        for ch in text:
            if ch in "。，！？；：.!?;:" and random.random()<0.5:
                new += random.choice(["～","！","？","…","❤️"])
            else:
                new += ch
        text = new
    if typo_rate > 0 and d:
        chars = list(text)
        for i,ch in enumerate(chars):
            if ch in d and random.random()<typo_rate:
                chars[i] = d[ch]
        text = "".join(chars)
    if emoji_rate > 0:
        sentences = re.split(r'(?<=[。！？.!?…])', text)
        for i,sent in enumerate(sentences):
            if sent and random.random()<emoji_rate:
                k = random.choice(KAOMOJI)
                sentences[i] = k + sent if random.random()<0.5 else sent + k
        text = "".join(sentences)
    return text

# ---------- 打字机 ----------
def typewriter(ph, text, speed):
    disp = ""
    for ch in text:
        disp += ch
        ph.markdown(disp + "▌")
        time.sleep(speed)
    ph.markdown(text)

# ---------- 分段函数 ----------
def random_split(text, min_len, max_len):
    segments = []
    i = 0
    n = len(text)
    while i < n:
        length = random.randint(min_len, max_len)
        end = min(i + length, n)
        segments.append(text[i:end])
        i = end
    return segments

def split_paragraphs(text, panic_mode=None):
    if not panic_mode:
        paras = re.split(r'\n{2,}', text.strip())
        return [p.strip() for p in paras if p.strip()] if len(paras) > 1 else [text]
    mode = panic_mode.get("segment_mode", "natural")
    if mode == "random":
        max_len = panic_mode.get("max_segment_length", 30)
        min_len = max(1, max_len // 2)
        return random_split(text, min_len, max_len)
    else:
        paras = re.split(r'\n{2,}', text.strip())
        return [p.strip() for p in paras if p.strip()] if len(paras) > 1 else [text]

def send_paragraphs(paragraphs, speed):
    for idx, para in enumerate(paragraphs):
        with st.chat_message("assistant"):
            placeholder = st.empty()
            typewriter(placeholder, para, speed)
        S.msgs.append({
            "role": "assistant",
            "content": para,
            "timestamp": now_beijing_timestamp()
        })
        if idx != len(paragraphs) - 1:
            pass

# ---------- CSS（聊天气泡）----------
def inject_css():
    st.markdown("""
        <style>
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) {
            display:flex !important; justify-content:flex-end !important; flex-direction:row-reverse !important;
        }
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-assistant"]) {
            display:flex !important; justify-content:flex-start !important;
        }
        div[data-testid="stChatMessageContent"] {
            max-width:70%; border-radius:20px; padding:10px 16px; box-shadow:0 4px 12px rgba(0,0,0,0.1);
        }
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) div[data-testid="stChatMessageContent"] {
            background:linear-gradient(135deg,#e3f2fd,#bbdefb); border:2px solid #42a5f5;
            border-radius:20px 6px 20px 20px; margin-left:8px;
        }
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-assistant"]) div[data-testid="stChatMessageContent"] {
            background:linear-gradient(135deg,#fff3e0,#ffe0b2); border:2px solid #ffa726;
            border-radius:6px 20px 20px 20px; margin-right:8px;
        }
        /* 图片在气泡中的样式 */
        div[data-testid="stChatMessageContent"] img {
            max-width: 200px;
            border-radius: 10px;
            margin: 8px 0;
        }
        .time-divider {text-align:center; color:#999; font-size:0.85em; margin:16px 0 8px 0;}
        </style>
    """, unsafe_allow_html=True)

st.set_page_config(page_title="OC 聊天助手", page_icon="🎭")
inject_css()

# ---------- 会话状态 ----------
S = st.session_state
defaults = {
    "msgs": [], "oc_id":None, "oc_pw":"", "oc_name":"", "oc_base":"", "oc_rules":[],
    "oc_material":None, "oc_speed":0.05, "oc_typo":0.0, "oc_emoji":0.0, "oc_punct":False,
    "oc_custom_typo":None, "oc_style":None, "oc_unread_prob":0.08, "oc_unread_mult":1.0,
    "oc_unread_consec":0, "oc_ignore":[], "oc_urg_thresh":0.7, "oc_panic":{},
    "auto_prob":0.0, "auto_prompt":"你可以偶尔主动聊聊天。",
    "auto_pending":False, "auto_text":"",
    "pw_error":"", "prev_oc":None,
    "stage":None, "last_prompt":None, "use_ai_urg":False,
    "ai_busy":False, "queue":[], 
    "oc_image_pool":[],               # 图片池
    "oc_image_prob":0.0               # AI 附加图片概率
}
for k,v in defaults.items():
    if k not in S:
        S[k] = v

def now_beijing_timestamp():
    return datetime.now(ZoneInfo("Asia/Shanghai")).timestamp()

# ---------- 主动消息生成与发送 ----------
def gen_auto():
    key = get_key()
    if not key: return
    try:
        cl = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")
        sys = build_sys()
        recent = S.msgs[-6:]
        msgs = [{"role":"system","content":sys}] if sys else []
        msgs += prepare_msgs(recent)
        msgs.append({"role":"user","content":f"[内部指令]{S.auto_prompt} 请直接说出一句主动发起的话题，简短自然。"})
        resp = cl.chat.completions.create(model="deepseek-chat", messages=msgs, temperature=1.1, max_tokens=100)
        txt = resp.choices[0].message.content
    except:
        txt = "（突然想找你聊聊天…）"
    if txt:
        # 主动消息也可能附加图片
        txt = maybe_attach_image(txt)
        txt = apply_effects(txt, S.oc_typo, S.oc_emoji, S.oc_punct)
        S.auto_text = txt
        S.auto_pending = True

def send_auto():
    if not S.auto_pending: return
    txt = S.auto_text
    S.auto_pending = False
    S.auto_text = ""
    with st.chat_message("assistant"):
        st.markdown(txt)
    S.msgs.append({"role":"assistant","content":txt,"timestamp":now_beijing_timestamp()})

def build_sys():
    if S.oc_id is None: return ""
    base = S.oc_base
    rules = S.oc_rules
    if rules:
        base = "【强制规则，必须无条件遵守】\n" + "\n".join(f"- {r}" for r in rules) + "\n\n" + base
    if S.oc_material:
        p = Path("materials") / f"{S.oc_material}.txt"
        if p.exists():
            base += "\n\n[知识库]\n" + p.read_text(encoding="utf-8")
    # 在系统提示中加入图片池信息
    if S.oc_image_pool:
        img_descriptions = "\n".join([f"- 图片{i+1}: {url}" for i, url in enumerate(S.oc_image_pool)])
        base += f"\n\n你可以使用以下图片链接来发送图片，在回复中用 Markdown 语法 ![描述](图片URL) 插入。可用图片列表：\n{img_descriptions}"
    return base

def prepare_msgs(msgs):
    out = []
    for m in msgs:
        if m.get("silent"): continue
        d = {"role":m["role"]}
        if "content" in m and m["content"] is not None:
            d["content"] = m["content"]
        if "image" in m:
            d["image"] = m["image"]   # 用户发送的图片 base64
        if "tool_calls" in m:
            d["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            d["tool_call_id"] = m["tool_call_id"]
        out.append(d)
    return out

# 随机附加图片到文本末尾
def maybe_attach_image(text):
    if S.oc_image_prob > 0 and S.oc_image_pool:
        if random.random() < S.oc_image_prob:
            img_url = random.choice(S.oc_image_pool)
            # 在末尾加上换行和图片标记
            text += f"\n\n![图片]({img_url})"
    return text

# ---------- 界面 ----------
if S.oc_name:
    st.title(f"🎭 {S.oc_name}")
else:
    st.title("🎭 OC 聊天助手")

# 密码行
col_label, col_input, col_status, col_clear = st.columns([1.5, 4, 0.5, 1])
with col_label:
    st.markdown("密码状态：")
with col_input:
    pw = st.text_input("", key="oc_pw_input", value=S.oc_pw, label_visibility="collapsed")
with col_status:
    if S.oc_id is not None:
        st.markdown("✅")
    elif S.pw_error:
        st.markdown("❌")
    else:
        st.write("")
with col_clear:
    if st.button("🗑️ 清空"):
        for k in defaults: S[k] = defaults[k]
        st.rerun()

if S.pw_error:
    st.error("❌ 密码无效")

# 密码处理
if pw != S.oc_pw:
    S.oc_pw = pw
    if pw.strip() == "":
        for k in defaults: S[k] = defaults[k]
        st.rerun()
    else:
        raw = pw.strip()
        oid_str = decode_numeric(raw)
        oid_str = re.sub(r'\D', '', oid_str)
        if oid_str:
            prof = load_oc(oid_str)
            if prof:
                S.oc_id = oid_str
                S.oc_name = prof.get("name","未命名")
                S.oc_base = prof.get("base_prompt","")
                S.oc_rules = prof.get("forced_rules",[])
                S.oc_material = prof.get("material")
                S.oc_speed = prof.get("typing_speed",0.05)
                S.oc_typo = prof.get("typo_rate",0.0)
                S.oc_emoji = prof.get("emoji_rate",0.0)
                S.oc_punct = prof.get("special_punct",False)
                S.oc_custom_typo = prof.get("custom_typo_dict")
                S.oc_style = prof.get("typo_style")
                if "unread_probability" in prof:
                    S.oc_unread_prob = prof["unread_probability"]
                elif "reply_probability" in prof:
                    S.oc_unread_prob = 1.0 - prof["reply_probability"]
                S.oc_unread_mult = prof.get("consecutive_unread_multiplier",1.0)
                S.oc_ignore = prof.get("ignore_keywords",[])
                S.oc_urg_thresh = prof.get("urgency_threshold",0.7)
                S.oc_panic = prof.get("panic_mode",{})
                S.auto_prob = prof.get("auto_message_probability",0.0)
                S.auto_prompt = prof.get("auto_message_prompt","你可以偶尔主动聊聊天。")
                S.use_ai_urg = prof.get("use_ai_urgency",False)
                S.oc_image_pool = prof.get("image_pool", [])
                S.oc_image_prob = prof.get("image_attachment_probability", 0.0)
                S.pw_error = ""
                if S.prev_oc != oid_str:
                    S.msgs = []; S.stage = None; S.ai_busy = False; S.queue = []
                S.prev_oc = oid_str
            else:
                S.oc_id = None
                S.pw_error = f"未找到 OC 文件 {oid_str}.json"
        else:
            S.oc_id = None
            S.pw_error = "密码无效（需包含数字）"

# ---------- 渲染消息 ----------
prev_t = None
for i, msg in enumerate(S.msgs):
    if msg["role"] == "tool" or msg.get("silent"): continue
    if msg["role"] == "assistant" and not msg.get("content"): continue

    is_read = False
    if msg["role"] == "user":
        if msg.get("read"):
            is_read = True
        else:
            for j in range(i+1, len(S.msgs)):
                nxt = S.msgs[j]
                if nxt["role"] in ("assistant","tool"):
                    is_read = True
                    break
                if nxt["role"] == "user":
                    break

    if prev_t is None or msg["timestamp"] - prev_t >= 1200:
        dt = datetime.fromtimestamp(msg["timestamp"], tz=ZoneInfo("Asia/Shanghai"))
        st.markdown(f'<div class="time-divider">📅 {dt.strftime("%m月%d日 %H:%M")}</div>', unsafe_allow_html=True)
        prev_t = msg["timestamp"]

    if msg["role"] == "user":
        with st.chat_message("user"):
            if msg.get("image"):
                st.image(base64.b64decode(msg["image"]), width=300)
            st.markdown(msg["content"])
            st.caption("已读" if is_read else "未读")
    else:
        with st.chat_message("assistant"):
            st.markdown(msg["content"])

# ---------- 铃铛 ----------
col_a, col_b = st.columns([9,1])
with col_b:
    bell_label = "🔔" + (" 🔴" if S.auto_pending else "")
    bell = st.button(bell_label, key="bell_btn", help="主动消息（点击查看）")

if bell and S.auto_pending:
    send_auto()
    st.rerun()

# ---------- 图片上传区域 ----------
with st.expander("📷 上传图片（可选）"):
    uploaded_file = st.file_uploader("选择图片", type=["jpg","jpeg","png"], label_visibility="collapsed")
    if uploaded_file is not None:
        img_bytes = uploaded_file.read()
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
        S.msgs.append({
            "role": "user",
            "content": "📷 我发了一张图片",
            "image": img_b64,
            "read": False,
            "timestamp": now_beijing_timestamp()
        })
        S.last_prompt = "我发了一张图片，请根据你的人物设定回应（注意：你无法真正看见图片，但可以假装看见了并作出有趣的反应）"
        S.stage = "generating"
        st.rerun()

# ---------- 聊天输入 ----------
user_input = st.chat_input("输入消息...")

if user_input:
    key = get_key()
    if not key: st.error("未配置 API Key"); st.stop()
    if S.oc_id is None: st.error("请先输入有效的 OC 密码"); st.stop()

    if S.ai_busy:
        S.queue.append(user_input)
        st.info("消息已排队")
        st.rerun()
    else:
        if S.auto_pending:
            send_auto()
        S.msgs.append({"role":"user","content":user_input,"read":False,"timestamp":now_beijing_timestamp()})
        S.last_prompt = user_input
        S.stage = "generating"
        st.rerun()

# ---------- 生成回复 ----------
if S.stage == "generating":
    key = get_key()
    if not key: st.stop()
    prompt = S.last_prompt
    should_reply = True
    if S.oc_ignore and any(kw in prompt for kw in S.oc_ignore):
        should_reply = False
    if should_reply:
        prob = S.oc_unread_prob * (S.oc_unread_mult ** S.oc_unread_consec)
        if random.random() < prob:
            should_reply = False
            S.oc_unread_consec += 1
        else:
            S.oc_unread_consec = 0
    if not should_reply:
        S.ai_busy = False; S.stage = None
        if S.queue: S.queue.pop(0); S.stage = "mark_read"; st.rerun()
        st.rerun()

    S.ai_busy = True
    tools, execs = load_skills()
    cl = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")
    sys = build_sys()
    msgs = [{"role":"system","content":sys}] if sys else []
    msgs += prepare_msgs(S.msgs)

    ph = st.empty()
    ph.markdown('<p style="color:#888;font-style:italic;">对方正在输入中...</p>', unsafe_allow_html=True)

    urgency = 0.0
    if S.use_ai_urg:
        try:
            eval_cl = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")
            recent = S.msgs[-6:]
            eval_msgs = [{"role":"system","content":f"{sys}\n\n请基于以上角色设定和对话历史，评估用户最后一条消息的紧急程度（0.0 非常平静，1.0 极度焦急）。只输出一个浮点数。"}]
            eval_msgs += prepare_msgs(recent)
            r = eval_cl.chat.completions.create(model="deepseek-chat", messages=eval_msgs, temperature=0, max_tokens=10)
            urgency = float(r.choices[0].message.content.strip())
        except:
            urgency = 0.0

    full = ""
    tool_calls = []
    resp = cl.chat.completions.create(model="deepseek-chat", messages=msgs, tools=tools if tools else None, stream=True)
    for chunk in resp:
        d = chunk.choices[0].delta
        if d.content: full += d.content
        if d.tool_calls:
            for td in d.tool_calls:
                if td.index >= len(tool_calls):
                    tool_calls.append({"id":td.id,"type":"function","function":{"name":"","arguments":""}})
                if td.id: tool_calls[td.index]["id"] = td.id
                if td.function:
                    if td.function.name: tool_calls[td.index]["function"]["name"] = td.function.name
                    if td.function.arguments: tool_calls[td.index]["function"]["arguments"] += td.function.arguments

    if tool_calls:
        S.msgs.append({"role":"assistant","content":None,"tool_calls":tool_calls,"timestamp":now_beijing_timestamp()})
        for tc in tool_calls:
            fname = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"])
            fn = execs.get(fname)
            res = fn(args) if fn else f"技能 {fname} 未找到"
            S.msgs.append({"role":"tool","tool_call_id":tc["id"],"content":res,"timestamp":now_beijing_timestamp()})
            with st.chat_message("tool"): st.caption(f"🔧 {fname} → {res}")
        msgs2 = [{"role":"system","content":sys}] if sys else []
        msgs2 += prepare_msgs(S.msgs)
        full2 = ""
        resp2 = cl.chat.completions.create(model="deepseek-chat", messages=msgs2, stream=True)
        for c in resp2:
            if c.choices[0].delta.content: full2 += c.choices[0].delta.content
        full = full2 if full2 else "（工具调用完成）"

    ph.empty()
    if full and full.strip():
        full = re.sub(r"\[URGENCY:\d+\.?\d*\]","",full).strip()
        # 应用特效之前，先尝试附加图片
        full = maybe_attach_image(full)
        speed = S.oc_speed
        panic_mode = None
        if urgency >= S.oc_urg_thresh and S.oc_panic:
            speed *= S.oc_panic.get("speed_multiplier", 1.0)
            panic_mode = S.oc_panic

        processed = apply_effects(full, S.oc_typo, S.oc_emoji, S.oc_punct)
        paragraphs = split_paragraphs(processed, panic_mode)
        send_paragraphs(paragraphs, speed)

    if S.auto_prob > 0 and random.random() < S.auto_prob:
        gen_auto()

    S.ai_busy = False; S.stage = None
    if S.queue:
        nxt = S.queue.pop(0)
        S.msgs.append({"role":"user","content":nxt,"read":False,"timestamp":now_beijing_timestamp()})
        S.last_prompt = nxt
        S.stage = "generating"
    st.rerun()
