import os
import sys
import re
import time
import uuid
import logging
import threading
import telebot
import requests
from telebot import types
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask import Flask

# ================= LOGGING SETUP =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ================= RENDER KEEP-ALIVE SERVER =================
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Ongoing Anime Master Bot is Active & Running 24/7!"

def run_flask_server():
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask_server, daemon=True).start()

# ================= CUSTOM STYLED BUTTON CLASSES =================
class StyledInlineKeyboardButton(types.InlineKeyboardButton):
    def __init__(self, text, style=None, *args, **kwargs):
        super().__init__(text=text, *args, **kwargs)
        self.style = style

class StyledKeyboardButton(types.KeyboardButton):
    def __init__(self, text, style=None, *args, **kwargs):
        super().__init__(text=text, *args, **kwargs)
        self.style = style

# ================= CONFIGURATION & CREDENTIALS =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8045722822:AAG4BgNxs59oXZ8HSJIeZ4ZUmSgt4pKapfk").strip()
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://skanis2008_db_user:skanis09@zeno.dzdqoaj.mongodb.net/?appName=Zeno").strip()
OWNER_ID_RAW = os.getenv("ADMIN_ID", "5659051138").strip()

try:
    OWNER_ID = int(OWNER_ID_RAW)
except ValueError:
    OWNER_ID = 5659051138

if not BOT_TOKEN or not MONGO_URI:
    logger.critical("❌ FATAL: Credentials missing in Environment Variables!")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

try:
    BOT_ME = bot.get_me()
    DETECTED_BOT_USERNAME = BOT_ME.username
except Exception:
    DETECTED_BOT_USERNAME = "ongoing_anime_by_zenobot"

# ================= MONGODB SETUP =================
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["anime_master_db"]
    client.server_info()
    logger.info("✅ Successfully connected to MongoDB Atlas!")
except Exception as e:
    logger.critical(f"❌ FATAL: MongoDB Connection Failed: {e}")
    sys.exit(1)

col_series = db["series"]
col_episodes = db["episodes"]
col_files = db["files"]
col_users = db["users"]
col_fsub = db["fsub"]
col_settings = db["settings"]
col_sessions = db["sessions"]
col_admins = db["admins"]
col_vip = db["vip"]

if not col_settings.find_one({"key": "config"}):
    col_settings.insert_one({
        "key": "config",
        "brand_name": "@ongoing_anime_by_zeno",
        "main_channel_id": "",
        "download_channel_link": "",
        "button_mode": "bot", # 'bot' or 'channel'
        "bot_username": DETECTED_BOT_USERNAME,
        "protect_content": "False"
    })

def get_setting(field):
    cfg = col_settings.find_one({"key": "config"}) or {}
    return cfg.get(field, "")

def update_setting(field, val):
    col_settings.update_one({"key": "config"}, {"$set": {field: str(val)}}, upsert=True)

def get_active_bot_username():
    un = get_setting("bot_username")
    return un if un else DETECTED_BOT_USERNAME

# ================= FONT STYLIZERS (𝐀𝐁𝐂𝐃 & ᴀʙᴄᴅ) =================
def to_bold_serif(text: str) -> str:
    result = []
    for char in str(text):
        code = ord(char)
        if 65 <= code <= 90:
            result.append(chr(0x1D400 + (code - 65)))
        elif 97 <= code <= 122:
            result.append(chr(0x1D41A + (code - 97)))
        elif 48 <= code <= 57:
            result.append(chr(0x1D7CE + (code - 48)))
        else:
            result.append(char)
    return "".join(result)

def to_small_caps(text: str) -> str:
    normal = "abcdefghijklmnopqrstuvwxyz"
    small_caps = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ"
    trans = str.maketrans(normal, small_caps)
    return str(text).lower().translate(trans)

# ================= ROLES & PERMISSIONS =================
def is_owner(user_id):
    return user_id == OWNER_ID

def is_admin(user_id):
    if user_id == OWNER_ID:
        return True
    return col_admins.find_one({"user_id": int(user_id)}) is not None

def is_vip(user_id):
    if is_admin(user_id):
        return True
    vip_entry = col_vip.find_one({"user_id": int(user_id)})
    if not vip_entry:
        return False
    if vip_entry.get("is_lifetime", False):
        return True
    return vip_entry.get("expires_at", 0) > time.time()

# ================= SMART PRIVATE CHANNEL LINK RESOLVER =================
def get_safe_channel_link(chat_identifier):
    """
    Converts any Private Channel ID / Username into a 100% accessible Invite Link.
    This prevents Telegram's 'Not Available' error completely.
    """
    if not chat_identifier:
        return None
    try:
        chat = bot.get_chat(chat_identifier)
        if chat.username:
            return f"https://t.me/{chat.username}"
        if chat.invite_link:
            return chat.invite_link
        return bot.export_chat_invite_link(chat.id)
    except Exception as e:
        logger.error(f"Failed to generate safe invite link for {chat_identifier}: {e}")
        return None

def resolve_channel_input(raw_input):
    val = str(raw_input).strip()
    if not val:
        return False, None, None, None, "Input cannot be empty!"

    # 1. Check for Private Post Link (t.me/c/123456789/10)
    c_match = re.search(r't\.me/c/(\d+)', val)
    if c_match:
        extracted_id = int(f"-100{c_match.group(1)}")
        safe_link = get_safe_channel_link(extracted_id) or val
        try:
            chat = bot.get_chat(extracted_id)
            return True, extracted_id, chat.title, safe_link, None
        except Exception:
            return True, extracted_id, f"Private Channel ({extracted_id})", safe_link, None

    # 2. Check for Numeric ID (-100xxx)
    if val.startswith("-100") or val.startswith("-") or val.isdigit():
        try:
            full_id = int(val) if str(val).startswith("-") else int(f"-100{val}")
            safe_link = get_safe_channel_link(full_id) or "https://t.me"
            try:
                chat = bot.get_chat(full_id)
                return True, full_id, chat.title, safe_link, None
            except Exception:
                return True, full_id, f"Channel ({full_id})", safe_link, None
        except ValueError:
            pass

    # 3. Check for Direct Invite Link (t.me/+...)
    if "t.me/+" in val or "t.me/joinchat/" in val:
        return True, val, "Invite Link Channel", val, None

    # 4. Check for Public Link / Username
    pub_match = re.search(r't\.me/([a-zA-Z0-9_]+)', val)
    username = pub_match.group(1) if pub_match else val
    if not username.startswith("@") and not username.startswith("-"):
        username = f"@{username}"

    try:
        chat = bot.get_chat(username)
        return True, chat.id, chat.title, f"https://t.me/{chat.username}", None
    except Exception as e:
        return False, None, None, None, f"❌ Access Error: <code>{e}</code>"

