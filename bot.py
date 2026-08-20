import os
import sys
import time
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
        self.style = style  # "primary", "success", "danger"

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

if not BOT_TOKEN:
    logger.critical("❌ FATAL: BOT_TOKEN is missing in Environment Variables!")
    sys.exit(1)

if not MONGO_URI:
    logger.critical("❌ FATAL: MONGO_URI is missing in Environment Variables!")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ================= MONGODB SETUP & INITIALIZATION =================
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["anime_master_db"]
    client.server_info()  # Force test connection
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
        return message.video.file_id, "video"
    if message.document:
        return message.document.file_id, "document"
    return None, None

# ================= USER /START & FILE RETRIEVAL =================
@bot.message_handler(commands=["start"])
def handle_start(message):
    u = message.chat.id
    col_users.update_one({"user_id": u}, {"$set": {"user_id": u}}, upsert=True)
    
    text = message.text or ""
    parts = text.split(" ")
    start_param = parts[1] if len(parts) > 1 else ""

    passed, unsubbed = check_fsub(u)
    if not passed:
        bot.send_message(
            chat_id=u,
            text="⚠️ <b>Access Denied!</b>\n\nEpisodes download karne ke liye official channels join karna zaroori hai:",
            reply_markup=get_fsub_keyboard(unsubbed, start_param)
        )
        return

    # Deep Link Deliver
    if start_param.startswith("file_"):
        file_doc = col_files.find_one({"file_key": start_param})
        if file_doc:
            warn = bot.send_message(
                chat_id=u,
                text=f"📁 <b>{file_doc['file_name']}</b>\n\n⏳ <i>Copyright protection ke tehat yeh file 30 minute baad auto-delete ho jayegi. Turant Saved Messages me forward kar lein!</i>"
            )
            if file_doc["file_type"] == "video":
                sent = bot.send_video(chat_id=u, video=file_doc["file_id"], caption=f"✦ <b>{file_doc['file_name']}</b>")
            else:
                sent = bot.send_document(chat_id=u, document=file_doc["file_id"], caption=f"✦ <b>{file_doc['file_name']}</b>")

            delete_messages_later(u, [warn.message_id, sent.message_id], delay=1800)
        else:
            bot.send_message(chat_id=u, text="❌ <b>Link expire ho chuka hai ya database me file exist nahi karti!</b>")
        return

    # Standard User Interface
    brand = get_setting("brand_name")
    kb = types.InlineKeyboardMarkup()
    if is_admin(u):
        kb.add(StyledInlineKeyboardButton(text="⚙️ Admin Control Hub", callback_data="admin_hub", style="danger"))
    kb.add(StyledInlineKeyboardButton(text="ℹ️ How to Download", callback_data="user_help", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="⛩️ Updates Channel", url="https://t.me/ongoing_anime_by_zeno", style="primary"))
    
    bot.send_message(
        chat_id=u,
        text=f"👋 <b>Welcome to Ongoing Anime Delivery Hub!</b>\n\nLatest anime episodes high speed par download karne ke liye ready hain.\n\n✦ <b>Powered by:</b> {brand}",
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda c: c.data == "user_help")
def handle_help_cb(call):
    help_text = (
        "📖 <b>How to Download:</b>\n\n"
        "1. Updates Channel par episode post par <b>Download Now ↗</b> click karein.\n"
        "2. Anime ke Private Series Channel me apni quality (480p / 720p / 1080p / HDRip) select karein.\n"
        "3. Bot aapko turant direct file forward kar dega.\n\n"
        "⏳ <i>Note: Sabhi files 30-minute self-destruct timer par set hain.</i>"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Back", callback_data="back_start", style="danger"))
    bot.send_message(chat_id=call.message.chat.id, text=help_text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "back_start")
def back_to_start(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    msg = types.Message(message_id=0, from_user=call.from_user, date=None, chat=call.message.chat, content_type="text", options={}, json_string="")
    msg.text = "/start"
    handle_start(msg)

@bot.callback_query_handler(func=lambda c: c.data.startswith("retry_"))
def handle_retry(call):
    u = call.message.chat.id
    param = call.data.replace("retry_", "")
    passed, unsubbed = check_fsub(u)
    if passed:
        try:
            bot.delete_message(u, call.message.message_id)
        except Exception:
            pass
        msg = types.Message(message_id=0, from_user=call.from_user, date=None, chat=call.message.chat, content_type="text", options={}, json_string="")
        msg.text = f"/start {param}" if param != "main" else "/start"
        handle_start(msg)
    else:
        bot.answer_callback_query(call.id, "❌ Aapne abhi tak saare required channels join nahi kiye!", show_alert=True)

# ================= ADMIN DASHBOARD & SETTINGS =================
@bot.message_handler(commands=["admin"])
def handle_admin_cmd(message):
    if not is_admin(message.chat.id):
        return
    show_admin_panel(message.chat.id)

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
    bot.send_message(chat_id=chat_id, text="⚙️ <b>Admin Master Control Hub</b>\n\nSelect operation below:", reply_markup=kb)

# --- Dynamic Settings Editor ---
@bot.callback_query_handler(func=lambda c: c.data == "admin_settings")
def show_settings_menu(call):
    brand = get_setting("brand_name")
    main_ch = get_setting("main_channel_id")
    bot_un = get_setting("bot_username")
    
    text = (
        f"⚙️ <b>Bot Configuration Settings:</b>\n\n"
        f"🏷️ <b>Brand Tag:</b> <code>{brand}</code>\n"
        f"📢 <b>Main Channel ID:</b> <code>{main_ch}</code>\n"
        f"🤖 <b>Bot Username:</b> <code>@{bot_un}</code>"
    )
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="✏️ Change Brand Tag", callback_data="edit_brand_name", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Change Main Channel ID", callback_data="edit_main_ch", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Change Bot Username", callback_data="edit_bot_user", style="primary"),
        StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger")
    )
    bot.send_message(chat_id=call.message.chat.id, text=text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "edit_brand_name")
