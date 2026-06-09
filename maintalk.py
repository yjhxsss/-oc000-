import streamlit as st
import openai
import json
import os
import time
import random
import re
import base64
import io
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image

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

# ---------- 图片加载（压缩并缓存）----------
@st.cache_data(ttl=3600, show_spinner=False)
def load_images_from_materials(file_names):
    data_map = {}
    materials_dir = Path("materials")
    for fname in file_names:
        img_path = materials_dir / fname
        if not img_path.exists():
            continue
        try:
            img = Image.open(img_path)
            img.thumbnail((300, 300))
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=70)
            img_bytes = buf.getvalue()
            data_url = f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode()}"
            data_map[fname] = data_url
        except:
            pass
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

# ---------- 图片提取（核心：标准格式 [图片:xxx]）----------
def extract_image_filename(text):
    """从文本中提取第一个匹配 [图片:xxx] 的文件名，若无则返回 None"""
    # 支持中文冒号和英文冒号
    pattern = re.compile(r'\[图片[:：]\s*([^\]]+?)\s*\]')
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return None

def render_message(content):
    """历史消息渲染（无打字机）"""
    img_name = extract_image_filename(content)
    # 移除图片标记，显示纯文本
    clean = re.sub(r'\[图片[:：][^\]]*\]', '', content).strip()
    if clean:
        st.markdown(clean)
    if img_name:
        data_url = S.oc_image_map.get(img_name)
        if data_url:
            st.image(data_url, width=200, caption=img_name)

def render_message_with_typewriter(content, speed):
    """打字机效果 + 图片"""
    img_name = extract_image_filename(content)
    clean = re.sub(r'\[图片[:：][^\]]*\]', '', content).strip()
    if clean:
        placeholder = st.empty()
        if speed > 0:
            typewriter(placeholder, clean, speed)
        else:
            placeholder.markdown(clean)
    if img_name:
        data_url = S.oc_image_map.get(img_name)
        if data_url:
            st.image(data_url, width=200, caption=img_name)

# ---------- 分段相关 ----------
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
            render_message_with_typewriter(para, speed)
        S.msgs.append({
            "role": "assistant",
            "content": para,
            "timestamp": now_beijing_timestamp()
        })
        if idx != len(paragraphs) - 1:
            time.sleep(0.2)

# ---------- CSS ----------
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
    "oc_image_map":{},
    "oc_image_file_names":[],
    "oc_image_prob":0.0
}
for k,v in defaults.items():
    if k not in S:
        S[k] = v

def now_beijing_timestamp():
    return datetime.now(ZoneInfo("Asia/Shanghai")).timestamp()

# ---------- 主动消息 ----------
def gen_auto():
    key = get_key()
    if not key: return
    try:
        cl = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")
        sys = build_sys(force_image=False)
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
    with st.chat_message("assistant"):
        render_message(txt)
    S.msgs.append({"role":"assistant","content":txt,"timestamp":now_beijing_timestamp()})

def build_sys(force_image=False):
    if S.oc_id is None: return ""
    base = S.oc_base
    rules = S.oc_rules
    if rules:
        base = "【强制规则，必须无条件遵守】\n" + "\n".join(f"- {r}" for r in rules) + "\n\n" + base
    if S.oc_material:
        p = Path("materials") / f"{S.oc_material}.txt"
        if p.exists():
            base += "\n\n[知识库]\n" + p.read_text(encoding="utf-8")
    
    if S.oc_image_file_names:
        base += "\n\n你拥有以下表情图片：\n"
        for fname in S.oc_image_file_names:
            base += f"- {fname}\n"
        if force_image:
            base += (
                "【重要】本次回复你必须附带一张图片。请在最末尾使用格式 `[图片:文件名]`（英文方括号，英文冒号），"
                "例如 `[图片:开坦克.png]`。文件名必须从上面列表中选择，不能自己编造。"
            )
        else:
            base += "【注意】本次回复不要添加任何图片标记。"
    
    return base

def get_history_msgs(max_len=12):
    return S.msgs[-max_len:]

def prepare_msgs(msgs):
    out = []
    for m in msgs:
        if m.get("silent"): continue
        d = {"role": m["role"]}
        if "content" in m and m["content"] is not None:
            content = m["content"]
            # 替换图片标记为占位符
            content = re.sub(r'\[图片[:：][^\]]*\]', '[图片]', content).strip()
            d["content"] = content if content else "…"
        out.append(d)
    return out

def mark_previous_messages_read():
    for msg in S.msgs:
        if msg["role"] == "user" and not msg.get("read", False):
            msg["read"] = True

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
                S.oc_image_file_names = prof.get("image_pool", [])
                S.oc_image_map = load_images_from_materials(S.oc_image_file_names)
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

# ---------- 渲染历史消息 ----------
visible_msgs = S.msgs[-30:] if len(S.msgs) > 30 else S.msgs
prev_t = None
for i, msg in enumerate(visible_msgs):
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
        with st.chat_message("assistant"):
            render_message(msg["content"])

# ---------- 铃铛 ----------
col_a, col_b = st.columns([9,1])
with col_b:
    bell_label = "🔔" + (" 🔴" if S.auto_pending else "")
    bell = st.button(bell_label, key="bell_btn", help="主动消息（点击查看）")

if bell and S.auto_pending:
    send_auto()
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
    mark_previous_messages_read()
    
    force_image = False
    if S.oc_image_prob > 0 and S.oc_image_file_names:
        if random.random() < S.oc_image_prob:
            force_image = True

    cl = openai.OpenAI(api_key=key, base_url="https://api.deepseek.com")
    sys = build_sys(force_image=force_image)
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
        processed = apply_effects(full, S.oc_typo, S.oc_emoji, S.oc_punct)
        speed = S.oc_speed
        if urgency >= S.oc_urg_thresh and S.oc_panic:
            speed *= S.oc_panic.get("speed_multiplier", 1.0)
        paragraphs = split_paragraphs(processed, S.oc_panic if urgency >= S.oc_urg_thresh else None)
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
