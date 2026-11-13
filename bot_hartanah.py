
import logging
import json
import os
import io
import threading
import re

from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InputMediaPhoto,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# =============================================================
# CONFIGURATION
# =============================================================

API_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

GROUP_CHAT_ID = -1003288686118
BACKUP_CHANNEL_ID = -5119617442

DB_FILE = "listings_data.json"
TIMEZONE = ZoneInfo("Asia/Kuala_Lumpur")

if not API_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN belum ditetapkan dalam Environment Variables."
    )

# =============================================================
# DATABASE
# =============================================================

listings_db = {}
pinned_index_message_id = None

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =============================================================
# WEB SERVER
# =============================================================

class SimpleHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Hartanah is alive!")

    def log_message(self, format, *args):
        return


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()


# =============================================================
# DATABASE VALIDATION
# =============================================================

def validate_database(raw_listings):

    if not isinstance(raw_listings, dict):
        raise ValueError("Format database tidak sah.")

    loaded_db = {}

    for key, item in raw_listings.items():

        listing_id = int(key)

        if not isinstance(item, dict):
            raise ValueError(f"Listing #{listing_id} tidak sah.")

        required_fields = [
            "title",
            "price",
            "desc",
            "status",
        ]

        for field in required_fields:
            if field not in item:
                raise ValueError(
                    f"Listing #{listing_id} tiada field {field}."
                )

        item.setdefault("photos", [])
        item.setdefault("group_message_ids", [])

        if not isinstance(item["photos"], list):
            item["photos"] = []

        if not isinstance(item["group_message_ids"], list):
            item["group_message_ids"] = []

        if item.get("status") not in ["ACTIVE", "BOOKED", "SOLD"]:
            item["status"] = "ACTIVE"

        loaded_db[listing_id] = item

    return loaded_db


# =============================================================
# LOAD LOCAL JSON
# =============================================================

def load_local_database():

    global listings_db
    global pinned_index_message_id

    try:

        if not os.path.exists(DB_FILE):
            print("⚠️ Fail JSON tempatan tidak dijumpai.")
            return False

        with open(DB_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        loaded_db = validate_database(
            data.get("listings", {})
        )

        if not loaded_db:
            return False

        listings_db = loaded_db

        pinned_index_message_id = data.get(
            "pinned_index_message_id"
        )

        print(
            f"✅ Local database berjaya dimuatkan: "
            f"{len(listings_db)} listing."
        )

        return True

    except Exception as e:

        print(f"❌ Gagal load local database: {e}")
        return False


# =============================================================
# LOAD LATEST JSON FROM TELEGRAM BACKUP CHANNEL
# =============================================================

async def load_data_from_channel(app: Application):

    global listings_db
    global pinned_index_message_id

    try:

        print("🔄 Membaca pinned backup JSON dari Telegram Channel...")

        chat = await app.bot.get_chat(
            chat_id=BACKUP_CHANNEL_ID
        )

        pinned = chat.pinned_message

        if not pinned:
            print("⚠️ Tiada pinned message dalam Backup Channel.")
            return False

        if not pinned.document:
            print("⚠️ Pinned message bukan dokumen JSON.")
            return False

        filename = pinned.document.file_name or ""

        if not filename.lower().endswith(".json"):
            print("⚠️ Pinned document bukan fail JSON.")
            return False

        telegram_file = await pinned.document.get_file()

        file_bytes = await telegram_file.download_as_bytearray()

        data = json.loads(
            file_bytes.decode("utf-8")
        )

        loaded_db = validate_database(
            data.get("listings", {})
        )

        # Pastikan backup mengandungi 9 listing asal
        if len(loaded_db) < 9 or 9 not in loaded_db:

            print(
                "⚠️ Backup tidak lengkap. "
                "Sekurang-kurangnya 9 listing diperlukan."
            )

            return False

        # Gantikan database RAM dengan backup terkini
        listings_db = loaded_db

        pinned_index_message_id = data.get(
            "pinned_index_message_id"
        )

        active_count = sum(
            1 for item in listings_db.values()
            if item.get("status") == "ACTIVE"
        )

        print("======================================")
        print("✅ BACKUP CHANNEL BERJAYA DIBACA")
        print(f"📦 Jumlah listing: {len(listings_db)}")
        print(f"🟢 Listing ACTIVE: {active_count}")
        print("======================================")

        # Simpan salinan tempatan
        save_data()

        return True

    except Exception as e:

        print(f"❌ Gagal load backup channel: {e}")

        return False


# =============================================================
# SAVE DATABASE
# =============================================================

def save_data():

    try:

        data = {
            "version": 1,
            "saved_at": datetime.now(TIMEZONE).isoformat(),
            "total_listings": len(listings_db),
            "listings": listings_db,
            "pinned_index_message_id": pinned_index_message_id,
        }

        with open(DB_FILE, "w", encoding="utf-8") as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=4,
            )

        print("💾 Database berjaya disimpan.")

        return True

    except Exception as e:

        print(f"❌ Gagal simpan database: {e}")

        return False