def start_edit_brand(call):
    u = call.message.chat.id
    msg = bot.send_message(chat_id=u, text="<b>Send New Brand Tag / Channel Link:</b>\nExample: <code>@ongoing_anime_by_zeno</code>")
    bot.register_next_step_handler(msg, step_save_brand)

def step_save_brand(message):
    update_setting("brand_name", message.text.strip())
    bot.send_message(chat_id=message.chat.id, text="✅ <b>Brand Tag Updated!</b>")
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "edit_main_ch")
def start_edit_main_ch(call):
    u = call.message.chat.id
    msg = bot.send_message(chat_id=u, text="<b>Send NEW Main Announcement Channel ID:</b>\nExample: <code>-1001234567890</code>")
    bot.register_next_step_handler(msg, step_save_main_ch)

def step_save_main_ch(message):
    update_setting("main_channel_id", message.text.strip())
    bot.send_message(chat_id=message.chat.id, text="✅ <b>Main Channel ID Updated!</b>")
    show_admin_panel(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "edit_bot_user")
def start_edit_bot_user(call):
    u = call.message.chat.id
    msg = bot.send_message(chat_id=u, text="<b>Send Bot Username without @:</b>\nExample: <code>ongoing_anime_by_zenobot</code>")
    bot.register_next_step_handler(msg, step_save_bot_user)

def step_save_bot_user(message):
    update_setting("bot_username", message.text.strip().replace("@", ""))
    bot.send_message(chat_id=message.chat.id, text="✅ <b>Bot Username Updated!</b>")
    show_admin_panel(message.chat.id)

# ================= SMART TITLE FINDER & SEARCH =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_search_series")
def start_smart_search(call):
    u = call.message.chat.id
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
    msg = bot.send_message(
        chat_id=u,
        text="🔍 <b>Smart Title Finder:</b>\n\nAnime ka koi bhi keyword ya naam likh kar bhejein:\n<i>Example: ReZero, Solo, Slayer, King</i>",
        reply_markup=kb
    )
    bot.register_next_step_handler(msg, step_execute_search)

def step_execute_search(message):
    u = message.chat.id
    if message.text == "/cancel" or not message.text:
        show_admin_panel(u)
        return

    query = message.text.strip()
    results = list(col_series.find({"title": {"$regex": query, "$options": "i"}}))

    if not results:
        kb = types.InlineKeyboardMarkup()
        kb.add(StyledInlineKeyboardButton(text="🔄 Search Again", callback_data="admin_search_series", style="primary"))
        kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
        bot.send_message(chat_id=u, text=f"❌ <b>'{query}' se match karti koi series nahi mili!</b>", reply_markup=kb)
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

    bot.send_message(chat_id=u, text=f"🔎 <b>Search Results for '{query}' ({len(results)} found):</b>\n\nManage karne ke liye series select karein:", reply_markup=kb)

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
        f"🎯 <b>Current Season:</b> Season {s.get('season', '01')}\n"
        f"🔢 <b>Total Episodes:</b> {s.get('total_episodes', 'ONGOING')}\n"
        f"🔗 <b>Channel ID:</b> <code>{s['channel_id']}</code>\n"
        f"📊 <b>Status:</b> <b>{s.get('status', 'ONGOING')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <i>Select quick action below:</i>"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        StyledInlineKeyboardButton(text="🎬 + Add New Episode", callback_data=f"quick_ep_{sid}", style="success"),
        StyledInlineKeyboardButton(text="🎯 + Update Season", callback_data=f"edit_season_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="✏️ Edit Title", callback_data=f"edit_title_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="🖼️ Change Poster", callback_data=f"edit_banner_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="🔄 Migrate Channel", callback_data=f"mig_ch_{sid}", style="primary"),
        StyledInlineKeyboardButton(text="🔁 Repost All", callback_data=f"repost_all_{sid}", style="primary")
    )
    kb.add(StyledInlineKeyboardButton(text="🔙 Back to Search", callback_data="admin_search_series", style="danger"))

    try:
        bot.send_photo(chat_id=call.message.chat.id, photo=s["banner"], caption=caption, reply_markup=kb)
    except Exception:
        bot.send_message(chat_id=call.message.chat.id, text=caption, reply_markup=kb)

