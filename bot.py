import os
import time
import threading
import telebot
from telebot import types
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================= CUSTOM STYLED BUTTON CLASSES =================
class StyledInlineKeyboardButton(types.InlineKeyboardButton):
    def __init__(self, text, style=None, *args, **kwargs):
        super().__init__(text=text, *args, **kwargs)
        self.style = style  # "primary", "success", "danger"

class StyledKeyboardButton(types.KeyboardButton):
    def __init__(self, text, style=None, *args, **kwargs):
        super().__init__(text=text, *args, **kwargs)
        self.style = style

# ================= CONFIGURATION & ENV VARIABLES =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8045722822:AAG4BgNxs59oXZ8HSJIeZ4ZUmSgt4pKapfk")
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://skanis2008_db_user:skanis09@zeno.dzdqoaj.mongodb.net/?appName=Zeno")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5659051138"))

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ================= MONGODB DATABASE SETUP =================
client = MongoClient(MONGO_URI)
db = client["anime_master_db"]

col_series = db["series"]
col_episodes = db["episodes"]
col_files = db["files"]
col_users = db["users"]
col_fsub = db["fsub"]
col_settings = db["settings"]

# Initialize Settings Config if not present
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

# Temporary memory cache for multi-step admin input
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

    # ForceSub Verification
    passed, unsubbed = check_fsub(u)
    if not passed:
        bot.send_message(
            chat_id=u,
            text="⚠️ <b>Access Denied!</b>\n\nEpisodes download karne ke liye official channels join karna zaroori hai:",
            reply_markup=get_fsub_keyboard(unsubbed, start_param)
        )
        return

    # Deep Link File Retrieval
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
    user_cache[u]["title"] = messag
