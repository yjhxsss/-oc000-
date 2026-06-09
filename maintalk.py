import streamlit as st
import openai
import json
import os
import time
import random
import re
import base64
import mimetypes
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------- 密码转换（数字循环偏移）----------
SHIFT = 1

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

# ---------- 从 materials 加载图片为 data URL（仅用于前端显示）----------
def load_images_from_materials(file_names):
    """返回字典 {文件名: data_url}，同时保存列表顺序"""
    data_map = {}
    materials_dir = Path("materials")
    if not materials_dir.exists():
        materials_dir.mkdir(exist_ok=True)
        return data_map
    for fname in file_names:
        img_path = materials_dir / fname
        if not img_path.exists():
            st.warning(f"图片文件不存在: {fname}")
            continue
        try:
            with open(img_path, "rb") as f:
                img_bytes = f.read()
            mime_type, _ = mimetypes.guess_type(img_path)
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = "image/jpeg"
            b64_str = base64.b64encode(img_bytes).decode("utf-8")
            data_url = f"data:{mime_type};base64,{b64_str}"
            data_map[fname] = data_url
        except Exception as e:
            st.warning(f"读取图片 {fname} 失败: {e}")
    return data_map

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

# ---------- 渲染消息（支持图片标记替换）----------
def render_message(content):
    """将消息中的 [图片:文件名] 替换为真正的图片 HTML"""
    def replace_img(match):
        img_name = match.group(1)
        # 从图片映射中获取 data_url
        data_url = S.oc_image_map.get(img_name)
        if data_url:
            return f'<img src="{data_url}" style="max-width:200px; border-radius:10px; margin:8px 0;">'
        else:
            return f'[图片不存在: {img_name}]'
    # 匹配 [图片:文件名] 格式
    rendered = re.sub(r'\[图片:(.*?)\]', replace_img, content)
    return rendered

def send_paragraphs(paragraphs, speed):
    S = st.session_state
    for idx, para in enumerate(paragraphs):
        # 先渲染图片标记（替换为真正的图片 HTML）
        rendered_para = render_message(para)
        with st.chat_message("assistant"):
            placeholder = st.empty()
            # 如果段落中包含图片 HTML，直接一次性渲染（避免逐字打印图片标签）
            if '<img' in rendered_para:
                placeholder.markdown(rendered_para, unsafe_allow_html=True)
            else:
                typewriter(placeholder, rendered_para, speed)
        # 存储原始消息（包含图片标记，不含 HTML）
        S.msgs.append({
            "role": "assistant",
            "content": para,   # 原始标记
            "timestamp": now_beijing_timestamp()
        })
        if idx != len(paragraphs) - 1:
            time.sleep(0.2)

# ---------- 标记所有未读用户消息为已读 ----------
def mark_previous_messages_read():
    for msg in st.session_state.msgs:
        if msg["role"] == "user" and not msg.get("read", False):
            msg["read"] = True

# ---------- 历史消息截断（节省 token）----------
MAX_HISTORY = 20

def get_history_msgs():
    if len(st.session_state.msgs) > MAX_HISTORY:
        return st.session_state.msgs[-MAX_HISTORY:]
    return st.session_state.msgs

# ---------- 清洗消息（无需额外处理，因为存储的是短标记）----------
def prepare_msgs(msgs):
    out = []
    for m in msgs:
        if m.get("silent"): continue
        d = {"role": m["role"]}
        if "content" in m and m["content"] is not None:
            d["content"] = m["content"]   # 直接使用原始标记（很短）
        out.append(d)
    return out

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
    "oc_image_map":{},               # 文件名 -> data_url 映射
    "oc_image_file_names":[],        # 文件名列表
    "oc_image_prob":0.0              # AI 发送图片的概率（在系统提示中告知）
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
        recent = get_history_msgs()[-6:]
        msgs = [{"role":"system","content":sys}] if sys else []
        msgs += prepare_msgs(recent)
        msgs.append({"role":"user","content":f"[内部指令]{S.auto_prompt} 请直接说出一句主动发起的话题，简短自然。"})
        resp = cl.chat.completions.create(model="deepseek-chat", messages=msgs, temperature=1.1, max_tokens=100)
        txt = resp.choices[0].message.content
    except:
        txt = "（突然想找你聊聊天…）"
    if txt:
        txt = apply_effects(txt, S.oc_typo, S.oc_emoji, S.oc_punct)
        S.auto_text = txt
        S.auto_pending = True