# --- Quick Action Handlers ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("quick_ep_"))
def handle_quick_add_ep(call):
    u = call.message.chat.id
    sid = call.data.replace("quick_ep_", "")
    s = col_series.find_one({"_id": ObjectId(sid)})
    
    user_cache[u] = {"series": s, "files": {}}
    msg = bot.send_message(chat_id=u, text=f"🎬 <b>Upload for:</b> {s['title']} (Season {s.get('season', '01')})\n\n<b>Send Episode Number:</b> (e.g. <code>14</code>, <code>15</code>)")
    bot.register_next_step_handler(msg, step_get_ep_number)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_season_"))
def handle_edit_season(call):
    u = call.message.chat.id
    sid = call.data.replace("edit_season_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = bot.send_message(chat_id=u, text="🎯 <b>Send NEW Season Number & Total Episodes:</b>\n\nFormat: <code>Season | Total Episodes</code>\nExample: <code>02 | 24</code> ya <code>03 | ONGOING</code>")
    bot.register_next_step_handler(msg, step_save_new_season)

def step_save_new_season(message):
    u = message.chat.id
    if u not in user_cache or "edit_sid" not in user_cache[u]:
        return
    sid = user_cache[u]["edit_sid"]
    
    parts = (message.text or "").split("|")
    new_season = parts[0].strip()
    new_total = parts[1].strip() if len(parts) > 1 else "ONGOING"

    col_series.update_one(
        {"_id": ObjectId(sid)},
        {"$set": {"season": new_season, "total_episodes": new_total, "status": "ONGOING"}}
    )
    bot.send_message(chat_id=u, text=f"✅ <b>Season Updated!</b>\nNew Season: <b>{new_season}</b> | Total Ep: <b>{new_total}</b>")
    del user_cache[u]
    show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_title_"))
def handle_edit_title(call):
    u = call.message.chat.id
    sid = call.data.replace("edit_title_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = bot.send_message(chat_id=u, text="✏️ <b>Send NEW Series Title:</b>")
    bot.register_next_step_handler(msg, step_save_new_title)

def step_save_new_title(message):
    u = message.chat.id
    if u not in user_cache or "edit_sid" not in user_cache[u]:
        return
    sid = user_cache[u]["edit_sid"]
    new_title = message.text.strip()

    col_series.update_one({"_id": ObjectId(sid)}, {"$set": {"title": new_title}})
    bot.send_message(chat_id=u, text=f"✅ <b>Title Updated to:</b> <code>{new_title}</code>")
    del user_cache[u]
    show_admin_panel(u)

@bot.callback_query_handler(func=lambda c: c.data.startswith("edit_banner_"))
def handle_edit_banner(call):
    u = call.message.chat.id
    sid = call.data.replace("edit_banner_", "")
    user_cache[u] = {"edit_sid": sid}
    
    msg = bot.send_message(chat_id=u, text="🖼️ <b>Send NEW Poster Banner (Direct Photo or Image URL):</b>")
    bot.register_next_step_handler(msg, step_save_new_banner)

def step_save_new_banner(message):
    u = message.chat.id
    if u not in user_cache or "edit_sid" not in user_cache[u]:
        return
    sid = user_cache[u]["edit_sid"]
    
    banner = message.photo[-1].file_id if message.photo else (message.text.strip() if message.text else None)
    if banner:
        col_series.update_one({"_id": ObjectId(sid)}, {"$set": {"banner": banner}})
        bot.send_message(chat_id=u, text="✅ <b>Poster Banner Updated!</b>")
        del user_cache[u]
        show_admin_panel(u)
    else:
        msg = bot.send_message(chat_id=u, text="❌ <b>Invalid image. Kripya photo send karein:</b>")
        bot.register_next_step_handler(msg, step_save_new_banner)

# ================= SERIES REGISTRATION WIZARD =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_add_series")
def start_series_wizard(call):
    u = call.message.chat.id
    user_cache[u] = {}
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="cancel_wizard", style="danger"))
    msg = bot.send_message(chat_id=u, text="<b>📺 Step 1/5: Send Anime / Series Title:</b>\n\nExample: <code>Solo Leveling</code>", reply_markup=kb)
    bot.register_next_step_handler(msg, step_save_title)

