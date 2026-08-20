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

# ================= CUSTOM BUTTON CLASSES =================
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

# ================= MONGODB SETUP & INITIALIZATION =================
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["anime_master_db"]
    client.server_info()
    logger.info("✅ Successfully connected to MongoDB Atlas!")
except Exception as e:
    logger.critical(f"❌ FATAL: Could not connect to MongoDB: {e}")
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
        "main_channel_id": "-1001234567890",
        "bot_username": "ongoing_anime_by_zenobot"
    })

def get_setting(field):
    cfg = col_settings.find_one({"key": "config"}) or {}
    return cfg.get(field, "")

def update_setting(field, val):
    col_settings.update_one({"key": "config"}, {"$set": {field: str(val)}}, upsert=True)

user_cache = {}

# ================= MESSAGE CLEANUP & SCREEN REPLACEMENT =================
def clean_send(chat_id, text, reply_markup=None, parse_mode="HTML"):
    """Deletes the previous bot message in chat before sending a new one to keep the UI clean."""
    if chat_id in user_cache and "last_msg_id" in user_cache[chat_id]:
        try:
            bot.delete_message(chat_id, user_cache[chat_id]["last_msg_id"])
        except Exception:
            pass
            
    sent = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    if chat_id not in user_cache:
        user_cache[chat_id] = {}
    user_cache[chat_id]["last_msg_id"] = sent.message_id
    return sent

def clean_send_photo(chat_id, photo, caption, reply_markup=None):
    """Deletes previous screen and renders a photo screen."""
    if chat_id in user_cache and "last_msg_id" in user_cache[chat_id]:
        try:
            bot.delete_message(chat_id, user_cache[chat_id]["last_msg_id"])
        except Exception:
            pass
            
    try:
        sent = bot.send_photo(chat_id, photo=photo, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        sent = bot.send_message(chat_id, caption, reply_markup=reply_markup, parse_mode="HTML")
        
    if chat_id not in user_cache:
        user_cache[chat_id] = {}
    user_cache[chat_id]["last_msg_id"] = sent.message_id
    return sent

def remove_user_input(message):
    """Deletes user's incoming message to keep conversation clutter-free."""
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

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
            m = bot.get_chat_member(chat_id=ch["channel_id"], user_id=user_id)
            if m.status not in ["creator", "administrator", "member"]:
                unsubbed.append({"title": ch["title"], "link": ch["invite_link"]})
        except Exception:
            pass
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

# ================= USER /START & FILE RETRIEVAL =================
@bot.message_handler(commands=["start"])
def handle_start(message):
    u = message.chat.id
    remove_user_input(message)
    col_users.update_one({"user_id": u}, {"$set": {"user_id": u}}, upsert=True)
    
    text = message.text or ""
    parts = text.split(" ")
    start_param = parts[1] if len(parts) > 1 else ""

    passed, unsubbed = check_fsub(u)
    if not passed:
        clean_send(
            u,
            "⚠️ <b>Access Denied!</b>\n\nYou must join our official update channels to retrieve files:",
            reply_markup=get_fsub_keyboard(unsubbed, start_param)
        )
        return

    # Deep Link File Retrieval
    if start_param.startswith("file_"):
        file_doc = col_files.find_one({"file_key": start_param})
        if file_doc:
            warn = bot.send_message(
                chat_id=u,
                text=f"📁 <b>{file_doc['file_name']}</b>\n\n⏳ <i>This file will automatically delete in 30 minutes due to copyright protection. Please forward it to your Saved Messages immediately!</i>"
            )
            if file_doc["file_type"] == "video":
                sent = bot.send_video(chat_id=u, video=file_doc["file_id"], caption=f"✦ <b>{file_doc['file_name']}</b>")
            else:
                sent = bot.send_document(chat_id=u, document=file_doc["file_id"], caption=f"✦ <b>{file_doc['file_name']}</b>")

            delete_messages_later(u, [warn.message_id, sent.message_id], delay=1800)
        else:
            clean_send(u, "❌ <b>This link has expired or the file no longer exists in our database.</b>")
        return

    # Standard Main Menu
    brand = get_setting("brand_name")
    kb = types.InlineKeyboardMarkup()
    if is_admin(u):
        kb.add(StyledInlineKeyboardButton(text="⚙️ Admin Control Hub", callback_data="admin_hub", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="ℹ️ How to Download", callback_data="user_help", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="⛩️ Official Updates Channel", url="https://t.me/ongoing_anime_by_zeno", style="primary"))
    
    clean_send(
        u,
        f"👋 <b>Welcome to Ongoing Anime Delivery Hub!</b>\n\nReady to download the latest ongoing anime episodes at maximum speed.\n\n✦ <b>Powered by:</b> {brand}",
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda c: c.data == "user_help")
def handle_help_cb(call):
    help_text = (
        "📖 <b>How to Download:</b>\n\n"
        "1. Click <b>Download Now ↗</b> on the release post in our channel.\n"
        "2. Select your desired resolution (480p / 720p / 1080p / HDRip).\n"
        "3. The bot will deliver the high-speed direct file to your chat.\n\n"
        "⏳ <i>Note: Delivered files have a 30-minute self-destruct timer.</i>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="back_start", style="danger"))
    clean_send(call.message.chat.id, help_text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "back_start")
def back_to_start(call):
    msg = types.Message(message_id=0, from_user=call.from_user, date=None, chat=call.message.chat, content_type="text", options={}, json_string="")
    msg.text = "/start"
    handle_start(msg)

@bot.callback_query_handler(func=lambda c: c.data.startswith("retry_"))
def handle_retry(call):
    u = call.message.chat.id
    param = call.data.replace("retry_", "")
    passed, unsubbed = check_fsub(u)
    if passed:
        msg = types.Message(message_id=0, from_user=call.from_user, date=None, chat=call.message.chat, content_type="text", options={}, json_string="")
        msg.text = f"/start {param}" if param != "main" else "/start"
        handle_start(msg)
    else:
        bot.answer_callback_query(call.id, "❌ You have not joined all required channels yet!", show_alert=True)

# ================= ADMIN DASHBOARD & SETTINGS =================
@bot.message_handler(commands=["admin"])
def handle_admin_cmd(message):
    remove_user_input(message)
    if not is_admin(message.chat.id):
        return
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "admin_hub")
def cb_admin_hub(call):
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
        StyledInlineKeyboardButton(text="🛡️ Force-Sub Channels", callback_data="admin_fsub_hub", style="primary"),
        StyledInlineKeyboardButton(text="⚙️ Bot Settings", callback_data="admin_settings", style="primary"),
        StyledInlineKeyboardButton(text="📢 Broadcast Message", callback_data="admin_broadcast", style="primary"),
        StyledInlineKeyboardButton(text="📊 Live Statistics", callback_data="admin_stats", style="primary")
    )
    clean_send(chat_id, "⚙️ <b>Admin Master Control Hub</b>\n\nSelect an operation below:", reply_markup=kb)

