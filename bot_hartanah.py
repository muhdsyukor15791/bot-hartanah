import logging
import json
import os
import io
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# -------------------------------------------------------------
# Tetapkan di Render > Environment: TELEGRAM_BOT_TOKEN, GROUP_CHAT_ID, BACKUP_CHANNEL_ID
API_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8924536875:AAHiCoNNZaxMO8Ud2Xozvsbef3oRD8VfBy8").strip()
GROUP_CHAT_ID = int(os.environ.get("GROUP_CHAT_ID", "-1003288686118"))

backup_channel_env = os.environ.get("BACKUP_CHANNEL_ID", "-5119617442")
if not backup_channel_env:
    raise RuntimeError("BACKUP_CHANNEL_ID belum ditetapkan dalam Environment Variables.")
BACKUP_CHANNEL_ID = int(backup_channel_env)

DB_FILE = 'listings_data.json'
# -------------------------------------------------------------

listings_db = {}
pinned_index_message_id = None
restore_completed = False

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("BotHartanah")

# --- SERVER WEB MINI UNTUK RENDER PORT BINDING ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot Hartanah is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        logger.debug("Health check: " + format, *args)

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()
# -------------------------------------------------

def _decode_backup_bytes(file_bytes: bytes):
    try:
        data = json.loads(file_bytes.decode("utf-8-sig"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Fail bukan JSON yang sah: {e}")

    if not isinstance(data, dict):
        raise ValueError("Format JSON tidak sah: root mesti object/dictionary.")

    if isinstance(data.get("listings"), dict):
        raw_listings = data["listings"]
    else:
        raw_listings = {
            key: value for key, value in data.items()
            if str(key).isdigit() and isinstance(value, dict)
        }
        if not raw_listings:
            raise ValueError("JSON tiada medan 'listings' atau rekod listing bernombor.")

    restored = {}
    for key, value in raw_listings.items():
        try:
            listing_id = int(key)
        except ValueError:
            raise ValueError(f"ID listing '{key}' bukan nombor sah.")

        if not isinstance(value, dict):
            raise ValueError(f"Rekod listing #{listing_id} bukan object.")
        
        title = value.get("title")
        if not title or not isinstance(title, str) or not title.strip():
            raise ValueError(f"Rekod listing #{listing_id} tiada title yang sah.")

        value.setdefault("price", "")
        value.setdefault("desc", "")
        value.setdefault("status", "ACTIVE")
        value.setdefault("photos", [])
        value.setdefault("group_message_ids", [])
        
        restored[listing_id] = value

    pinned_id = data.get("pinned_index_message_id")
    if pinned_id is not None:
        try:
            pinned_id = int(pinned_id)
        except ValueError:
            pinned_id = None

    return restored, pinned_id


async def _restore_from_pinned_backup(app: Application):
    chat = await app.bot.get_chat(chat_id=BACKUP_CHANNEL_ID)
    message = getattr(chat, "pinned_message", None)
    if message is None:
        raise FileNotFoundError(f"Channel {BACKUP_CHANNEL_ID} tiada pinned message.")

    document = getattr(message, "document", None)
    if document is None:
        raise ValueError(f"Pinned message #{message.message_id} bukan dokumen.")

    filename = (document.file_name or "").strip()
    if filename.lower() != DB_FILE.lower():
        raise ValueError(f"Nama fail pinned ialah '{filename}', sepatutnya '{DB_FILE}'.")

    logger.info(f"📌 Pinned backup dijumpai: message_id={message.message_id}, file={filename}")
    telegram_file = await document.get_file()
    file_bytes = await telegram_file.download_as_bytearray()
    restored, restored_pin_id = _decode_backup_bytes(bytes(file_bytes))
    logger.info(f"📥 JSON Telegram berjaya dimuat turun dan disahkan: {len(restored)} listing.")
    return restored, restored_pin_id


async def load_data_from_channel(app: Application):
    global listings_db, pinned_index_message_id, restore_completed
    restore_completed = False
    
    logger.info("[STARTUP] Bot sedang dimulakan.")
    logger.info("[RESTORE] Memeriksa database tempatan.")

    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "rb") as f:
                restored, restored_pin_id = _decode_backup_bytes(f.read())
            if restored:
                listings_db = restored
                pinned_index_message_id = restored_pin_id
                restore_completed = True
                logger.info(f"[RESTORE] Database tempatan sah dijumpai: {len(listings_db)} listing dipulihkan.")
                logger.info("[STARTUP] Sistem sedia digunakan.")
                return
    except Exception as local_error:
        logger.warning(f"[RESTORE] Fail tempatan rosak/tidak sah: {local_error}")

    logger.info("[RESTORE] Database tempatan kosong atau tidak sah. Cuba mendapatkan backup Telegram...")

    try:
        restored, restored_pin_id = await _restore_from_pinned_backup(app)
        if restored:
            listings_db = restored
            pinned_index_message_id = restored_pin_id
            restore_completed = True
            save_data()
            logger.info(f"[RESTORE] Backup Telegram berjaya dibaca: {len(listings_db)} listing dipulihkan.")
            logger.info("[STARTUP] Sistem sedia digunakan.")
            return
    except Exception as telegram_error:
        logger.error(f"❌ [RESTORE] Backup Telegram gagal dibaca. Sebab: {telegram_error}")

    listings_db = {}
    restore_completed = False
    logger.error("🛑 [RESTORE] Pemulihan gagal. Bot bermula dengan database kosong.")
    logger.info("[STARTUP] Sistem sedia digunakan (Keadaan kosong).")


async def refresh_index_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    global listings_db, pinned_index_message_id, restore_completed

    if listings_db:
        logger.info("Refresh Index: Database memori mempunyai data. Teruskan proses refresh.")
    else:
        logger.info("Refresh Index: Database kosong. Cuba dapatkan backup daripada Telegram...")
        try:
            restored, restored_pin_id = await _restore_from_pinned_backup(context.application)
            if restored:
                listings_db = restored
                pinned_index_message_id = restored_pin_id
                restore_completed = True
                save_data()
                logger.info(f"Refresh Index: Berjaya pulihkan {len(listings_db)} listing daripada Telegram.")
                await query.message.reply_text(f"✅ Berjaya memulihkan {len(listings_db)} listing daripada backup Telegram.")
            else:
                raise ValueError("Backup kosong.")
        except Exception as e:
            logger.error(f"❌ Refresh Index Gagal. Sebab: {e}")
            await query.message.reply_text(f"❌ Kegagalan Pemulihan: Sila pastikan fail 'listings_data.json' dipin dengan betul di Backup Channel.")
            return

    success = await update_index_page(context)
    if success:
        await query.message.reply_text(f"✅ Index berjaya disegarkan! Jumlah listing aktif: {len(listings_db)}")
    else:
        await query.message.reply_text("❌ Gagal membina semula Index Page.")


def save_data():
    temp_file = DB_FILE + ".tmp"
    try:
        payload = {
            "version": 1,
            "saved_at": datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).isoformat(),
            "listings": listings_db,
            "pinned_index_message_id": pinned_index_message_id,
        }
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, DB_FILE)
        logger.info("💾 Data disimpan ke fail tempatan JSON.")
    except Exception as e:
        logger.error(f"⚠️ Gagal simpan data tempatan: {e}")
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except OSError:
            pass