def step_save_title(message):
    u = message.chat.id
    if message.text == "/cancel" or u not in user_cache:
        return
    user_cache[u]["title"] = message.text.strip()
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="cancel_wizard", style="danger"))
    msg = bot.send_message(chat_id=u, text=f"✅ <b>Title:</b> {user_cache[u]['title']}\n\n<b>🔗 Step 2/5: Send Dedicated Channel Link or Numeric ID:</b>", reply_markup=kb)
    bot.register_next_step_handler(msg, step_save_channel)

def step_save_channel(message):
    u = message.chat.id
    if message.text == "/cancel" or u not in user_cache:
        return
    raw = message.text.strip()
    cid = f"-100{raw.split('t.me/c/')[1].split('/')[0]}" if "t.me/c/" in raw else raw
    user_cache[u]["channel_id"] = cid
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="cancel_wizard", style="danger"))
    msg = bot.send_message(chat_id=u, text=f"✅ <b>Channel Saved:</b> <code>{cid}</code>\n\n<b>🎯 Step 3/5: Season Number?</b> (e.g. <code>01</code>, <code>02</code>):", reply_markup=kb)
    bot.register_next_step_handler(msg, step_save_season)

def step_save_season(message):
    u = message.chat.id
    if message.text == "/cancel" or u not in user_cache:
        return
    user_cache[u]["season"] = message.text.strip()
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="cancel_wizard", style="danger"))
    msg = bot.send_message(chat_id=u, text=f"✅ <b>Season:</b> {user_cache[u]['season']}\n\n<b>🔢 Step 4/5: Total Episodes?</b> (e.g. <code>12</code>, <code>24</code>, <code>ONGOING</code>):", reply_markup=kb)
    bot.register_next_step_handler(msg, step_save_episodes)

def step_save_episodes(message):
    u = message.chat.id
    if message.text == "/cancel" or u not in user_cache:
        return
    user_cache[u]["total_episodes"] = message.text.strip()
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="cancel_wizard", style="danger"))
    msg = bot.send_message(chat_id=u, text="<b>🖼️ Step 5/5: Send Poster Banner (Direct Photo or URL):</b>", reply_markup=kb)
    bot.register_next_step_handler(msg, step_save_banner)

def step_save_banner(message):
    u = message.chat.id
    if message.text == "/cancel" or u not in user_cache:
        return
    banner = message.photo[-1].file_id if message.photo else (message.text.strip() if message.text else None)

    if banner:
        data = user_cache[u]
        col_series.insert_one({
            "title": data["title"],
            "channel_id": data["channel_id"],
            "season": data["season"],
            "total_episodes": data["total_episodes"],
            "banner": banner,
            "status": "ONGOING"
        })
        bot.send_message(chat_id=u, text=f"🎉 <b>Series Registered!</b>\n\n📺 <b>Title:</b> {data['title']}\n🔗 <b>Channel:</b> <code>{data['channel_id']}</code>")
        del user_cache[u]
        show_series_hub(u)
    else:
        msg = bot.send_message(chat_id=u, text="❌ <b>Image invalid! Send photo again:</b>")
        bot.register_next_step_handler(msg, step_save_banner)

# ================= SERIES HUB & REPOST =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_series_hub")
def handle_series_hub_cb(call):
    show_series_hub(call.message.chat.id)

def show_series_hub(chat_id):
    ongoing = list(col_series.find({"status": "ONGOING"}))
    completed = list(col_series.find({"status": "COMPLETED"}))

    kb = types.InlineKeyboardMarkup()
    for s in ongoing:
        sid = str(s["_id"])
        kb.row(
            StyledInlineKeyboardButton(text=f"🟢 {s['title']}", callback_data=f"view_series_{sid}", style="primary"),
            StyledInlineKeyboardButton(text="📦 Archive", callback_data=f"archive_series_{sid}", style="danger")
        )
    kb.add(StyledInlineKeyboardButton(text="➕ Register New Series", callback_data="admin_add_series", style="success"))
    kb.row(
        StyledInlineKeyboardButton(text=f"📁 Completed ({len(completed)})", callback_data="view_completed_series", style="primary"),
        StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger")
    )
    bot.send_message(chat_id=chat_id, text=f"<b>📺 Series Management Hub</b>\n\n🟢 <b>Ongoing:</b> <code>{len(ongoing)}</code>\n📦 <b>Completed:</b> <code>{len(completed)}</code>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("view_series_"))
def view_series_detail(call):
    sid = call.data.replace("view_series_", "")
    s = col_series.find_one({"_id": ObjectId(sid)})
    if s:
        caption = f"📺 <b>Title:</b> {s['title']}\n🔗 <b>Channel ID:</b> <code>{s['channel_id']}</code>\n🎯 <b>Season:</b> {s['season']}\n🔢 <b>Total Episodes:</b> {s['total_episodes']}\n📊 <b>Status:</b> <b>{s['status']}</b>"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            StyledInlineKeyboardButton(text="🔄 Change Channel / Migrate", callback_data=f"mig_ch_{sid}", style="primary"),
            StyledInlineKeyboardButton(text="🔁 Repost All Episodes to Channel", callback_data=f"repost_all_{sid}", style="primary"),
            StyledInlineKeyboardButton(text="🔙 Back to Series Hub", callback_data="admin_series_hub", style="danger")
        )
        try:
            bot.send_photo(chat_id=call.message.chat.id, photo=s["banner"], caption=caption, reply_markup=kb)
        except Exception:
            bot.send_message(chat_id=call.message.chat.id, text=caption, reply_markup=kb)

