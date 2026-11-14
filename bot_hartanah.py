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
# DATABASE (HARDCODED FALLBACK UNTUK 9 LISTING ANDA)
# =============================================================

listings_db = {
    1: {
        "photos": [
            "AgACAgUAAxkBAAOiavMFB08MUgHJkTIWiByrGvpzmucAArcVaxulsJhXkglu9VBbaOEBAAMCAAN4AAM9BA",
            "AgACAgUAAxkBAAOjavMFBwirSYZqmYu66dw0hdfbBvQAArgVaxulsJhXXb-Pb6Mb0jwBAAMCAAN4AAM9BA",
            "AgACAgUAAxkBAAOkavMFB1_R9ug5EzzFMZRZ8zYbU_0AArkVaxulsJhXGOE6Dumj7E8BAAMCAAN5AAM9BA",
            "AgACAgUAAxkBAAOlavMFByRR4cNtvmRTQ31QczIed6YAAroVaxulsJhXij0t65CU5AkBAAMCAAN4AAM9BA",
            "AgACAgUAAxkBAAOmavMFB9I2qXCa8vsvl0tKolXIVs4AArsVaxulsJhXVczPolVsYkIBAAMCAAN4AAM9BA"
        ],
        "title": "UNTUK DISEWA: RESIDENSI MIRAI, KAJANG 2",
        "price": "RM1,200 / bulan",
        "desc": "💰 Sewa: RM1,200 / bulan\n📏 Saiz Binaan: 578 kaki persegi\n🛏️ Layout: 2 Bilik Tidur | 1 Bilik Air\n🚗 Parkir: 1 Petak Tempat Letak Kereta\n🔑 Status Unit: Separa Berperabot\n📅 Kemasukan: Sedia Diduduki Segera\n#Sewa76",
        "status": "ACTIVE",
        "group_message_ids": [2662, 2663, 2664, 2665, 2666, 2667]
    },
    2: {
        "photos": [
            "AgACAgUAAxkBAAIBs2rzM-ci9zwhglf4emB81USd55kCAAI2FmsbpbCYVzL-DPUVkA8xAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIBtGrzM-etu4KOnJuvZERVYBVkJ32uAAI3FmsbpbCYV9GW1x2TSmitAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIBtWrzM-cKgwh_oEbnWEaRwMvb5D07AAI4FmsbpbCYV6HGTdJPz6ugAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIBtmrzM-e6og-AvOe1CAWj5WM0ojuIAAI5FmsbpbCYVyi_qq1csCz7AQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIBuWrzM-ctAk6RrqaB8SHUsjxMEj37AAI8FmsbpbCYV9U3CchYwDuAAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIBumrzM-eHPTg65eYKlEQJd75NzOtcAAI9FmsbpbCYV2ARUXxSp-L5AQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIBt2rzM-fZ-sjjvHIn9ERMLHsSaXH5AAI6FmsbpbCYV2hEnZNlp45SAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIBuGrzM-eSwU5jEh4_GjJmrpwGA6uRAAI7FmsbpbCYVz2ef6nD5yR8AQADAgADeAADPQQ"
        ],
        "title": "UNTUK DISEWA Villa Tropika Apartment, Kajang",
        "price": "RM1,100 / bulan",
        "desc": "(Level 6 dengan Lif)\nKeluasan: 870 sqft (3 Bilik, 2 Bilik Air)\nStatus: Partly Furnished (Gated & Guarded)\nSewa Bulanan: RM1,100\n#Sewa140",
        "status": "ACTIVE",
        "group_message_ids": [2670, 2671, 2672, 2673, 2674, 2675, 2676, 2677, 2678]
    },
    3: {
        "photos": [
            "AgACAgUAAxkBAAIB_2rzQB_HoqKvxiHDHgJEOQ3IvL-AAAJUFmsbpbCYV7hY1PWFKsYZAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAICAAFq80AffEiZTWr9X2mL6HdITNoQSwACWBZrG6WwmFekxRhik3eEKAEAAwIAA3gAAz0E",
            "AgACAgUAAxkBAAICAWrzQB8hyqlZo9_cbVDtddZOzmIuAAJZFmsbpbCYV6tj-V3_dmJCAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAICAmrzQB_qMVohU9HhPx1ZP_ppkidhAAJaFmsbpbCYV9ojUJ_lykdnAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAICA2rzQB-iZ65OqbUlg-QjFbJMW8SzAAJVFmsbpbCYV-_ko_RTJ7ryAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAICBGrzQB-fI7GcpiKPsJXFmb2vBhu2AAJWFmsbpbCYV7u6Ve_qwIS9AQADAgADeAADPQQ",
            "AgACAgUAAxkBAAICBWrzQB-oH-vQspMIqNe9geDSHoW-AAJbFmsbpbCYVzv-U0NDovZQAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAICBmrzQB-x72X7tN5GN6lkwLtxsL0oAAJXFmsbpbCYV63tp9SzkrGKAQADAgADeQADPQQ"
        ],
        "title": "UNTUK DISEWA: RESIDENSI EMAS, KAJANG 2",
        "price": "RM1,300 / bulan",
        "desc": "📌 Sewa: RM1,300 / bulan\n📐 Saiz: 930 kaki persegi\n🛏️ Layout: 4 Bilik Tidur | 3 Bilik Air\n#Sewa148",
        "status": "ACTIVE",
        "group_message_ids": [2681, 2682, 2683, 2684, 2685, 2686, 2687, 2688, 2689]
    },
    4: {
        "photos": [
            "AgACAgUAAxkBAAIC1Grzr0fG_052frLRuZ6RhEzFHqROAALcE2sbpbCgVzLpDBeiwTeFAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIC1Wrzr0fb7NQBa5yqsRcmQb6Dxx41AALdE2sbpbCgV3fTj5eszwXJAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIC1mrzr0dH1z5Jmmz__Y4uNd-0uow_AALeE2sbpbCgV-PW62CIaNjcAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIC12rzr0d2OjiECV1ZlKepdj2uGMtAAALfE2sbpbCgV1DEwt8T4I73AQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIC2Grzr0c4-OzrpZ2c2AphMnRfXrmpAALgE2sbpbCgV2KJW0fpEHB2AQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIC2Wrzr0fOS_cJoNzlN2KCTabDpm76AALhE2sbpbCgVy-7cAXCE1VbAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIC2mrzr0fMe0fUSFjz5uYpZNfq5od2AALiE2sbpbCgVxrFiINukd80AQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIC22rzr0eQ8m3EtzfM_1FqW9i7gi-3AALjE2sbpbCgV_LsobN88gZsAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIC3Grzr0eVkgIFKamDHWy8owrsSmJYAALkE2sbpbCgV362wBr-0J3HAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIC3mrzr0eDaoxpIhmxyFdEU8uDVyX7AALmE2sbpbCgVxM33lWUvtA1AQADAgADeAADPQQ"
        ],
        "title": "UNTUK DISEWA: RESIDENSI IDAMAN ABADI, KAJANG 2 | RM1,200",
        "price": "RM1,200 / bulan",
        "desc": "💰 Sewa: RM1,200 / bulan\n📐 Saiz: 1,022 sqft | 3 Bilik Tidur | 3 Bilik Air\n🚗 Keistimewaan: Lvl 16, Unit Corner + Ada Charger EV\n#Sewa139",
        "status": "ACTIVE",
        "group_message_ids": [2714, 2715, 2716, 2717, 2718, 2719, 2720, 2721, 2722, 2723, 2724]
    },
    5: {
        "photos": [
            "AgACAgUAAxkBAAIDImrzsf5O5-JesbEuMHkUCk4Ul3HPAALoE2sbpbCgV5Wr5TyolNBdAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDI2rzsf5c1jKKRh7qbcHaDKqZ3vprAALpE2sbpbCgVynyX_nWdlwlAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIDJGrzsf6D6jtKaA7mFjzLscagbIMWAALqE2sbpbCgV5pMHZbOfdkaAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDJWrzsf50gPPK6TUDdZeUaUIEvdlwAALrE2sbpbCgV72qWbo-q_ljAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIDJmrzsf7OW-K2O5OqcROfVsov4XkLAALsE2sbpbCgV8mFDIkl7xtJAQADAgADeAADPQQ"
        ],
        "title": "UNTUK DISEWA: CERRADO SUITES, SOUTHVILLE CITY | RM1,600",
        "price": "RM1,600 / bulan",
        "desc": "💰 Sewa: RM1,600/Bulanan\n📐 Layout: 2 Bilik Tidur & 1 Bilik Air\n🚗 Parkir: 2 Tempat Letak Kereta\n#Sewa155",
        "status": "ACTIVE",
        "group_message_ids": [2727, 2728, 2729, 2730, 2731, 2732]
    },
    6: {
        "photos": [
            "AgACAgUAAxkBAAIDQ2rzs6u64k_5iMgOKn5gPEpNfg5mAALvE2sbpbCgVxyfpE5opmCYAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDRGrzs6vEUmuJgqjPCUX9zlAPCRo3AALwE2sbpbCgV4K8jGP5oPB4AQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDRWrzs6umqk1YtfFtkZtmC8hA-AfOAALxE2sbpbCgV4dPukQHqWGIAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDRmrzs6uTsU4XWQPTKtulJD8d-TCMAALyE2sbpbCgVxdRWLD_Wr0TAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIDR2rzs6t7S689JlxXM1IR4vJLy80kAALzE2sbpbCgV-9bW3lWr1K7AQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDSGrzs6t82Rge74I9TF9wX5vvKp7KAAL0E2sbpbCgVw-fSPgagPSgAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDSWrzs6u4N9j8KCNrJ-p7fiAJyc0dAAL1E2sbpbCgVz9flO5WIqsrAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDSmrzs6vufPJJ1z0SBTzKbuxPHF1vAAL2E2sbpbCgV_jsZPsVyRgZAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIDS2rzs6shI2Xnv8TChLt6Fm6ulkDKAAL3E2sbpbCgV16_Nu-N2Fy4AQADAgADeAADPQQ"
        ],
        "title": "UNTUK DISEWA: APARTMENT KARISMA, ECO MAJESTIC, SEMENYIH | RM1,000",
        "price": "RM1,000 / bulan",
        "desc": "💰 Sewa: RM1,000 / bulan\n🛏️ Layout: 3 Bilik Tidur | 2 Bilik Air\n🚗 Parkir: 2 Tempat Letak Kereta\n#Sewa165",
        "status": "ACTIVE",
        "group_message_ids": [2735, 2736, 2737, 2738, 2739, 2740, 2741, 2742, 2743, 2744]
    },
    7: {
        "photos": [
            "AgACAgUAAxkBAAIDXWrztFv-H6T0fQfBMQzNV3ru3zVKAAL4E2sbpbCgV1-9OU3gjWtUAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDXmrztFsJ6RYKUni7t59t_utKrSsOAAL5E2sbpbCgV5s0O6ouYEo4AQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDX2rztFtGtZTZIbMO03MXyfZoAAGJXQAC-hNrG6WwoFdeR9Aiol9bMQEAAwIAA3gAAz0E",
            "AgACAgUAAxkBAAIDYGrztFtW7dNJo4BfQ4KW37UO7QABTAAC-xNrG6WwoFcLTheMXzga6QEAAwIAA3gAAz0E",
            "AgACAgUAAxkBAAIDYWrztFvydrmxwISR0HPzmQwNy5P9AAL8E2sbpbCgV8GV_QcX53dQAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDYmrztFt_o1ei8aKWcdPlPcnOEtSiAAL9E2sbpbCgV8Ka6SzwNjSfAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIDY2rztFu8OQfKDE0Qk88xFNG6zdaDAAL-E2sbpbCgV6gOsbMfsFbaAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDZGrztFuYN7Aqj4mk6YHiB7mcP9rBAAL_E2sbpbCgV8bGB5FZYpi-AQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDZWrztFtn5rBvD90LwzfWMiLo093ZAAMUaxulsKBXe1gOQU8R-zQBAAMCAAN5AAM9BA",
            "AgACAgUAAxkBAAIDZmrztFtbgbjfXLmyKRggd1KxpRWTAAIBFGsbpbCgVwNJR04DY07_AQADAgADeAADPQQ"
        ],
        "title": "UNTUK DISEWA: RESIDENSI IDAMAN ABADI, KAJANG 2 | RM1,400 (Partial Furnished)",
        "price": "RM1,400 / bulan",
        "desc": "💰 Sewa: RM1,400 / bulan\n🏠 Ciri Istimewa: Corner Unit (Partially Furnished)\n🚗 Parkir: 2 Petak Tempat Letak Kereta\n#Sewa166",
        "status": "ACTIVE",
        "group_message_ids": [2747, 2748, 2749, 2750, 2751, 2752, 2753, 2754, 2755, 2756, 2757]
    },
    8: {
        "photos": [
            "AgACAgUAAxkBAAIDemrztWRQzRhUtPFKEKNW2IbEHOEpAAICFGsbpbCgV4wWY5T9l0vVAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDe2rztWSmf-eEMUigU4rM_1aH9vmoAAIDFGsbpbCgV6LTRWTOePPIAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDfGrztWQIruBLF_TND-o-9UY29rInAAIEFGsbpbCgV94UbUvk_Th_AQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDfWrztWR_2NsNvk3Lx5ILWmwENrQ-AAIFFGsbpbCgV8c4-NTodK-FAQADAgADeQADPQQ",
            "AgACAgUAAxkBAAIDfmrztWQAAc8UNXnB--u0FKFGwLxlLgACBhRrG6WwoFfXtIYe_PCWogEAAwIAA3kAAz0E",
            "AgACAgUAAxkBAAIDf2rztWSvVeMI60Mgf5jZ8U7AimhRAAIHFGsbpbCgV7egsqgL8R8YAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDgGrztWSUx2GAyttFisUW-gUP8a63AAIIFGsbpbCgV6EW9wqVgcOVAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDgWrztWREFKxw8jkrL0qN1yaa8z4mAAIJFGsbpbCgV4vvtS10ympiAQADAgADeAADPQQ",
            "AgACAgUAAxkBAAIDgmrztWTZ-RhUREPOAAEiBdZSTz3IpAACChRrG6WwoFfQuf9G3vlwjwEAAwIAA3kAAz0E",
            "AgACAgUAAxkBAAIDg2rztWTS2APIB-SaX2OV9IfbeoteAAILFGsbpbCgV-wOvNpLonFBAQADAgADeAADPQQ"
        ],
        "title": "UNTUK DISEWA: RESIDENSI JED, KAJANG 2 | RM1,500",
        "price": "RM1,500 / bulan",
        "desc": "💰 Sewa: RM1,500 / bulan\n🏠 Ciri Istimewa: Rumah Baru | Corner Unit\n🛏️ 4 Bilik Tidur | 3 Bilik Mandi\n#Sewa167",
        "status": "ACTIVE",
        "group_message_ids": [2760, 2761, 2762, 2763, 2764, 2765, 2766, 2767, 2768, 2769, 2770]
    },
    9: {
        "photos": [],
        "title": "UNTUK DISEWA: CANOPY HILLS, KAJANG | RM1,300",
        "price": "RM1,300 / bulan",
        "desc": "💰 Sewa: RM1,300 / bulan\n🏢 Blok & Saiz: Blok A (590 Sqft)\n🛏️ Layout: 2 Bilik Tidur | 1 Bilik Air\n🚗 Parkir: 1 Petak Tempat Letak Kereta\n🔑 Status Unit: Fully Furnished\n#Id9",
        "status": "ACTIVE",
        "group_message_ids": []
    }
}