async def backup_to_channel(context: ContextTypes.DEFAULT_TYPE):
    global pinned_index_message_id
    if not listings_db:
        logger.warning("🛑 BACKUP DIBATALKAN: listings_db kosong.")
        return False
    
    save_data()
    try:
        payload = {
            "version": 1,
            "saved_at": datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).isoformat(),
            "total_listings": len(listings_db),
            "listings": listings_db,
            "pinned_index_message_id": pinned_index_message_id,
        }
        data_to_send = json.dumps(payload, ensure_ascii=False, indent=4).encode("utf-8")
        file_doc = io.BytesIO(data_to_send)
        file_doc.name = DB_FILE

        chat = await context.bot.get_chat(chat_id=BACKUP_CHANNEL_ID)
        old_pinned_message = getattr(chat, "pinned_message", None)
        old_pinned_id = old_pinned_message.message_id if old_pinned_message else None

        # Kapsyen ringkas tanpa sebarang emoji supaya mudah dibaca dan tidak mengelirukan bot
        simple_caption = (
            f"Auto-Backup Listing Data (Terkini)\n"
            f"Tarikh: {payload['saved_at']}\n"
            f"Jumlah Listing: {len(listings_db)}"
        )

        sent_backup = await context.bot.send_document(
            chat_id=BACKUP_CHANNEL_ID,
            document=file_doc,
            caption=simple_caption
        )

        if not sent_backup or not sent_backup.message_id:
            logger.error("⚠️ Gagal menghantar dokumen backup ke channel Telegram.")
            return False

        await context.bot.pin_chat_message(
            chat_id=BACKUP_CHANNEL_ID,
            message_id=sent_backup.message_id,
            disable_notification=True,
        )
        logger.info(f"☁️ BACKUP OK: Mesej #{sent_backup.message_id} berjaya dihantar dan dipin.")

        if old_pinned_id and old_pinned_id != sent_backup.message_id:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=BACKUP_CHANNEL_ID,
                    message_id=old_pinned_id
                )
            except Exception as unpin_err:
                logger.warning(f"⚠️ Gagal unpin backup lama: {unpin_err}")

        return True
    except Exception as e:
        logger.error(f"⚠️ Gagal proses backup ke Telegram Channel: {e}")
        return False