# =============================================================
# BACKUP TO TELEGRAM CHANNEL
# =============================================================

async def backup_to_channel(context: ContextTypes.DEFAULT_TYPE):

    save_data()

    try:

        data_to_send = {
            "version": 1,
            "saved_at": datetime.now(TIMEZONE).isoformat(),
            "total_listings": len(listings_db),
            "listings": listings_db,
            "pinned_index_message_id": pinned_index_message_id,
        }

        json_bytes = json.dumps(
            data_to_send,
            ensure_ascii=False,
            indent=4,
        ).encode("utf-8")

        file_doc = io.BytesIO(json_bytes)
        file_doc.name = DB_FILE

        sent_msg = await context.bot.send_document(
            chat_id=BACKUP_CHANNEL_ID,
            document=file_doc,
            caption=(
                "📦 AUTO BACKUP LISTING DATA\n"
                f"Tarikh: {datetime.now(TIMEZONE).strftime('%d/%m/%Y %I:%M %p')}\n"
                f"Jumlah Listing: {len(listings_db)}"
            ),
        )

        try:

            await context.bot.pin_chat_message(
                chat_id=BACKUP_CHANNEL_ID,
                message_id=sent_msg.message_id,
            )

        except Exception as pin_error:

            print(f"⚠️ Gagal pin backup: {pin_error}")

        print("☁️ Backup berjaya dihantar ke Telegram Channel.")

        return True

    except Exception as e:

        print(f"❌ Gagal backup ke channel: {e}")

        return False


# =============================================================
# LISTING UTILITIES
# =============================================================

def get_next_listing_id():

    if not listings_db:
        return 1

    return max(listings_db.keys()) + 1


def get_display_price(item):

    price = item.get("price", "").strip()

    if price:
        return price

    # Sesetengah listing dalam JSON menyimpan harga
    # di dalam description dan bukan field price.
    text_to_check = (
        item.get("title", "")
        + "\n"
        + item.get("desc", "")
    )

    match = re.search(
        r"RM\s?[\d,]+(?:\.\d{2})?",
        text_to_check,
        re.IGNORECASE,
    )

    if match:
        return match.group(0)

    return ""


def get_active_count():

    return sum(
        1 for item in listings_db.values()
        if item.get("status", "ACTIVE") == "ACTIVE"
    )


def get_listing_keyboard(prefix, title_prefix):

    keyboard = []

    for l_id in sorted(listings_db.keys()):

        item = listings_db[l_id]

        title = item.get("title", "")

        keyboard.append([
            InlineKeyboardButton(
                f"{title_prefix} #{l_id}: {title[:45]}",
                callback_data=f"{prefix}_{l_id}",
            )
        ])

    return InlineKeyboardMarkup(keyboard)


# =============================================================
# REINDEX LISTINGS
# =============================================================