# ================= ANILIST AUTO-FETCHER =================
def fetch_anilist_data(query_text):
    query = '''
    query ($search: String) {
        Media (search: $search, type: ANIME) {
            id
            title { romaji english }
            coverImage { extraLarge large }
            bannerImage
            description(asHtml: false)
            episodes
            seasonYear
            genres
            averageScore
            status
        }
    }
    '''
    try:
        resp = requests.post(
            'https://graphql.anilist.co',
            json={'query': query, 'variables': {'search': query_text}},
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get('data', {}).get('Media')
    except Exception as e:
        logger.error(f"AniList Fetch Error: {e}")
    return None

# ================= PERSISTENT SESSIONS =================
def get_session(user_id):
    return col_sessions.find_one({"user_id": user_id}) or {}

def update_session(user_id, update_dict):
    col_sessions.update_one({"user_id": user_id}, {"$set": update_dict}, upsert=True)

def clear_session(user_id):
    col_sessions.update_one(
        {"user_id": user_id},
        {"$set": {
            "series_id": None,
            "files": {},
            "audio": None,
            "ep_num": None,
            "temp_series": {},
            "upload_ep": {},
            "current_quality": None,
            "batch_mode": False,
            "batch_data": {}
        }},
        upsert=True
    )

# ================= ZERO-CLUTTER PURGE SYSTEM =================
def track_message(chat_id, message_id):
    col_sessions.update_one(
        {"user_id": chat_id},
        {"$addToSet": {"msg_history": message_id}},
        upsert=True
    )

def clean_screen(chat_id, text, reply_markup=None, photo=None):
    try:
        bot.clear_step_handler_by_chat_id(chat_id=chat_id)
    except Exception:
        pass

    session = get_session(chat_id)
    history = session.get("msg_history", [])
    
    for mid in history:
        try:
            bot.delete_message(chat_id, mid)
        except Exception:
            pass

    col_sessions.update_one({"user_id": chat_id}, {"$set": {"msg_history": []}})

    if photo:
        try:
            sent = bot.send_photo(chat_id, photo=photo, caption=text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            sent = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        sent = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")

    track_message(chat_id, sent.message_id)
    return sent

def remove_user_msg(message):
    track_message(message.chat.id, message.message_id)
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

def get_channel_title(chat_identifier):
    if not chat_identifier:
        return "⚠️ Not Configured"
    try:
        chat = bot.get_chat(chat_identifier)
        return f"{chat.title} (<code>{chat.id}</code>)"
    except Exception:
        return f"<code>{chat_identifier}</code>"

def notify_admin_error(context, error_obj):
    err_str = str(error_obj)
    logger.error(f"[SYSTEM ALERT] {context}: {err_str}")
    try:
        alert_text = (
            f"🚨 <b>System Error Alert!</b>\n\n"
            f"📌 <b>Context:</b> {context}\n"
            f"❌ <b>Error Details:</b> <code>{err_str}</code>"
        )
        bot.send_message(OWNER_ID, alert_text, parse_mode="HTML")
    except Exception:
        pass

def delete_messages_later(chat_id, message_ids, delay=1800):
    def _del():
        time.sleep(delay)
        for mid in message_ids:
            try:
                bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass
    threading.Thread(target=_del, daemon=True).start()

def check_fsub(user_id):
    if is_vip(user_id):
        return True, []
    channels = list(col_fsub.find())
    if not channels:
        return True, []
    
    unsubbed = []
    for ch in channels:
        try:
            m = bot.get_chat_member(chat_id=ch["channel_id"], user_id=user_id)
            if m.status not in ["creator", "administrator", "member"]:
                unsubbed.append({"title": ch["title"], "link": ch["invite_link"]})
        except Exception as e:
            notify_admin_error(f"Force-Sub Check Error ({ch.get('title')})", e)
    return len(unsubbed) == 0, unsubbed

def get_fsub_keyboard(unsubbed, start_param=""):
    kb = types.InlineKeyboardMarkup()
    for ch in unsubbed:
        kb.add(StyledInlineKeyboardButton(text=f"🔔 Join {ch['title']}", url=ch["link"], style="primary"))
    retry_cb = f"retry_{start_param}" if start_param else "retry_main"
    kb.add(StyledInlineKeyboardButton(text="🔄 Verify & Try Again", callback_data=retry_cb, style="success"))
    return kb

def extract_file(message):
    if message.video:
        return message.video.file_id, "video", message.video.file_name or "Anime_Episode.mp4"
    if message.document:
        return message.document.file_id, "document", message.document.file_name or "Anime_Episode.mkv"
    return None, None, None

# ================= FORWARD CHANNEL AUTO DETECT =================
@bot.message_handler(func=lambda msg: is_admin(msg.chat.id) and msg.forward_from_chat is not None)
def handle_forwarded_channel_id(message):
    remove_user_msg(message)
    ch_id = message.forward_from_chat.id
    ch_title = message.forward_from_chat.title
    safe_link = get_safe_channel_link(ch_id) or "Private ID Stored"
    
    clean_screen(
        message.chat.id,
        f"📢 <b>Forwarded Channel Detected:</b>\n\n"
        f"📌 <b>Title:</b> {ch_title}\n"
        f"🆔 <b>Numeric ID:</b> <code>{ch_id}</code>\n"
        f"🔗 <b>Safe Invite Link:</b> <code>{safe_link}</code>\n\n"
        f"<i>Copied automatically! You can use this ID/Link in buttons.</i>"
    )

# ================= USER /START & FILE RETRIEVAL =================
@bot.message_handler(commands=["start"])
def handle_start(message):
    remove_user_msg(message)
    u = message.chat.id
    col_users.update_one({"user_id": u}, {"$set": {"user_id": u}}, upsert=True)
    
    text = message.text or ""
    parts = text.split(" ")
    start_param = parts[1] if len(parts) > 1 else ""

    passed, unsubbed = check_fsub(u)
    if not passed:
        clean_screen(
            u,
            "⚠️ <b>Access Denied!</b>\n\nYou must join our official channels to download episodes:",
            reply_markup=get_fsub_keyboard(unsubbed, start_param)
        )
        return

    # Direct File Download Token
    if start_param.startswith("file_"):
        file_doc = col_files.find_one({"file_key": start_param})
        if file_doc:
            file_name = file_doc.get("file_name", "Anime Episode")
            is_protected = (get_setting("protect_content") == "True")
            user_is_vip = is_vip(u)
            
            # 1. SEND FILE FIRST
            if file_doc["file_type"] == "video":
                sent = bot.send_video(
                    chat_id=u,
                    video=file_doc["file_id"],
                    caption=f"✦ <b>{file_name}</b>",
                    protect_content=is_protected
                )
            else:
                sent = bot.send_document(
                    chat_id=u,
                    document=file_doc["file_id"],
                    caption=f"✦ <b>{file_name}</b>",
                    protect_content=is_protected
                )

            # 2. SEND NOTICE SECOND
            if user_is_vip:
                bot.send_message(
                    chat_id=u,
                    text=f"📁 <b>{file_name}</b>\n\n👑 <i>VIP Membership Active: File will stay permanently in your chat!</i>"
                )
            else:
                notice = bot.send_message(
                    chat_id=u,
                    text=f"📁 <b>{file_name}</b>\n\n⏳ <i>This file will auto-delete in 30 minutes due to copyright policies. Forward it to your Saved Messages now!</i>"
                )
                delete_messages_later(u, [sent.message_id, notice.message_id], delay=1800)
        else:
            clean_screen(u, "❌ <b>This download link is expired or does not exist.</b>")
        return

    # Episode Selection Menu with Smart Navigation
    if start_param.startswith("ep_"):
        ep_id = start_param.replace("ep_", "")
        try:
            ep_doc = col_episodes.find_one({"_id": ObjectId(ep_id)})
            series = col_series.find_one({"_id": ep_doc["series_id"]}) if ep_doc else None
        except Exception:
            ep_doc, series = None, None

        if ep_doc and series:
            bot_un = get_active_bot_username()
            files = ep_doc.get("files", {})
            current_num = int(ep_doc.get("ep_num", "1"))

            prev_ep = col_episodes.find_one({"series_id": series["_id"], "ep_num": str(current_num - 1).zfill(2)})
            next_ep = col_episodes.find_one({"series_id": series["_id"], "ep_num": str(current_num + 1).zfill(2)})

            kb = types.InlineKeyboardMarkup()
            row1 = [
                StyledInlineKeyboardButton(text="480p", url=f"https://t.me/{bot_un}?start={files.get('480p', start_param)}", style="primary"),
                StyledInlineKeyboardButton(text="720p", url=f"https://t.me/{bot_un}?start={files.get('720p', start_param)}", style="primary"),
                StyledInlineKeyboardButton(text="1080p", url=f"https://t.me/{bot_un}?start={files.get('1080p', start_param)}", style="primary")
            ]
            row2 = [
                StyledInlineKeyboardButton(text="HDRip", url=f"https://t.me/{bot_un}?start={files.get('HDRip', start_param)}", style="primary")
            ]
            kb.row(*row1)
            kb.row(*row2)

            nav_row = []
            if prev_ep:
                nav_row.append(StyledInlineKeyboardButton(text=f"⏮️ Ep {current_num - 1}", url=f"https://t.me/{bot_un}?start=ep_{prev_ep['_id']}", style="primary"))
            if next_ep:
                nav_row.append(StyledInlineKeyboardButton(text=f"Ep {current_num + 1} ⏭️", url=f"https://t.me/{bot_un}?start=ep_{next_ep['_id']}", style="primary"))
            if nav_row:
                kb.row(*nav_row)

            styled_title = to_bold_serif(series['title'])
            caption = (
                f"✦ <b>{styled_title}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"▶ <b>Status :</b> ONGOING\n"
                f"▶ <b>Seasons :</b> {series.get('season', '01')}\n"
                f"▶ <b>Episodes :</b> {ep_doc.get('ep_num', '01')}\n"
                f"▶ <b>Audio :</b> {series.get('audio', 'Japanese [Eng-Sub]')}\n"
                f"▶ <b>Quality :</b> 480p , 720p , 1080p , HDRip\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"✦ <b>Powered By :</b> {get_setting('brand_name')}"
            )
            clean_screen(u, caption, reply_markup=kb, photo=series.get("poster"))
            return

    brand = get_setting("brand_name")
    kb = types.InlineKeyboardMarkup()
    if is_admin(u):
        kb.add(StyledInlineKeyboardButton(text="⚙️ Admin Control Hub", callback_data="admin_hub", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="ℹ️ How to Download", callback_data="user_help", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="👑 VIP Membership", callback_data="user_vip_info", style="success"))
    kb.add(StyledInlineKeyboardButton(text="⛩️ Official Updates Channel", url="https://t.me/ongoing_anime_by_zeno", style="primary"))
    
    clean_screen(
        u,
        f"👋 <b>Welcome to Ongoing Anime Delivery Hub!</b>\n\nDownload the latest anime episodes with high speed.\n\n✦ <b>Powered by:</b> {brand}",
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda c: c.data == "user_vip_info")
def handle_vip_info_cb(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    is_user_vip = is_vip(u)
    
    vip_status = "✅ <b>Active VIP Member</b>" if is_user_vip else "❌ <b>Free Tier User</b>"
    text = (
        f"👑 <b>VIP Membership Hub:</b>\n\n"
        f"📌 <b>Status:</b> {vip_status}\n\n"
        f"💎 <b>VIP Benefits:</b>\n"
        f"• 🚫 No Force-Subscription required\n"
        f"• ⏳ No 30-Minute Auto-Deletion (Keep files forever)\n"
        f"• ⚡ Unlimited Direct Access\n\n"
        f"<i>Contact Admin to upgrade your account!</i>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="back_start", style="danger"))
    clean_screen(u, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "user_help")
def handle_help_cb(call):
    bot.answer_callback_query(call.id)
    help_text = (
        "📖 <b>How to Download:</b>\n\n"
        "1. Channel par jaakar episode post ke neeche Quality button choose karein (480p / 720p / 1080p / HDRip).\n"
        "2. Bot turant direct download file deliver karega.\n"
        "3. <b>File aate hi apne 'Saved Messages' me forward kar lein</b> (Free users ke liye file 30 min baad delete hogi)."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="back_start", style="danger"))
    clean_screen(call.message.chat.id, help_text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "back_start")
def back_to_start(call):
    bot.answer_callback_query(call.id)
    msg = types.Message(message_id=0, from_user=call.from_user, date=None, chat=call.message.chat, content_type="text", options={}, json_string="")
    msg.text = "/start"
    handle_start(msg)

@bot.callback_query_handler(func=lambda c: c.data.startswith("retry_"))
def handle_retry(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    param = call.data.replace("retry_", "")
    passed, unsubbed = check_fsub(u)
    if passed:
        msg = types.Message(message_id=0, from_user=call.from_user, date=None, chat=call.message.chat, content_type="text", options={}, json_string="")
        msg.text = f"/start {param}" if param != "main" else "/start"
        handle_start(msg)
    else:
        bot.answer_callback_query(call.id, "❌ You have not joined all required channels yet!", show_alert=True)

# ================= ADMIN DASHBOARD =================
@bot.message_handler(commands=["admin"])
def handle_admin_cmd(message):
    remove_user_msg(message)
    if not is_admin(message.chat.id):
        return
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "admin_hub")
def cb_admin_hub(call):
    bot.answer_callback_query(call.id)
    if not is_admin(call.message.chat.id):
        return
    show_admin_panel(call.message.chat.id)

def show_admin_panel(chat_id):
    clear_session(chat_id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        StyledInlineKeyboardButton(text="🔍 Search Title", callback_data="admin_search_series", style="primary"),
        StyledInlineKeyboardButton(text="🎬 Upload Episode", callback_data="admin_upload_ep", style="success"),
        StyledInlineKeyboardButton(text="📦 Batch Uploader", callback_data="admin_batch_upload", style="success"),
        StyledInlineKeyboardButton(text="📺 Series Hub", callback_data="admin_series_hub", style="primary"),
        StyledInlineKeyboardButton(text="➕ Add New Series", callback_data="admin_add_series", style="success"),
        StyledInlineKeyboardButton(text="👑 VIP Manager", callback_data="admin_vip_hub", style="primary"),
        StyledInlineKeyboardButton(text="👥 Admin Team", callback_data="admin_team_hub", style="primary"),
        StyledInlineKeyboardButton(text="🛡️ ForceSub Hub", callback_data="admin_fsub_hub", style="primary"),
        StyledInlineKeyboardButton(text="⚙️ Bot Settings", callback_data="admin_settings", style="primary"),
        StyledInlineKeyboardButton(text="📢 Rich Broadcast", callback_data="admin_broadcast", style="primary"),
        StyledInlineKeyboardButton(text="📊 Live Stats", callback_data="admin_stats", style="primary")
    )
    clean_screen(chat_id, "⚙️ <b>Admin Master Control Hub</b>\n\nSelect an operation below:", reply_markup=kb)

# ================= BOT SETTINGS & TOGGLES =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_settings")
def show_settings_menu(call):
    bot.answer_callback_query(call.id)
    brand = get_setting("brand_name")
    main_ch = get_setting("main_channel_id")
    dl_ch = get_setting("download_channel_link")
    bot_un = get_active_bot_username()
    prot = get_setting("protect_content") or "False"
    b_mode = get_setting("button_mode") or "bot"
    
    text = (
        f"⚙️ <b>Bot Configuration:</b>\n\n"
        f"🏷️ <b>Brand Tag:</b> <code>{brand}</code>\n"
        f"📢 <b>Main Channel:</b> {get_channel_title(main_ch)}\n"
        f"🔗 <b>Download Channel Link:</b> <code>{dl_ch or 'Not Configured'}</code>\n"
        f"🔘 <b>Download Button Target:</b> <code>{'Direct Channel Link' if b_mode == 'channel' else 'Bot DM Links'}</code>\n"
        f"🤖 <b>Bot Username:</b> <code>@{bot_un}</code>\n"
        f"🛡️ <b>Anti-Forward:</b> <code>{prot}</code>"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text=f"🔘 Toggle Button Target ({'CHANNEL' if b_mode == 'channel' else 'BOT'})", callback_data="toggle_bmode", style="primary"),
        StyledInlineKeyboardButton(text="🔗 Set Download Channel Link", callback_data="edit_dl_ch", style="primary"),
        StyledInlineKeyboardButton(text=f"🛡️ Toggle Protect Content ({'ON' if prot == 'True' else 'OFF'})", callback_data="toggle_protect", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Brand Tag", callback_data="edit_brand_name", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Main Channel ID / Link", callback_data="edit_main_ch", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Bot Username", callback_data="edit_bot_user", style="primary"),
        StyledInlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_hub", style="danger")
    )
    clean_screen(call.message.chat.id, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "toggle_bmode")
def toggle_button_mode(call):
    bot.answer_callback_query(call.id)
    cur = get_setting("button_mode") or "bot"
    new_val = "channel" if cur == "bot" else "bot"
    update_setting("button_mode", new_val)
    show_settings_menu(call)

@bot.callback_query_handler(func=lambda c: c.data == "edit_dl_ch")
def start_edit_dl_ch(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(
        u,
        "🔗 <b>Send Channel Link for Download Buttons:</b>\n\n"
        "• <b>Private Channel:</b> Send post link (<code>https://t.me/c/...</code>) or Invite Link (<code>https://t.me/+...</code>)\n"
        "• <b>Public Channel:</b> Send link (<code>https://t.me/channel</code>)"
    )
    bot.register_next_step_handler(msg, step_save_dl_ch)

def step_save_dl_ch(message):
    remove_user_msg(message)
    u = message.chat.id
    success, cid, title, safe_link, err = resolve_channel_input(message.text)
    if not success:
        msg = clean_screen(u, f"{err}\n\n<b>Please send again:</b>")
        bot.register_next_step_handler(msg, step_save_dl_ch)
        return

    update_setting("download_channel_link", safe_link)
    clean_screen(u, f"✅ <b>Download Channel Link Configured:</b> <code>{safe_link}</code>")
    show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data == "toggle_protect")
def toggle_protect_cb(call):
    bot.answer_callback_query(call.id)
    cur = get_setting("protect_content") or "False"
    new_val = "False" if cur == "True" else "True"
    update_setting("protect_content", new_val)
    show_settings_menu(call)

@bot.callback_query_handler(func=lambda c: c.data == "edit_brand_name")
def start_edit_brand(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(u, "<b>Send New Brand Tag:</b>\nExample: <code>@ongoing_anime_by_zeno</code>")
    bot.register_next_step_handler(msg, step_save_brand)

def step_save_brand(message):
    remove_user_msg(message)
    update_setting("brand_name", message.text.strip())
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "edit_main_ch")
def start_edit_main_ch(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(u, "📢 <b>Send Main Channel Link or Numeric ID:</b>")
    bot.register_next_step_handler(msg, step_save_main_ch)

def step_save_main_ch(message):
    remove_user_msg(message)
    u = message.chat.id
    success, cid, title, safe_link, err = resolve_channel_input(message.text)
    if not success:
        msg = clean_screen(u, f"{err}\n\n<b>Please send a valid link or ID again:</b>")
        bot.register_next_step_handler(msg, step_save_main_ch)
        return

    update_setting("main_channel_id", cid)
    clean_screen(u, f"✅ <b>Main Channel Configured:</b> {title} (<code>{cid}</code>)")
    show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data == "edit_bot_user")
def start_edit_bot_user(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(u, "<b>Send Bot Username without @:</b>")
    bot.register_next_step_handler(msg, step_save_bot_user)

def step_save_bot_user(message):
    remove_user_msg(message)
    update_setting("bot_username", message.text.strip().replace("@", ""))
    show_admin_panel(message.chat.id)

# ================= MULTI-ADMIN TEAM =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_team_hub")
def show_admin_team_menu(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    if not is_owner(u):
        bot.answer_callback_query(call.id, "❌ Only the Bot Owner can manage Admins!", show_alert=True)
        return

    admins = list(col_admins.find())
    text = f"👥 <b>Admin Team Management:</b>\n\n👑 <b>Owner:</b> <code>{OWNER_ID}</code>\n\n<b>Sub-Admins:</b>\n"
    if admins:
        for idx, adm in enumerate(admins, 1):
            text += f"{idx}. ID: <code>{adm['user_id']}</code>\n"
    else:
        text += "<i>No sub-admins added yet.</i>\n"

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="➕ Add Sub-Admin", callback_data="add_sub_admin", style="success"),
        StyledInlineKeyboardButton(text="🗑️ Remove Sub-Admin", callback_data="rem_sub_admin", style="danger"),
        StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger")
    )
    clean_screen(u, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "add_sub_admin")
def start_add_sub_admin(call):
    bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "👤 <b>Send User ID of the new admin:</b>")
    bot.register_next_step_handler(msg, step_save_sub_admin)

def step_save_sub_admin(message):
    remove_user_msg(message)
    u = message.chat.id
    try:
        new_admin_id = int(message.text.strip())
        col_admins.update_one({"user_id": new_admin_id}, {"$set": {"user_id": new_admin_id}}, upsert=True)
        clean_screen(u, f"✅ Sub-Admin <code>{new_admin_id}</code> Added Successfully!")
    except ValueError:
        clean_screen(u, "❌ Invalid Numeric User ID.")
    show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data == "rem_sub_admin")
def remove_sub_admin_menu(call):
    bot.answer_callback_query(call.id)
    admins = list(col_admins.find())
    kb = types.InlineKeyboardMarkup(row_width=1)
    for adm in admins:
        kb.add(StyledInlineKeyboardButton(text=f"❌ Remove {adm['user_id']}", callback_data=f"del_adm_{adm['user_id']}", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_team_hub", style="primary"))
    clean_screen(call.message.chat.id, "🗑️ <b>Select Admin to Remove:</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_adm_"))
def perform_del_adm(call):
    bot.answer_callback_query(call.id)
    aid = int(call.data.replace("del_adm_", ""))
    col_admins.delete_one({"user_id": aid})
    show_admin_team_menu(call)

# ================= VIP SUBSCRIPTION MANAGER =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_vip_hub")
def show_vip_menu(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    vips = list(col_vip.find())
    
    text = "👑 <b>VIP Members Manager:</b>\n\n"
    if vips:
        for idx, v in enumerate(vips, 1):
            exp = "Lifetime" if v.get("is_lifetime") else time.strftime("%d-%m-%Y", time.localtime(v.get("expires_at", 0)))
            text += f"{idx}. ID: <code>{v['user_id']}</code> | Exp: <code>{exp}</code>\n"
    else:
        text += "<i>No VIP members found.</i>\n"

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="➕ Add VIP Member", callback_data="add_vip_user", style="success"),
        StyledInlineKeyboardButton(text="🗑️ Remove VIP Member", callback_data="rem_vip_user", style="danger"),
        StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger")
    )
    clean_screen(u, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "add_vip_user")
def start_add_vip(call):
    bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "👑 <b>Send User ID to Grant VIP:</b>")
    bot.register_next_step_handler(msg, step_vip_uid)