# --- Channel Migration ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("mig_ch_"))
def start_channel_migration(call):
    u = call.message.chat.id
    sid = call.data.replace("mig_ch_", "")
    user_cache[u] = {"mig_sid": sid}
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="admin_series_hub", style="danger"))
    msg = bot.send_message(chat_id=u, text="<b>Send NEW Dedicated Channel Link or ID:</b>", reply_markup=kb)
    bot.register_next_step_handler(msg, step_save_mig_channel)

def step_save_mig_channel(message):
    u = message.chat.id
    if u not in user_cache or "mig_sid" not in user_cache[u]:
        return
    sid = user_cache[u]["mig_sid"]
    raw = message.text.strip()
    new_cid = f"-100{raw.split('t.me/c/')[1].split('/')[0]}" if "t.me/c/" in raw else raw

    col_series.update_one({"_id": ObjectId(sid)}, {"$set": {"channel_id": new_cid}})
    bot.send_message(chat_id=u, text=f"✅ <b>Channel Successfully Updated to:</b> <code>{new_cid}</code>\nNaye episodes ab naye channel par post honge.")
    del user_cache[u]
    show_series_hub(u)

# --- 1-Click Repost All Episodes to New Channel ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("repost_all_"))
def repost_all_episodes(call):
    u = call.message.chat.id
    sid = call.data.replace("repost_all_", "")
    s = col_series.find_one({"_id": ObjectId(sid)})
    episodes = list(col_episodes.find({"series_id": sid}))

    if not episodes:
        bot.answer_callback_query(call.id, "Is series ke koi episodes saved nahi hain!", show_alert=True)
        return

    bot.send_message(chat_id=u, text=f"⏳ <b>Reposting {len(episodes)} episodes to new channel...</b>")
    bot_user = get_setting("bot_username")

    for ep in episodes:
        q_files = list(col_files.find({"series_id": sid, "ep_num": ep["ep_num"]}))
        row1, row2 = [], []
        for qf in q_files:
            btn = StyledInlineKeyboardButton(text=f"{qf['quality']} ↗", url=f"https://t.me/{bot_user}?start={qf['file_key']}", style="primary")
            if qf["quality"] == "HDRip":
                row2.append(btn)
            else:
                row1.append(btn)
        
        kb = types.InlineKeyboardMarkup()
        if row1:
            kb.row(*row1)
        if row2:
            kb.row(*row2)

        try:
            bot.send_photo(chat_id=s["channel_id"], photo=s["banner"], caption=ep["caption"], reply_markup=kb)
            time.sleep(1)
        except Exception as e:
            logger.error(f"Repost Error: {e}")

    bot.send_message(chat_id=u, text="🎉 <b>All episodes successfully reposted to new channel!</b>")
    show_series_hub(u)

# --- Archive and Restore ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("archive_series_"))
def archive_series(call):
    sid = call.data.replace("archive_series_", "")
    col_series.update_one({"_id": ObjectId(sid)}, {"$set": {"status": "COMPLETED"}})
    bot.answer_callback_query(call.id, "Series moved to Archive!")
    show_series_hub(call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "view_completed_series")
