import os
import sys
import re
import time
import uuid
import random
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
    return "✅ Ongoing Anime Master Bot Cluster is Active & Running 24/7!"

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

master_bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

try:
    BOT_ME = master_bot.get_me()
    DETECTED_MASTER_USERNAME = BOT_ME.username
except Exception:
    DETECTED_MASTER_USERNAME = "ongoing_anime_by_zenobot"

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
col_workers = db["workers"]
col_auto_delete = db["auto_delete"]

if not col_settings.find_one({"key": "config"}):
    col_settings.insert_one({
        "key": "config",
        "brand_name": "@ongoing_anime_by_zeno",
        "main_channel_id": "",
        "download_channel_link": "",
        "button_mode": "bot",
        "bot_username": DETECTED_MASTER_USERNAME,
        "protect_content": "False"
    })

def get_setting(field):
    cfg = col_settings.find_one({"key": "config"}) or {}
    return cfg.get(field, "")

def update_setting(field, val):
    col_settings.update_one({"key": "config"}, {"$set": {field: str(val)}}, upsert=True)

def get_master_username():
    un = get_setting("bot_username")
    return un if un else DETECTED_MASTER_USERNAME

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
    vip_entry = col_vip.find_one({"user_id": int(user_id)})
    if not vip_entry:
        return False
    if vip_entry.get("is_lifetime", False):
        return True
    return vip_entry.get("expires_at", 0) > time.time()

# ================= SMART CHANNEL RESOLVER =================
def get_safe_channel_link(chat_identifier):
    if not chat_identifier:
        return None
    try:
        chat = master_bot.get_chat(chat_identifier)
        if chat.username:
            return f"https://t.me/{chat.username}"
        if chat.invite_link:
            return chat.invite_link
        return master_bot.export_chat_invite_link(chat.id)
    except Exception as e:
        logger.error(f"Invite Link Error: {e}")
        return None

def resolve_channel_input(raw_input):
    val = str(raw_input).strip()
    if not val:
        return False, None, None, None, "Input cannot be empty!"

    c_match = re.search(r't\.me/c/(\d+)', val)
    if c_match:
        extracted_id = int(f"-100{c_match.group(1)}")
        safe_link = get_safe_channel_link(extracted_id) or val
        try:
            chat = master_bot.get_chat(extracted_id)
            return True, extracted_id, chat.title, safe_link, None
        except Exception:
            return True, extracted_id, f"Private Channel ({extracted_id})", safe_link, None

    if val.startswith("-100") or val.startswith("-") or val.isdigit():
        try:
            full_id = int(val) if str(val).startswith("-") else int(f"-100{val}")
            safe_link = get_safe_channel_link(full_id) or "https://t.me"
            try:
                chat = master_bot.get_chat(full_id)
                return True, full_id, chat.title, safe_link, None
            except Exception:
                return True, full_id, f"Channel ({full_id})", safe_link, None
        except ValueError:
            pass

    if "t.me/+" in val or "t.me/joinchat/" in val:
        return True, val, "Invite Link Channel", val, None

    pub_match = re.search(r't\.me/([a-zA-Z0-9_]+)', val)
    username = pub_match.group(1) if pub_match else val
    if not username.startswith("@") and not username.startswith("-"):
        username = f"@{username}"

    try:
        chat = master_bot.get_chat(username)
        return True, chat.id, chat.title, f"https://t.me/{chat.username}", None
    except Exception as e:
        return False, None, None, None, f"❌ Access Error: <code>{e}</code>"

def get_channel_title(chat_identifier):
    if not chat_identifier:
        return "⚠️ Not Configured"
    try:
        chat = master_bot.get_chat(chat_identifier)
        return f"{chat.title} (<code>{chat.id}</code>)"
    except Exception:
        return f"<code>{chat_identifier}</code>"

def notify_admin_error(context, error_obj):
    err_str = str(error_obj)
    logger.error(f"[SYSTEM ALERT] {context}: {err_str}")
    try:
        master_bot.send_message(
            OWNER_ID,
            f"🚨 <b>System Error Alert!</b>\n\n📌 <b>Context:</b> {context}\n❌ <b>Error Details:</b> <code>{err_str}</code>",
            parse_mode="HTML"
        )
    except Exception:
        pass

# ================= RELIABLE DATABASE-BACKED AUTO-DELETE ENGINE =================
def schedule_auto_delete(bot_token, chat_id, message_ids, delay=1800):
    """Saves deletion task in MongoDB so restarts won't break the timer."""
    col_auto_delete.insert_one({
        "bot_token": bot_token,
        "chat_id": chat_id,
        "message_ids": message_ids,
        "delete_at": time.time() + delay,
        "created_at": time.time()
    })

def auto_delete_daemon():
    """Background worker that continuously scans DB and purges expired messages."""
    bot_instances = {}
    while True:
        try:
            now = time.time()
            due_tasks = list(col_auto_delete.find({"delete_at": {"$lte": now}}))
            for task in due_tasks:
                token = task.get("bot_token", BOT_TOKEN)
                if token not in bot_instances:
                    bot_instances[token] = telebot.TeleBot(token)
                target_bot = bot_instances[token]

                chat_id = task.get("chat_id")
                for mid in task.get("message_ids", []):
                    try:
                        target_bot.delete_message(chat_id=chat_id, message_id=mid)
                    except Exception:
                        pass
                col_auto_delete.delete_one({"_id": task["_id"]})
        except Exception as e:
            logger.error(f"Auto-delete daemon error: {e}")
        time.sleep(10)

threading.Thread(target=auto_delete_daemon, daemon=True).start()