def get_next_listing_id():
    if not listings_db:
        return 1
    return max(listings_db.keys()) + 1

async def reindex_listings():
    global listings_db
    sorted_items = sorted(listings_db.items(), key=lambda x: x[0])
    new_db = {}
    for new_id, (old_id, data) in enumerate(sorted_items, start=1):
        new_db[new_id] = data
    listings_db = new_db

async def update_index_page(context: ContextTypes.DEFAULT_TYPE):
    global pinned_index_message_id, restore_completed

    if not listings_db and not restore_completed:
        logger.error("Database kosong dan restore belum berjaya. Index kosong tidak diterbitkan.")
        return False

    try:
        malaysia_tz = ZoneInfo("Asia/Kuala_Lumpur")
        current_time = datetime.now(malaysia_tz).strftime('%d/%m/%Y %I:%M %p')
    except Exception:
        current_time = datetime.utcnow().strftime('%d/%m/%Y %I:%M %p')

    index_text = f"🏠 **SENARAI UTAMA LISTING HARTANAH** 🏠\n🕒 *Last Updated: {current_time}*\n\n"

    if not listings_db:
        index_text += "⚠️ *Tiada listing aktif buat masa ini.*"
    else:
        for l_id in sorted(listings_db.keys()):
            data = listings_db[l_id]
            status_val = data.get('status', 'ACTIVE')
            status_str = ""
            if status_val == "BOOKED":
                status_str = " [BOOKED]"
            elif status_val == "SOLD":
                status_str = " [SOLD]"

            group_msg_ids = data.get('group_message_ids', [])
            link_text = "Tiada pautan"
            if group_msg_ids:
                first_msg_id = group_msg_ids[0]
                clean_chat_id = str(GROUP_CHAT_ID).replace("-100", "")
                link_text = f"https://t.me/c/{clean_chat_id}/{first_msg_id}"

            price_display = data.get('price', '')
            price_line = f"   {price_display}\n" if price_display else ""

            index_text += (
                f"🔹 **ID #{l_id}** | {data['title']}{status_str}\n"
                f"{price_line}"
                f"   🔗 {link_text}\n"
                f"-----------------------------------\n"
            )

    try:
        old_pinned_id = pinned_index_message_id

        sent_msg = await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=index_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        pinned_index_message_id = sent_msg.message_id
        save_data()
        await backup_to_channel(context)
        
        try:
            await context.bot.pin_chat_message(
                chat_id=GROUP_CHAT_ID,
                message_id=pinned_index_message_id
            )
        except Exception as e:
            logger.warning(f"Nota pin mesej index: {e}")

        if old_pinned_id and old_pinned_id != pinned_index_message_id:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=GROUP_CHAT_ID,
                    message_id=old_pinned_id
                )
                await context.bot.delete_message(
                    chat_id=GROUP_CHAT_ID,
                    message_id=old_pinned_id
                )
            except Exception as unpin_err:
                logger.warning(f"Nota unpin/padam index lama: {unpin_err}")

        return True
    except Exception as e:
        logger.error(f"❌ Ralat kritikal kemaskini index: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("➕ Tambah Listing Baru", callback_data="add_listing")],
        [InlineKeyboardButton("✏️ Kemaskini Harga", callback_data="edit_price_menu")],
        [InlineKeyboardButton("📝 Kemaskini Description", callback_data="edit_desc_menu")],
        [InlineKeyboardButton("🏷️ Set Status", callback_data="set_status")],
        [InlineKeyboardButton("🗑️ Padam Listing", callback_data="delete_listing")],
        [InlineKeyboardButton("📢 Refresh Index", callback_data="refresh_index")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🏠 **Sistem Pengurusan Listing Hartanah**\n\nPilih tindakan di bawah:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "add_listing":
        context.user_data['state'] = 'WAITING_FOR_LISTING_PHOTOS'
        context.user_data['temp_photos'] = []
        context.user_data['temp_caption'] = ''
        await query.message.reply_text(
            "📸 **Tambah Listing Baru:**\n"
            "Sila hantar gambar-gambar hartanah berserta **kapsyen (minima 3 baris)** pada gambar pertama, kemudian taip **DONE**."
        )
    elif data == "refresh_index":
        await refresh_index_handler(update, context)

    elif data == "edit_price_menu":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif.")
            return
        keyboard = [[InlineKeyboardButton(f"Harga #{l_id}: {d['title']}", callback_data=f"editprice_{l_id}")] for l_id, d in listings_db.items()]
        await query.message.reply_text("✏️ Pilih listing untuk dikemaskini harganya:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("editprice_"):
        l_id = int(data.split("_")[1])
        context.user_data['editing_id'] = l_id
        context.user_data['state'] = 'WAITING_FOR_NEW_PRICE'
        await query.message.reply_text(f"Sila taip harga baru untuk Listing #{l_id}:")

    elif data == "edit_desc_menu":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif.")
            return
        keyboard = [[InlineKeyboardButton(f"Desc #{l_id}: {d['title']}", callback_data=f"editdesc_{l_id}")] for l_id, d in listings_db.items()]
        await query.message.reply_text("📝 Pilih listing untuk dikemaskini description:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("editdesc_"):
        l_id = int(data.split("_")[1])
        context.user_data['editing_desc_id'] = l_id
        context.user_data['state'] = 'WAITING_FOR_NEW_DESC'
        await query.message.reply_text(f"📝 Sila hantar **description baru** untuk Listing #{l_id}:")

    elif data == "set_status":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif.")
            return
        keyboard = [[InlineKeyboardButton(f"Status #{l_id}: {d['title']}", callback_data=f"status_{l_id}")] for l_id, d in listings_db.items()]
        await query.message.reply_text("🏷️ Pilih listing untuk dikemaskini status:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("status_"):
        l_id = int(data.split("_")[1])
        context.user_data['status_id'] = l_id
        keyboard = [
            [InlineKeyboardButton("🟢 ACTIVE", callback_data=f"setstat_{l_id}_ACTIVE")],
            [InlineKeyboardButton("🟡 BOOKED", callback_data=f"setstat_{l_id}_BOOKED")],
            [InlineKeyboardButton("🔴 SOLD", callback_data=f"setstat_{l_id}_SOLD")]
        ]
        await query.message.reply_text(f"Pilih status baru untuk Listing #{l_id}:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("setstat_"):
        _, l_id_str, new_status = data.split("_")
        l_id = int(l_id_str)
        if l_id in listings_db:
            listings_db[l_id]['status'] = new_status
            await update_index_page(context)
            
            group_msg_ids = listings_db[l_id].get('group_message_ids', [])
            if len(group_msg_ids) > 1:
                desc_msg_id = group_msg_ids[-1]
                d_item = listings_db[l_id]
                status_str = f" - *[{new_status}]*" if new_status != "ACTIVE" else ""
                price_txt = f"💰 **{d_item['price']}**\n\n" if d_item.get('price') else ""
                updated_desc_message = (
                    f"📄 **MAKLUMAT LANJUT (ID #{l_id})**{status_str}\n\n"
                    f"📍 **{d_item['title']}**\n"
                    f"{price_txt}"
                    f"{d_item['desc']}"
                )
                try:
                    read_opts = {"read_timeout": 60.0, "write_timeout": 60.0, "connect_timeout": 60.0}
                    await context.bot.edit_message_text(
                        chat_id=GROUP_CHAT_ID,
                        message_id=desc_msg_id,
                        text=updated_desc_message,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                        **read_opts
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Gagal edit mesej group: {e}")

            await query.message.reply_text(f"✅ Status Listing #{l_id} ditukar kepada {new_status}!")

    elif data == "delete_listing":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif.")
            return
        keyboard = [[InlineKeyboardButton(f"Padam #{l_id}: {d['title']}", callback_data=f"del_{l_id}")] for l_id, d in listings_db.items()]
        await query.message.reply_text("🗑️ Pilih listing untuk dipadam:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("del_"):
        l_id = int(data.split("_")[1])
        if l_id in listings_db:
            backup_before_delete = listings_db.copy()
            
            try:
                for msg_id in listings_db[l_id].get('group_message_ids', []):
                    try:
                        await context.bot.delete_message(chat_id=GROUP_CHAT_ID, message_id=msg_id)
                    except:
                        pass
                
                listings_db.pop(l_id, None)
                await reindex_listings()
                
                success = await update_index_page(context)
                if not success:
                    raise RuntimeError("Kemaskini index gagal selepas padam.")

                await query.message.reply_text(f"✅ Listing #{l_id} dipadam dan ID disusun semula!")
            except Exception as e:
                logger.error(f"❌ Ralat semasa memadam listing: {e}")
                listings_db = backup_before_delete
                await query.message.reply_text("❌ Ralat berlaku semasa kemas kini. Tindakan dipadam dibatalkan.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')

    if state == 'WAITING_FOR_NEW_PRICE':
        if not update.message.text:
            await update.message.reply_text("⚠️ Sila hantar teks harga sahaja.")
            return
            
        new_price = update.message.text.strip()
        l_id = context.user_data.get('editing_id')
        if l_id in listings_db:
            listings_db[l_id]['price'] = new_price
            await update_index_page(context)
            
            group_msg_ids = listings_db[l_id].get('group_message_ids', [])
            if len(group_msg_ids) > 1:
                desc_msg_id = group_msg_ids[-1]
                d_item = listings_db[l_id]
                status_val = d_item.get('status', 'ACTIVE')
                status_str = f" - *[{status_val}]*" if status_val != "ACTIVE" else ""
                price_txt = f"💰 **{d_item['price']}**\n\n" if d_item.get('price') else ""
                
                updated_desc_message = (
                    f"📄 **MAKLUMAT LANJUT (ID #{l_id})**{status_str}\n\n"
                    f"📍 **{d_item['title']}**\n"
                    f"{price_txt}"
                    f"{d_item['desc']}"
                )
                try:
                    read_opts = {"read_timeout": 60.0, "write_timeout": 60.0, "connect_timeout": 60.0}
                    await context.bot.edit_message_text(
                        chat_id=GROUP_CHAT_ID,
                        message_id=desc_msg_id,
                        text=updated_desc_message,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                        **read_opts
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Gagal edit harga di group: {e}")

            context.user_data.clear()
            await update.message.reply_text(f"✅ Harga Listing #{l_id} dikemaskini!")
        return

    elif state == 'WAITING_FOR_NEW_DESC':
        new_desc = None
        if update.message.text:
            new_desc = update.message.text.strip()
        elif update.message.caption:
            new_desc = update.message.caption.strip()

        if not new_desc:
            await update.message.reply_text("⚠️ Tiada teks atau kapsyen dikesan.")
            return

        l_id = context.user_data.get('editing_desc_id')
        if l_id in listings_db:
            listings_db[l_id]['desc'] = new_desc
            await update_index_page(context)
            
            group_msg_ids = listings_db[l_id].get('group_message_ids', [])
            if len(group_msg_ids) > 1:
                desc_msg_id = group_msg_ids[-1]
                d_item = listings_db[l_id]
                status_val = d_item.get('status', 'ACTIVE')
                status_str = f" - *[{status_val}]*" if status_val != "ACTIVE" else ""
                price_txt = f"💰 **{d_item['price']}**\n\n" if d_item.get('price') else ""
                
                updated_desc_message = (
                    f"📄 **MAKLUMAT LANJUT (ID #{l_id})**{status_str}\n\n"
                    f"📍 **{d_item['title']}**\n"
                    f"{price_txt}"
                    f"{new_desc}"
                )
                try:
                    read_opts = {"read_timeout": 60.0, "write_timeout": 60.0, "connect_timeout": 60.0}
                    await context.bot.edit_message_text(
                        chat_id=GROUP_CHAT_ID,
                        message_id=desc_msg_id,
                        text=updated_desc_message,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                        **read_opts
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Gagal edit description di group: {e}")

            context.user_data.clear()
            await update.message.reply_text(f"✅ Description Listing #{l_id} dikemaskini!")
        return

    elif state == 'WAITING_FOR_LISTING_PHOTOS':
        if update.message.photo:
            photo_file_id = update.message.photo[-1].file_id
            context.user_data['temp_photos'].append(photo_file_id)

            if update.message.caption and not context.user_data.get('temp_caption'):
                context.user_data['temp_caption'] = update.message.caption

            await update.message.reply_text(
                f"📸 Gambar diterima! (Jumlah: {len(context.user_data['temp_photos'])}).\n"
                f"Hantar lagi gambar atau taip **DONE**."
            )
            return

        if update.message.text:
            text_input = update.message.text.strip().upper()
            
            if text_input == "DONE":
                photos = context.user_data.get('temp_photos', [])
                caption_text = context.user_data.get('temp_caption', '')

                if not photos:
                    await update.message.reply_text("⚠️ Tiada gambar dikesan.")
                    return

                if not caption_text:
                    await update.message.reply_text("⚠️ Sila pastikan gambar pertama mempunyai kapsyen.")
                    return

                lines = caption_text.split('\n')
                if len(lines) >= 3:
                    title = lines[0].strip()
                    price = lines[1].strip()
                    desc = "\n".join(lines[2:]).strip()
                    saved_id = get_next_listing_id()

                    short_media_caption = (
                        f"📢 **NEW LISTING!** (ID #{saved_id})\n"
                        f"📍 **{title}**\n"
                        f"💰 Harga/Sewa: {price}\n"
                        f"*(Maklumat lanjut di bawah 👇)*"
                    )

                    full_desc_message = (
                        f"📄 **MAKLUMAT LANJUT (ID #{saved_id})**\n\n"
                        f"📍 **{title}**\n"
                        f"💰 **{price}**\n\n"
                        f"{desc}"
                    )

                    group_message_ids = []
                    try:
                        read_opts = {"read_timeout": 60.0, "write_timeout": 60.0, "connect_timeout": 60.0}

                        if len(photos) > 1:
                            media_list = [InputMediaPhoto(media=photos[0], caption=short_media_caption, parse_mode="Markdown")]
                            for p_id in photos[1:]:
                                media_list.append(InputMediaPhoto(media=p_id))
                            
                            sent_msgs = await context.bot.send_media_group(chat_id=GROUP_CHAT_ID, media=media_list, **read_opts)
                            for msg in sent_msgs:
                                group_message_ids.append(msg.message_id)
                        else:
                            sent_msg = await context.bot.send_photo(
                                chat_id=GROUP_CHAT_ID,
                                photo=photos[0],
                                caption=short_media_caption,
                                parse_mode="Markdown",
                                **read_opts
                            )
                            group_message_ids.append(sent_msg.message_id)

                        desc_sent_msg = await context.bot.send_message(
                            chat_id=GROUP_CHAT_ID,
                            text=full_desc_message,
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                            **read_opts
                        )
                        group_message_ids.append(desc_sent_msg.message_id)

                    except Exception as e:
                        logger.error(f"❌ Ralat hantar ke group: {e}")
                        await update.message.reply_text(f"❌ Ralat teknikal: {e}")
                        return

                    listings_db[saved_id] = {
                        "photos": photos,
                        "title": title,
                        "price": price,
                        "desc": desc,
                        "status": "ACTIVE",
                        "group_message_ids": group_message_ids
                    }

                    context.user_data.clear()
                    await update_index_page(context)
                    await update.message.reply_text(f"✅ Listing #{saved_id} berjaya disimpan dan di-backup!")
                else:
                    await update.message.reply_text("⚠️ Format kapsyen perlukan sekurang-kurangnya 3 baris.")
            else:
                if not context.user_data.get('temp_caption'):
                    context.user_data['temp_caption'] = update.message.text
                    await update.message.reply_text("📝 Kapsyen diterima! Sekarang hantar gambar atau taip **DONE**.")
                else:
                    await update.message.reply_text("Sila hantar gambar seterusnya atau taip **DONE**.")
    else:
        await update.message.reply_text("Sila hantar /start untuk membuka semula menu utama.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    logger.error(f"❌ BOT ERROR: {type(error).__name__}: {error}")
    try:
        from telegram.error import Conflict
        if isinstance(error, Conflict):
            logger.critical(
                "🛑 TELEGRAM 409 CONFLICT: Lebih daripada satu instance bot sedang aktif menggunakan token yang sama! "
                "Sila pastikan tiada bot berjalan secara lokal dan pastikan Render hanya menjalankan SATU instance."
            )
    except Exception:
        pass

def main():
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()

    if not API_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum ditetapkan dalam Environment Variables.")

    app = Application.builder().token(API_TOKEN).post_init(load_data_from_channel).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot Hartanah sedang berjalan.")
    app.run_polling(drop_pending_updates=False)

if __name__ == '__main__':
    main()
