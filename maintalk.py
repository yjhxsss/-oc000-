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

# ---------- 62进制 ----------
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CHAR_MAP = {c: i for i, c in enumerate(CHARS)}
def decode_62(s):
    n = 0
    for c in s:
        n = n * 62 + CHAR_MAP[c]
    return n

# ---------- 文件路径 ----------
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

# ---------- 错别字库 ----------
TYPO_STYLES = {
    "cute": {"是":"系","我":"窝","你":"泥","很":"狠","的":"哒","了":"啦","吗":"嘛"},
    "cool": {"什么":"啥","怎么":"怎","没有":"无"},
    "classical": {"我":"吾","你":"汝","很":"甚","的":"之"},
    "dialect": {"什么":"啥子","怎么":"咋个","没有":"冇"},
    "lazy": {"这样":"酱","那样":"酿","不要":"表"}
}
BASE_TYPO = {"什么":"啥","怎么":"咋","没有":"没","知道":"知","不要":"别"}

def get_typo_dict():
    custom = st.session_state.get("oc_custom_typo_dict")
    if custom:
        return custom
    style = st.session_state.get("oc_typo_style")
    if style == "random":
        keys = list(TYPO_STYLES.keys())
        return TYPO_STYLES[random.choice(keys)] if keys else BASE_TYPO
    return TYPO_STYLES.get(style, BASE_TYPO)

# ---------- 颜文字 ----------
KAOMOJI = ["(◕ᴗ◕✿)","(≧◡≦)","(๑•̀ㅂ•́)و✧","(*/ω＼*)","(´• ω •`)"]

# ---------- 特效应用 ----------
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

# ---------- 段落切割 ----------
def split_paras(text):
    paras = re.split(r'\n{2,}', text.strip())
    return [p.strip() for p in paras if p.strip()] if len(paras)>1 else [text]