# ================= FSUB & ANILIST =================
def check_fsub(bot_instance, user_id):
    if is_vip(user_id):
        return True, []
    channels = list(col_fsub.find())
    if not channels:
        return True, []
    
    unsubbed = []
    for ch in channels:
        try:
            m = bot_instance.get_chat_member(chat_id=ch["channel_id"], user_id=user_id)
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

def fetch_anilist_data(query_text):
    query = '''
    query ($search: String) {
        Media (search: $search, type: ANIME) {
            id
            title { romaji english }
            coverImage { extraLarge large }
            bannerImage
            episodes
            genres
            averageScore
        }
    }
    '''
    try:
        resp = requests.post(
            'https://graphql.anilist.co',
            json={'query': query, 'variables': {'search': query_text}},
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get('data', {}).get('Media')
    except Exception as e:
        logger.error(f"AniList Fetch Error: {e}")
    return None

# ================= PERSISTENT SESSIONS & SCREEN PURGE =================
def get_session(user_id):
    return col_sessions.find_one({"user_id": user_id}) or {}

def update_session(user_id, update_dict):
    col_sessions.update_one({"user_id": user_id}, {"$set": update_dict}, upsert=True)

def clear_session(user_id):
    col_sessions.update_one(
        {"user_id": user_id},
        {"$set": {
            "series_id": None, "files": {}, "audio": None, "ep_num": None,
            "temp_series": {}, "upload_ep": {}, "current_quality": None,
            "batch_mode": False, "batch_data": {}
        }},
        upsert=True
    )

def track_message(chat_id, message_id):
    col_sessions.update_one({"user_id": chat_id}, {"$addToSet": {"msg_history": message_id}}, upsert=True)

def clean_screen(chat_id, text, reply_markup=None, photo=None):
    try:
        master_bot.clear_step_handler_by_chat_id(chat_id=chat_id)
    except Exception:
        pass

    session = get_session(chat_id)
    for mid in session.get("msg_history", []):
        try:
            master_bot.delete_message(chat_id, mid)
        except Exception:
            pass

    col_sessions.update_one({"user_id": chat_id}, {"$set": {"msg_history": []}})

    if photo:
        try:
            sent = master_bot.send_photo(chat_id, photo=photo, caption=text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            sent = master_bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        sent = master_bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")

    track_message(chat_id, sent.message_id)
    return sent

def remove_user_msg(message):
    track_message(message.chat.id, message.message_id)
    try:
        master_bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

# ================= FORWARD CHANNEL AUTO DETECT =================
@master_bot.message_handler(func=lambda msg: is_admin(msg.chat.id) and msg.forward_from_chat is not None)
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
        f"<i>Copied automatically! You can use this ID/Link anytime.</i>"
    )

# ================= MULTI-BOT DYNAMIC RANDOM ENGINE =================
active_worker_threads = {}

def get_all_active_bots():
    workers = list(col_workers.find({"is_active": True}))
    usernames = [w["username"] for w in workers if w.get("username")]
    master_un = get_master_username()
    if master_un not in usernames:
        usernames.append(master_un)
    return usernames if usernames else [master_un]

def get_random_worker():
    pool = get_all_active_bots()
    return random.choice(pool)

def common_file_delivery_handler(bot_instance, message, current_bot_username):
    u = message.chat.id
    col_users.update_one({"user_id": u}, {"$set": {"user_id": u}}, upsert=True)
    
    parts = (message.text or "").split(" ")
    start_param = parts[1] if len(parts) > 1 else ""

    passed, unsubbed = check_fsub(bot_instance, u)
    if not passed:
        bot_instance.send_message(
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
                sent = bot_instance.send_video(
                    chat_id=u,
                    video=file_doc["file_id"],
                    caption=f"✦ <b>{file_name}</b>",
                    protect_content=is_protected
                )
            else:
                sent = bot_instance.send_document(
                    chat_id=u,
                    document=file_doc["file_id"],
                    caption=f"✦ <b>{file_name}</b>",
                    protect_content=is_protected
                )

            # 2. SEND NOTICE SECOND (AND SCHEDULE DATABASE 30-MIN PURGE)
            if user_is_vip:
                bot_instance.send_message(
                    chat_id=u,
                    text=f"📁 <b>{file_name}</b>\n\n👑 <i>VIP Active: File is permanent in your chat!</i>"
                )
            else:
                notice = bot_instance.send_message(
                    chat_id=u,
                    text=f"📁 <b>{file_name}</b>\n\n⏳ <i>This file will auto-delete in 30 minutes due to copyright policies. Forward it to your Saved Messages now!</i>"
                )
                # PERSISTENT 30-MINUTE AUTO-DELETE
                schedule_auto_delete(
                    bot_token=bot_instance.token,
                    chat_id=u,
                    message_ids=[sent.message_id, notice.message_id],
                    delay=1800
                )
        else:
            bot_instance.send_message(u, "❌ <b>This download link is expired or does not exist.</b>")
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
            files = ep_doc.get("files", {})
            current_num = int(ep_doc.get("ep_num", "1"))

            prev_ep = col_episodes.find_one({"series_id": series["_id"], "ep_num": str(current_num - 1).zfill(2)})
            next_ep = col_episodes.find_one({"series_id": series["_id"], "ep_num": str(current_num + 1).zfill(2)})

            kb = types.InlineKeyboardMarkup()
            row1 = [
                StyledInlineKeyboardButton(text="480p", url=f"https://t.me/{get_random_worker()}?start={files.get('480p', start_param)}", style="primary"),
                StyledInlineKeyboardButton(text="720p", url=f"https://t.me/{get_random_worker()}?start={files.get('720p', start_param)}", style="primary"),
                StyledInlineKeyboardButton(text="1080p", url=f"https://t.me/{get_random_worker()}?start={files.get('1080p', start_param)}", style="primary")
            ]
            row2 = [
                StyledInlineKeyboardButton(text="HDRip", url=f"https://t.me/{get_random_worker()}?start={files.get('HDRip', start_param)}", style="primary")
            ]
            kb.row(*row1)
            kb.row(*row2)

            nav_row = []
            if prev_ep:
                nav_row.append(StyledInlineKeyboardButton(text=f"⏮️ Ep {current_num - 1}", url=f"https://t.me/{get_random_worker()}?start=ep_{prev_ep['_id']}", style="primary"))
            if next_ep:
                nav_row.append(StyledInlineKeyboardButton(text=f"Ep {current_num + 1} ⏭️", url=f"https://t.me/{get_random_worker()}?start=ep_{next_ep['_id']}", style="primary"))
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
            bot_instance.send_photo(u, photo=series.get("poster"), caption=caption, reply_markup=kb)
            return

    brand = get_setting("brand_name")
    kb = types.InlineKeyboardMarkup()
    if is_admin(u):
        kb.add(StyledInlineKeyboardButton(text="⚙️ Admin Control Hub", callback_data="admin_hub", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="ℹ️ How to Download", callback_data="user_help", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="👑 VIP Membership", callback_data="user_vip_info", style="success"))
    kb.add(StyledInlineKeyboardButton(text="⛩️ Official Updates Channel", url="https://t.me/ongoing_anime_by_zeno", style="primary"))
    
    bot_instance.send_message(
        u,
        f"👋 <b>Welcome to Ongoing Anime Delivery Hub!</b>\n\nCluster worker online for lightning speed file delivery.\n\n✦ <b>Powered by:</b> {brand}",
        reply_markup=kb
    )

def start_worker_bot_instance(token, username):
    try:
        worker = telebot.TeleBot(token, parse_mode="HTML")

        @worker.message_handler(commands=["start"])
        def worker_start(msg):
            common_file_delivery_handler(worker, msg, username)

        @worker.callback_query_handler(func=lambda c: c.data.startswith("retry_"))
        def worker_retry(call):
            worker.answer_callback_query(call.id)
            param = call.data.replace("retry_", "")
            passed, _ = check_fsub(worker, call.message.chat.id)
            if passed:
                msg = types.Message(message_id=0, from_user=call.from_user, date=None, chat=call.message.chat, content_type="text", options={}, json_string="")
                msg.text = f"/start {param}" if param != "main" else "/start"
                common_file_delivery_handler(worker, msg, username)
            else:
                worker.answer_callback_query(call.id, "❌ You have not joined all required channels yet!", show_alert=True)

        logger.info(f"🚀 Worker Bot @{username} polling started successfully!")
        worker.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
    except Exception as e:
        logger.error(f"❌ Failed to run Worker Bot @{username}: {e}")

def initialize_all_workers():
    workers = list(col_workers.find({"is_active": True}))
    for w in workers:
        token = w["token"]
        username = w["username"]
        if token not in active_worker_threads:
            t = threading.Thread(target=start_worker_bot_instance, args=(token, username), daemon=True)
            t.start()
            active_worker_threads[token] = t

threading.Thread(target=initialize_all_workers, daemon=True).start()

# ================= USER /START & MASTER DISPATCHER =================
@master_bot.message_handler(commands=["start"])
def handle_master_start(message):
    remove_user_msg(message)
    common_file_delivery_handler(master_bot, message, get_master_username())

@master_bot.callback_query_handler(func=lambda c: c.data == "user_vip_info")
def handle_vip_info_cb(call):
    master_bot.answer_callback_query(call.id)
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

@master_bot.callback_query_handler(func=lambda c: c.data == "user_help")
def handle_help_cb(call):
    master_bot.answer_callback_query(call.id)
    help_text = (
        "📖 <b>How to Download:</b>\n\n"
        "1. Channel par kisi bhi episode post ke neeche Quality button choose karein.\n"
        "2. Bot turant direct download file bhejega.\n"
        "3. <b>File aate hi apne 'Saved Messages' me forward karein</b> (Free users ke liye file 30 min baad delete hogi)."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="back_start", style="danger"))
    clean_screen(call.message.chat.id, help_text, reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data == "back_start")
def back_to_start(call):
    master_bot.answer_callback_query(call.id)
    msg = types.Message(message_id=0, from_user=call.from_user, date=None, chat=call.message.chat, content_type="text", options={}, json_string="")
    msg.text = "/start"
    handle_master_start(msg)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("retry_"))