def view_completed_list(call):
    completed = list(col_series.find({"status": "COMPLETED"}))
    kb = types.InlineKeyboardMarkup()
    for s in completed:
        sid = str(s["_id"])
        kb.row(
            StyledInlineKeyboardButton(text=f"📦 {s['title']}", callback_data=f"view_series_{sid}", style="primary"),
            StyledInlineKeyboardButton(text="🟢 Restore", callback_data=f"restore_series_{sid}", style="success")
        )
    kb.add(StyledInlineKeyboardButton(text="🔙 Back to Ongoing", callback_data="admin_series_hub", style="danger"))
    bot.send_message(chat_id=call.message.chat.id, text=f"<b>📁 Completed Anime Archive ({len(completed)}):</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("restore_series_"))
def restore_series(call):
    sid = call.data.replace("restore_series_", "")
    col_series.update_one({"_id": ObjectId(sid)}, {"$set": {"status": "ONGOING"}})
    bot.answer_callback_query(call.id, "Series restored to Ongoing!")
    show_series_hub(call.message.chat.id)

# ================= EPISODE UPLOAD WIZARD =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_upload_ep")
def start_upload_wizard(call):
    u = call.message.chat.id
    ongoing = list(col_series.find({"status": "ONGOING"}))
    if not ongoing:
        bot.send_message(chat_id=u, text="❌ <b>No ongoing series found. Register one first!</b>")
        return

    kb = types.InlineKeyboardMarkup()
    for s in ongoing:
        kb.add(StyledInlineKeyboardButton(text=f"🎬 {s['title']}", callback_data=f"sel_ep_series_{str(s['_id'])}", style="primary"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Cancel", callback_data="admin_hub", style="danger"))
    bot.send_message(chat_id=u, text="<b>Select Anime Series To Upload:</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sel_ep_series_"))
def select_ep_series(call):
    u = call.message.chat.id
    sid = call.data.replace("sel_ep_series_", "")
    s = col_series.find_one({"_id": ObjectId(sid)})
    
    user_cache[u] = {"series": s, "files": {}}
    msg = bot.send_message(chat_id=u, text=f"Selected: <b>{s['title']}</b>\n\n<b>Send Episode Number:</b> (e.g. <code>01</code>, <code>07</code>)")
    bot.register_next_step_handler(msg, step_get_ep_number)

def step_get_ep_number(message):
    u = message.chat.id
    if u not in user_cache:
        return
    user_cache[u]["ep_num"] = message.text.strip()

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        StyledInlineKeyboardButton(text="🇯🇵 Japanese [Eng-Sub]", callback_data="aud_jap", style="primary"),
        StyledInlineKeyboardButton(text="🔊 Dual Audio [Hindi + Jap]", callback_data="aud_dual", style="success"),
        StyledInlineKeyboardButton(text="🌐 Multi Audio [Multi-Lang]", callback_data="aud_multi", style="success"),
        StyledInlineKeyboardButton(text="🇬🇧 English Dub / Sub", callback_data="aud_eng", style="primary")
    )
    bot.send_message(chat_id=u, text="<b>Select Audio Format:</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("aud_"))
def set_ep_audio(call):
    u = call.message.chat.id
    if u not in user_cache:
        return
    aud_map = {
        "aud_jap": "Japanese [Eng-Sub]",
        "aud_dual": "[Dual Audio]",
        "aud_multi": "[Multi Audio]",
        "aud_eng": "English [Sub/Dub]"
    }
    user_cache[u]["audio"] = aud_map.get(call.data, "Japanese [Eng-Sub]")

    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="⏩ Skip 480p", callback_data="skip_file_480", style="danger"))
    msg = bot.send_message(chat_id=u, text=f"Audio: <b>{user_cache[u]['audio']}</b>\n\n📁 <b>Step 1/4: Forward / Send 480p File:</b>", reply_markup=kb)
    bot.register_next_step_handler(msg, step_get_480)

def step_get_480(message):
    u = message.chat.id
    if u not in user_cache:
        return
    f_id, f_type = extract_file(message)
    if f_id:
        user_cache[u]["files"]["480p"] = {"id": f_id, "type": f_type}
        bot.send_message(chat_id=u, text="✅ <b>480p Captured!</b>")
    prompt_q(u, "720p", "2/4", step_get_720, "skip_file_720")

@bot.callback_query_handler(func=lambda c: c.data == "skip_file_480")
def skip_480_cb(call):
    prompt_q(call.message.chat.id, "720p", "2/4", step_get_720, "skip_file_720")

def step_get_720(message):
    u = message.chat.id
    if u not in user_cache:
        return
    f_id, f_type = extract_file(message)
    if f_id:
        user_cache[u]["files"]["720p"] = {"id": f_id, "type": f_type}
        bot.send_message(chat_id=u, text="✅ <b>720p Captured!</b>")
    prompt_q(u, "1080p", "3/4", step_get_1080, "skip_file_1080")

@bot.callback_query_handler(func=lambda c: c.data == "skip_file_720")
def skip_720_cb(call):
    prompt_q(call.message.chat.id, "1080p", "3/4", step_get_1080, "skip_file_1080")

def step_get_1080(message):
    u = message.chat.id
    if u not in user_cache:
        return
    f_id, f_type = extract_file(message)
    if f_id:
        user_cache[u]["files"]["1080p"] = {"id": f_id, "type": f_type}
        bot.send_message(chat_id=u, text="✅ <b>1080p Captured!</b>")
    prompt_q(u, "HDRip", "4/4", step_get_hdrip, "skip_file_hdrip")

@bot.callback_query_handler(func=lambda c: c.data == "skip_file_1080")
def skip_1080_cb(call):
    prompt_q(call.message.chat.id, "HDRip", "4/4", step_get_hdrip, "skip_file_hdrip")