async def reindex_listings():

    global listings_db

    sorted_items = sorted(
        listings_db.items(),
        key=lambda x: x[0],
    )

    new_db = {}

    for new_id, (old_id, item) in enumerate(
        sorted_items,
        start=1,
    ):

        new_db[new_id] = item

    listings_db = new_db


# =============================================================
# UPDATE GROUP DESCRIPTION MESSAGE
# =============================================================

async def update_group_description(context, l_id):

    item = listings_db.get(l_id)

    if not item:
        return False

    group_msg_ids = item.get("group_message_ids", [])

    # ID #9 belum mempunyai mesej dalam group.
    # Oleh itu, skip edit group tetapi kekalkan dalam database.
    if not group_msg_ids:
        print(f"ℹ️ Listing #{l_id} belum mempunyai mesej group.")
        return False

    desc_msg_id = group_msg_ids[-1]

    status_val = item.get("status", "ACTIVE")

    status_str = (
        f" - *[{status_val}]*"
        if status_val != "ACTIVE"
        else ""
    )

    price = get_display_price(item)

    price_txt = (
        f"💰 **{price}**\n\n"
        if price
        else ""
    )

    updated_message = (
        f"📄 **MAKLUMAT LANJUT (ID #{l_id})**{status_str}\n\n"
        f"📍 **{item['title']}**\n"
        f"{price_txt}"
        f"{item['desc']}"
    )

    try:

        await context.bot.edit_message_text(
            chat_id=GROUP_CHAT_ID,
            message_id=desc_msg_id,
            text=updated_message,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            read_timeout=60,
            write_timeout=60,
            connect_timeout=60,
        )

        return True

    except Exception as e:

        print(
            f"⚠️ Gagal edit description Listing #{l_id}: {e}"
        )

        return False


# =============================================================
# UPDATE MAIN INDEX
# =============================================================

async def update_index_page(context: ContextTypes.DEFAULT_TYPE):

    global pinned_index_message_id

    try:

        current_time = datetime.now(TIMEZONE).strftime(
            "%d/%m/%Y %I:%M %p"
        )

        active_count = get_active_count()

        index_text = (
            "🏠 **SENARAI UTAMA LISTING HARTANAH** 🏠\n"
            f"🕒 *Last Updated: {current_time}*\n"
            f"📦 *Jumlah Listing: {len(listings_db)}*\n"
            f"🟢 *Listing ACTIVE: {active_count}*\n\n"
        )

        if not listings_db:

            index_text += "⚠️ *Tiada listing buat masa ini.*"

        else:

            for l_id in sorted(listings_db.keys()):

                item = listings_db[l_id]

                status_val = item.get("status", "ACTIVE")

                status_str = ""

                if status_val == "BOOKED":
                    status_str = " [BOOKED]"

                elif status_val == "SOLD":
                    status_str = " [SOLD]"

                group_msg_ids = item.get(
                    "group_message_ids", []
                )

                link_text = "Tiada pautan"

                if group_msg_ids:

                    first_msg_id = group_msg_ids[0]

                    clean_chat_id = str(
                        GROUP_CHAT_ID
                    ).replace("-100", "", 1)

                    link_text = (
                        f"https://t.me/c/{clean_chat_id}/{first_msg_id}"
                    )

                price_display = get_display_price(item)

                price_line = (
                    f"   {price_display}\n"
                    if price_display
                    else ""
                )

                index_text += (
                    f"🔹 **ID #{l_id}** | "
                    f"{item['title']}{status_str}\n"
                    f"{price_line}"
                    f"   🔗 {link_text}\n"
                    f"-----------------------------------\n"
                )

        old_pinned_id = pinned_index_message_id

        # Hantar index baharu
        sent_msg = await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=index_text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

        pinned_index_message_id = sent_msg.message_id

        # Simpan database dengan index ID terkini
        save_data()

        # Backup database terkini
        backup_success = await backup_to_channel(context)

        # Pin index baharu
        try:

            await context.bot.pin_chat_message(
                chat_id=GROUP_CHAT_ID,
                message_id=pinned_index_message_id,
            )

        except Exception as e:

            print(f"⚠️ Gagal pin index baharu: {e}")

        # Padam index lama
        if old_pinned_id and old_pinned_id != pinned_index_message_id:

            try:

                await context.bot.unpin_chat_message(
                    chat_id=GROUP_CHAT_ID,
                    message_id=old_pinned_id,
                )

                await context.bot.delete_message(
                    chat_id=GROUP_CHAT_ID,
                    message_id=old_pinned_id,
                )

            except Exception as e:

                print(f"⚠️ Gagal padam index lama: {e}")

        print(
            f"✅ Index berjaya dikemaskini. "
            f"{len(listings_db)} listing."
        )

        return backup_success

    except Exception as e:

        print(f"❌ Ralat update index: {e}")

        return False