pinned_index_message_id = None
backup_pinned_message_id = None

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
            print("⚠️ Fail JSON tempatan tidak dijumpai. Mengekalkan database asas.")
            return False

        with open(DB_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        loaded_db = validate_database(
            data.get("listings", {})
        )

        if loaded_db:
            listings_db = loaded_db
            pinned_index_message_id = data.get("pinned_index_message_id")
            print(f"✅ Local database berjaya dimuatkan: {len(listings_db)} listing.")
            return True

        return False

    except Exception as e:

        print(f"❌ Gagal load local database: {e}")
        return False


# =============================================================
# LOAD LATEST JSON FROM TELEGRAM BACKUP CHANNEL
# =============================================================

async def load_data_from_channel(app: Application):

    global listings_db
    global pinned_index_message_id
    global backup_pinned_message_id

    try:

        print("🔄 Membaca backup JSON dari Telegram Channel...")

        chat = await app.bot.get_chat(
            chat_id=BACKUP_CHANNEL_ID
        )

        target_document = None

        pinned = chat.pinned_message
        if pinned and pinned.document:
            filename = pinned.document.file_name or ""
            if filename.lower().endswith(".json"):
                target_document = pinned.document
                backup_pinned_message_id = pinned.message_id
                print("📌 Dokumen JSON dijumpai melalui Pinned Message.")

        if not target_document:
            async for message in app.bot.get_chat_history(chat_id=BACKUP_CHANNEL_ID, limit=5):
                if message.document:
                    fname = message.document.file_name or ""
                    if fname.lower().endswith(".json"):
                        target_document = message.document
                        print(f"📄 Dokumen JSON dijumpai dari sejarah channel: {fname}")
                        break

        if not target_document:
            print("⚠️ Tiada fail JSON dijumpai dalam Backup Channel. Menggunakan hardcoded database.")
            return False

        telegram_file = await target_document.get_file()
        file_bytes = await telegram_file.download_as_bytearray()

        data = json.loads(
            file_bytes.decode("utf-8")
        )

        loaded_db = validate_database(
            data.get("listings", {})
        )

        if loaded_db:
            listings_db = loaded_db
            pinned_index_message_id = data.get("pinned_index_message_id")
            print(f"✅ Berjaya muat turun {len(listings_db)} listing dari Channel!")
            save_data()
            return True

        return False

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
# BACKUP TO TELEGRAM CHANNEL (AUTO UNPIN & DELETE PREVIOUS)
# =============================================================

async def backup_to_channel(context: ContextTypes.DEFAULT_TYPE):
    global backup_pinned_message_id
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

        new_msg_id = sent_msg.message_id

        try:
            await context.bot.pin_chat_message(
                chat_id=BACKUP_CHANNEL_ID,
                message_id=new_msg_id,
            )
        except Exception as pin_error:
            print(f"⚠️ Gagal pin backup baharu: {pin_error}")

        if backup_pinned_message_id and backup_pinned_message_id != new_msg_id:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=BACKUP_CHANNEL_ID,
                    message_id=backup_pinned_message_id,
                )
            except Exception as unpin_err:
                print(f"⚠️ Nota unpin mesej lama: {unpin_err}")

            try:
                await context.bot.delete_message(
                    chat_id=BACKUP_CHANNEL_ID,
                    message_id=backup_pinned_message_id,
                )
                print("🗑️ Mesej backup lama berjaya dipadam dari channel.")
            except Exception as del_err:
                print(f"⚠️ Nota padam mesej lama: {del_err}")

        backup_pinned_message_id = new_msg_id

        print("☁️ Backup baharu berjaya dihantar dan dipinn ke Telegram Channel.")
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

    if not group_msg_ids:
        print(f"ℹ️ Listing #{l_id} belum mempunyai mesej group.")
        return False

    desc_msg_id = group_msg_ids[-1]

    status_val = item.get("status", "ACTIVE")

    status_str = ""
    if status_val == "BOOKED":
        status_str = " - *⛔️ [BOOKED]*"
    elif status_val == "SOLD":
        status_str = " - *🔴 [SOLD]*"

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
                    status_str = " ⛔️ [BOOKED]"
                elif status_val == "SOLD":
                    status_str = " 🔴 [SOLD]"

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

        sent_msg = await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=index_text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

        pinned_index_message_id = sent_msg.message_id

        save_data()

        backup_success = await backup_to_channel(context)

        try:
            await context.bot.pin_chat_message(
                chat_id=GROUP_CHAT_ID,
                message_id=pinned_index_message_id,
            )
        except Exception as e:
            print(f"⚠️ Gagal pin index baharu: {e}")

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

        print(f"✅ Index berjaya dikemaskini. {len(listings_db)} listing.")
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
        [InlineKeyboardButton("➕ Tambah Listing Baru", callback_data="add_listing")],
        [InlineKeyboardButton("✏️ Kemaskini Harga", callback_data="edit_price_menu")],
        [InlineKeyboardButton("📝 Kemaskini Description", callback_data="edit_desc_menu")],
        [InlineKeyboardButton("🏷️ Set Status", callback_data="set_status")],
        [InlineKeyboardButton("🗑️ Padam Listing", callback_data="delete_listing")],
        [InlineKeyboardButton("📢 Refresh Index", callback_data="refresh_index")],
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

    if data == "add_listing":

        context.user_data["state"] = "WAITING_FOR_LISTING_PHOTOS"
        context.user_data["temp_photos"] = []
        context.user_data["temp_caption"] = ""

        await query.message.reply_text(
            "📸 **Tambah Listing Baru:**\n\n"
            "Hantar gambar hartanah berserta kapsyen pada gambar pertama.\n\n"
            "Format kapsyen:\n"
            "Baris 1: Tajuk Listing\n"
            "Baris 2: Harga\n"
            "Baris 3 dan seterusnya: Description\n\n"
            "Selepas selesai, taip **DONE**."
        )

    elif data == "refresh_index":

        await query.message.reply_text(
            "🔄 Sedang menyegarkan semula index group..."
        )

        success = await update_index_page(context)

        if success:
            await query.message.reply_text(
                "✅ INDEX BERJAYA DISEGARKAN!\n\n"
                f"📦 Jumlah listing: {len(listings_db)}\n"
                f"🟢 Listing ACTIVE: {get_active_count()}\n"
                "📢 Index baharu telah dihantar ke group."
            )
        else:
            await query.message.reply_text(
                "⚠️ Gagal mengemaskini index ke group. Sila cuba lagi."
            )

    elif data == "edit_price_menu":

        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing.")
            return

        await query.message.reply_text(
            "✏️ Pilih listing untuk dikemaskini harganya:",
            reply_markup=get_listing_keyboard("editprice", "Harga"),
        )

    elif data.startswith("editprice_"):

        l_id = int(data.split("_")[1])
        if l_id not in listings_db:
            return

        context.user_data["editing_id"] = l_id
        context.user_data["state"] = "WAITING_FOR_NEW_PRICE"

        await query.message.reply_text(f"Sila taip harga baru untuk Listing #{l_id}:")

    elif data == "edit_desc_menu":

        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing.")
            return

        await query.message.reply_text(
            "📝 Pilih listing untuk dikemaskini description:",
            reply_markup=get_listing_keyboard("editdesc", "Desc"),
        )

    elif data.startswith("editdesc_"):

        l_id = int(data.split("_")[1])
        if l_id not in listings_db:
            return

        context.user_data["editing_desc_id"] = l_id
        context.user_data["state"] = "WAITING_FOR_NEW_DESC"

        await query.message.reply_text(
            f"📝 Hantar description baru untuk Listing #{l_id}."
        )

    elif data == "set_status":

        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing.")
            return

        await query.message.reply_text(
            "🏷️ Pilih listing untuk dikemaskini status:",
            reply_markup=get_listing_keyboard("status", "Status"),
        )

    elif data.startswith("status_"):

        l_id = int(data.split("_")[1])
        if l_id not in listings_db:
            return

        keyboard = [
            [InlineKeyboardButton("🟢 ACTIVE", callback_data=f"setstat_{l_id}_ACTIVE")],
            [InlineKeyboardButton("⛔️ BOOKED", callback_data=f"setstat_{l_id}_BOOKED")],
            [InlineKeyboardButton("🔴 SOLD", callback_data=f"setstat_{l_id}_SOLD")],
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
        await update_group_description(context, l_id)
        await update_index_page(context)

        if new_status == "BOOKED":
            group_msg_ids = listings_db[l_id].get("group_message_ids", [])
            if group_msg_ids:
                first_msg_id = group_msg_ids[0]
                try:
                    await context.bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text="Assalamualaikum guys, unit ni dah di booked ya. Boleh turunkan iklan. TQ",
                        reply_to_message_id=first_msg_id
                    )
                except Exception as quote_err:
                    print(f"⚠️ Gagal hantar mesej quote booked ke group: {quote_err}")

        await query.message.reply_text(
            f"✅ Status Listing #{l_id} ditukar kepada {new_status}."
        )

    elif data == "delete_listing":

        if not listings_db:
            await query.message.reply_text("⚠️ Tiada listing.")
            return

        await query.message.reply_text(
            "🗑️ Pilih listing untuk dipadam:",
            reply_markup=get_listing_keyboard("del", "Padam"),
        )

    elif data.startswith("del_"):

        l_id = int(data.split("_")[1])
        if l_id not in listings_db:
            return

        for msg_id in listings_db[l_id].get("group_message_ids", []):
            try:
                await context.bot.delete_message(chat_id=GROUP_CHAT_ID, message_id=msg_id)
            except Exception:
                pass

        listings_db.pop(l_id, None)
        await reindex_listings()
        save_data()
        await update_index_page(context)

        await query.message.reply_text("✅ Listing berjaya dipadam & ID disusun semula.")


