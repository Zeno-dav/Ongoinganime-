import os
import sys
import time
import uuid
import logging
import threading
import telebot
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
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "5659051138").strip()

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 5659051138

if not BOT_TOKEN or not MONGO_URI:
    logger.critical("❌ FATAL: Credentials missing in Environment Variables!")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

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

if not col_settings.find_one({"key": "config"}):
    col_settings.insert_one({
        "key": "config",
        "brand_name": "@ongoing_anime_by_zeno",
        "main_channel_id": "",
        "bot_username": "ongoing_anime_by_zenobot"
    })

def get_setting(field):
    cfg = col_settings.find_one({"key": "config"}) or {}
    return cfg.get(field, "")

def update_setting(field, val):
    col_settings.update_one({"key": "config"}, {"$set": {field: str(val)}}, upsert=True)

user_cache = {}

# ================= ADMIN DIRECT ERROR NOTIFIER =================
def notify_admin_error(context, error_obj):
    """Logs the issue and delivers an immediate notification to the Admin DM."""
    err_str = str(error_obj)
    logger.error(f"[SYSTEM ALERT] {context}: {err_str}")
    try:
        alert_text = (
            f"🚨 <b>System Error Alert!</b>\n\n"
            f"📌 <b>Context:</b> {context}\n"
            f"❌ <b>Error Details:</b> <code>{err_str}</code>\n\n"
            f"<i>Please verify bot admin rights and channel IDs.</i>"
        )
        bot.send_message(ADMIN_ID, alert_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to send error notification to admin DM: {e}")

# ================= CLEAN UI & MESSAGE HANDLERS =================
def clean_screen(chat_id, text, reply_markup=None):
    """Deletes previous screen and sends the next page cleanly."""
    try:
        bot.clear_step_handler_by_chat_id(chat_id=chat_id)
    except Exception:
        pass

    if chat_id in user_cache and "active_msg_id" in user_cache[chat_id]:
        try:
            bot.delete_message(chat_id, user_cache[chat_id]["active_msg_id"])
        except Exception:
            pass

    sent = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
    if chat_id not in user_cache:
        user_cache[chat_id] = {}
    user_cache[chat_id]["active_msg_id"] = sent.message_id
    return sent

def clean_screen_photo(chat_id, photo, caption, reply_markup=None):
    """Deletes previous screen and renders photo."""
    try:
        bot.clear_step_handler_by_chat_id(chat_id=chat_id)
    except Exception:
        pass

    if chat_id in user_cache and "active_msg_id" in user_cache[chat_id]:
        try:
            bot.delete_message(chat_id, user_cache[chat_id]["active_msg_id"])
        except Exception:
            pass

    try:
        sent = bot.send_photo(chat_id, photo=photo, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        sent = bot.send_message(chat_id, caption, reply_markup=reply_markup, parse_mode="HTML")

    if chat_id not in user_cache:
        user_cache[chat_id] = {}
    user_cache[chat_id]["active_msg_id"] = sent.message_id
    return sent

def remove_user_msg(message):
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

def parse_target_chat(chat_identifier):
    """Converts channel string ID or integer to valid telegram target."""
    chat_str = str(chat_identifier).strip()
    if chat_str.startswith("-100") or chat_str.startswith("-") or chat_str.isdigit():
        try:
            return int(chat_str)
        except ValueError:
            return chat_str
    return chat_str

def get_channel_title(chat_identifier):
    """Fetches human-readable channel title if accessible, otherwise falls back to ID."""
    if not chat_identifier:
        return "Not Configured ❌"
    try:
        chat = bot.get_chat(parse_target_chat(chat_identifier))
        return f"{chat.title} (<code>{chat.id}</code>)"
    except Exception:
        return f"<code>{chat_identifier}</code>"

# ================= HELPER & BACKGROUND TASKS =================
def is_admin(user_id):
    return user_id == ADMIN_ID

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
    if user_id == ADMIN_ID:
        return True, []
    channels = list(col_fsub.find())
    if not channels:
        return True, []
    
    unsubbed = []
    for ch in channels:
        try:
            m = bot.get_chat_member(chat_id=parse_target_chat(ch["channel_id"]), user_id=user_id)
            if m.status not in ["creator", "administrator", "member"]:
                unsubbed.append({"title": ch["title"], "link": ch["invite_link"]})
        except Exception as e:
            notify_admin_error(f"Force-Sub Verification Failed for Channel {ch.get('title')}", e)
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

# ================= AUTO ID EXTRACTOR =================
@bot.message_handler(func=lambda msg: is_admin(msg.chat.id) and msg.forward_from_chat is not None)
def handle_forwarded_channel_id(message):
    """Automatically extracts Channel ID when admin forwards a message from any channel."""
    ch_id = message.forward_from_chat.id
    ch_title = message.forward_from_chat.title
    ch_username = f"@{message.forward_from_chat.username}" if message.forward_from_chat.username else "Private Channel"
    
    clean_screen(
        message.chat.id,
        f"📢 <b>Forwarded Channel Detected:</b>\n\n"
        f"📌 <b>Title:</b> {ch_title}\n"
        f"🆔 <b>Channel ID:</b> <code>{ch_id}</code>\n"
        f"🔗 <b>Username:</b> {ch_username}\n\n"
        f"<i>Copy this ID and paste it in Bot Settings or Series Channel ID!</i>"
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

    # Deep Link File Delivery
    if start_param.startswith("file_"):
        file_doc = col_files.find_one({"file_key": start_param})
        if file_doc:
            warn = bot.send_message(
                chat_id=u,
                text=f"📁 <b>{file_doc['file_name']}</b>\n\n⏳ <i>This file will auto-delete in 30 minutes due to copyright policies. Forward it to your Saved Messages now!</i>"
            )
            if file_doc["file_type"] == "video":
                sent = bot.send_video(chat_id=u, video=file_doc["file_id"], caption=f"✦ <b>{file_doc['file_name']}</b>")
            else:
                sent = bot.send_document(chat_id=u, document=file_doc["file_id"], caption=f"✦ <b>{file_doc['file_name']}</b>")

            delete_messages_later(u, [warn.message_id, sent.message_id], delay=1800)
        else:
            clean_screen(u, "❌ <b>This download link is expired or does not exist.</b>")
        return

    # Standard User Interface
    brand = get_setting("brand_name")
    kb = types.InlineKeyboardMarkup()
    if is_admin(u):
        kb.add(StyledInlineKeyboardButton(text="⚙️ Admin Control Hub", callback_data="admin_hub", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="ℹ️ How to Download", callback_data="user_help", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="⛩️ Official Updates Channel", url="https://t.me/ongoing_anime_by_zeno", style="primary"))
    
    clean_screen(
        u,
        f"👋 <b>Welcome to Ongoing Anime Delivery Hub!</b>\n\nDownload the latest anime episodes with high speed.\n\n✦ <b>Powered by:</b> {brand}",
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda c: c.data == "user_help")
def handle_help_cb(call):
    bot.answer_callback_query(call.id)
    help_text = (
        "📖 <b>How to Download:</b>\n\n"
        "1. Open our updates channel and click <b>Download Now ↗</b> on any episode post.\n"
        "2. Choose your quality (480p / 720p / 1080p / HDRip).\n"
        "3. The bot will deliver the high-speed file to your chat.\n\n"
        "⏳ <i>Note: All sent files auto-delete after 30 minutes.</i>"
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

# ================= ADMIN CONTROL PANEL =================
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
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        StyledInlineKeyboardButton(text="🔍 Smart Title Finder", callback_data="admin_search_series", style="primary"),
        StyledInlineKeyboardButton(text="🎬 Upload Episode", callback_data="admin_upload_ep", style="success"),
        StyledInlineKeyboardButton(text="📺 Series Hub", callback_data="admin_series_hub", style="primary"),
        StyledInlineKeyboardButton(text="➕ Add New Series", callback_data="admin_add_series", style="success"),
        StyledInlineKeyboardButton(text="🛡️ Manage ForceSub", callback_data="admin_fsub_hub", style="primary"),
        StyledInlineKeyboardButton(text="⚙️ Bot Settings", callback_data="admin_settings", style="primary"),
        StyledInlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast", style="primary"),
        StyledInlineKeyboardButton(text="📊 Live Stats", callback_data="admin_stats", style="primary")
    )
    clean_screen(chat_id, "⚙️ <b>Admin Master Control Hub</b>\n\nSelect an operation below:", reply_markup=kb)

# --- Bot Settings ---
@bot.callback_query_handler(func=lambda c: c.data == "admin_settings")
def show_settings_menu(call):
    bot.answer_callback_query(call.id)
    brand = get_setting("brand_name")
    main_ch = get_setting("main_channel_id")
    bot_un = get_setting("bot_username")
    
    text = (
        f"⚙️ <b>Bot Configuration:</b>\n\n"
        f"🏷️ <b>Brand Tag:</b> <code>{brand}</code>\n"
        f"📢 <b>Main Announcement Channel:</b> {get_channel_title(main_ch)}\n"
        f"🤖 <b>Bot Username:</b> <code>@{bot_un}</code>"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="✏️ Edit Brand Tag", callback_data="edit_brand_name", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Main Channel ID", callback_data="edit_main_ch", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Bot Username", callback_data="edit_bot_user", style="primary"),
        StyledInlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_hub", style="danger")
    )
    clean_screen(call.message.chat.id, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "edit_brand_name")
def start_edit_brand(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(u, "<b>Send New Brand Tag / Channel Link:</b>\nExample: <code>@ongoing_anime_by_zeno</code>")
    bot.register_next_step_handler(msg, step_save_brand)

def step_save_brand(message):
    remove_user_msg(message)
    update_setting("brand_name", message.text.strip())
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "edit_main_ch")
def start_edit_main_ch(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(u, "<b>Send NEW Main Channel ID:</b>\nMust start with <code>-100</code> (e.g. <code>-100219047xxxx</code>)\n\n<i>Tip: Forward any message from the channel to get its ID automatically!</i>")
    bot.register_next_step_handler(msg, step_save_main_ch)

def step_save_main_ch(message):
    remove_user_msg(message)
    update_setting("main_channel_id", message.text.strip())
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "edit_bot_user")
def start_edit_bot_user(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(u, "<b>Send Bot Username without @:</b>\nExample: <code>ongoing_anime_by_zenobot</code>")
    bot.register_next_step_handler(msg, step_save_bot_user)

def step_save_bot_user(message):
    remove_user_msg(message)
    update_setting("bot_username", message.text.strip().replace("@", ""))
    show_admin_panel(message.chat.id)

# ================= DIRECT SERIES LIST & SEARCH =================
@bot.callback_query_handler(func=lambda c: c.data in ["admin_upload_ep", "admin_series_hub"])
def handle_direct_series_list(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    target_action = "upload" if call.data == "admin_upload_ep" else "manage"
    
    series_list = list(col_series.find().sort("title", 1))
    if not series_list:
        kb = types.InlineKeyboardMarkup()
        kb.add(StyledInlineKeyboardButton(text="➕ Add New Series", callback_data="admin_add_series", style="success"))
        kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
        clean_screen(u, "⚠️ <b>No Series Found in Database!</b>\n\nPlease add a series first.", reply_markup=kb)
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for s in series_list:
        btn_cb = f"start_upload_{str(s['_id'])}" if target_action == "upload" else f"manage_s_{str(s['_id'])}"
        kb.add(StyledInlineKeyboardButton(
            text=f"🎬 {s['title']} (S{s.get('season', '01')})",
            callback_data=btn_cb,
            style="primary"
        ))

    kb.add(
        StyledInlineKeyboardButton(text="🔍 Search by Keyword", callback_data="admin_search_series", style="primary"),
        StyledInlineKeyboardButton(text="🔙 Cancel", callback_data="admin_hub", style="danger")
    )
    
    title_text = "Select Anime Series To Upload:" if target_action == "upload" else "Select Anime Series To Manage:"
    clean_screen(u, f"<b>{title_text}</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "admin_search_series")
def start_smart_search(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
    msg = clean_screen(
        u,
        "🔍 <b>Series Finder:</b>\n\nEnter anime title or search keywords:\n<i>Examples: ReZero, Solo, Bleach, Demon</i>",
        reply_markup=kb
    )
    bot.register_next_step_handler(msg, step_execute_search)

def step_execute_search(message):
    remove_user_msg(message)
    u = message.chat.id
    if not message.text or message.text == "/cancel":
        show_admin_panel(u)
        return

    query = message.text.strip()
    results = list(col_series.find({"title": {"$regex": query, "$options": "i"}}))

    if not results:
        kb = types.InlineKeyboardMarkup()
        kb.add(StyledInlineKeyboardButton(text="➕ Add New Series", callback_data="admin_add_series", style="success"))
        kb.add(StyledInlineKeyboardButton(text="🔄 Search Again", callback_data="admin_search_series", style="primary"))
        kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
        clean_screen(u, f"❌ <b>No series found matching '{query}'.</b>", reply_markup=kb)
        return

    kb = types.InlineKeyboardMarkup()
    for s in results:
        status_dot = "🟢" if s.get("status") == "ONGOING" else "📦"
        kb.add(StyledInlineKeyboardButton(
            text=f"{status_dot} {s['title']} (S{s.get('season', '01')})",
            callback_data=f"manage_s_{str(s['_id'])}",
            style="primary"
        ))
    
    kb.add(StyledInlineKeyboardButton(text="🔍 Search Another", callback_data="admin_search_series", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
    clean_screen(u, f"🔎 <b>Search Results for '{query}' ({len(results)} found):</b>\n\nSelect a series to manage:", reply_markup=kb)

# ================= FULL SERIES & EPISODE EDITING SUITE =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("manage_s_"))
def show_series_action_hub(call):
    bot.answer_callback_query(call.id)
    sid = call.data.replace("manage_s_", "")
    s = col_series.find_one({"_id": ObjectId(sid)})
    if not s:
        clean_screen(call.message.chat.id, "❌ Series not found!")
        return

    caption = (
        f"📺 <b>{s['title']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Season:</b> Season {s.get('season', '01')}\n"
        f"🔢 <b>Total Episodes:</b> {s.get('total_episodes', 'ONGOING')}\n"
        f"🔗 <b>Target Channel:</b> {get_channel_title(s['channel_id'])}\n"
        f"📊 <b>Status:</b> <b>{s.get('status', 'ONGOING')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <i>Select an action below:</i>"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        StyledInlineKeyboardButton(text="🎬 + Upload Episode", callback_data=f"start_upload_{sid}", style="success"),
        StyledInlineKeyboardButton(text="📋 Episodes List", callback_data=f"list_eps_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Rename Title", callback_data=f"edit_title_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="🎯 Season / Total", callback_data=f"edit_season_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="📢 Edit Channel ID", callback_data=f"edit_chid_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="🖼️ Change Poster", callback_data=f"edit_banner_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="🗑️ Delete Series", callback_data=f"del_s_{sid}", style="danger"),
        StyledInlineKeyboardButton(text="🔙 Back to Series List", callback_data="admin_series_hub", style="danger")
    )
    clean_screen_photo(call.message.chat.id, photo=s["banner"], caption=caption, reply_markup=kb)

# --- Metadata Editors ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_title_"))
def handle_edit_title(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("edit_title_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = clean_screen(u, "✏️ <b>Enter NEW Series Title:</b>")
    bot.register_next_step_handler(msg, step_save_new_title)

def step_save_new_title(message):
    remove_user_msg(message)
    u = message.chat.id
    if u not in user_cache or "edit_sid" not in user_cache[u]:
        return
    sid = user_cache[u]["edit_sid"]
    new_title = message.text.strip()

    col_series.update_one({"_id": ObjectId(sid)}, {"$set": {"title": new_title}})
    user_cache.pop(u, None)
    show_series_action_hub(types.CallbackQuery(id="", from_user=message.from_user, data=f"manage_s_{sid}", message=message, chat_instance="", json_string=""))

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_season_"))
def handle_edit_season(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("edit_season_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = clean_screen(u, "🎯 <b>Send NEW Season Number & Total Episodes:</b>\n\nFormat: <code>Season | Total Episodes</code>\nExample: <code>02 | 24</code> or <code>03 | ONGOING</code>")
    bot.register_next_step_handler(msg, step_save_new_season)

def step_save_new_season(message):
    remove_user_msg(message)
    u = message.chat.id
    if u not in user_cache or "edit_sid" not in user_cache[u]:
        return
    sid = user_cache[u]["edit_sid"]
    
    parts = (message.text or "").split("|")
    new_season = parts[0].strip().zfill(2)
    new_total = parts[1].strip().upper() if len(parts) > 1 else "ONGOING"

    col_series.update_one(
        {"_id": ObjectId(sid)},
        {"$set": {"season": new_season, "total_episodes": new_total, "status": "ONGOING"}}
    )
    user_cache.pop(u, None)
    show_series_action_hub(types.CallbackQuery(id="", from_user=message.from_user, data=f"manage_s_{sid}", message=message, chat_instance="", json_string=""))

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_chid_"))
def handle_edit_chid(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("edit_chid_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = clean_screen(u, "📢 <b>Enter NEW Dedicated Channel ID:</b>\nMust start with <code>-100</code> (e.g. <code>-100219047xxxx</code>)\n\n<i>Tip: Forward any message from the channel to get its exact ID.</i>")
    bot.register_next_step_handler(msg, step_save_new_chid)

def step_save_new_chid(message):
    remove_user_msg(message)
    u = message.chat.id
    if u not in user_cache or "edit_sid" not in user_cache[u]:
        return
    sid = user_cache[u]["edit_sid"]
    ch_text = message.text.strip()

    col_series.update_one({"_id": ObjectId(sid)}, {"$set": {"channel_id": ch_text}})
    user_cache.pop(u, None)
    show_series_action_hub(types.CallbackQuery(id="", from_user=message.from_user, data=f"manage_s_{sid}", message=message, chat_instance="", json_string=""))

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_banner_"))
def handle_edit_banner(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("edit_banner_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = clean_screen(u, "🖼️ <b>Upload NEW Poster Banner Image:</b>")
    bot.register_next_step_handler(msg, step_save_new_banner)

def step_save_new_banner(message):
    remove_user_msg(message)
    u = message.chat.id
    if u not in user_cache or "edit_sid" not in user_cache[u]:
        return
    sid = user_cache[u]["edit_sid"]
    
    if message.photo:
        banner = message.photo[-1].file_id
        col_series.update_one({"_id": ObjectId(sid)}, {"$set": {"banner": banner}})
        user_cache.pop(u, None)
        show_series_action_hub(types.CallbackQuery(id="", from_user=message.from_user, data=f"manage_s_{sid}", message=message, chat_instance="", json_string=""))
    else:
        msg = clean_screen(u, "⚠️ Please upload a valid image:")
        bot.register_next_step_handler(msg, step_save_new_banner)

# --- Episode List & Deletion ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("list_eps_"))
def handle_list_episodes(call):
    bot.answer_callback_query(call.id)
    sid = call.data.replace("list_eps_", "")
    s = col_series.find_one({"_id": ObjectId(sid)})
    episodes = list(col_episodes.find({"series_id": sid}).sort("episode_number", 1))

    kb = types.InlineKeyboardMarkup()
    if episodes:
        for ep in episodes:
            kb.add(
                StyledInlineKeyboardButton(
                    text=f"🎬 Ep {ep.get('episode_number')} ({ep.get('audio', 'Default')})",
                    callback_data="ignore",
                    style="primary"
                ),
                StyledInlineKeyboardButton(
                    text="🗑️ Delete",
                    callback_data=f"del_ep_{str(ep['_id'])}_{sid}",
                    style="danger"
                )
            )
    else:
        kb.add(StyledInlineKeyboardButton(text="🎬 Upload First Episode", callback_data=f"start_upload_{sid}", style="success"))

    kb.add(StyledInlineKeyboardButton(text="🔙 Back to Series", callback_data=f"manage_s_{sid}", style="danger"))
    clean_screen(call.message.chat.id, f"📋 <b>Episodes List:</b> {s['title']} (Total: <b>{len(episodes)}</b>)", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_ep_"))
def handle_delete_episode(call):
    bot.answer_callback_query(call.id, "Episode deleted!")
    parts = call.data.replace("del_ep_", "").split("_")
    ep_id = parts[0]
    sid = parts[1]
    
    col_episodes.delete_one({"_id": ObjectId(ep_id)})
    handle_list_episodes(types.CallbackQuery(id="", from_user=call.from_user, data=f"list_eps_{sid}", message=call.message, chat_instance="", json_string=""))

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_s_"))
def handle_delete_series(call):
    bot.answer_callback_query(call.id, "Series deleted successfully!", show_alert=True)
    sid = call.data.replace("del_s_", "")
    col_series.delete_one({"_id": ObjectId(sid)})
    col_episodes.delete_many({"series_id": sid})
    show_admin_panel(call.message.chat.id)

# ================= EPISODE UPLOAD FLOW (WITH CHANNEL PREVIEW) =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("start_upload_"))
def handle_start_upload(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    sid = call.data.replace("start_upload_", "")
    s = col_series.find_one({"_id": ObjectId(sid)})
    
    user_cache[u] = {"series": s, "files": {}}
    main_ch = get_setting("main_channel_id")
    
    # Clearly displays destination channels before prompting for episode number
    destination_preview = (
        f"Selected: <b>{s['title']}</b> (Season {s.get('season', '01')})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Broadcast Channels Target:</b>\n"
        f"• <b>Series Channel:</b> {get_channel_title(s.get('channel_id'))}\n"
        f"• <b>Main Channel:</b> {get_channel_title(main_ch)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Send Episode Number: (e.g. 01, 07)</b>"
    )
    msg = clean_screen(u, destination_preview)
    bot.register_next_step_handler(msg, step_get_ep_number)

def step_get_ep_number(message):
    remove_user_msg(message)
    u = message.chat.id
    if u not in user_cache or "series" not in user_cache[u]:
        show_admin_panel(u)
        return

    ep_num = (message.text or "01").strip().zfill(2)
    user_cache[u]["ep_num"] = ep_num

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="🇯🇵 Japanese [Eng-Sub]", callback_data="set_audio_jap", style="primary"),
        StyledInlineKeyboardButton(text="🔊 Dual Audio [Hindi + Jap]", callback_data="set_audio_dual", style="success"),
        StyledInlineKeyboardButton(text="🌐 Multi Audio [Multi-Lang]", callback_data="set_audio_multi", style="success"),
        StyledInlineKeyboardButton(text="🇬🇧 English Dub / Sub", callback_data="set_audio_eng", style="primary")
    )
    clean_screen(u, "<b>Select Audio Format:</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_audio_"))
def handle_audio_choice(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    if u not in user_cache:
        show_admin_panel(u)
        return

    mapping = {
        "set_audio_jap": "Japanese [Eng-Sub]",
        "set_audio_dual": "Dual Audio [Hindi + Jap]",
        "set_audio_multi": "Multi Audio [Multi-Lang]",
        "set_audio_eng": "English [Sub/Dub]"
    }
    user_cache[u]["audio"] = mapping.get(call.data, "Japanese [Eng-Sub]")
    start_quality_upload_flow(u, "480p", "1/4")

def start_quality_upload_flow(chat_id, quality, step_label):
    bot.clear_step_handler_by_chat_id(chat_id=chat_id)
    
    audio = user_cache.get(chat_id, {}).get("audio", "Unknown")
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text=f"⏩ Skip {quality}", callback_data=f"skip_{quality}", style="danger"))
    
    text = f"Audio: <b>{audio}</b>\n\n📁 <b>Step {step_label}: Forward / Send {quality} File:</b>"
    msg = clean_screen(chat_id, text, reply_markup=kb)
    bot.register_next_step_handler(msg, process_quality_file, quality)

def process_quality_file(message, quality):
    remove_user_msg(message)
    u = message.chat.id
    if u not in user_cache:
        return

    file_id, file_type, file_name = extract_file(message)
    if file_id:
        user_cache[u]["files"][quality] = {
            "file_id": file_id,
            "file_type": file_type,
            "file_name": file_name
        }

    advance_next_quality(u, quality)

@bot.callback_query_handler(func=lambda c: c.data in ["skip_480p", "skip_720p", "skip_1080p", "skip_HDRip"])
def handle_explicit_skips(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id=u)
    quality = call.data.replace("skip_", "")
    advance_next_quality(u, quality)

def advance_next_quality(chat_id, current_quality):
    steps = ["480p", "720p", "1080p", "HDRip"]
    labels = ["1/4", "2/4", "3/4", "4/4"]
    
    idx = steps.index(current_quality)
    if idx + 1 < len(steps):
        next_q = steps[idx + 1]
        next_lbl = labels[idx + 1]
        start_quality_upload_flow(chat_id, next_q, next_lbl)
    else:
        finalize_and_publish_episode(chat_id)

# ================= FINALIZE, PUBLISH & ADMIN ERROR DISPATCH =================
def finalize_and_publish_episode(chat_id):
    bot.clear_step_handler_by_chat_id(chat_id=chat_id)
    data = user_cache.get(chat_id)
    if not data or not data.get("files"):
        clean_screen(chat_id, "⚠️ <b>Notice:</b> All qualities were skipped. At least 1 file is required to broadcast.")
        user_cache.pop(chat_id, None)
        return

    series = data["series"]
    ep_num = data["ep_num"]
    audio = data["audio"]
    files = data["files"]
    bot_username = get_setting("bot_username")
    main_ch_raw = get_setting("main_channel_id")
    target_ch_raw = series.get("channel_id")

    # 1. Save Files & Generate Deep-Links
    download_buttons = []
    for quality, finfo in files.items():
        unique_key = f"file_{uuid.uuid4().hex[:10]}"
        col_files.insert_one({
            "file_key": unique_key,
            "file_id": finfo["file_id"],
            "file_type": finfo["file_type"],
            "file_name": f"{series['title']} - S{series.get('season', '01')}E{ep_num} [{quality}]",
            "created_at": time.time()
        })
        deep_link = f"https://t.me/{bot_username}?start={unique_key}"
        download_buttons.append(StyledInlineKeyboardButton(text=f"📥 Download {quality}", url=deep_link, style="primary"))

    # 2. Post to Dedicated Series Channel
    series_caption = (
        f"🎬 <b>{series['title']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Season:</b> Season {series.get('season', '01')}\n"
        f"🔢 <b>Episode:</b> Episode {ep_num}\n"
        f"🔊 <b>Audio:</b> {audio}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✦ <b>Powered by:</b> {get_setting('brand_name')}"
    )

    series_kb = types.InlineKeyboardMarkup(row_width=2)
    for i in range(0, len(download_buttons), 2):
        series_kb.row(*download_buttons[i:i+2])

    channel_post_link = None
    errors_encountered = []

    try:
        target_chat = parse_target_chat(target_ch_raw)
        sent_post = bot.send_photo(chat_id=target_chat, photo=series['banner'], caption=series_caption, reply_markup=series_kb)
        if str(target_chat).startswith("-100"):
            clean_cid = str(target_chat).replace("-100", "")
            channel_post_link = f"https://t.me/c/{clean_cid}/{sent_post.message_id}"
    except Exception as e:
        notify_admin_error(f"Failed Posting to Series Channel ({target_ch_raw})", e)
        errors_encountered.append(f"• <b>Series Channel:</b> <code>{e}</code>")

    # 3. Broadcast to Main Updates Channel
    main_caption = (
        f"🔥 <b>NEW EPISODE RELEASED!</b>\n\n"
        f"📺 <b>{series['title']}</b>\n"
        f"🎯 <b>Season {series.get('season', '01')} | Episode {ep_num}</b>\n"
        f"🔊 <b>Audio:</b> {audio}\n\n"
        f"✦ <i>High speed direct download links are now live below!</i>"
    )

    main_kb = types.InlineKeyboardMarkup()
    if channel_post_link:
        main_kb.add(StyledInlineKeyboardButton(text="🚀 Download Now ↗", url=channel_post_link, style="success"))
    else:
        for btn in download_buttons:
            main_kb.add(btn)

    if main_ch_raw:
        try:
            main_chat = parse_target_chat(main_ch_raw)
            bot.send_photo(chat_id=main_chat, photo=series['banner'], caption=main_caption, reply_markup=main_kb)
        except Exception as e:
            notify_admin_error(f"Failed Broadcasting to Main Updates Channel ({main_ch_raw})", e)
            errors_encountered.append(f"• <b>Main Updates Channel:</b> <code>{e}</code>")
    else:
        err_text = "Main Channel ID is not configured in Bot Settings."
        notify_admin_error("Main Channel Broadcast Skipped", err_text)
        errors_encountered.append(f"• <b>Main Updates Channel:</b> {err_text}")

    # 4. Record Episode in DB
    col_episodes.insert_one({
        "series_id": str(series["_id"]),
        "season": series.get("season", "01"),
        "episode_number": ep_num,
        "audio": audio,
        "created_at": time.time()
    })

    user_cache.pop(chat_id, None)
    
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🎬 Upload Another Episode", callback_data="admin_upload_ep", style="success"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
    
    status_report = (
        f"✅ <b>Episode {ep_num} Saved & Processed!</b>\n\n"
        f"📢 <b>Broadcast Target Overview:</b>\n"
        f"• <b>Series Channel:</b> {get_channel_title(target_ch_raw)}\n"
        f"• <b>Main Channel:</b> {get_channel_title(main_ch_raw)}\n"
    )
    
    if errors_encountered:
        status_report += "\n⚠️ <b>Broadcast Warnings:</b>\n" + "\n".join(errors_encountered)
    else:
        status_report += "\n🚀 <b>Successfully published to all targeted channels!</b>"

    clean_screen(chat_id, status_report, reply_markup=kb)

# ================= ADD NEW SERIES WIZARD =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_add_series")
def start_add_series(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    user_cache[u] = {}
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Cancel", callback_data="admin_hub", style="danger"))
    msg = clean_screen(u, "➕ <b>Add New Series (Step 1/5)</b>\n\nEnter Series Title:", reply_markup=kb)
    bot.register_next_step_handler(msg, step_as_title)

def step_as_title(message):
    remove_user_msg(message)
    u = message.chat.id
    if not message.text or message.text == "/cancel":
        show_admin_panel(u)
        return
    user_cache[u]["title"] = message.text.strip()
    msg = clean_screen(u, f"➕ <b>{user_cache[u]['title']}</b> (Step 2/5)\n\nEnter Season Number (e.g. <code>01</code>, <code>02</code>):")
    bot.register_next_step_handler(msg, step_as_season)

def step_as_season(message):
    remove_user_msg(message)
    u = message.chat.id
    user_cache[u]["season"] = (message.text or "01").strip().zfill(2)
    msg = clean_screen(u, f"➕ <b>{user_cache[u]['title']}</b> (Step 3/5)\n\nEnter Total Episodes (e.g. <code>12</code>, <code>24</code>, or <code>ONGOING</code>):")
    bot.register_next_step_handler(msg, step_as_total)

def step_as_total(message):
    remove_user_msg(message)
    u = message.chat.id
    user_cache[u]["total_episodes"] = (message.text or "ONGOING").strip().upper()
    msg = clean_screen(u, f"➕ <b>{user_cache[u]['title']}</b> (Step 4/5)\n\nEnter Dedicated Series Channel ID:\nMust start with <code>-100</code> (e.g. <code>-100219047xxxx</code>)\n\n<i>Tip: Forward any message from that channel to get the exact ID automatically!</i>")
    bot.register_next_step_handler(msg, step_as_channel)

def step_as_channel(message):
    remove_user_msg(message)
    u = message.chat.id
    user_cache[u]["channel_id"] = (message.text or "").strip()
    msg = clean_screen(u, f"➕ <b>{user_cache[u]['title']}</b> (Step 5/5)\n\nSend Poster Banner Image:")
    bot.register_next_step_handler(msg, step_as_banner)

def step_as_banner(message):
    remove_user_msg(message)
    u = message.chat.id
    banner = message.photo[-1].file_id if message.photo else None
    if not banner:
        msg = clean_screen(u, "⚠️ Please upload a valid image banner:")
        bot.register_next_step_handler(msg, step_as_banner)
        return

    data = user_cache.get(u, {})
    new_series = {
        "title": data["title"],
        "season": data["season"],
        "total_episodes": data["total_episodes"],
        "channel_id": data["channel_id"],
        "banner": banner,
        "status": "ONGOING",
        "created_at": time.time()
    }
    inserted = col_series.insert_one(new_series)
    user_cache.pop(u, None)
    
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🎬 Upload First Episode", callback_data=f"start_upload_{str(inserted.inserted_id)}", style="success"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
    clean_screen(u, f"✅ <b>Series '{new_series['title']}' created successfully!</b>", reply_markup=kb)

# ================= FORCE-SUB & BROADCAST =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_fsub_hub")
def show_fsub_hub(call):
    bot.answer_callback_query(call.id)
    channels = list(col_fsub.find())
    kb = types.InlineKeyboardMarkup()
    for ch in channels:
        kb.add(StyledInlineKeyboardButton(text=f"❌ Remove {ch['title']}", callback_data=f"rm_fsub_{str(ch['_id'])}", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="➕ Add Force-Sub Channel", callback_data="add_fsub_ch", style="success"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="primary"))
    
    clean_screen(call.message.chat.id, f"🛡️ <b>Force-Sub Channel Management:</b>\n\nTotal Configured Channels: <b>{len(channels)}</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "add_fsub_ch")
def start_add_fsub(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    msg = clean_screen(u, "🛡️ <b>Send Force-Sub Details:</b>\n\nFormat: <code>Channel_ID | Channel_Title | Invite_Link</code>\nExample: <code>-1001234567890 | Anime Updates | https://t.me/+AbCdEfGh</code>")
    bot.register_next_step_handler(msg, step_save_fsub)

def step_save_fsub(message):
    remove_user_msg(message)
    u = message.chat.id
    parts = (message.text or "").split("|")
    if len(parts) >= 3:
        col_fsub.insert_one({
            "channel_id": parts[0].strip(),
            "title": parts[1].strip(),
            "invite_link": parts[2].strip()
        })
    show_fsub_hub(types.CallbackQuery(id="", from_user=message.from_user, data="admin_fsub_hub", message=message, chat_instance="", json_string=""))

@bot.callback_query_handler(func=lambda c: c.data.startswith("rm_fsub_"))
def remove_fsub(call):
    bot.answer_callback_query(call.id)
    fid = call.data.replace("rm_fsub_", "")
    col_fsub.delete_one({"_id": ObjectId(fid)})
    show_fsub_hub(call)

@bot.callback_query_handler(func=lambda c: c.data == "admin_broadcast")
def start_broadcast(call):
    bot.answer_callback_query(call.id)
    u = call.message.chat.id
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Cancel", callback_data="admin_hub", style="danger"))
    msg = clean_screen(u, "📢 <b>Send the message or media you want to broadcast to all registered bot users:</b>", reply_markup=kb)
    bot.register_next_step_handler(msg, execute_broadcast)

def execute_broadcast(message):
    remove_user_msg(message)
    u = message.chat.id
    if message.text == "/cancel":
        show_admin_panel(u)
        return

    users = list(col_users.find())
    clean_screen(u, f"⏳ <b>Broadcasting to {len(users)} users...</b>")

    def _bc():
        success = 0
        failed = 0
        for doc in users:
            uid = doc.get("user_id")
            try:
                bot.copy_message(chat_id=uid, from_chat_id=u, message_id=message.message_id)
                success += 1
                time.sleep(0.05)
            except Exception as e:
                failed += 1
        clean_screen(u, f"✅ <b>Broadcast Completed!</b>\n\n🟢 Successful: <b>{success}</b>\n🔴 Failed / Blocked: <b>{failed}</b>")

    threading.Thread(target=_bc, daemon=True).start()

@bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
def show_live_stats(call):
    bot.answer_callback_query(call.id)
    total_users = col_users.count_documents({})
    total_series = col_series.count_documents({})
    total_episodes = col_episodes.count_documents({})
    total_files = col_files.count_documents({})

    stats_text = (
        "📊 <b>Live System Statistics:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Total Bot Users:</b> <code>{total_users}</code>\n"
        f"📺 <b>Registered Series:</b> <code>{total_series}</code>\n"
        f"🎬 <b>Total Episodes:</b> <code>{total_episodes}</code>\n"
        f"📁 <b>Active File Keys:</b> <code>{total_files}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
    clean_screen(call.message.chat.id, stats_text, reply_markup=kb)

# ================= POLLING LAUNCHER =================
if __name__ == "__main__":
    logger.info("Bot is starting polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as err:
            notify_admin_error("Bot Polling Crashed", err)
            time.sleep(5)
