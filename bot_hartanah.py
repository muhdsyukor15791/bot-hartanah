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
API_TOKEN = (
    "8924536875:"
    "AAHOATpmmc6l-"
    "zJV8efdI5TLaedk7GCnbho"
)
GROUP_CHAT_ID = -1003288686118  # Nombor ID Group yang sah
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
                raw_listings = data.get('listings', {})
                listings_db = {}
                for idx, (old_key, val) in enumerate(sorted(raw_listings.items(), key=lambda x: int(x[0])), start=1):
                    listings_db[idx] = val
                    
                pinned_index_message_id = data.get('pinned_index_message_id')
                print(f"✅ Data dimuatkan & dinomborkan semula: {len(listings_db)} listing.")
        except Exception as e:
            print(f"⚠️ Gagal baca DB: {e}")
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
            print("💾 Data disimpan ke JSON.")
    except Exception as e:
        print(f"⚠️ Gagal simpan data: {e}")

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

            group_msg_ids = data.get('group_message_ids', [])
            link_text = "Tiada pautan"
            if group_msg_ids:
                first_msg_id = group_msg_ids[0]
                clean_chat_id = str(GROUP_CHAT_ID).replace("-100", "")
                link_text = f"https://t.me/c/{clean_chat_id}/{first_msg_id}"

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
            except Exception as edit_err:
                print(f"⚠️ Tidak dapat edit mesej index lama: {edit_err}")
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
            print(f"⚠️ Nota pin mesej index: {e}")

        return True
    except Exception as e:
        print(f"❌ Ralat kritikal kemaskini index: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['state'] = None
    keyboard = [
        [InlineKeyboardButton("➕ Tambah Listing Baru", callback_data="add_listing")],
        [InlineKeyboardButton("✏️ Kemaskini Harga", callback_data="edit_listing")],
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

    if query.data == "add_listing":
        context.user_data['state'] = 'WAITING_FOR_LISTING_PHOTOS'
        context.user_data['temp_photos'] = []
        context.user_data['temp_caption'] = ''
        await query.message.reply_text(
            "📸 **Tambah Listing Baru:**\n"
            "Sila hantar gambar-gambar hartanah berserta **kapsyen (minima 3 baris)** pada gambar pertama, kemudian taip **DONE**."
        )
    elif query.data == "refresh_index":
        success = await update_index_page(context)
        if success:
            await query.message.reply_text("✅ Index berjaya disegarkan!")
        else:
            await query.message.reply_text("❌ Gagal segarkan index.")
    elif query.data == "edit_listing":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif.")
            return
        keyboard = [[InlineKeyboardButton(f"Edit #{l_id}: {d['title']}", callback_data=f"edit_{l_id}")] for l_id, d in listings_db.items()]
        await query.message.reply_text("✏️ Pilih listing untuk dikemaskini harganya:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data.startswith("edit_") and not query.data.startswith("editdesc_"):
        l_id = int(query.data.split("_")[1])
        context.user_data['editing_id'] = l_id
        context.user_data['state'] = 'WAITING_FOR_NEW_PRICE'
        await query.message.reply_text(f"Sila taip harga baru untuk Listing #{l_id}:")
    elif query.data == "edit_desc_menu":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif.")
            return
        keyboard = [[InlineKeyboardButton(f"Desc #{l_id}: {d['title']}", callback_data=f"editdesc_{l_id}")] for l_id, d in listings_db.items()]
        await query.message.reply_text("📝 Pilih listing untuk dikemaskini description:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data.startswith("editdesc_"):
        l_id = int(query.data.split("_")[1])
        context.user_data['editing_desc_id'] = l_id
        context.user_data['state'] = 'WAITING_FOR_NEW_DESC'
        await query.message.reply_text(f"Sila hantar **description baru** untuk Listing #{l_id}:")
    elif query.data == "set_status":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif.")
            return
        keyboard = [[InlineKeyboardButton(f"Status #{l_id}: {d['title']}", callback_data=f"status_{l_id}")] for l_id, d in listings_db.items()]
        await query.message.reply_text("🏷️ Pilih listing untuk dikemaskini status:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data.startswith("status_"):
        l_id = int(query.data.split("_")[1])
        context.user_data['status_id'] = l_id
        keyboard = [
            [InlineKeyboardButton("🟢 ACTIVE", callback_data=f"setstat_{l_id}_ACTIVE")],
            [InlineKeyboardButton("🟡 BOOKED", callback_data=f"setstat_{l_id}_BOOKED")],
            [InlineKeyboardButton("🔴 SOLD", callback_data=f"setstat_{l_id}_SOLD")]
        ]
        await query.message.reply_text(f"Pilih status baru untuk Listing #{l_id}:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data.startswith("setstat_"):
        _, l_id_str, new_status = query.data.split("_")
        l_id = int(l_id_str)
        if l_id in listings_db:
            listings_db[l_id]['status'] = new_status
            save_data()
            await update_index_page(context)
            
            group_msg_ids = listings_db[l_id].get('group_message_ids', [])
            if len(group_msg_ids) > 1:
                desc_msg_id = group_msg_ids[-1]
                data = listings_db[l_id]
                status_str = f" - *[{new_status}]*" if new_status != "ACTIVE" else ""
                updated_desc_message = (
                    f"📄 **MAKLUMAT LANJUT (ID #{l_id})**{status_str}\n\n"
                    f"📍 **{data['title']}**\n"
                    f"💰 **{data['price']}**\n\n"
                    f"{data['desc']}"
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
                    print(f"⚠️ Gagal edit mesej group: {e}")

            await query.message.reply_text(f"✅ Status Listing #{l_id} telah ditukar kepada {new_status} dan dikemaskini di group!")
    elif query.data == "delete_listing":
        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing aktif.")
            return
        keyboard = [[InlineKeyboardButton(f"Padam #{l_id}: {d['title']}", callback_data=f"del_{l_id}")] for l_id, d in listings_db.items()]
        await query.message.reply_text("🗑️ Pilih listing untuk dipadam:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data.startswith("del_"):
        l_id = int(query.data.split("_")[1])
        if l_id in listings_db:
            for msg_id in listings_db[l_id].get('group_message_ids', []):
                try:
                    await context.bot.delete_message(chat_id=GROUP_CHAT_ID, message_id=msg_id)
                except:
                    pass
            
            listings_db.pop(l_id, None)
            await reindex_listings()
            save_data()
            await update_index_page(context)
            await query.message.reply_text(f"✅ Listing dipadam dan ID telah disusun semula secara automatik!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')

    if state == 'WAITING_FOR_NEW_PRICE':
        new_price = update.message.text.strip()
        l_id = context.user_data.get('editing_id')
        if l_id in listings_db:
            listings_db[l_id]['price'] = new_price
            save_data()
            await update_index_page(context)
            
            group_msg_ids = listings_db[l_id].get('group_message_ids', [])
            if len(group_msg_ids) > 1:
                desc_msg_id = group_msg_ids[-1]
                data = listings_db[l_id]
                status_val = data.get('status', 'ACTIVE')
                status_str = f" - *[{status_val}]*" if status_val != "ACTIVE" else ""
                
                updated_desc_message = (
                    f"📄 **MAKLUMAT LANJUT (ID #{l_id})**{status_str}\n\n"
                    f"📍 **{data['title']}**\n"
                    f"💰 **{data['price']}**\n\n"
                    f"{data['desc']}"
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
                    print(f"⚠️ Gagal edit mesej harga di group: {e}")

            context.user_data['state'] = None
            context.user_data['editing_id'] = None
            await update.message.reply_text(f"✅ Harga Listing #{l_id} berjaya dikemaskini di bot dan di dalam group!")
        return

    elif state == 'WAITING_FOR_NEW_DESC':
        new_desc = update.message.text.strip()
        l_id = context.user_data.get('editing_desc_id')
        if l_id in listings_db:
            listings_db[l_id]['desc'] = new_desc
            save_data()
            
            group_msg_ids = listings_db[l_id].get('group_message_ids', [])
            if len(group_msg_ids) > 1:
                desc_msg_id = group_msg_ids[-1]
                data = listings_db[l_id]
                status_val = data.get('status', 'ACTIVE')
                status_str = f" - *[{status_val}]*" if status_val != "ACTIVE" else ""
                
                updated_desc_message = (
                    f"📄 **MAKLUMAT LANJUT (ID #{l_id})**{status_str}\n\n"
                    f"📍 **{data['title']}**\n"
                    f"💰 **{data['price']}**\n\n"
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
                    print(f"⚠️ Gagal edit mesej description di group: {e}")

            context.user_data['state'] = None
            context.user_data['editing_desc_id'] = None
            await update.message.reply_text(f"✅ Description Listing #{l_id} berjaya dikemaskini secara live di group!")
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
                    await update.message.reply_text("⚠️ Tiada gambar dikesan. Sila hantar sekurang-kurangnya satu gambar.")
                    return

                if not caption_text:
                    await update.message.reply_text("⚠️ Sila pastikan gambar pertama anda mempunyai kapsyen.")
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

                        print("✅ Berjaya hantar media dan info penuh ke group!")
                    except Exception as e:
                        print(f"❌ Ralat hantar ke group: {e}")
                        await update.message.reply_text(f"❌ Ralat teknikal menghantar ke group: {e}")
                        return

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
                    await update.message.reply_text(f"✅ Listing #${saved_id} berjaya disimpan, dihantar ke group, dan index dikemas kini!")
                else:
                    await update.message.reply_text("⚠️ Format kapsyen perlukan sekurang-kurangnya 3 baris.")
            else:
                if not context.user_data.get('temp_caption'):
                    context.user_data['temp_caption'] = update.message.text
                    await update.message.reply_text("📝 Kapsyen diterima! Sekarang hantar gambar atau taip **DONE**.")
                else:
                    await update.message.reply_text("Sila hantar gambar seterusnya atau taip **DONE** untuk selesai.")
    else:
        await update.message.reply_text("Sila tekan /start untuk menggunakan menu utama.")

def main():
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()

    load_data()
    app = Application.builder().token(API_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot Hartanah sedang berjalan...")
    app.run_polling()

if __name__ == '__main__':
    main()