def step_get_hdrip(message):
    u = message.chat.id
    if u not in user_cache:
        return
    f_id, f_type = extract_file(message)
    if f_id:
        user_cache[u]["files"]["HDRip"] = {"id": f_id, "type": f_type}
        bot.send_message(chat_id=u, text="✅ <b>HDRip Captured!</b>")
    publish_episode(u)

@bot.callback_query_handler(func=lambda c: c.data == "skip_file_hdrip")
def skip_hdrip_cb(call):
    publish_episode(call.message.chat.id)

def prompt_q(u, q_name, step_str, next_fn, skip_cb):
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text=f"⏩ Skip {q_name}", callback_data=skip_cb, style="danger"))
    msg = bot.send_message(chat_id=u, text=f"📁 <b>Step {step_str}: Forward / Send {q_name} File:</b>", reply_markup=kb)
    bot.register_next_step_handler(msg, next_fn)

# ================= DUAL CHANNEL PUBLISHER =================
def publish_episode(u):
    if u not in user_cache:
        return
    data = user_cache[u]
    files = data["files"]

    if not files:
        bot.send_message(chat_id=u, text="❌ <b>No files attached! Upload cancelled.</b>")
        del user_cache[u]
        show_admin_panel(u)
        return

    s = data["series"]
    sid = str(s["_id"])
    ep_num = data["ep_num"]
    audio = data["audio"]
    timestamp = int(time.time())
    bot_user = get_setting("bot_username")

    row1, row2 = [], []
    qualities = []

    for q in ["480p", "720p", "1080p", "HDRip"]:
        if q in files:
            qualities.append(q)
            file_key = f"file_{u}_{timestamp}_{q.lower()}"
            file_name = f"{s['title']} Ep {ep_num} [{q}]"
            
            col_files.insert_one({
                "file_key": file_key,
                "file_id": files[q]["id"],
                "file_type": files[q]["type"],
                "file_name": file_name,
                "series_id": sid,
                "ep_num": ep_num,
                "quality": q
            })
            btn = StyledInlineKeyboardButton(text=f"{q} ↗", url=f"https://t.me/{bot_user}?start={file_key}", style="primary")
            if q == "HDRip":
                row2.append(btn)
            else:
                row1.append(btn)

    series_kb = types.InlineKeyboardMarkup()
    if row1:
        series_kb.row(*row1)
    if row2:
        series_kb.row(*row2)

    brand = get_setting("brand_name")
    main_channel = get_setting("main_channel_id")

    caption = (
        f"✦ <b>{s['title']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"▶ <b>ꜱᴛᴀᴛᴜꜱ :</b> {s['status']}\n"
        f"▶ <b>ꜱᴇᴀꜱᴏɴꜱ :</b> {s['season']}\n"
        f"▶ <b>ᴇᴘɪꜱᴏᴅᴇꜱ :</b> {ep_num}\n"
        f"▶ <b>ᴀᴜᴅɪᴏ :</b> {audio}\n"
        f"▶ <b>Qᴜᴀʟɪᴛʏ :</b> {' , '.join(qualities)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✦ <b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ :</b> {brand}"
    )

    # 1. Post to Dedicated Anime Series Channel
    target_post = bot.send_photo(chat_id=s["channel_id"], photo=s["banner"], caption=caption, reply_markup=series_kb)
    
    col_episodes.insert_one({
        "series_id": sid,
        "ep_num": ep_num,
        "audio": audio,
        "caption": caption,
        "msg_id_target": target_post.message_id
    })

    # 2. Post to Main Channel with Redirect Button
    clean_target_cid = str(s["channel_id"]).replace("-100", "")
    target_post_url = f"https://t.me/c/{clean_target_cid}/{target_post.message_id}"
    
    main_kb = types.InlineKeyboardMarkup()
    main_kb.add(StyledInlineKeyboardButton(text="⛩️ ᴅᴏᴡɴʟᴏᴀᴅ ɴᴏᴡ ⛩️ ↗", url=target_post_url, style="success"))

    try:
        bot.send_photo(chat_id=main_channel, photo=s["banner"], caption=caption, reply_markup=main_kb)
    except Exception as e:
        logger.error(f"Main Broadcast Error: {e}")

    bot.send_message(chat_id=u, text="🎉 <b>Episode published successfully on both channels!</b>")
    del user_cache[u]
    show_admin_panel(u)