def step_vip_uid(message):
    remove_user_msg(message)
    u = message.chat.id
    try:
        target_uid = int(message.text.strip())
        update_session(u, {"vip_target": target_uid})
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            StyledInlineKeyboardButton(text="7 Days", callback_data="vip_dur_7", style="primary"),
            StyledInlineKeyboardButton(text="30 Days", callback_data="vip_dur_30", style="primary"),
            StyledInlineKeyboardButton(text="365 Days", callback_data="vip_dur_365", style="primary"),
            StyledInlineKeyboardButton(text="🌟 Lifetime", callback_data="vip_dur_life", style="success")
        )
        clean_screen(u, f"👑 <b>Select VIP Duration for ID:</b> <code>{target_uid}</code>", reply_markup=kb)
    except ValueError:
        clean_screen(u, "❌ Invalid User ID.")
        show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data.startswith("vip_dur_"))
def perform_grant_vip(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    session = get_session(u)
    target_uid = session.get("vip_target")
    dur_type = call.data.replace("vip_dur_", "")

    if dur_type == "life":
        col_vip.update_one({"user_id": target_uid}, {"$set": {"user_id": target_uid, "is_lifetime": True}}, upsert=True)
    else:
        days = int(dur_type)
        exp_time = time.time() + (days * 86400)
        col_vip.update_one({"user_id": target_uid}, {"$set": {"user_id": target_uid, "expires_at": exp_time, "is_lifetime": False}}, upsert=True)

    clean_screen(u, f"✅ <b>VIP granted successfully to User ID:</b> <code>{target_uid}</code>")
    show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data == "rem_vip_user")