# =============================================================
# START MENU
# =============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data.clear()

    keyboard = [

        [
            InlineKeyboardButton(
                "➕ Tambah Listing Baru",
                callback_data="add_listing",
            )
        ],

        [
            InlineKeyboardButton(
                "✏️ Kemaskini Harga",
                callback_data="edit_price_menu",
            )
        ],

        [
            InlineKeyboardButton(
                "📝 Kemaskini Description",
                callback_data="edit_desc_menu",
            )
        ],

        [
            InlineKeyboardButton(
                "🏷️ Set Status",
                callback_data="set_status",
            )
        ],

        [
            InlineKeyboardButton(
                "🗑️ Padam Listing",
                callback_data="delete_listing",
            )
        ],

        [
            InlineKeyboardButton(
                "📢 Refresh Index",
                callback_data="refresh_index",
            )
        ],
    ]

    await update.message.reply_text(
        "🏠 **Sistem Pengurusan Listing Hartanah**\n\n"
        f"📦 Jumlah Listing: {len(listings_db)}\n"
        f"🟢 Listing ACTIVE: {get_active_count()}\n\n"
        "Pilih tindakan di bawah:",

        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# =============================================================
# BUTTON HANDLER
# =============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    data = query.data

    # ---------------------------------------------------------
    # ADD LISTING
    # ---------------------------------------------------------

    if data == "add_listing":

        context.user_data["state"] = "WAITING_FOR_LISTING_PHOTOS"
        context.user_data["temp_photos"] = []
        context.user_data["temp_caption"] = ""

        await query.message.reply_text(
            "📸 **Tambah Listing Baru:**\n\n"
            "Hantar gambar hartanah berserta kapsyen "
            "pada gambar pertama.\n\n"
            "Format kapsyen:\n"
            "Baris 1: Tajuk Listing\n"
            "Baris 2: Harga\n"
            "Baris 3 dan seterusnya: Description\n\n"
            "Selepas selesai, taip **DONE**."
        )

    # ---------------------------------------------------------
    # REFRESH INDEX
    # ---------------------------------------------------------

    elif data == "refresh_index":

        await query.message.reply_text(
            "🔄 Sedang membaca pinned JSON terkini "
            "daripada Backup Channel..."
        )

        loaded = await load_data_from_channel(
            context.application
        )

        if not loaded:

            await query.message.reply_text(
                "❌ Gagal membaca backup terkini.\n\n"
                "Database sedia ada dikekalkan. "
                "Sila semak pinned JSON dalam Backup Channel."
            )

            return

        print(
            f"📦 Jumlah listing dibaca: {len(listings_db)}"
        )

        success = await update_index_page(context)

        if success:

            await query.message.reply_text(
                "✅ INDEX BERJAYA DIKEMASKINI!\n\n"
                f"📦 Jumlah listing: {len(listings_db)}\n"
                f"🟢 Listing ACTIVE: {get_active_count()}\n"
                "📥 Data dibaca daripada Backup Channel.\n"
                "📢 Index baharu dihantar ke group.\n"
                "☁️ Backup terkini berjaya disimpan."
            )

        else:

            await query.message.reply_text(
                "⚠️ Index telah diproses tetapi backup "
                "mungkin gagal. Sila semak Telegram Channel."
            )

    # ---------------------------------------------------------
    # EDIT PRICE MENU
    # ---------------------------------------------------------

    elif data == "edit_price_menu":

        if not listings_db:

            await query.message.reply_text(
                "⚠️ Tiada listing."
            )

            return

        await query.message.reply_text(
            "✏️ Pilih listing untuk dikemaskini harganya:",
            reply_markup=get_listing_keyboard(
                "editprice",
                "Harga",
            ),
        )

    elif data.startswith("editprice_"):

        l_id = int(data.split("_")[1])

        if l_id not in listings_db:
            return

        context.user_data["editing_id"] = l_id
        context.user_data["state"] = "WAITING_FOR_NEW_PRICE"

        await query.message.reply_text(
            f"Sila taip harga baru untuk Listing #{l_id}:"
        )

    # ---------------------------------------------------------
    # EDIT DESCRIPTION MENU
    # ---------------------------------------------------------

    elif data == "edit_desc_menu":

        if not listings_db:

            await query.message.reply_text(
                "⚠️ Tiada listing."
            )

            return

        await query.message.reply_text(
            "📝 Pilih listing untuk dikemaskini description:",
            reply_markup=get_listing_keyboard(
                "editdesc",
                "Desc",
            ),
        )

    elif data.startswith("editdesc_"):

        l_id = int(data.split("_")[1])

        if l_id not in listings_db:
            return

        context.user_data["editing_desc_id"] = l_id
        context.user_data["state"] = "WAITING_FOR_NEW_DESC"

        await query.message.reply_text(
            f"📝 Hantar description baru untuk Listing #{l_id}.\n\n"
            "Boleh hantar teks biasa atau gambar berserta kapsyen."
        )

    # ---------------------------------------------------------
    # SET STATUS MENU
    # ---------------------------------------------------------

    elif data == "set_status":

        if not listings_db:

            await query.message.reply_text(
                "⚠️ Tiada listing."
            )

            return

        await query.message.reply_text(
            "🏷️ Pilih listing untuk dikemaskini status:",
            reply_markup=get_listing_keyboard(
                "status",
                "Status",
            ),
        )

    elif data.startswith("status_"):

        l_id = int(data.split("_")[1])

        if l_id not in listings_db:
            return

        keyboard = [

            [
                InlineKeyboardButton(
                    "🟢 ACTIVE",
                    callback_data=f"setstat_{l_id}_ACTIVE",
                )
            ],

            [
                InlineKeyboardButton(
                    "🟡 BOOKED",
                    callback_data=f"setstat_{l_id}_BOOKED",
                )
            ],

            [
                InlineKeyboardButton(
                    "🔴 SOLD",
                    callback_data=f"setstat_{l_id}_SOLD",
                )
            ],

        ]

        await query.message.reply_text(
            f"Pilih status baru untuk Listing #{l_id}:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("setstat_"):

        _, l_id_str, new_status = data.split("_")

        l_id = int(l_id_str)

        if l_id not in listings_db:
            return

        listings_db[l_id]["status"] = new_status

        save_data()

        await update_group_description(
            context,
            l_id,
        )

        success = await update_index_page(context)

        await query.message.reply_text(
            f"✅ Status Listing #{l_id} ditukar kepada {new_status}.\n"
            "Index dan database telah dikemaskini."
        )

    # ---------------------------------------------------------
    # DELETE LISTING MENU
    # ---------------------------------------------------------

    elif data == "delete_listing":

        if not listings_db:

            await query.message.reply_text(
                "⚠️ Tiada listing."
            )

            return

        await query.message.reply_text(
            "🗑️ Pilih listing untuk dipadam:",
            reply_markup=get_listing_keyboard(
                "del",
                "Padam",
            ),
        )

    elif data.startswith("del_"):

        l_id = int(data.split("_")[1])

        if l_id not in listings_db:
            return

        group_msg_ids = listings_db[l_id].get(
            "group_message_ids", []
        )

        for msg_id in group_msg_ids:

            try:

                await context.bot.delete_message(
                    chat_id=GROUP_CHAT_ID,
                    message_id=msg_id,
                )

            except Exception:
                pass

        listings_db.pop(l_id, None)

        # Kekalkan fungsi reindex asal
        await reindex_listings()

        save_data()

        await update_index_page(context)

        await query.message.reply_text(
            "✅ Listing berjaya dipadam.\n"
            "ID telah disusun semula secara automatik."
        )


# =============================================================
# MESSAGE HANDLER
# =============================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    state = context.user_data.get("state")

    # ---------------------------------------------------------
    # UPDATE PRICE
    # ---------------------------------------------------------

    if state == "WAITING_FOR_NEW_PRICE":

        if not update.message.text:

            await update.message.reply_text(
                "⚠️ Sila hantar teks harga sahaja."
            )

            return

        new_price = update.message.text.strip()

        l_id = context.user_data.get("editing_id")

        if l_id in listings_db:

            listings_db[l_id]["price"] = new_price

            save_data()

            await update_group_description(
                context,
                l_id,
            )

            await update_index_page(context)

            context.user_data.clear()

            await update.message.reply_text(
                f"✅ Harga Listing #{l_id} berjaya dikemaskini!"
            )

        return

    # ---------------------------------------------------------
    # UPDATE DESCRIPTION
    # ---------------------------------------------------------

    elif state == "WAITING_FOR_NEW_DESC":

        new_desc = None

        if update.message.text:

            new_desc = update.message.text.strip()

        elif update.message.caption:

            new_desc = update.message.caption.strip()

        if not new_desc:

            await update.message.reply_text(
                "⚠️ Tiada teks atau kapsyen dikesan."
            )

            return

        l_id = context.user_data.get("editing_desc_id")

        if l_id in listings_db:

            listings_db[l_id]["desc"] = new_desc

            save_data()

            await update_group_description(
                context,
                l_id,
            )

            await update_index_page(context)

            context.user_data.clear()

            await update.message.reply_text(
                f"✅ Description Listing #{l_id} berjaya dikemaskini!"
            )

        return

    # ---------------------------------------------------------
    # ADD NEW LISTING
    # ---------------------------------------------------------

    elif state == "WAITING_FOR_LISTING_PHOTOS":

        if update.message.photo:

            photo_file_id = update.message.photo[-1].file_id

            context.user_data["temp_photos"].append(
                photo_file_id
            )

            if (
                update.message.caption
                and not context.user_data.get("temp_caption")
            ):

                context.user_data["temp_caption"] = (
                    update.message.caption
                )

            await update.message.reply_text(
                f"📸 Gambar diterima!\n"
                f"Jumlah: {len(context.user_data['temp_photos'])}\n\n"
                "Hantar lagi gambar atau taip DONE."
            )

            return

        if update.message.text:

            text_input = update.message.text.strip()

            if text_input.upper() == "DONE":

                photos = context.user_data.get(
                    "temp_photos", []
                )

                caption_text = context.user_data.get(
                    "temp_caption", ""
                )

                if not photos:

                    await update.message.reply_text(
                        "⚠️ Tiada gambar dikesan."
                    )

                    return

                if not caption_text:

                    await update.message.reply_text(
                        "⚠️ Sila pastikan gambar pertama "
                        "mempunyai kapsyen."
                    )

                    return

                lines = caption_text.split("\n")

                if len(lines) < 3:

                    await update.message.reply_text(
                        "⚠️ Format kapsyen memerlukan sekurang-kurangnya 3 baris."
                    )

                    return

                title = lines[0].strip()
                price = lines[1].strip()
                desc = "\n".join(lines[2:]).strip()

                saved_id = get_next_listing_id()

                short_caption = (
                    f"📢 **NEW LISTING! (ID #{saved_id})**\n"
                    f"📍 **{title}**\n"
                    f"💰 Harga/Sewa: {price}\n"
                    "*(Maklumat lanjut di bawah 👇)*"
                )

                full_desc = (
                    f"📄 **MAKLUMAT LANJUT (ID #{saved_id})**\n\n"
                    f"📍 **{title}**\n"
                    f"💰 **{price}**\n\n"
                    f"{desc}"
                )

                group_message_ids = []

                try:

                    read_opts = {
                        "read_timeout": 60,
                        "write_timeout": 60,
                        "connect_timeout": 60,
                    }

                    if len(photos) > 1:

                        media_list = [
                            InputMediaPhoto(
                                media=photos[0],
                                caption=short_caption,
                                parse_mode="Markdown",
                            )
                        ]

                        for photo_id in photos[1:]:

                            media_list.append(
                                InputMediaPhoto(
                                    media=photo_id
                                )
                            )

                        sent_messages = await context.bot.send_media_group(
                            chat_id=GROUP_CHAT_ID,
                            media=media_list,
                            **read_opts,
                        )

                        for msg in sent_messages:

                            group_message_ids.append(
                                msg.message_id
                            )

                    else:

                        sent_msg = await context.bot.send_photo(
                            chat_id=GROUP_CHAT_ID,
                            photo=photos[0],
                            caption=short_caption,
                            parse_mode="Markdown",
                            **read_opts,
                        )

                        group_message_ids.append(
                            sent_msg.message_id
                        )

                    desc_msg = await context.bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=full_desc,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                        **read_opts,
                    )

                    group_message_ids.append(
                        desc_msg.message_id
                    )

                except Exception as e:

                    print(f"❌ Ralat hantar listing: {e}")

                    await update.message.reply_text(
                        f"❌ Gagal menghantar listing ke group:\n{e}"
                    )

                    return

                listings_db[saved_id] = {

                    "photos": photos,

                    "title": title,

                    "price": price,

                    "desc": desc,

                    "status": "ACTIVE",

                    "group_message_ids": group_message_ids,

                }

                save_data()

                context.user_data.clear()

                await update_index_page(context)

                await update.message.reply_text(
                    f"✅ Listing #{saved_id} berjaya disimpan!\n\n"
                    f"📦 Jumlah listing: {len(listings_db)}\n"
                    "📢 Dihantar ke group.\n"
                    "☁️ Backup telah diproses."
                )

            else:

                if not context.user_data.get("temp_caption"):

                    context.user_data["temp_caption"] = text_input

                    await update.message.reply_text(
                        "📝 Kapsyen diterima!\n"
                        "Sekarang hantar gambar atau taip DONE."
                    )

                else:

                    await update.message.reply_text(
                        "Sila hantar gambar seterusnya atau taip DONE."
                    )

    else:

        await update.message.reply_text(
            "Sila taip /start untuk membuka menu utama."
        )


# =============================================================
# POST INIT
# =============================================================

async def post_init(app: Application):

    print("🚀 Bot sedang memulakan sistem database...")

    # Cuba baca backup channel dahulu
    loaded = await load_data_from_channel(app)

    # Jika gagal, gunakan local JSON
    if not loaded:

        print("⚠️ Menggunakan local database sebagai fallback.")

        load_local_database()

    print("======================================")
    print("🏠 BOT HARTANAH BERJAYA DIMULAKAN")
    print(f"📦 Jumlah listing: {len(listings_db)}")
    print(f"🟢 Listing ACTIVE: {get_active_count()}")
    print("======================================")


# =============================================================
# MAIN
# =============================================================

def main():

    # Web server untuk hosting
    server_thread = threading.Thread(
        target=run_web_server,
        daemon=True,
    )

    server_thread.start()

    request = HTTPXRequest(
        read_timeout=60,
        write_timeout=60,
        connect_timeout=60,
        pool_timeout=60,
    )

    app = (
        Application.builder()
        .token(API_TOKEN)
        .request(request)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.PHOTO | (filters.TEXT & ~filters.COMMAND),
            handle_message,
        )
    )

    print("🏠 Bot Hartanah sedang berjalan...")

    app.run_polling()


if __name__ == "__main__":
    main()