# --- Dynamic Settings Editor ---
@bot.callback_query_handler(func=lambda c: c.data == "admin_settings")
def show_settings_menu(call):
    brand = get_setting("brand_name")
    main_ch = get_setting("main_channel_id")
    bot_un = get_setting("bot_username")
    
    text = (
        f"⚙️ <b>Bot Configuration Settings:</b>\n\n"
        f"🏷️ <b>Brand Tag:</b> <code>{brand}</code>\n"
        f"📢 <b>Main Announcement Channel:</b> <code>{main_ch}</code>\n"
        f"🤖 <b>Bot Username:</b> <code>@{bot_un}</code>"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="✏️ Edit Brand Tag", callback_data="edit_brand_name", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Main Channel ID", callback_data="edit_main_ch", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Bot Username", callback_data="edit_bot_user", style="primary"),
        StyledInlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_hub", style="danger")
    )
    clean_send(call.message.chat.id, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "edit_brand_name")
def start_edit_brand(call):
    u = call.message.chat.id
    msg = clean_send(u, "<b>Send New Brand Tag / Channel Link:</b>\nExample: <code>@ongoing_anime_by_zeno</code>")
    bot.register_next_step_handler(msg, step_save_brand)

def step_save_brand(message):
    remove_user_input(message)
    update_setting("brand_name", message.text.strip())
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "edit_main_ch")
def start_edit_main_ch(call):
    u = call.message.chat.id
    msg = clean_send(u, "<b>Send NEW Main Announcement Channel ID:</b>\nMust include <code>-100</code> prefix (e.g. <code>-1001234567890</code>)")
    bot.register_next_step_handler(msg, step_save_main_ch)