# ---------- CSS (仅聊天气泡+隐藏触发框) ----------
def inject_css():
    st.markdown("""
        <style>
        /* 聊天气泡左右布局 */
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) {
            display:flex !important; justify-content:flex-end !important; flex-direction:row-reverse !important;
        }
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-assistant"]) {
            display:flex !important; justify-content:flex-start !important;
        }
        div[data-testid="stChatMessageContent"] {
            max-width:70%; border-radius:20px; padding:10px 16px; box-shadow:0 4px 12px rgba(0,0,0,0.1);
        }
        /* 用户气泡 */
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-user"]) div[data-testid="stChatMessageContent"] {
            background:linear-gradient(135deg,#e3f2fd,#bbdefb); border:2px solid #42a5f5;
            border-radius:20px 6px 20px 20px; margin-left:8px;
        }
        /* AI气泡 */
        div[data-testid="stChatMessage"]:has(div[data-testid="chatAvatarIcon-assistant"]) div[data-testid="stChatMessageContent"] {
            background:linear-gradient(135deg,#fff3e0,#ffe0b2); border:2px solid #ffa726;
            border-radius:6px 20px 20px 20px; margin-right:8px;
        }
        .time-divider {text-align:center; color:#999; font-size:0.85em; margin:16px 0 8px 0;}

        /* 彻底隐藏定时器触发输入框 */
        div[data-st-key="auto_trigger"] {
            display: none !important;
            width: 0 !important;
            height: 0 !important;
            overflow: hidden !important;
            position: absolute !important;
            left: -9999px !important;
        }
        /* 铃铛按钮红点基础样式 */
        button[data-st-key="bell_btn"] {
            position: relative;
        }
        button[data-st-key="bell_btn"]::after {
            content: '';
            position: absolute;
            top: 2px;
            right: 2px;
            width: 12px;
            height: 12px;
            background: red;
            border-radius: 50%;
            display: none; /* 默认隐藏，动态显示 */
        }
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
    "auto_prob":0.0, "auto_dmin":60, "auto_dmax":180, "auto_prompt":"你可以偶尔主动聊聊天。",
    "auto_pending":False, "auto_text":"", "auto_end":None, "auto_active":False,
    "auto_trigger_handled":False, "pw_error":"", "prev_oc":None,
    "stage":None, "last_prompt":None, "use_ai_urg":False,
    "ai_busy":False, "queue":[]
}
for k,v in defaults.items():
    if k not in S:
        S[k] = v

def now_ts():
    return datetime.now(ZoneInfo("Asia/Shanghai")).timestamp()

# ---------- 主动消息功能 ----------
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
        txt = apply_effects(txt, S.oc_typo, S.oc_emoji, S.oc_punct)
        S.auto_text = txt
        S.auto_pending = True

def send_auto():
    if not S.auto_pending: return
    txt = S.auto_text
    S.auto_pending = False
    S.auto_text = ""
    S.auto_active = False
    S.auto_end = None
    with st.chat_message("assistant"):
        st.markdown(txt)
    S.msgs.append({"role":"assistant","content":txt,"timestamp":now_ts()})

# ---------- 辅助函数 ----------
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
    return base

def prepare_msgs(msgs):
    out = []
    for m in msgs:
        if m.get("silent"): continue
        d = {"role":m["role"]}
        if "content" in m and m["content"] is not None:
            d["content"] = m["content"]
        if "tool_calls" in m:
            d["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            d["tool_call_id"] = m["tool_call_id"]
        out.append(d)
    return out

# ---------- 界面 ----------
if S.oc_name:
    st.title(f"🎭 {S.oc_name}")
else:
    st.title("🎭 OC 聊天助手")

# 密码行
c1, c2 = st.columns([5,1])
with c1:
    pw = st.text_input("🔐 OC 密码", key="oc_pw_input", value=S.oc_pw)
with c2:
    if st.button("🗑️ 清空"):
        for k in defaults: S[k] = defaults[k]
        st.rerun()

# 密码正确绿框（立即生效）
if S.oc_id is not None:
    st.markdown("""
        <style>
        div[data-st-key="oc_pw_input"] input {
            border-color: #28a745 !important;
            box-shadow: 0 0 0 1px #28a745 !important;
        }
        </style>
    """, unsafe_allow_html=True)

if S.pw_error:
    st.error("❌ 密码无效")

# 密码处理
if pw != S.oc_pw:
    S.oc_pw = pw
    if pw.strip() == "":
        # 重置状态
        for k in defaults: S[k] = defaults[k]
        st.rerun()
    else:
        try:
            oid = decode_62(pw)
            prof = load_oc(oid)
            if prof:
                S.oc_id = oid
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
                S.oc_unread_prob = prof.get("unread_probability", prof.get("reply_probability") and 1-prof["reply_probability"] or 0.08)
                S.oc_unread_mult = prof.get("consecutive_unread_multiplier",1.0)
                S.oc_ignore = prof.get("ignore_keywords",[])
                S.oc_urg_thresh = prof.get("urgency_threshold",0.7)
                S.oc_panic = prof.get("panic_mode",{})
                S.auto_prob = prof.get("auto_message_probability",0.0)
                S.auto_dmin = prof.get("auto_message_delay_min",60)
                S.auto_dmax = prof.get("auto_message_delay_max",180)
                S.auto_prompt = prof.get("auto_message_prompt","你可以偶尔主动聊聊天。")
                S.use_ai_urg = prof.get("use_ai_urgency",False)
                S.pw_error = ""
                if S.prev_oc != oid:
                    S.msgs = []; S.stage = None; S.ai_busy = False; S.queue = []
                S.prev_oc = oid
            else:
                S.oc_id = None; S.pw_error = f"未找到 OC 文件 {oid}.json"
        except Exception as e:
            S.oc_id = None; S.pw_error = str(e)

# 渲染消息
prev_t = None
for i,msg in enumerate(S.msgs):
    if msg["role"] == "tool" or msg.get("silent"): continue
    if msg["role"] == "assistant" and not msg.get("content"): continue
    is_read = False
    if msg["role"] == "user":
        for j in range(i+1, len(S.msgs)):
            nxt = S.msgs[j]
            if nxt["role"] in ("assistant","tool"):
                is_read = True; break
            if nxt["role"] == "user": break
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
            st.markdown(msg["content"])

# 主动消息定时器 JS
def inject_timer():
    if not S.auto_active or S.auto_trigger_handled: return
    if S.auto_end is None: return
    remain = max(0, int(S.auto_end - time.time()))
    st.text_input("", key="auto_trigger", label_visibility="collapsed")
    js = f"""<script>setTimeout(()=>{{const i=window.parent.document.querySelector('input[aria-label=""]');if(i){{Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(i,'trig_'+Date.now());i.dispatchEvent(new Event('input',{{bubbles:true}}));}}}},{remain*1000});</script>"""
    st.components.v1.html(js, height=0)

inject_timer()
if S.get("auto_trigger") and not S.auto_trigger_handled:
    if S.auto_trigger.startswith("trig_"):
        S.auto_trigger_handled = True
        if S.auto_active and S.auto_end and time.time() >= S.auto_end:
            send_auto()
            st.rerun()

# 铃铛按钮（放在输入框上方一行，居右）
col_left, col_right = st.columns([9, 1])
with col_right:
    bell = st.button("🔔", key="bell_btn", help="主动消息（点击查看）")
# 输入框
user_input = st.chat_input("输入消息...")

# 铃铛红点
if S.auto_pending:
    st.markdown("""
        <style>
        button[data-st-key="bell_btn"]::after {
            display: block !important;
        }
        </style>
    """, unsafe_allow_html=True)

if bell and S.auto_pending:
    send_auto()
    st.rerun()

# 用户输入处理
if user_input:
    key = get_key()
    if not key: st.error("未配置 API Key"); st.stop()
    if S.oc_id is None: st.error("请先输入有效的 OC 密码"); st.stop()
    S.auto_active = False
    if S.ai_busy:
        S.queue.append(user_input)
        st.info("消息已排队")
        st.rerun()
    else:
        if S.auto_pending:
            send_auto()
        S.msgs.append({"role":"user","content":user_input,"read":False,"timestamp":now_ts()})
        S.last_prompt = user_input
        S.stage = "generating"
        st.rerun()

# 生成回复
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
        S.msgs.append({"role":"assistant","content":None,"tool_calls":tool_calls,"timestamp":now_ts()})
        for tc in tool_calls:
            fname = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"])
            fn = execs.get(fname)
            res = fn(args) if fn else f"技能 {fname} 未找到"
            S.msgs.append({"role":"tool","tool_call_id":tc["id"],"content":res,"timestamp":now_ts()})
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
        speed = S.oc_speed
        if urgency >= S.oc_urg_thresh and S.oc_panic:
            speed *= S.oc_panic.get("speed_multiplier",1.0)
        processed = apply_effects(full, S.oc_typo, S.oc_emoji, S.oc_punct)
        paras = split_paras(processed)
        for para in paras:
            with st.chat_message("assistant"):
                ph2 = st.empty()
                typewriter(ph2, para, speed)
            S.msgs.append({"role":"assistant","content":para,"timestamp":now_ts()})

    if S.auto_prob > 0 and random.random() < S.auto_prob:
        gen_auto()
        delay = random.randint(S.auto_dmin, S.auto_dmax)
        S.auto_end = now_ts() + delay
        S.auto_active = True
        S.auto_trigger_handled = False
    else:
        S.auto_pending = False; S.auto_active = False

    S.ai_busy = False; S.stage = None
    if S.queue:
        nxt = S.queue.pop(0)
        S.msgs.append({"role":"user","content":nxt,"read":False,"timestamp":now_ts()})
        S.last_prompt = nxt
        S.stage = "generating"
    st.rerun()
