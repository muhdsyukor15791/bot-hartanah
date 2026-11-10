import logging
import json
import os
import threading
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
# ⚠️ PASTIKAN TOKEN DAN CHAT ID GROUP ANDA BETUL DI SINI:
API_TOKEN = '8924536875:AAHOATpmmc6l-zJV8efdI5TLaedk7GCnbho'
GROUP_CHAT_ID = -1003288686118  # Tukar kepada ID Group anda (biasanya nombor negatif bermula dengan -100)
DB_FILE = 'listings_data.json'
# -------------------------------------------------------------

listings_db = {}
pinned_index_message_id = None

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- SERVER WEB MINI UNTUK RENDER PORT BINDING ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Hartanah is alive!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()
# -------------------------------------------------

def load_data():
    global listings_db, pinned_index_message_id
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                data = json.load(f)
                listings_db = {int(k): v for k, v in data.get('listings', {}).items()}
                pinned_index_message_id = data.get('pinned_index_message_id')
                print(f"✅ Data berjaya dimuatkan: {len(listings_db)} listing dijumpai.")
        except Exception as e:
            print(f"⚠️ Gagal membaca fail database: {e}")
            listings_db = {}
    else:
        listings_db = {}

def save_data():
    try:
        with open(DB_FILE, 'w') as f:
            json.dump({
                'listings': listings_db,
                'pinned_index_message_id': pinned_index_message_id
            }, f, indent=4)
            print("💾 Data berjaya disimpan ke fail JSON.")
    except Exception as e:
        print(f"⚠️ Gagal menyimpan data: {e}")

def get_next_listing_id():
    if not listings_db:
        return 1
    existing_ids = sorted(listings_db.keys())
    expected_id = 1
    for l_id in existing_ids:
        if l_id == expected_id:
            expected_id += 1
        else:
            break
    return expected_id