def step_save_main_ch(message):
    remove_user_input(message)
    update_setting("main_channel_id", message.text.strip())
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "edit_bot_user")
def start_edit_bot_user(call):
    u = call.message.chat.id
    msg = clean_send(u, "<b>Send Bot Username without @:</b>\nExample: <code>ongoing_anime_by_zenobot</code>")
    bot.register_next_step_handler(msg, step_save_bot_user)

def step_save_bot_user(message):
    remove_user_input(message)
    update_setting("bot_username", message.text.strip().replace("@", ""))
    show_admin_panel(message.chat.id)

# ================= ADD NEW SERIES WIZARD =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_add_series")
def start_add_series(call):
    u = call.message.chat.id
    user_cache[u] = {}
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Cancel", callback_data="admin_hub", style="danger"))
    msg = clean_send(u, "➕ <b>Add New Series (Step 1/5)</b>\n\nEnter the full Title of the Anime:", reply_markup=kb)
    bot.register_next_step_handler(msg, step_as_title)

def step_as_title(message):
    remove_user_input(message)
    u = message.chat.id
    if not message.text or message.text == "/cancel":
        show_admin_panel(u)
        return
    user_cache[u]["title"] = message.text.strip()
    msg = clean_send(u, f"➕ <b>{user_cache[u]['title']}</b> (Step 2/5)\n\nEnter Season Number:\nExample: <code>01</code> or <code>02</code>")
    bot.register_next_step_handler(msg, step_as_season)

def step_as_season(message):
    remove_user_input(message)
    u = message.chat.id
    user_cache[u]["season"] = (message.text or "01").strip().zfill(2)
    msg = clean_send(u, f"➕ <b>{user_cache[u]['title']}</b> (Step 3/5)\n\nEnter Total Episodes:\nExample: <code>12</code>, <code>24</code>, or <code>ONGOING</code>")
    bot.register_next_step_handler(msg, step_as_total)

def step_as_total(message):
    remove_user_input(message)
    u = message.chat.id
    user_cache[u]["total_episodes"] = (message.text or "ONGOING").strip().upper()
    msg = clean_send(u, f"➕ <b>{user_cache[u]['title']}</b> (Step 4/5)\n\nEnter Dedicated Private Series Channel ID:\nExample: <code>-1001987654321</code>")
    bot.register_next_step_handler(msg, step_as_channel)

def step_as_channel(message):
    remove_user_input(message)
    u = message.chat.id
    ch_id = (message.text or "").strip()
    try:
        user_cache[u]["channel_id"] = int(ch_id)
    except ValueError:
        user_cache[u]["channel_id"] = ch_id

    msg = clean_send(u, f"➕ <b>{user_cache[u]['title']}</b> (Step 5/5)\n\nSend Poster Banner image:")
    bot.register_next_step_handler(msg, step_as_banner)