def remove_vip_menu(call):
    bot.answer_callback_query(call.id)
    vips = list(col_vip.find())
    kb = types.InlineKeyboardMarkup(row_width=1)
    for v in vips:
        kb.add(StyledInlineKeyboardButton(text=f"❌ Revoke {v['user_id']}", callback_data=f"del_vip_{v['user_id']}", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_vip_hub", style="primary"))
    clean_screen(call.message.chat.id, "🗑️ <b>Select VIP user to revoke:</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_vip_"))
def perform_del_vip(call):
    bot.answer_callback_query(call.id)
    vid = int(call.data.replace("del_vip_", ""))
    col_vip.delete_one({"user_id": vid})
    show_vip_menu(call)

# ================= ANILIST AUTO-FETCH & ADD SERIES =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_add_series")
def start_add_series_options(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    clear_session(u)
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="🌐 Auto-Fetch via AniList (Recommended)", callback_data="add_s_anilist", style="success"),
        StyledInlineKeyboardButton(text="✍️ Manual Series Entry", callback_data="add_s_manual", style="primary"),
        StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger")
    )
    clean_screen(u, "🎬 <b>Add New Anime Series:</b>\n\nChoose method:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "add_s_anilist")
def prompt_anilist_search(call):
    bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "🌐 <b>Enter Anime Title for Auto-Fetch:</b>\nExample: <code>Solo Leveling</code> or <code>Tomb Raider King</code>")
    bot.register_next_step_handler(msg, step_execute_anilist_fetch)