async def update_index_page(context: ContextTypes.DEFAULT_TYPE):
    """Fungsi untuk bina dan kemaskini senarai Main Page (Index) di Group"""
    global pinned_index_message_id

    index_text = "🏠 **SENARAI UTAMA LISTING HARTANAH** 🏠\n\n"

    if not listings_db:
        index_text += "⚠️ *Tiada listing aktif buat masa ini.*"
    else:
        for l_id in sorted(listings_db.keys()):
            data = listings_db[l_id]
            status_val = data.get('status', 'ACTIVE')
            status_icon = "🟢"
            if status_val == "BOOKED":
                status_icon = "🟡 [BOOKED]"
            elif status_val == "SOLD":
                status_icon = "🔴 [SOLD]"

            # Bina pautan terus ke mesej posting dalam group
            group_msg_ids = data.get('group_message_ids', [])
            link_text = "Tiada pautan"
            if group_msg_ids:
                first_msg_id = group_msg_ids[0]
                # Tukar ID group (cth: -1001234567890 -> 1234567890) untuk pautan t.me
                clean_chat_id = str(GROUP_CHAT_ID).replace("-100", "")
                link_text = f"https://t.me/c/{clean_chat_id}/{first_msg_id}"

            # Baris 1: Tajuk & Harga (Maintain), Baris 2: Hanya link message tanpa emoji
            index_text += (
                f"🔹 **ID #{l_id}** | {data['title']}\n"
                f"   💰 {data['price']} {status_icon}\n"
                f"   🔗 {link_text}\n"
                f"-----------------------------------\n"
            )

    try:
        if pinned_index_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=GROUP_CHAT_ID,
                    message_id=pinned_index_message_id,
                    text=index_text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                save_data()
                return True
            except Exception:
                pinned_index_message_id = None

        sent_msg = await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=index_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        pinned_index_message_id = sent_msg.message_id
        save_data()
        
        try:
            await context.bot.pin_chat_message(
                chat_id=GROUP_CHAT_ID,
                message_id=pinned_index_message_id
            )
        except Exception as e:
            print(f"Nota: Gagal pin mesej index: {e}")

        return True
    except Exception as e:
        print(f"Gagal kemaskini Main Page index di group: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Tambah Listing Baru", callback_data="add_listing")],
        [InlineKeyboardButton("✏️ Kemaskini Harga & Notify", callback_data="edit_listing")],
        [InlineKeyboardButton("🏷️ Set Status (Booked/Sold)", callback_data="set_status")],
        [InlineKeyboardButton("🗑️ Padam Listing", callback_data="delete_listing")],
        [InlineKeyboardButton("📢 Refresh Main Page / Index", callback_data="refresh_index")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🏠 **Sistem Pengurusan Listing Hartanah**\n\nSila pilih tindakan di bawah:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "add_listing":
        context.user_data['state'] = 'WAITING_FOR_LISTING_PHOTOS'
        context.user_data['temp_photos'] = []
        await query.message.reply_text(
            "📸 **Langkah Tambah Listing (Multi-Gambar):**\n"
            "Sila **pilih dan hantar beberapa gambar sekaligus** (atau hantar satu persatu, kemudian taip 'DONE').\n"
            "Pastikan anda letakkan **kapsyen (3 baris)** pada gambar pertama:\n\n"
            "Baris 1: Tajuk / Lokasi\n"
            "Baris 2: Harga / Kadar Sewa\n"
            "Baris 3: Keterangan ringkas"
        )

    elif query.data == "edit_listing":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif untuk dikemaskini.")
            return
        
        keyboard = []
        for l_id in sorted(listings_db.keys()):
            data = listings_db[l_id]
            btn_text = f"Edit #{l_id}: {data['title']} (Semasa: {data['price']})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"edit_{l_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("✏️ Pilih listing yang hendak dikemaskini harganya:", reply_markup=reply_markup)

    elif query.data.startswith("edit_"):
        l_id = int(query.data.split("_")[1])
        context.user_data['editing_id'] = l_id
        context.user_data['state'] = 'WAITING_FOR_NEW_PRICE'
        
        current_price = listings_db[l_id]['price']
        await query.message.reply_text(
            f"💰 Harga/Sewa semasa bagi **Listing #{l_id}** ialah: `{current_price}`\n\n"
            f"Sila taip **HARGA BARU** (contoh: `RM 1,200/bulan (HARGA TURUN!)`):"
        )

    elif query.data == "set_status":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif untuk dikemaskini statusnya.")
            return
        
        keyboard = []
        for l_id in sorted(listings_db.keys()):
            data = listings_db[l_id]
            btn_text = f"Status #{l_id}: {data['title']} [{data.get('status', 'ACTIVE')}]"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"status_{l_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("🏷️ Pilih listing untuk dikemaskini status:", reply_markup=reply_markup)

    elif query.data.startswith("status_"):
        l_id = int(query.data.split("_")[1])
        
        keyboard = [
            [InlineKeyboardButton("🟢 ACTIVE (Kemas Kini Semula)", callback_data=f"stval_{l_id}_ACTIVE")],
            [InlineKeyboardButton("🟡 BOOKED (Sudah Ditempah)", callback_data=f"stval_{l_id}_BOOKED")],
            [InlineKeyboardButton("🔴 SOLD / RENTED (Sudah Selesai)", callback_data=f"stval_{l_id}_SOLD")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"📌 Pilih status baru untuk **Listing #{l_id}**:", reply_markup=reply_markup)

    elif query.data.startswith("stval_"):
        parts = query.data.split("_")
        l_id = int(parts[1])
        new_status = parts[2]
        
        if l_id in listings_db:
            listings_db[l_id]['status'] = new_status
            save_data()
            await update_index_page(context)
            await query.message.reply_text(f"✅ Status bagi **Listing #{l_id}** telah ditukar kepada `{new_status}` dan Main Page telah dikemaskini!")

    elif query.data == "refresh_index":
        success = await update_index_page(context)
        if success:
            await query.message.reply_text("✅ Main Page / Index telah berjaya disegarkan (refreshed) di group!")
        else:
            await query.message.reply_text("❌ Gagal menyegarkan Main Page. Pastikan bot adalah Admin group.")

    elif query.data == "delete_listing":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif buat masa ini.")
            return
        
        keyboard = []
        for l_id in sorted(listings_db.keys()):
            data = listings_db[l_id]
            btn_text = f"Padam #{l_id}: {data['title']} ({data['price']})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"del_{l_id}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("🗑️ Pilih listing yang hendak dipadam:", reply_markup=reply_markup)

    elif query.data.startswith("del_"):
        l_id = int(query.data.split("_")[1])
        if l_id in listings_db:
            deleted_title = listings_db[l_id]['title']
            
            for msg_id in listings_db[l_id].get('group_message_ids', []):
                try:
                    await context.bot.delete_message(chat_id=GROUP_CHAT_ID, message_id=msg_id)
                except Exception as e:
                    print(f"Nota: Gagal padam mesej dari group: {e}")

            del listings_db[l_id]
            save_data()
            await update_index_page(context)

            await query.message.reply_text(f"✅ Listing #{l_id} ({deleted_title}) telah dipadam dari sistem dan Main Page!")
        else:
            await query.message.reply_text("⚠️ Listing tidak dijumpai.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')

    if state == 'WAITING_FOR_LISTING_PHOTOS':
        if update.message.photo:
            photo_file_id = update.message.photo[-1].file_id
            context.user_data['temp_photos'].append(photo_file_id)

            if update.message.caption:
                context.user_data['temp_caption'] = update.message.caption

            await update.message.reply_text(
                f"📸 Gambar diterima! (Jumlah terkumpul: {len(context.user_data['temp_photos'])} gambar).\n"
                f"Sila hantar lagi gambar lain, atau taip **DONE** jika sudah selesai."
            )
        elif update.message.text:
            text_input = update.message.text.strip().upper()
            if text_input == "DONE":
                photos = context.user_data.get('temp_photos', [])
                caption_text = context.user_data.get('temp_caption', '')

                if not photos:
                    await update.message.reply_text("⚠️ Anda belum menghantar sebarang gambar. Sila hantar sekurang-kurangnya satu gambar.")
                    return

                if not caption_text:
                    await update.message.reply_text("⚠️ Anda belum menyertakan kapsyen (3 baris) pada gambar. Sila hantar semula gambar berserta kapsyen.")
                    context.user_data['temp_photos'] = []
                    return

                lines = caption_text.split('\n')
                if len(lines) >= 3:
                    title = lines[0].strip()
                    price = lines[1].strip()
                    desc = "\n".join(lines[2:]).strip()

                    saved_id = get_next_listing_id()

                    group_caption = (
                        f"📢 **NEW LISTING!** (ID #{saved_id})\n\n"
                        f"📍 **{title}**\n"
                        f"💰 Harga/Sewa: {price}\n"
                        f"📄 Info: {desc}"
                    )

                    group_message_ids = []
                    try:
                        if len(photos) > 1:
                            media_list = [InputMediaPhoto(media=photos[0], caption=group_caption, parse_mode="Markdown")]
                            for p_id in photos[1:]:
                                media_list.append(InputMediaPhoto(media=p_id))
                            
                            sent_msgs = await context.bot.send_media_group(chat_id=GROUP_CHAT_ID, media=media_list)
                            for msg in sent_msgs:
                                group_message_ids.append(msg.message_id)
                        else:
                            sent_msg = await context.bot.send_photo(
                                chat_id=GROUP_CHAT_ID,
                                photo=photos[0],
                                caption=group_caption,
                                parse_mode="Markdown"
                            )
                            group_message_ids.append(sent_msg.message_id)
                    except Exception as e:
                        print(f"Gagal hantar album ke group: {e}")

                    listings_db[saved_id] = {
                        "photos": photos,
                        "title": title,
                        "price": price,
                        "desc": desc,
                        "status": "ACTIVE",
                        "group_message_ids": group_message_ids
                    }

                    save_data()

                    context.user_data['state'] = None
                    context.user_data['temp_photos'] = []
                    context.user_data['temp_caption'] = ''

                    await update_index_page(context)

                    await update.message.reply_text(
                        f"✅ Listing berjaya disimpan sebagai **ID #{saved_id}** dengan {len(photos)} gambar!\n"
                        f"*(Album telah dihantar ke Group dan data telah disimpan secara kekal).* \n\n"
                        f"Taip /start untuk kembali ke menu utama."
                    )
                else:
                    await update.message.reply_text("⚠️ Format kapsyen salah. Pastikan sekurang-kurangnya 3 baris.")

    elif state == 'WAITING_FOR_NEW_PRICE':
        new_price = update.message.text.strip()
        l_id = context.user_data.get('editing_id')

        if l_id in listings_db:
            listings_db[l_id]['price'] = new_price
            save_data()
            await update_index_page(context)

            context.user_data['state'] = None
            context.user_data['editing_id'] = None

            await update.message.reply_text(
                f"✅ Harga bagi **Listing #{l_id}** berjaya dikemaskini dan Main Page telah diselaraskan!\n\n"
                f"Taip /start kembali ke menu utama."
            )

def main():
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()

    load_data()
    app = Application.builder().token(API_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot Hartanah (Cloud 24/7) sedang berjalan...")
    app.run_polling()

if __name__ == '__main__':
    main()