def handle_master_retry(call):
    master_bot.answer_callback_query(call.id)
    param = call.data.replace("retry_", "")
    passed, _ = check_fsub(master_bot, call.message.chat.id)
    if passed:
        msg = types.Message(message_id=0, from_user=call.from_user, date=None, chat=call.message.chat, content_type="text", options={}, json_string="")
        msg.text = f"/start {param}" if param != "main" else "/start"
        handle_master_start(msg)
    else:
        master_bot.answer_callback_query(call.id, "❌ You have not joined all required channels yet!", show_alert=True)

# ================= MASTER ADMIN DASHBOARD =================
@master_bot.message_handler(commands=["admin"])
def handle_admin_cmd(message):
    remove_user_msg(message)
    if not is_admin(message.chat.id):
        return
    show_admin_panel(message.chat.id)

@master_bot.callback_query_handler(func=lambda c: c.data == "admin_hub")
def cb_admin_hub(call):
    master_bot.answer_callback_query(call.id)
    if not is_admin(call.message.chat.id):
        return
    show_admin_panel(call.message.chat.id)

def show_admin_panel(chat_id):
    clear_session(chat_id)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        StyledInlineKeyboardButton(text="🔍 Smart Title Finder", callback_data="admin_search_series", style="primary"),
        StyledInlineKeyboardButton(text="🎬 Upload Episode", callback_data="admin_upload_ep", style="success"),
        StyledInlineKeyboardButton(text="🤖 Worker Bot Cluster", callback_data="admin_workers_hub", style="success"),
        StyledInlineKeyboardButton(text="📦 Batch Uploader", callback_data="admin_batch_upload", style="primary"),
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