def step_execute_anilist_fetch(message):
    remove_user_msg(message)
    u = message.chat.id
    query_title = message.text.strip()
    data = fetch_anilist_data(query_title)
    
    if not data:
        kb = types.InlineKeyboardMarkup()
        kb.add(StyledInlineKeyboardButton(text="✍️ Enter Manually", callback_data="add_s_manual", style="primary"))
        clean_screen(u, f"❌ Could not find Anime on AniList for: <code>{query_title}</code>", reply_markup=kb)
        return

    anime_title = data.get("title", {}).get("english") or data.get("title", {}).get("romaji") or query_title
    poster_url = data.get("coverImage", {}).get("extraLarge") or data.get("coverImage", {}).get("large")
    
    col_series.insert_one({
        "title": anime_title,
        "season": "01",
        "status": "ONGOING",
        "audio": "Japanese [Eng-Sub]",
        "poster": poster_url,
        "created_at": time.time()
    })
    
    clean_screen(
        u,
        f"✅ <b>Series Auto-Fetched & Added!</b>\n\n"
        f"📌 <b>Title:</b> {anime_title}\n"
        f"⚡ <b>Season:</b> 01\n"
        f"📊 <b>Score:</b> {data.get('averageScore', 'N/A')}%\n"
        f"🎭 <b>Genres:</b> {', '.join(data.get('genres', []))}",
        photo=poster_url
    )
    show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data == "add_s_manual")