def send_auto():
    if not S.auto_pending: return
    txt = S.auto_text
    S.auto_pending = False
    S.auto_text = ""
    # 主动消息也可能包含图片标记，同样需要渲染
    rendered = render_message(txt)
    with st.chat_message("assistant"):
        st.markdown(rendered, unsafe_allow_html=True)
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
    # 告知 AI 图片发送规则
    if S.oc_image_file_names and S.oc_image_prob > 0:
        base += f"\n\n你有 {S.oc_image_prob*100:.0f}% 的概率在回复中附带一张图片。你可以主动选择是否发送图片，以及发送哪张。图片列表如下（用文件名标识）：\n"
        for idx, fname in enumerate(S.oc_image_file_names):
            base += f"- {fname} (索引 {idx})\n"
        base += "如果你决定发送图片，请在回复的**末尾**单独一行写上 `[图片:文件名]`（例如 `[图片:cat.jpg]`）。注意：不要写其他解释，只写这个标记。"
    return base

# ---------- 界面 ----------
if S.oc_name:
    st.title(f"🎭 {S.oc_name}")
else:
    st.title("🎭 OC 聊天助手")

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
                # 加载图片映射（仅用于前端显示）
                raw_image_files = prof.get("image_pool", [])
                S.oc_image_file_names = raw_image_files
                S.oc_image_map = load_images_from_materials(raw_image_files)
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

    is_read = msg.get("read", False) if msg["role"] == "user" else False

    if prev_t is None or msg["timestamp"] - prev_t >= 1200:
        dt = datetime.fromtimestamp(msg["timestamp"], tz=ZoneInfo("Asia/Shanghai"))
        st.markdown(f'<div class="time-divider">📅 {dt.strftime("%m月%d日 %H:%M")}</div>', unsafe_allow_html=True)
        prev_t = msg["timestamp"]

    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
            st.caption("已读" if is_read else "未读")
    else:
        # 渲染助手的消息（将图片标记替换为真实图片）
        rendered = render_message(msg["content"])
        with st.chat_message("assistant"):
            st.markdown(rendered, unsafe_allow_html=True)

col_a, col_b = st.columns([9,1])
with col_b:
    bell_label = "🔔" + (" 🔴" if S.auto_pending else "")
    bell = st.button(bell_label, key="bell_btn", help="主动消息（点击查看）")

if bell and S.auto_pending:
    send_auto()
    st.rerun()

# ---------- 聊天输入（无图片上传）----------
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
    mark_previous_messages_read()
    
    cl = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")
    sys = build_sys()
    msgs = [{"role":"system","content":sys}] if sys else []
    msgs += prepare_msgs(get_history_msgs())

    ph = st.empty()
    ph.markdown('<p style="color:#888;font-style:italic;">对方正在输入中...</p>', unsafe_allow_html=True)

    urgency = 0.0
    if S.use_ai_urg:
        try:
            eval_cl = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")
            recent = get_history_msgs()[-6:]
            eval_msgs = [{"role":"system","content":f"{sys}\n\n请基于以上角色设定和对话历史，评估用户最后一条消息的紧急程度（0.0 非常平静，1.0 极度焦急）。只输出一个浮点数。"}]
            eval_msgs += prepare_msgs(recent)
            r = eval_cl.chat.completions.create(model="deepseek-chat", messages=eval_msgs, temperature=0, max_tokens=10)
            urgency = float(r.choices[0].message.content.strip())
        except:
            urgency = 0.0

    full = ""
    resp = cl.chat.completions.create(model="deepseek-chat", messages=msgs, stream=True)
    for chunk in resp:
        if chunk.choices[0].delta.content:
            full += chunk.choices[0].delta.content

    ph.empty()
    if full and full.strip():
        full = re.sub(r"\[URGENCY:\d+\.?\d*\]","",full).strip()
        # 应用特效（注意：图片标记 [图片:xxx] 不会被特效改变，因为是纯文本）
        processed = apply_effects(full, S.oc_typo, S.oc_emoji, S.oc_punct)
        # 分段
        paragraphs = split_paragraphs(processed, S.oc_panic if urgency >= S.oc_urg_thresh else None)
        # 发送并渲染（会自动处理图片标记）
        send_paragraphs(paragraphs, S.oc_speed)

    if S.auto_prob > 0 and random.random() < S.auto_prob:
        gen_auto()

    S.ai_busy = False; S.stage = None
    if S.queue:
        nxt = S.queue.pop(0)
        S.msgs.append({"role":"user","content":nxt,"read":False,"timestamp":now_beijing_timestamp()})
        S.last_prompt = nxt
        S.stage = "generating"
    st.rerun()