# ================= SMART TITLE FINDER =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_search_series")
def admin_search_series_prompt(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(u, "🔍 <b>Enter Series Title to Search:</b>")
    master_bot.register_next_step_handler(msg, step_search_series)

def step_search_series(message):
    remove_user_msg(message)
    u = message.chat.id
    q = message.text.strip()
    series_list = list(col_series.find({"title": {"$regex": q, "$options": "i"}}))
    
    if not series_list:
        kb = types.InlineKeyboardMarkup()
        kb.add(StyledInlineKeyboardButton(text="🔍 Search Again", callback_data="admin_search_series", style="primary"))
        kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
        clean_screen(u, f"❌ No anime series matched: <code>{q}</code>", reply_markup=kb)
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for s in series_list:
        kb.add(StyledInlineKeyboardButton(text=f"🎬 {s['title']} (S{s.get('season', '01')})", callback_data=f"view_s_{s['_id']}", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
    clean_screen(u, f"🔍 <b>Search Results for:</b> <code>{q}</code>", reply_markup=kb)

# ================= SERIES HUB & MANAGE =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_series_hub")
def handle_series_hub_list(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    series_list = list(col_series.find().sort("title", 1))
    
    if not series_list:
        kb = types.InlineKeyboardMarkup()
        kb.add(StyledInlineKeyboardButton(text="➕ Add New Series", callback_data="admin_add_series", style="success"))
        kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
        clean_screen(u, "⚠️ <b>No Series Found in Database!</b>", reply_markup=kb)
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for s in series_list:
        kb.add(StyledInlineKeyboardButton(text=f"📺 {s['title']} (S{s.get('season', '01')})", callback_data=f"view_s_{s['_id']}", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger"))
    clean_screen(u, "📺 <b>Series Hub:</b> Select a series to view/manage:", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("view_s_"))
def view_series_details(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("view_s_", "")
    series = col_series.find_one({"_id": ObjectId(sid)})
    if not series:
        clean_screen(u, "❌ Series not found.")
        return

    ep_count = col_episodes.count_documents({"series_id": series["_id"]})
    styled_title = to_bold_serif(series['title'])
    
    caption = (
        f"✦ <b>{styled_title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"▶ <b>Status :</b> {series.get('status', 'ONGOING')}\n"
        f"▶ <b>Season :</b> {series.get('season', '01')}\n"
        f"▶ <b>Total Uploaded Episodes :</b> {ep_count}\n"
        f"▶ <b>Audio :</b> {series.get('audio', 'Japanese [Eng-Sub]')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        StyledInlineKeyboardButton(text="🎬 Upload Episode", callback_data=f"sel_ep_up_{sid}", style="success"),
        StyledInlineKeyboardButton(text="🗑️ Delete Series", callback_data=f"del_s_conf_{sid}", style="danger"),
        StyledInlineKeyboardButton(text="🔙 Series Hub", callback_data="admin_series_hub", style="primary"),
        StyledInlineKeyboardButton(text="🏠 Dashboard", callback_data="admin_hub", style="danger")
    )
    clean_screen(u, caption, reply_markup=kb, photo=series.get("poster"))

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("del_s_conf_"))
def delete_series_confirm(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("del_s_conf_", "")
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        StyledInlineKeyboardButton(text="⚠️ Yes, Delete", callback_data=f"del_s_exec_{sid}", style="danger"),
        StyledInlineKeyboardButton(text="❌ Cancel", callback_data=f"view_s_{sid}", style="primary")
    )
    clean_screen(u, "⚠️ <b>Are you sure you want to completely delete this series and all its episodes?</b>", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("del_s_exec_"))
def delete_series_action(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = ObjectId(call.data.replace("del_s_exec_", ""))
    col_series.delete_one({"_id": sid})
    col_episodes.delete_many({"series_id": sid})
    clean_screen(u, "✅ <b>Series Deleted Successfully!</b>")
    show_admin_panel(u)

# ================= WORKER BOT CLUSTER MANAGER =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_workers_hub")
def show_workers_hub_menu(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    workers = list(col_workers.find())
    
    text = (
        f"🤖 <b>Multi-Bot Random Cluster Manager:</b>\n\n"
        f"👑 <b>Master Bot:</b> <code>@{get_master_username()}</code>\n"
        f"⚡ <b>Active Workers in Pool:</b> <code>{len(workers)}</code>\n\n"
        f"<i>All active bots are selected randomly for every download button!</i>\n\n"
    )
    if workers:
        for idx, w in enumerate(workers, 1):
            text += f"{idx}. <b>@{w['username']}</b> (<code>{w['token'][:10]}...</code>)\n"
    else:
        text += "<i>No secondary worker bots added yet. Master handles all links.</i>\n"

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="➕ Add New Worker Bot", callback_data="add_worker_bot", style="success"),
        StyledInlineKeyboardButton(text="🗑️ Remove Worker Bot", callback_data="rem_worker_bot", style="danger"),
        StyledInlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_hub", style="danger")
    )
    clean_screen(u, text, reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data == "add_worker_bot")
def start_add_worker(call):
    master_bot.answer_callback_query(call.id)
    msg = clean_screen(
        call.message.chat.id,
        "🤖 <b>Add New Worker Bot:</b>\n\n"
        "Send the <b>BOT TOKEN</b> from @BotFather:\n"
        "Example: <code>123456789:ABCdefGhIJKlmNoPQRstuVWXyz</code>"
    )
    master_bot.register_next_step_handler(msg, step_save_worker_bot)

def step_save_worker_bot(message):
    remove_user_msg(message)
    u = message.chat.id
    token = message.text.strip()

    try:
        temp_bot = telebot.TeleBot(token)
        me = temp_bot.get_me()
        bot_username = me.username

        col_workers.update_one(
            {"token": token},
            {"$set": {"token": token, "username": bot_username, "is_active": True, "created_at": time.time()}},
            upsert=True
        )

        if token not in active_worker_threads:
            t = threading.Thread(target=start_worker_bot_instance, args=(token, bot_username), daemon=True)
            t.start()
            active_worker_threads[token] = t

        clean_screen(u, f"✅ <b>Worker Bot @{bot_username} Connected & Running Live!</b>")
    except Exception as e:
        clean_screen(u, f"❌ <b>Failed to Connect Bot Token!</b>\n\nError: <code>{e}</code>")

    show_admin_panel(u)

@master_bot.callback_query_handler(func=lambda c: c.data == "rem_worker_bot")
def remove_worker_menu(call):
    master_bot.answer_callback_query(call.id)
    workers = list(col_workers.find())
    kb = types.InlineKeyboardMarkup(row_width=1)
    for w in workers:
        kb.add(StyledInlineKeyboardButton(text=f"❌ @{w['username']}", callback_data=f"del_wrk_{w['_id']}", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_workers_hub", style="primary"))
    clean_screen(call.message.chat.id, "🗑️ <b>Select Worker Bot to Remove:</b>", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("del_wrk_"))
def perform_del_worker(call):
    master_bot.answer_callback_query(call.id)
    wid = ObjectId(call.data.replace("del_wrk_", ""))
    col_workers.delete_one({"_id": wid})
    show_workers_hub_menu(call)

# ================= MULTI-ADMIN TEAM =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_team_hub")
def show_admin_team_menu(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    if not is_owner(u):
        master_bot.answer_callback_query(call.id, "❌ Only the Bot Owner can manage Admins!", show_alert=True)
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

@master_bot.callback_query_handler(func=lambda c: c.data == "add_sub_admin")
def start_add_sub_admin(call):
    master_bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "👤 <b>Send User ID of the new admin:</b>")
    master_bot.register_next_step_handler(msg, step_save_sub_admin)

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

@master_bot.callback_query_handler(func=lambda c: c.data == "rem_sub_admin")
def remove_sub_admin_menu(call):
    master_bot.answer_callback_query(call.id)
    admins = list(col_admins.find())
    kb = types.InlineKeyboardMarkup(row_width=1)
    for adm in admins:
        kb.add(StyledInlineKeyboardButton(text=f"❌ Remove {adm['user_id']}", callback_data=f"del_adm_{adm['user_id']}", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_team_hub", style="primary"))
    clean_screen(call.message.chat.id, "🗑️ <b>Select Admin to Remove:</b>", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("del_adm_"))
def perform_del_adm(call):
    master_bot.answer_callback_query(call.id)
    aid = int(call.data.replace("del_adm_", ""))
    col_admins.delete_one({"user_id": aid})
    show_admin_team_menu(call)

# ================= VIP SUBSCRIPTION MANAGER =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_vip_hub")
def show_vip_menu(call):
    master_bot.answer_callback_query(call.id)
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

@master_bot.callback_query_handler(func=lambda c: c.data == "add_vip_user")
def start_add_vip(call):
    master_bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "👑 <b>Send User ID to Grant VIP:</b>")
    master_bot.register_next_step_handler(msg, step_vip_uid)

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

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("vip_dur_"))
def perform_grant_vip(call):
    master_bot.answer_callback_query(call.id)
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

@master_bot.callback_query_handler(func=lambda c: c.data == "rem_vip_user")
def remove_vip_menu(call):
    master_bot.answer_callback_query(call.id)
    vips = list(col_vip.find())
    kb = types.InlineKeyboardMarkup(row_width=1)
    for v in vips:
        kb.add(StyledInlineKeyboardButton(text=f"❌ Revoke {v['user_id']}", callback_data=f"del_vip_{v['user_id']}", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_vip_hub", style="primary"))
    clean_screen(call.message.chat.id, "🗑️ <b>Select VIP user to revoke:</b>", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("del_vip_"))
def perform_del_vip(call):
    master_bot.answer_callback_query(call.id)
    vid = int(call.data.replace("del_vip_", ""))
    col_vip.delete_one({"user_id": vid})
    show_vip_menu(call)

# ================= ANILIST & MANUAL ADD SERIES =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_add_series")
def start_add_series_options(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    clear_session(u)
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="🌐 Auto-Fetch via AniList", callback_data="add_s_anilist", style="success"),
        StyledInlineKeyboardButton(text="✍️ Manual Series Entry", callback_data="add_s_manual", style="primary"),
        StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger")
    )
    clean_screen(u, "🎬 <b>Add New Anime Series:</b>\n\nChoose method:", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data == "add_s_anilist")
def prompt_anilist_search(call):
    master_bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "🌐 <b>Enter Anime Title for Auto-Fetch:</b>\nExample: <code>Solo Leveling</code> or <code>Tomb Raider King</code>")
    master_bot.register_next_step_handler(msg, step_execute_anilist_fetch)

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
    
    clean_screen(u, f"✅ <b>Series Auto-Fetched & Added!</b>\n\n📌 <b>Title:</b> {anime_title}", photo=poster_url)
    show_admin_panel(u)

@master_bot.callback_query_handler(func=lambda c: c.data == "add_s_manual")
def start_manual_add_series(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    clear_session(u)
    msg = clean_screen(u, "🎬 <b>Enter Anime Title:</b>\nExample: <code>Tomb Raider King</code>")
    master_bot.register_next_step_handler(msg, step_series_title)

def step_series_title(message):
    remove_user_msg(message)
    u = message.chat.id
    title = message.text.strip()
    update_session(u, {"temp_series.title": title})
    msg = clean_screen(u, f"📌 <b>Series:</b> {title}\n\n<b>Enter Season Number:</b> (e.g. <code>01</code>)")
    master_bot.register_next_step_handler(msg, step_series_season)

def step_series_season(message):
    remove_user_msg(message)
    u = message.chat.id
    season = str(message.text.strip()).zfill(2)
    update_session(u, {"temp_series.season": season})
    msg = clean_screen(u, "🔊 <b>Enter Audio / Language:</b>\nExample: <code>Japanese [Eng-Sub]</code>")
    master_bot.register_next_step_handler(msg, step_series_audio)

def step_series_audio(message):
    remove_user_msg(message)
    u = message.chat.id
    audio = message.text.strip()
    update_session(u, {"temp_series.audio": audio})
    msg = clean_screen(u, "🖼️ <b>Send Poster Photo for this Series:</b>")
    master_bot.register_next_step_handler(msg, step_series_poster)

def step_series_poster(message):
    remove_user_msg(message)
    u = message.chat.id
    if not message.photo:
        clean_screen(u, "❌ <b>Please send a valid photo:</b>")
        return

    poster_id = message.photo[-1].file_id
    temp = get_session(u).get("temp_series", {})
    
    col_series.insert_one({
        "title": temp.get("title", "Unknown"),
        "season": temp.get("season", "01"),
        "status": "ONGOING",
        "audio": temp.get("audio", "Japanese [Eng-Sub]"),
        "poster": poster_id,
        "created_at": time.time()
    })
    
    clean_screen(u, f"✅ <b>Series Added!</b>\n📌 {temp.get('title')}")
    show_admin_panel(u)

# ================= EPISODE UPLOAD FLOW =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_upload_ep")
def handle_upload_ep_entry(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    series_list = list(col_series.find().sort("title", 1))
    if not series_list:
        clean_screen(u, "⚠️ No series found. Please add a series first.")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for s in series_list:
        kb.add(StyledInlineKeyboardButton(text=f"🎬 {s['title']} (S{s.get('season', '01')})", callback_data=f"sel_ep_up_{s['_id']}", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger"))
    clean_screen(u, "🎬 <b>Select Series to Upload Episode:</b>", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("sel_ep_up_"))
def start_episode_upload(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    series_id = call.data.replace("sel_ep_up_", "")
    series = col_series.find_one({"_id": ObjectId(series_id)})
    if not series:
        return
    
    clear_session(u)
    update_session(u, {"upload_ep.series_id": series_id, "upload_ep.files": {}})
    msg = clean_screen(u, f"🎬 <b>Series:</b> {series['title']}\n\n<b>Enter Episode Number:</b> (e.g. <code>01</code>, <code>07</code>)")
    master_bot.register_next_step_handler(msg, step_ep_num)

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
        kb.add(StyledInlineKeyboardButton(text="🚀 Publish to Cluster", callback_data="publish_episode", style="success"))
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="admin_hub", style="danger"))

    clean_screen(chat_id, f"🎬 <b>Series:</b> {series.get('title')}\n🔢 <b>Episode:</b> {ep_data.get('ep_num')}\n\nTap quality to upload video:", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("up_q_"))
def handle_quality_upload_prompt(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    quality = call.data.replace("up_q_", "")
    update_session(u, {"current_quality": quality})
    
    msg = clean_screen(u, f"📤 <b>Send Video/Document for [{quality}]:</b>")
    master_bot.register_next_step_handler(msg, step_receive_file)

def step_receive_file(message):
    remove_user_msg(message)
    u = message.chat.id
    fid, ftype, fname = extract_file(message)
    
    if not fid:
        msg = clean_screen(u, "❌ <b>Please send a valid Video or Document file:</b>")
        master_bot.register_next_step_handler(msg, step_receive_file)
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

    col_sessions.update_one({"user_id": u}, {"$set": {f"upload_ep.files.{quality}": file_key}})
    show_quality_upload_menu(u)

# ================= BATCH EPISODE UPLOADER =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_batch_upload")
def handle_batch_upload_entry(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    series_list = list(col_series.find().sort("title", 1))
    if not series_list:
        clean_screen(u, "⚠️ No series found.")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for s in series_list:
        kb.add(StyledInlineKeyboardButton(text=f"📦 {s['title']}", callback_data=f"sel_batch_{s['_id']}", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger"))
    clean_screen(u, "📦 <b>Batch Uploader:</b> Select Series:", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("sel_batch_"))
def start_batch_series_conf(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("sel_batch_", "")
    update_session(u, {"batch_data.series_id": sid})
    msg = clean_screen(u, "🔢 <b>Enter Starting Episode Number:</b> (e.g. <code>01</code>)")
    master_bot.register_next_step_handler(msg, step_batch_start_ep)

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

@master_bot.message_handler(func=lambda m: is_admin(m.chat.id) and get_session(m.chat.id).get("batch_mode") is True, content_types=['video', 'document'])
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

    update_session(u, {"batch_data.current_ep": cur_ep + 1, "batch_data.count": bdata.get("count", 0) + 1})

    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🛑 Finish Batch Upload", callback_data="finish_batch", style="success"))
    clean_screen(u, f"✅ <b>Episode {ep_str} Saved!</b> Send next video or finish.", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data == "finish_batch")
def finish_batch_cb(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    total = get_session(u).get("batch_data", {}).get("count", 0)
    clear_session(u)
    clean_screen(u, f"🎉 <b>Batch Complete!</b> Uploaded {total} episodes.")
    show_admin_panel(u)

# ================= BROADCAST WITH RANDOM LOAD DISTRIBUTION =================
@master_bot.callback_query_handler(func=lambda c: c.data == "publish_episode")
def publish_episode_broadcast(call):
    master_bot.answer_callback_query(call.id)
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

    def make_random_button_url(quality_key):
        if b_mode == "channel" and dl_ch_link:
            return dl_ch_link
        target_bot = get_random_worker()
        if quality_key in files:
            return f"https://t.me/{target_bot}?start={files[quality_key]}"
        return f"https://t.me/{target_bot}?start=ep_{ep_id}"

    # Random Distributed 2-Row Alignment
    kb = types.InlineKeyboardMarkup()
    row1 = [
        StyledInlineKeyboardButton(text="480p", url=make_random_button_url("480p"), style="primary"),
        StyledInlineKeyboardButton(text="720p", url=make_random_button_url("720p"), style="primary"),
        StyledInlineKeyboardButton(text="1080p", url=make_random_button_url("1080p"), style="primary")
    ]
    row2 = [
        StyledInlineKeyboardButton(text="HDRip", url=make_random_button_url("HDRip"), style="primary")
    ]
    kb.row(*row1)
    kb.row(*row2)

    if main_ch:
        try:
            master_bot.send_photo(chat_id=main_ch, photo=series.get("poster"), caption=caption, reply_markup=kb, parse_mode="HTML")
            clean_screen(u, "✅ <b>Episode Published & Distributed Randomly Across All Bots!</b>")
        except Exception as e:
            notify_admin_error("Broadcast Failed", e)
            clean_screen(u, f"⚠️ Broadcast Error: <code>{e}</code>")
    else:
        clean_screen(u, "⚠️ Saved in DB, but Main Channel is not set.")

    clear_session(u)
    show_admin_panel(u)

# ================= SETTINGS & TOGGLES =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_settings")
def show_settings_menu(call):
    master_bot.answer_callback_query(call.id)
    brand = get_setting("brand_name")
    main_ch = get_setting("main_channel_id")
    dl_ch = get_setting("download_channel_link")
    bot_un = get_master_username()
    prot = get_setting("protect_content") or "False"
    b_mode = get_setting("button_mode") or "bot"
    
    text = (
        f"⚙️ <b>Bot Configuration:</b>\n\n"
        f"🏷️ <b>Brand Tag:</b> <code>{brand}</code>\n"
        f"📢 <b>Main Channel:</b> {get_channel_title(main_ch)}\n"
        f"🔗 <b>Download Channel:</b> <code>{dl_ch or 'Not Set'}</code>\n"
        f"🔘 <b>Button Target:</b> <code>{'DIRECT CHANNEL' if b_mode == 'channel' else 'RANDOM MULTI-BOT'}</code>\n"
        f"🤖 <b>Master Username:</b> <code>@{bot_un}</code>\n"
        f"🛡️ <b>Anti-Forward:</b> <code>{prot}</code>"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text=f"🔘 Toggle Mode ({'CHANNEL' if b_mode == 'channel' else 'MULTI-BOT'})", callback_data="toggle_bmode", style="primary"),
        StyledInlineKeyboardButton(text="🔗 Set Download Channel Link", callback_data="edit_dl_ch", style="primary"),
        StyledInlineKeyboardButton(text=f"🛡️ Toggle Protect ({'ON' if prot == 'True' else 'OFF'})", callback_data="toggle_protect", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Brand Tag", callback_data="edit_brand_name", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Main Channel ID", callback_data="edit_main_ch", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Bot Username", callback_data="edit_bot_user", style="primary"),
        StyledInlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_hub", style="danger")
    )
    clean_screen(call.message.chat.id, text, reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data == "toggle_bmode")
def toggle_button_mode(call):
    master_bot.answer_callback_query(call.id)
    cur = get_setting("button_mode") or "bot"
    update_setting("button_mode", "channel" if cur == "bot" else "bot")
    show_settings_menu(call)

@master_bot.callback_query_handler(func=lambda c: c.data == "edit_dl_ch")
def start_edit_dl_ch(call):
    master_bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "🔗 <b>Send Channel Link for Buttons:</b>")
    master_bot.register_next_step_handler(msg, step_save_dl_ch)

def step_save_dl_ch(message):
    remove_user_msg(message)
    u = message.chat.id
    success, cid, title, safe_link, err = resolve_channel_input(message.text)
    if not success:
        clean_screen(u, f"{err}")
        return
    update_setting("download_channel_link", safe_link)
    clean_screen(u, f"✅ <b>Download Channel Configured:</b> <code>{safe_link}</code>")
    show_admin_panel(u)

@master_bot.callback_query_handler(func=lambda c: c.data == "toggle_protect")
def toggle_protect_cb(call):
    master_bot.answer_callback_query(call.id)
    cur = get_setting("protect_content") or "False"
    update_setting("protect_content", "False" if cur == "True" else "True")
    show_settings_menu(call)

@master_bot.callback_query_handler(func=lambda c: c.data == "edit_brand_name")
def start_edit_brand(call):
    master_bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "<b>Send New Brand Tag:</b>")
    master_bot.register_next_step_handler(msg, lambda m: [update_setting("brand_name", m.text.strip()), show_admin_panel(m.chat.id)])

@master_bot.callback_query_handler(func=lambda c: c.data == "edit_main_ch")
def start_edit_main_ch(call):
    master_bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "📢 <b>Send Main Channel Username or ID:</b>")
    master_bot.register_next_step_handler(msg, step_save_main_ch)

def step_save_main_ch(message):
    remove_user_msg(message)
    success, cid, title, safe_link, err = resolve_channel_input(message.text)
    if success:
        update_setting("main_channel_id", cid)
        clean_screen(message.chat.id, f"✅ Main Channel Set: {title}")
    show_admin_panel(message.chat.id)

@master_bot.callback_query_handler(func=lambda c: c.data == "edit_bot_user")
def start_edit_bot_user(call):
    master_bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "<b>Send Master Bot Username without @:</b>")
    master_bot.register_next_step_handler(msg, lambda m: [update_setting("bot_username", m.text.strip().replace("@", "")), show_admin_panel(m.chat.id)])

# ================= RICH BROADCAST TO USERS =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_broadcast")
def start_rich_broadcast_prompt(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(
        u,
        "📢 <b>Rich Media Broadcast:</b>\n\n"
        "Send any <b>Text, Photo, or Video</b> to broadcast.\n\n"
        "<i>Tip: Caption ke aakhri line me button add kar sakte hain:</i>\n"
        "<code>Button Text | https://t.me/yourlink</code>"
    )
    master_bot.register_next_step_handler(msg, perform_rich_broadcast)

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
        try:
            if message.photo:
                master_bot.send_photo(usr["user_id"], photo=message.photo[-1].file_id, caption=caption_text, reply_markup=btn_markup)
            elif message.video:
                master_bot.send_video(usr["user_id"], video=message.video.file_id, caption=caption_text, reply_markup=btn_markup)
            elif message.document:
                master_bot.send_document(usr["user_id"], document=message.document.file_id, caption=caption_text, reply_markup=btn_markup)
            else:
                master_bot.send_message(usr["user_id"], text=caption_text, reply_markup=btn_markup)
            success += 1
        except Exception:
            fail += 1

    clean_screen(u, f"📢 <b>Broadcast Finished!</b>\n\n✅ Success: {success}\n❌ Failed: {fail}")
    show_admin_panel(u)

# ================= FORCESUB HUB =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_fsub_hub")
def show_fsub_menu(call):
    master_bot.answer_callback_query(call.id)
    u = call.message.chat.id
    channels = list(col_fsub.find())
    text = "🛡️ <b>ForceSub Channels:</b>\n\n"
    if channels:
        for i, ch in enumerate(channels, 1):
            text += f"{i}. <b>{ch['title']}</b> (<code>{ch['channel_id']}</code>)\n"
    else:
        text += "<i>No ForceSub channel active.</i>\n"

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="➕ Add ForceSub Channel", callback_data="add_fsub_ch", style="success"),
        StyledInlineKeyboardButton(text="🗑️ Remove ForceSub Channel", callback_data="rem_fsub_ch", style="danger"),
        StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger")
    )
    clean_screen(u, text, reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data == "add_fsub_ch")
def start_add_fsub(call):
    master_bot.answer_callback_query(call.id)
    msg = clean_screen(call.message.chat.id, "📢 <b>Send ForceSub Channel Username or ID:</b>")
    master_bot.register_next_step_handler(msg, step_save_fsub)

def step_save_fsub(message):
    remove_user_msg(message)
    success, cid, title, safe_link, err = resolve_channel_input(message.text)
    if success:
        col_fsub.update_one({"channel_id": cid}, {"$set": {"channel_id": cid, "title": title, "invite_link": safe_link}}, upsert=True)
        clean_screen(message.chat.id, f"✅ ForceSub Added: <b>{title}</b>")
    show_admin_panel(message.chat.id)

@master_bot.callback_query_handler(func=lambda c: c.data == "rem_fsub_ch")
def remove_fsub_menu(call):
    master_bot.answer_callback_query(call.id)
    channels = list(col_fsub.find())
    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        kb.add(StyledInlineKeyboardButton(text=f"❌ {ch['title']}", callback_data=f"del_fsub_{ch['channel_id']}", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_fsub_hub", style="primary"))
    clean_screen(call.message.chat.id, "🗑️ <b>Select channel to remove:</b>", reply_markup=kb)

@master_bot.callback_query_handler(func=lambda c: c.data.startswith("del_fsub_"))
def perform_del_fsub(call):
    master_bot.answer_callback_query(call.id)
    cid = int(call.data.replace("del_fsub_", ""))
    col_fsub.delete_one({"channel_id": cid})
    show_fsub_menu(call)

# ================= LIVE STATS =================
@master_bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
def show_live_stats(call):
    master_bot.answer_callback_query(call.id)
    u_count = col_users.count_documents({})
    s_count = col_series.count_documents({})
    e_count = col_episodes.count_documents({})
    w_count = col_workers.count_documents({})
    v_count = col_vip.count_documents({})
    
    text = (
        f"📊 <b>Live Database Statistics:</b>\n\n"
        f"👥 <b>Total Users:</b> <code>{u_count}</code>\n"
        f"🤖 <b>Active Worker Bots:</b> <code>{w_count}</code>\n"
        f"👑 <b>VIP Members:</b> <code>{v_count}</code>\n"
        f"📺 <b>Total Series:</b> <code>{s_count}</code>\n"
        f"🎬 <b>Total Episodes:</b> <code>{e_count}</code>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="admin_hub", style="danger"))
    clean_screen(call.message.chat.id, text, reply_markup=kb)

# ================= BOT POLLING START =================
if __name__ == "__main__":
    logger.info(f"🤖 Starting Master Cluster Engine (@{DETECTED_MASTER_USERNAME})...")
    master_bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