def step_as_banner(message):
    remove_user_input(message)
    u = message.chat.id
    banner = message.photo[-1].file_id if message.photo else None
    if not banner:
        msg = clean_send(u, "⚠️ Please upload a valid image for the poster banner:")
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
    kb.add(StyledInlineKeyboardButton(text="🎬 Upload First Episode", callback_data=f"quick_ep_{str(inserted.inserted_id)}", style="success"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_hub", style="danger"))
    clean_send(u, f"✅ <b>Series '{new_series['title']}' created successfully!</b>", reply_markup=kb)

# ================= SMART TITLE FINDER & SEARCH =================
@bot.callback_query_handler(func=lambda c: c.data in ["admin_search_series", "admin_series_hub", "admin_upload_ep"])
def start_smart_search(call):
    u = call.message.chat.id
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_hub", style="danger"))
    msg = clean_send(
        u,
        "🔍 <b>Series Finder:</b>\n\nEnter anime title or search keywords:\n<i>Examples: ReZero, Solo Leveling, Bleach, Demon</i>",
        reply_markup=kb
    )
    bot.register_next_step_handler(msg, step_execute_search)

def step_execute_search(message):
    remove_user_input(message)
    u = message.chat.id
    if message.text == "/cancel" or not message.text:
        show_admin_panel(u)
        return

    query = message.text.strip()
    results = list(col_series.find({"title": {"$regex": query, "$options": "i"}}))

    if not results:
        kb = types.InlineKeyboardMarkup()
        kb.add(StyledInlineKeyboardButton(text="➕ Add New Series", callback_data="admin_add_series", style="success"))
        kb.add(StyledInlineKeyboardButton(text="🔄 Search Again", callback_data="admin_search_series", style="primary"))
        kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
        clean_send(u, f"❌ <b>No series found matching '{query}'.</b>", reply_markup=kb)
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
    clean_send(u, f"🔎 <b>Search Results for '{query}' ({len(results)} found):</b>\n\nSelect a series to manage:", reply_markup=kb)

# --- Series Action Hub ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("manage_s_"))
def show_series_action_hub(call):
    sid = call.data.replace("manage_s_", "")
    s = col_series.find_one({"_id": ObjectId(sid)})
    if not s:
        bot.answer_callback_query(call.id, "Series not found!", show_alert=True)
        return

    caption = (
        f"📺 <b>{s['title']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Season:</b> Season {s.get('season', '01')}\n"
        f"🔢 <b>Total Episodes:</b> {s.get('total_episodes', 'ONGOING')}\n"
        f"🔗 <b>Target Channel:</b> <code>{s['channel_id']}</code>\n"
        f"📊 <b>Status:</b> <b>{s.get('status', 'ONGOING')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <i>Select an action below:</i>"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        StyledInlineKeyboardButton(text="🎬 + Upload Episode", callback_data=f"quick_ep_{sid}", style="success"),
        StyledInlineKeyboardButton(text="🎯 Update Season", callback_data=f"edit_season_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Title", callback_data=f"edit_title_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="🖼️ Change Poster", callback_data=f"edit_banner_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="🗑️ Delete Series", callback_data=f"del_s_{sid}", style="danger"),
        StyledInlineKeyboardButton(text="🔙 Back to Search", callback_data="admin_search_series", style="danger")
    )
    clean_send_photo(call.message.chat.id, photo=s["banner"], caption=caption, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_s_"))
def handle_delete_series(call):
    sid = call.data.replace("del_s_", "")
    col_series.delete_one({"_id": ObjectId(sid)})
    col_episodes.delete_many({"series_id": sid})
    bot.answer_callback_query(call.id, "Series deleted successfully!", show_alert=True)
    show_admin_panel(call.message.chat.id)

# --- Series Metadata Editors ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_season_"))
def handle_edit_season(call):
    u = call.message.chat.id
    sid = call.data.replace("edit_season_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = clean_send(u, "🎯 <b>Send NEW Season Number & Total Episodes:</b>\n\nFormat: <code>Season | Total Episodes</code>\nExample: <code>02 | 24</code> or <code>03 | ONGOING</code>")
    bot.register_next_step_handler(msg, step_save_new_season)

def step_save_new_season(message):
    remove_user_input(message)
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

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_title_"))
def handle_edit_title(call):
    u = call.message.chat.id
    sid = call.data.replace("edit_title_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = clean_send(u, "✏️ <b>Enter NEW Series Title:</b>")
    bot.register_next_step_handler(msg, step_save_new_title)

def step_save_new_title(message):
    remove_user_input(message)
    u = message.chat.id
    if u not in user_cache or "edit_sid" not in user_cache[u]:
        return
    sid = user_cache[u]["edit_sid"]
    new_title = message.text.strip()

    col_series.update_one({"_id": ObjectId(sid)}, {"$set": {"title": new_title}})
    user_cache.pop(u, None)
    show_series_action_hub(types.CallbackQuery(id="", from_user=message.from_user, data=f"manage_s_{sid}", message=message, chat_instance="", json_string=""))

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_banner_"))
def handle_edit_banner(call):
    u = call.message.chat.id
    sid = call.data.replace("edit_banner_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = clean_send(u, "🖼️ <b>Upload NEW Poster Banner Image:</b>")
    bot.register_next_step_handler(msg, step_save_new_banner)

def step_save_new_banner(message):
    remove_user_input(message)
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
        msg = clean_send(u, "⚠️ Please upload a valid image banner:")
        bot.register_next_step_handler(msg, step_save_new_banner)

# ================= EPISODE UPLOAD WIZARD (STEP-BY-STEP) =================
@bot.callback_query_handler(func=lambda c: c.data.startswith("quick_ep_"))
def handle_quick_add_ep(call):
    u = call.message.chat.id
    sid = call.data.replace("quick_ep_", "")
    s = col_series.find_one({"_id": ObjectId(sid)})
    
    user_cache[u] = {"series": s, "files": {}, "last_msg_id": user_cache.get(u, {}).get("last_msg_id")}
    msg = clean_send(u, f"🎬 <b>Upload for:</b> {s['title']} (Season {s.get('season', '01')})\n\n<b>Enter Episode Number:</b> (e.g. <code>01</code>, <code>14</code>)")
    bot.register_next_step_handler(msg, step_get_ep_number)

def step_get_ep_number(message):
    remove_user_input(message)
    u = message.chat.id
    if u not in user_cache or "series" not in user_cache[u]:
        show_admin_panel(u)
        return

    ep_num = (message.text or "01").strip().zfill(2)
    user_cache[u]["ep_num"] = ep_num

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="🌐 Multi Audio [Multi-Lang]", callback_data="set_audio_multi", style="success"),
        StyledInlineKeyboardButton(text="🇬🇧 English Dub / Sub", callback_data="set_audio_eng", style="primary"),
        StyledInlineKeyboardButton(text="🇯🇵 Japanese [Eng-Sub]", callback_data="set_audio_jap", style="primary")
    )
    clean_send(u, f"🎧 <b>Select Audio Track for Episode {ep_num}:</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_audio_"))
def handle_audio_choice(call):
    u = call.message.chat.id
    if u not in user_cache:
        show_admin_panel(u)
        return

    mapping = {
        "set_audio_multi": "Multi Audio [Multi-Lang]",
        "set_audio_eng": "English Dub / Sub",
        "set_audio_jap": "Japanese [Eng-Sub]"
    }
    user_cache[u]["audio"] = mapping.get(call.data, "Japanese [Eng-Sub]")
    start_quality_upload_flow(u, "480p", "1/4")

def get_skip_keyboard(step_name):
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text=f"⏩ Skip {step_name}", callback_data=f"skip_q_{step_name}", style="danger"))
    return kb

def start_quality_upload_flow(chat_id, quality, step_label):
    kb = get_skip_keyboard(quality)
    msg = clean_send(
        chat_id,
        f"📂 <b>Step {step_label}: Send or Forward the {quality} File:</b>",
        reply_markup=kb
    )
    bot.register_next_step_handler(msg, process_quality_file, quality, step_label)

def process_quality_file(message, quality, step_label):
    remove_user_input(message)
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

    advance_to_next_step(u, quality)

@bot.callback_query_handler(func=lambda c: c.data.startswith("skip_q_"))
def handle_quality_skip(call):
    u = call.message.chat.id
    quality = call.data.replace("skip_q_", "")
    advance_to_next_step(u, quality)

def advance_to_next_step(chat_id, current_quality):
    steps = ["480p", "720p", "1080p", "HDRip"]
    labels = ["1/4", "2/4", "3/4", "4/4"]
    
    idx = steps.index(current_quality)
    if idx + 1 < len(steps):
        next_q = steps[idx + 1]
        next_lbl = labels[idx + 1]
        start_quality_upload_flow(chat_id, next_q, next_lbl)
    else:
        finalize_and_publish_episode(chat_id)

# ================= FINALIZE, STORE & BROADCAST EPISODE =================
def finalize_and_publish_episode(chat_id):
    data = user_cache.get(chat_id)
    if not data or not data.get("files"):
        clean_send(chat_id, "⚠️ <b>Upload Cancelled:</b> No files were provided across all quality steps.")
        user_cache.pop(chat_id, None)
        return

    series = data["series"]
    ep_num = data["ep_num"]
    audio = data["audio"]
    files = data["files"]
    bot_username = get_setting("bot_username")
    main_ch_id = get_setting("main_channel_id")
    target_ch_id = series.get("channel_id")

    # 1. Save uploaded file records to database with unique retrieval keys
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

    # 2. Construct Series Channel Post
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
    try:
        # Post to dedicated private series channel
        sent_post = bot.send_photo(chat_id=target_ch_id, photo=series['banner'], caption=series_caption, reply_markup=series_kb)
        if str(target_ch_id).startswith("-100"):
            clean_cid = str(target_ch_id).replace("-100", "")
            channel_post_link = f"https://t.me/c/{clean_cid}/{sent_post.message_id}"
    except Exception as e:
        logger.error(f"Series channel post failed: {e}")
        clean_send(chat_id, f"⚠️ <b>Warning:</b> Could not post to Series Channel: <code>{e}</code>\nEnsure the bot is an Admin with Post Messages rights.")

    # 3. Construct Main Updates Channel Broadcast
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

    try:
        if main_ch_id:
            bot.send_photo(chat_id=main_ch_id, photo=series['banner'], caption=main_caption, reply_markup=main_kb)
    except Exception as e:
        logger.error(f"Main announcement broadcast failed: {e}")

    # 4. Save episode entry to DB
    col_episodes.insert_one({
        "series_id": str(series["_id"]),
        "season": series.get("season", "01"),
        "episode_number": ep_num,
        "audio": audio,
        "created_at": time.time()
    })

    user_cache.pop(chat_id, None)
    
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🎬 Upload Another Episode", callback_data=f"quick_ep_{str(series['_id'])}", style="success"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
    clean_send(chat_id, f"✅ <b>Episode {ep_num} of '{series['title']}' has been published and broadcasted successfully!</b>", reply_markup=kb)

# ================= FORCE-SUB CHANNEL MANAGEMENT =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_fsub_hub")
def show_fsub_hub(call):
    channels = list(col_fsub.find())
    kb = types.InlineKeyboardMarkup()
    for ch in channels:
        kb.add(StyledInlineKeyboardButton(text=f"❌ Remove {ch['title']}", callback_data=f"rm_fsub_{str(ch['_id'])}", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="➕ Add Force-Sub Channel", callback_data="add_fsub_ch", style="success"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="primary"))
    
    clean_send(call.message.chat.id, f"🛡️ <b>Force-Sub Channel Management:</b>\n\nTotal Configured Channels: <b>{len(channels)}</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "add_fsub_ch")
def start_add_fsub(call):
    u = call.message.chat.id
    msg = clean_send(u, "🛡️ <b>Send Force-Sub Details:</b>\n\nFormat: <code>Channel_ID | Channel_Title | Invite_Link</code>\nExample: <code>-1001234567890 | Anime Updates | https://t.me/+AbCdEfGh</code>")
    bot.register_next_step_handler(msg, step_save_fsub)

def step_save_fsub(message):
    remove_user_input(message)
    u = message.chat.id
    parts = (message.text or "").split("|")
    if len(parts) >= 3:
        try:
            cid = int(parts[0].strip())
        except ValueError:
            cid = parts[0].strip()
        col_fsub.insert_one({
            "channel_id": cid,
            "title": parts[1].strip(),
            "invite_link": parts[2].strip()
        })
    show_fsub_hub(types.CallbackQuery(id="", from_user=message.from_user, data="admin_fsub_hub", message=message, chat_instance="", json_string=""))

@bot.callback_query_handler(func=lambda c: c.data.startswith("rm_fsub_"))
def remove_fsub(call):
    fid = call.data.replace("rm_fsub_", "")
    col_fsub.delete_one({"_id": ObjectId(fid)})
    show_fsub_hub(call)

# ================= BROADCAST & STATISTICS =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_broadcast")
def start_broadcast(call):
    u = call.message.chat.id
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Cancel", callback_data="admin_hub", style="danger"))
    msg = clean_send(u, "📢 <b>Send the message or photo you want to broadcast to all registered bot users:</b>", reply_markup=kb)
    bot.register_next_step_handler(msg, execute_broadcast)

def execute_broadcast(message):
    remove_user_input(message)
    u = message.chat.id
    if message.text == "/cancel":
        show_admin_panel(u)
        return

    users = list(col_users.find())
    clean_send(u, f"⏳ <b>Broadcasting to {len(users)} users...</b>")

    def _bc():
        success = 0
        failed = 0
        for doc in users:
            uid = doc.get("user_id")
            try:
                bot.copy_message(chat_id=uid, from_chat_id=u, message_id=message.message_id)
                success += 1
                time.sleep(0.05)
            except Exception:
                failed += 1
        clean_send(u, f"✅ <b>Broadcast Completed!</b>\n\n🟢 Successful: <b>{success}</b>\n🔴 Failed / Blocked: <b>{failed}</b>")

    threading.Thread(target=_bc, daemon=True).start()

@bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
def show_live_stats(call):
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
    clean_send(call.message.chat.id, stats_text, reply_markup=kb)

# ================= POLLING LAUNCHER =================
if __name__ == "__main__":
    logger.info("Bot is starting polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as err:
            logger.error(f"Polling crashed: {err}. Reconnecting in 5 seconds...")
            time.sleep(5)