def start_manual_add_series(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    clear_session(u)
    msg = clean_screen(u, "🎬 <b>Enter Anime Title:</b>\nExample: <code>Tomb Raider King</code>")
    bot.register_next_step_handler(msg, step_series_title)

def step_series_title(message):
    remove_user_msg(message)
    u = message.chat.id
    title = message.text.strip()
    update_session(u, {"temp_series.title": title})
    msg = clean_screen(u, f"📌 <b>Series:</b> {title}\n\n<b>Enter Season Number:</b> (e.g. <code>01</code>)")
    bot.register_next_step_handler(msg, step_series_season)

def step_series_season(message):
    remove_user_msg(message)
    u = message.chat.id
    season = str(message.text.strip()).zfill(2)
    update_session(u, {"temp_series.season": season})
    msg = clean_screen(u, "🔊 <b>Enter Audio / Language:</b>\nExample: <code>Japanese [Eng-Sub]</code>")
    bot.register_next_step_handler(msg, step_series_audio)

def step_series_audio(message):
    remove_user_msg(message)
    u = message.chat.id
    audio = message.text.strip()
    update_session(u, {"temp_series.audio": audio})
    msg = clean_screen(u, "🖼️ <b>Send Poster Photo for this Series:</b>")
    bot.register_next_step_handler(msg, step_series_poster)

def step_series_poster(message):
    remove_user_msg(message)
    u = message.chat.id
    if not message.photo:
        msg = clean_screen(u, "❌ <b>Please send a valid photo:</b>")
        bot.register_next_step_handler(msg, step_series_poster)
        return

    poster_id = message.photo[-1].file_id
    session = get_session(u)
    temp = session.get("temp_series", {})
    
    col_series.insert_one({
        "title": temp.get("title", "Unknown"),
        "season": temp.get("season", "01"),
        "status": "ONGOING",
        "audio": temp.get("audio", "Japanese [Eng-Sub]"),
        "poster": poster_id,
        "created_at": time.time()
    })
    
    clean_screen(u, f"✅ <b>Series Added Successfully!</b>\n\n📌 <b>Title:</b> {temp.get('title')}\n⚡ <b>Season:</b> {temp.get('season')}")
    show_admin_panel(u)

# ================= EPISODE UPLOAD FLOW =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_upload_ep")
def handle_upload_ep_entry(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    series_list = list(col_series.find().sort("title", 1))
    if not series_list:
        kb = types.InlineKeyboardMarkup()
        kb.add(StyledInlineKeyboardButton(text="➕ Add New Series", callback_data="admin_add_series", style="success"))
        kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
        clean_screen(u, "⚠️ <b>No Series Found!</b>\nPlease create a series first.", reply_markup=kb)
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for s in series_list:
        kb.add(StyledInlineKeyboardButton(text=f"🎬 {s['title']} (S{s.get('season', '01')})", callback_data=f"sel_ep_up_{s['_id']}", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger"))
    clean_screen(u, "🎬 <b>Select Series to Upload Episode:</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sel_ep_up_"))
def start_episode_upload(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    series_id = call.data.replace("sel_ep_up_", "")
    series = col_series.find_one({"_id": ObjectId(series_id)})
    if not series:
        return
    
    clear_session(u)
    update_session(u, {"upload_ep.series_id": series_id, "upload_ep.files": {}})
    msg = clean_screen(u, f"🎬 <b>Series:</b> {series['title']}\n\n<b>Enter Episode Number:</b> (e.g. <code>01</code>, <code>07</code>)")
    bot.register_next_step_handler(msg, step_ep_num)

def step_ep_num(message):
    remove_user_msg(message)
    u = message.chat.id
    ep_num = str(message.text.strip()).zfill(2)
    update_session(u, {"upload_ep.ep_num": ep_num})
    show_quality_upload_menu(u)

def show_quality_upload_menu(chat_id):
    session = get_session(chat_id)
    ep_data = session.get("upload_ep", {})
    files = ep_data.get("files", {})
    series_id = ep_data.get("series_id")
    series = col_series.find_one({"_id": ObjectId(series_id)}) if series_id else {}

    kb = types.InlineKeyboardMarkup()
    row1 = [
        StyledInlineKeyboardButton(text=f"{'✅' if '480p' in files else '📤'} 480p", callback_data="up_q_480p", style="primary"),
        StyledInlineKeyboardButton(text=f"{'✅' if '720p' in files else '📤'} 720p", callback_data="up_q_720p", style="primary"),
        StyledInlineKeyboardButton(text=f"{'✅' if '1080p' in files else '📤'} 1080p", callback_data="up_q_1080p", style="primary")
    ]
    row2 = [
        StyledInlineKeyboardButton(text=f"{'✅' if 'HDRip' in files else '📤'} HDRip", callback_data="up_q_HDRip", style="primary")
    ]
    kb.row(*row1)
    kb.row(*row2)
    
    if files:
        kb.add(StyledInlineKeyboardButton(text="🚀 Publish to Main Channel", callback_data="publish_episode", style="success"))
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="admin_hub", style="danger"))

    text = (
        f"🎬 <b>Series:</b> {series.get('title', 'Unknown')}\n"
        f"🔢 <b>Episode:</b> {ep_data.get('ep_num', '01')}\n\n"
        f"<i>Quality par tap karke video/file upload karein:</i>"
    )
    clean_screen(chat_id, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("up_q_"))
def handle_quality_upload_prompt(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    quality = call.data.replace("up_q_", "")
    update_session(u, {"current_quality": quality})
    
    msg = clean_screen(u, f"📤 <b>Send Video/Document for [{quality}]:</b>")
    bot.register_next_step_handler(msg, step_receive_file)

def step_receive_file(message):
    remove_user_msg(message)
    u = message.chat.id
    fid, ftype, fname = extract_file(message)
    
    if not fid:
        msg = clean_screen(u, "❌ <b>Please send a valid Video or Document file:</b>")
        bot.register_next_step_handler(msg, step_receive_file)
        return

    session = get_session(u)
    quality = session.get("current_quality", "720p")
    ep_data = session.get("upload_ep", {})
    series = col_series.find_one({"_id": ObjectId(ep_data.get("series_id"))}) or {}
    
    file_key = f"file_{uuid.uuid4().hex[:10]}"
    col_files.insert_one({
        "file_key": file_key,
        "file_id": fid,
        "file_type": ftype,
        "file_name": f"{series.get('title', 'Anime')} - S{series.get('season', '01')}E{ep_data.get('ep_num', '01')} [{quality}]",
        "created_at": time.time()
    })

    col_sessions.update_one(
        {"user_id": u},
        {"$set": {f"upload_ep.files.{quality}": file_key}}
    )
    show_quality_upload_menu(u)

# ================= BATCH EPISODE UPLOADER =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_batch_upload")
def handle_batch_upload_entry(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    series_list = list(col_series.find().sort("title", 1))
    if not series_list:
        clean_screen(u, "⚠️ No series found. Please add a series first.")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for s in series_list:
        kb.add(StyledInlineKeyboardButton(text=f"📦 {s['title']}", callback_data=f"sel_batch_{s['_id']}", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger"))
    clean_screen(u, "📦 <b>Batch Uploader:</b> Select Series:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sel_batch_"))
def start_batch_series_conf(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("sel_batch_", "")
    update_session(u, {"batch_data.series_id": sid})
    
    msg = clean_screen(u, "🔢 <b>Enter Starting Episode Number:</b> (e.g. <code>01</code>)")
    bot.register_next_step_handler(msg, step_batch_start_ep)

def step_batch_start_ep(message):
    remove_user_msg(message)
    u = message.chat.id
    start_ep = int(message.text.strip())
    update_session(u, {"batch_data.current_ep": start_ep, "batch_data.count": 0, "batch_mode": True})
    
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🛑 Finish Batch Upload", callback_data="finish_batch", style="success"))
    clean_screen(
        u,
        f"⚡ <b>Batch Mode ACTIVE!</b>\n\n"
        f"Starting from <b>Episode {start_ep}</b> (720p/Direct).\n"
        f"• Forward or send video files one by one.\n"
        f"• Episode numbers auto-increment automatically!\n"
        f"• Tap <b>'Finish'</b> when done.",
        reply_markup=kb
    )

@bot.message_handler(func=lambda m: is_admin(m.chat.id) and get_session(m.chat.id).get("batch_mode") is True, content_types=['video', 'document'])
def handle_incoming_batch_file(message):
    remove_user_msg(message)
    u = message.chat.id
    session = get_session(u)
    bdata = session.get("batch_data", {})
    sid = bdata.get("series_id")
    cur_ep = bdata.get("current_ep", 1)
    series = col_series.find_one({"_id": ObjectId(sid)})

    fid, ftype, fname = extract_file(message)
    if not fid:
        return

    ep_str = str(cur_ep).zfill(2)
    file_key = f"file_{uuid.uuid4().hex[:10]}"
    col_files.insert_one({
        "file_key": file_key,
        "file_id": fid,
        "file_type": ftype,
        "file_name": f"{series.get('title')} - S{series.get('season', '01')}E{ep_str} [720p]",
        "created_at": time.time()
    })

    col_episodes.insert_one({
        "series_id": series["_id"],
        "ep_num": ep_str,
        "files": {"720p": file_key},
        "created_at": time.time()
    })

    update_session(u, {
        "batch_data.current_ep": cur_ep + 1,
        "batch_data.count": bdata.get("count", 0) + 1
    })

    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🛑 Finish Batch Upload", callback_data="finish_batch", style="success"))
    clean_screen(u, f"✅ <b>Episode {ep_str} Saved!</b> Send next video or click finish.", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "finish_batch")
def finish_batch_cb(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    session = get_session(u)
    bdata = session.get("batch_data", {})
    total = bdata.get("count", 0)
    clear_session(u)
    clean_screen(u, f"🎉 <b>Batch Complete!</b> Successfully uploaded {total} episodes.")
    show_admin_panel(u)

# ================= BROADCAST WITH SMART BUTTONS =================
@bot.callback_query_handler(func=lambda c: c.data == "publish_episode")
def publish_episode_broadcast(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    session = get_session(u)
    ep_data = session.get("upload_ep", {})
    series = col_series.find_one({"_id": ObjectId(ep_data.get("series_id"))})
    
    if not series or not ep_data.get("files"):
        clean_screen(u, "❌ Incomplete data. Upload cancelled.")
        return

    ep_res = col_episodes.insert_one({
        "series_id": series["_id"],
        "ep_num": ep_data["ep_num"],
        "files": ep_data["files"],
        "created_at": time.time()
    })

    main_ch = get_setting("main_channel_id")
    bot_un = get_active_bot_username()
    brand = get_setting("brand_name")
    b_mode = get_setting("button_mode") or "bot"
    dl_ch_link = get_setting("download_channel_link")
    files = ep_data["files"]
    ep_id = str(ep_res.inserted_id)

    styled_title = to_bold_serif(series['title'])
    caption = (
        f"✦ <b>{styled_title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"▶ <b>Status :</b> ONGOING\n"
        f"▶ <b>Seasons :</b> {series.get('season', '01')}\n"
        f"▶ <b>Episodes :</b> {ep_data['ep_num']}\n"
        f"▶ <b>Audio :</b> {series.get('audio', 'Japanese [Eng-Sub]')}\n"
        f"▶ <b>Quality :</b> 480p , 720p , 1080p , HDRip\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✦ <b>Powered By :</b> {brand}"
    )

    # Resolve button links based on active mode
    def make_btn_url(quality_key):
        if b_mode == "channel" and dl_ch_link:
            return dl_ch_link
        if quality_key in files:
            return f"https://t.me/{bot_un}?start={files[quality_key]}"
        return f"https://t.me/{bot_un}?start=ep_{ep_id}"

    kb = types.InlineKeyboardMarkup()
    row1 = [
        StyledInlineKeyboardButton(text="480p", url=make_btn_url("480p"), style="primary"),
        StyledInlineKeyboardButton(text="720p", url=make_btn_url("720p"), style="primary"),
        StyledInlineKeyboardButton(text="1080p", url=make_btn_url("1080p"), style="primary")
    ]
    row2 = [
        StyledInlineKeyboardButton(text="HDRip", url=make_btn_url("HDRip"), style="primary")
    ]
    kb.row(*row1)
    kb.row(*row2)

    if main_ch:
        try:
            bot.send_photo(
                chat_id=main_ch,
                photo=series.get("poster"),
                caption=caption,
                reply_markup=kb,
                parse_mode="HTML"
            )
            clean_screen(u, "✅ <b>Episode Published & Broadcasted Successfully!</b>")
        except Exception as e:
            notify_admin_error("Broadcast Failed", e)
            clean_screen(u, f"⚠️ Broadcast Error: <code>{e}</code>")
    else:
        clean_screen(u, "⚠️ Saved in DB, but Main Channel is not set.")

    clear_session(u)
    show_admin_panel(u)

# ================= RICH MEDIA BROADCAST TO USERS =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_broadcast")
def start_rich_broadcast_prompt(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(
        u,
        "📢 <b>Rich Media Broadcast:</b>\n\n"
        "Send any <b>Text, Photo, or Video</b> to broadcast.\n\n"
        "<i>Tip: Aap caption ke aakhri me button add kar sakte hain:</i>\n"
        "<code>Button Text | https://t.me/yourlink</code>"
    )
    bot.register_next_step_handler(msg, perform_rich_broadcast)

def perform_rich_broadcast(message):
    remove_user_msg(message)
    u = message.chat.id
    users = list(col_users.find())
    
    caption_text = message.caption or message.text or ""
    btn_markup = None
    
    if "|" in caption_text:
        lines = caption_text.split("\n")
        last_line = lines[-1]
        if "|" in last_line:
            b_parts = last_line.split("|")
            b_text = b_parts[0].strip()
            b_url = b_parts[1].strip()
            btn_markup = types.InlineKeyboardMarkup()
            btn_markup.add(StyledInlineKeyboardButton(text=b_text, url=b_url, style="primary"))
            caption_text = "\n".join(lines[:-1]).strip()

    clean_screen(u, f"⏳ Broadcasting to {len(users)} users...")
    success, fail = 0, 0

    for usr in users:
        uid = usr.get("user_id")
        try:
            if message.photo:
                bot.send_photo(uid, photo=message.photo[-1].file_id, caption=caption_text, reply_markup=btn_markup, parse_mode="HTML")
            elif message.video:
                bot.send_video(uid, video=message.video.file_id, caption=caption_text, reply_markup=btn_markup, parse_mode="HTML")
            elif message.document:
                bot.send_document(uid, document=message.document.file_id, caption=caption_text, reply_markup=btn_markup, parse_mode="HTML")
            else:
                bot.send_message(uid, text=caption_text, reply_markup=btn_markup, parse_mode="HTML")
            success += 1
        except Exception:
            fail += 1

    clean_screen(u, f"📢 <b>Broadcast Finished!</b>\n\n✅ <b>Success:</b> {success}\n❌ <b>Failed/Blocked:</b> {fail}")
    show_admin_panel(u)

# ================= FORCESUB HUB =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_fsub_hub")
def show_fsub_menu(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    channels = list(col_fsub.find())
    
    text = "🛡️ <b>Force-Subscription Management:</b>\n\n"
    if channels:
        for i, ch in enumerate(channels, 1):
            text += f"{i}. <b>{ch['title']}</b> (<code>{ch['channel_id']}</code>)\n"
    else:
        text += "<i>No ForceSub channels active.</i>\n"

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="➕ Add ForceSub Channel", callback_data="add_fsub_ch", style="success"),
        StyledInlineKeyboardButton(text="🗑️ Remove ForceSub Channel", callback_data="rem_fsub_ch", style="danger"),
        StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger")
    )
    clean_screen(u, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "add_fsub_ch")
def start_add_fsub(call):
    bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "📢 <b>Send ForceSub Channel Username, ID, or Post Link:</b>")
    bot.register_next_step_handler(msg, step_save_fsub)

def step_save_fsub(message):
    remove_user_msg(message)
    u = message.chat.id
    success, cid, title, safe_link, err = resolve_channel_input(message.text)
    if not success:
        msg = clean_screen(u, f"{err}\n\n<b>Send again:</b>")
        bot.register_next_step_handler(msg, step_save_fsub)
        return

    col_fsub.update_one(
        {"channel_id": cid},
        {"$set": {"channel_id": cid, "title": title, "invite_link": safe_link}},
        upsert=True
    )
    clean_screen(u, f"✅ Added ForceSub: <b>{title}</b>")
    show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data == "rem_fsub_ch")
def remove_fsub_menu(call):
    bot.answer_callback_query(call.id)
    channels = list(col_fsub.find())
    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        kb.add(StyledInlineKeyboardButton(text=f"❌ {ch['title']}", callback_data=f"del_fsub_{ch['channel_id']}", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_fsub_hub", style="primary"))
    clean_screen(call.message.chat.id, "🗑️ <b>Select channel to remove:</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_fsub_"))
def perform_del_fsub(call):
    bot.answer_callback_query(call.id)
    cid = int(call.data.replace("del_fsub_", ""))
    col_fsub.delete_one({"channel_id": cid})
    show_fsub_menu(call)

# ================= SERIES HUB & STATS =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_series_hub")
def handle_series_hub_list(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    series_list = list(col_series.find().sort("title", 1))
    
    if not series_list:
        clean_screen(u, "⚠️ <b>No Series Found!</b>")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for s in series_list:
        kb.add(StyledInlineKeyboardButton(text=f"📺 {s['title']} (S{s.get('season', '01')})", callback_data=f"view_s_{s['_id']}", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger"))
    clean_screen(u, "📺 <b>Series Hub:</b> Select a series to view:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("view_s_"))
def view_series_details(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("view_s_", "")
    series = col_series.find_one({"_id": ObjectId(sid)})
    if not series:
        return

    ep_count = col_episodes.count_documents({"series_id": series["_id"]})
    styled_title = to_bold_serif(series['title'])
    
    caption = (
        f"✦ <b>{styled_title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"▶ <b>Status :</b> {series.get('status', 'ONGOING')}\n"
        f"▶ <b>Season :</b> {series.get('season', '01')}\n"
        f"▶ <b>Uploaded Episodes :</b> {ep_count}\n"
        f"▶ <b>Audio :</b> {series.get('audio', 'Japanese [Eng-Sub]')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        StyledInlineKeyboardButton(text="🎬 Upload Ep", callback_data=f"sel_ep_up_{sid}", style="success"),
        StyledInlineKeyboardButton(text="🗑️ Delete Series", callback_data=f"del_s_conf_{sid}", style="danger"),
        StyledInlineKeyboardButton(text="🔙 Hub", callback_data="admin_series_hub", style="primary")
    )
    clean_screen(u, caption, reply_markup=kb, photo=series.get("poster"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_s_conf_"))
def delete_series_confirm(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("del_s_conf_", "")
    col_series.delete_one({"_id": ObjectId(sid)})
    col_episodes.delete_many({"series_id": ObjectId(sid)})
    clean_screen(u, "✅ <b>Series Deleted!</b>")
    show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
def show_live_stats(call):
    bot.answer_callback_query(call.id)
    total_users = col_users.count_documents({})
    total_series = col_series.count_documents({})
    total_episodes = col_episodes.count_documents({})
    total_vips = col_vip.count_documents({})
    
    text = (
        f"📊 <b>Live Database Statistics:</b>\n\n"
        f"👥 <b>Total Users:</b> <code>{total_users}</code>\n"
        f"👑 <b>VIP Users:</b> <code>{total_vips}</code>\n"
        f"📺 <b>Total Series:</b> <code>{total_series}</code>\n"
        f"🎬 <b>Total Episodes:</b> <code>{total_episodes}</code>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger"))
    clean_screen(call.message.chat.id, text, reply_markup=kb)

# ================= BOT POLLING START =================
if __name__ == "__main__":
    logger.info(f"🤖 Starting Anime Delivery Master Bot (@{DETECTED_BOT_USERNAME})...")
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