# ================= FORCESUB CONFIGURATION MENU =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_fsub_hub")
def show_fsub_menu(call):
    channels = list(col_fsub.find())
    kb = types.InlineKeyboardMarkup()
    for ch in channels:
        cid_str = str(ch["_id"])
        kb.row(
            StyledInlineKeyboardButton(text=f"📢 {ch['title']}", callback_data=f"view_fsub_{cid_str}", style="primary"),
            StyledInlineKeyboardButton(text="❌ Remove", callback_data=f"del_fsub_{cid_str}", style="danger")
        )
    kb.add(StyledInlineKeyboardButton(text="➕ Add ForceSub Channel", callback_data="add_fsub_ch", style="success"))
    kb.add(StyledInlineKeyboardButton(text="🔙 Dashboard", callback_data="admin_hub", style="danger"))
    bot.send_message(chat_id=call.message.chat.id, text=f"🛡️ <b>ForceSub Management Hub ({len(channels)} Channels):</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "add_fsub_ch")
def start_add_fsub(call):
    u = call.message.chat.id
    user_cache[u] = {}
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="admin_fsub_hub", style="danger"))
    msg = bot.send_message(chat_id=u, text="<b>Send: Channel Title | Channel Numeric ID (-100...) | Invite Link:</b>\n\nExample:\n<code>Main Updates | -1001234567890 | https://t.me/+AbCdEfGh</code>", reply_markup=kb)
    bot.register_next_step_handler(msg, step_save_fsub)

def step_save_fsub(message):
    u = message.chat.id
    parts = (message.text or "").split("|")
    if len(parts) >= 3:
        title, cid, link = parts[0].strip(), parts[1].strip(), parts[2].strip()
        col_fsub.insert_one({"title": title, "channel_id": cid, "invite_link": link})
        bot.send_message(chat_id=u, text=f"✅ <b>ForceSub Channel Added:</b> {title}")
    else:
        bot.send_message(chat_id=u, text="❌ <b>Invalid format! Use Title | ID | Link</b>")
    show_fsub_menu(types.CallbackQuery(id=0, from_user=message.from_user, data="admin_fsub_hub", message=message, chat_instance=None, json_string=""))

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_fsub_"))
def del_fsub_channel(call):
    fid = call.data.replace("del_fsub_", "")
    col_fsub.delete_one({"_id": ObjectId(fid)})
    bot.answer_callback_query(call.id, "Channel removed from ForceSub!")
    show_fsub_menu(call)

# ================= MASS BROADCAST SYSTEM =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_broadcast")
def start_broadcast(call):
    u = call.message.chat.id
    kb = types.InlineKeyboardMarkup()
    kb.add(StyledInlineKeyboardButton(text="❌ Cancel", callback_data="admin_hub", style="danger"))
    msg = bot.send_message(chat_id=u, text="📢 <b>Send the message you want to broadcast:</b>", reply_markup=kb)
    bot.register_next_step_handler(msg, execute_broadcast)

def execute_broadcast(message):
    u = message.chat.id
    if message.text == "/cancel":
        return
    users = list(col_users.find())
    
    bot.send_message(chat_id=u, text=f"⏳ <b>Broadcasting to {len(users)} users...</b>")
    sent, failed = 0, 0

    for user in users:
        try:
            bot.copy_message(chat_id=user["user_id"], from_chat_id=u, message_id=message.message_id)
            sent += 1
            time.sleep(0.05)
        except Exception:
            failed += 1

    bot.send_message(chat_id=u, text=f"✅ <b>Broadcast Completed!</b>\n\n🟢 <b>Sent:</b> {sent}\n🔴 <b>Failed/Blocked:</b> {failed}")
    show_admin_panel(u)

# ================= STATS & CANCEL =================
@bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
def show_stats(call):
    u_count = col_users.count_documents({})
    s_count = col_series.count_documents({"status": "ONGOING"})
    c_count = col_series.count_documents({"status": "COMPLETED"})
    ep_count = col_episodes.count_documents({})

    bot.send_message(
        chat_id=call.message.chat.id,
        text=f"📊 <b>MongoDB Live System Statistics</b>\n\n"
             f"👥 <b>Total Users:</b> <code>{u_count}</code>\n"
             f"🟢 <b>Ongoing Series:</b> <code>{s_count}</code>\n"
             f"📦 <b>Completed Series:</b> <code>{c_count}</code>\n"
             f"🎬 <b>Total Episodes Uploaded:</b> <code>{ep_count}</code>\n"
             f"⚡ <b>Engine:</b> <code>Python MongoDB Atlas Cluster</code>"
    )

@bot.callback_query_handler(func=lambda c: c.data == "admin_hub")
def back_admin(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    show_admin_panel(call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "cancel_wizard")
def cancel_wizard_action(call):
    u = call.message.chat.id
    if u in user_cache:
        del user_cache[u]
    try:
        bot.delete_message(u, call.message.message_id)
    except Exception:
        pass
    bot.send_message(chat_id=u, text="❌ <b>Operation Cancelled.</b>")
    show_admin_panel(u)

# ================= BOT POLLING WITH AUTO-RETRY =================
if __name__ == "__main__":
    logger.info("🚀 Master MongoDB Anime Bot is starting polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            logger.error(f"⚠️ Polling Exception encountered: {e}. Retrying in 5 seconds...")
            time.sleep(5)