# =============================================================
# MESSAGE HANDLER
# =============================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    state = context.user_data.get("state")

    if state == "WAITING_FOR_NEW_PRICE":

        if not update.message.text:
            await update.message.reply_text("⚠️ Sila hantar teks harga sahaja.")
            return

        new_price = update.message.text.strip()
        l_id = context.user_data.get("editing_id")

        if l_id in listings_db:
            listings_db[l_id]["price"] = new_price
            save_data()
            await update_group_description(context, l_id)
            await update_index_page(context)
            context.user_data.clear()
            await update.message.reply_text(f"✅ Harga Listing #{l_id} berjaya dikemaskini!")

        return

    elif state == "WAITING_FOR_NEW_DESC":

        new_desc = update.message.text.strip() if update.message.text else (update.message.caption.strip() if update.message.caption else None)

        if not new_desc:
            await update.message.reply_text("⚠️ Tiada teks atau kapsyen dikesan.")
            return

        l_id = context.user_data.get("editing_desc_id")

        if l_id in listings_db:
            listings_db[l_id]["desc"] = new_desc
            save_data()
            await update_group_description(context, l_id)
            await update_index_page(context)
            context.user_data.clear()
            await update.message.reply_text(f"✅ Description Listing #{l_id} dikemaskini!")

        return

    elif state == "WAITING_FOR_LISTING_PHOTOS":

        if update.message.photo:
            photo_file_id = update.message.photo[-1].file_id
            context.user_data["temp_photos"].append(photo_file_id)

            if update.message.caption and not context.user_data.get("temp_caption"):
                context.user_data["temp_caption"] = update.message.caption

            await update.message.reply_text(
                f"📸 Gambar diterima! (Jumlah: {len(context.user_data['temp_photos'])}).\n"
                "Hantar lagi atau taip DONE."
            )
            return

        if update.message.text:
            text_input = update.message.text.strip()

            if text_input.upper() == "DONE":
                photos = context.user_data.get("temp_photos", [])
                caption_text = context.user_data.get("temp_caption", "")

                if not photos:
                    await update.message.reply_text("⚠️ Tiada gambar dikesan.")
                    return

                if not caption_text:
                    await update.message.reply_text("⚠️ Sila pastikan gambar pertama mempunyai kapsyen.")
                    return

                lines = caption_text.split("\n")
                if len(lines) < 3:
                    await update.message.reply_text("⚠️ Format kapsyen memerlukan sekurang-kurangnya 3 baris.")
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
                    read_opts = {"read_timeout": 60, "write_timeout": 60, "connect_timeout": 60}

                    if len(photos) > 1:
                        media_list = [InputMediaPhoto(media=photos[0], caption=short_caption, parse_mode="Markdown")]
                        for photo_id in photos[1:]:
                            media_list.append(InputMediaPhoto(media=photo_id))

                        sent_messages = await context.bot.send_media_group(chat_id=GROUP_CHAT_ID, media=media_list, **read_opts)
                        for msg in sent_messages:
                            group_message_ids.append(msg.message_id)
                    else:
                        sent_msg = await context.bot.send_photo(chat_id=GROUP_CHAT_ID, photo=photos[0], caption=short_caption, parse_mode="Markdown", **read_opts)
                        group_message_ids.append(sent_msg.message_id)

                    desc_msg = await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=full_desc, parse_mode="Markdown", disable_web_page_preview=True, **read_opts)
                    group_message_ids.append(desc_msg.message_id)

                except Exception as e:
                    print(f"❌ Ralat hantar listing: {e}")
                    await update.message.reply_text(f"❌ Gagal menghantar listing ke group: {e}")
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

                if group_message_ids:
                    try:
                        await context.bot.send_message(
                            chat_id=GROUP_CHAT_ID,
                            text="Assalamualaikum guys, listing baru masuk!! Jom kita sama-sama close the deal!!",
                            reply_to_message_id=group_message_ids[0]
                        )
                    except Exception as new_quote_err:
                        print(f"⚠️ Gagal hantar mesej quote listing baharu: {new_quote_err}")

                await update.message.reply_text(
                    f"✅ Listing #{saved_id} berjaya disimpan dan dihantar ke group!"
                )
            else:
                if not context.user_data.get("temp_caption"):
                    context.user_data["temp_caption"] = text_input
                    await update.message.reply_text("📝 Kapsyen diterima! Sekarang hantar gambar atau taip DONE.")
                else:
                    await update.message.reply_text("Sila hantar gambar seterusnya atau taip DONE.")
    else:
        await update.message.reply_text("Sila taip /start untuk membuka menu utama.")


# =============================================================
# ERROR HANDLER
# =============================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


# =============================================================
# POST INIT
# =============================================================

async def post_init(app: Application):

    print("🚀 Bot sedang memulakan sistem database...")

    loaded = await load_data_from_channel(app)

    if not loaded:
        print("⚠️ Cuba muat local JSON...")
        loaded_local = load_local_database()
        
        if not loaded_local:
            print("✅ Menggunakan hardcoded default database (9 listing aktif).")
            save_data()

    print("======================================")
    print("🏠 BOT HARTANAH BERJAYA DIMULAKAN")
    print(f"📦 Jumlah listing: {len(listings_db)}")
    print(f"🟢 Listing ACTIVE: {get_active_count()}")
    print("======================================")


# =============================================================
# MAIN
# =============================================================

def main():

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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), handle_message))
    app.add_error_handler(error_handler)

    print("🏠 Bot Hartanah sedang berjalan...")
    app.run_polling()


if __name__ == "__main__":
    main()
