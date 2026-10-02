import os
import re
import uuid
import asyncio
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters, ContextTypes
)
import yt_dlp

# ===== الإعدادات =====
TOKEN = os.environ.get("BOT_TOKEN")
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB حد تلقرام

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ===== التحقق من الرابط =====
URL_REGEX = re.compile(
    r'https?://(www\.)?'
    r'(twitter\.com|x\.com|instagram\.com|tiktok\.com|'
    r'youtube\.com|youtu\.be|facebook\.com|fb\.watch|'
    r'reddit\.com|pinterest\.com|snapchat\.com|'
    r'tumblr\.com|vimeo\.com|dailymotion\.com)'
    r'[^\s]*'
)

def extract_url(text: str):
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


# ===== التحميل بالجودة الأصلية =====
def download_media(url: str, job_id: str):
    output_template = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")

    ydl_opts = {
        'outtmpl': output_template,
        'format': 'bestvideo+bestaudio/best',  # الجودة الأصلية
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0 Safari/537.36'
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)

        if not os.path.exists(filepath):
            base = os.path.splitext(filepath)[0]
            for ext in ['.mp4', '.mkv', '.webm', '.jpg', '.png', '.jpeg']:
                if os.path.exists(base + ext):
                    filepath = base + ext
                    break

    is_video = filepath.lower().endswith(('.mp4', '.mkv', '.webm', '.mov'))
    return filepath, is_video


# ===== الأوامر =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك!\n\n"
        "أرسل لي رابط فيديو أو صورة من:\n"
        "• تويتر / X\n"
        "• إنستغرام\n"
        "• تيك توك\n"
        "• يوتيوب\n"
        "• فيسبوك\n"
        "• ريديت\n"
        "• بينتريست\n\n"
        "وسأحمّلها لك بالجودة الأصلية 📥"
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    url = extract_url(text)

    if not url:
        await update.message.reply_text(
            "❌ لم أجد رابطاً مدعوماً.\n"
            "أرسل رابطاً من المواقع المدعومة."
        )
        return

    status_msg = await update.message.reply_text("⏳ جاري التحميل...")

    job_id = uuid.uuid4().hex
    filepath = None

    try:
        loop = asyncio.get_event_loop()
        filepath, is_video = await loop.run_in_executor(
            None, download_media, url, job_id
        )

        size = os.path.getsize(filepath)
        if size > MAX_FILE_SIZE:
            await status_msg.edit_text(
                f"⚠️ حجم الملف كبير ({size // (1024*1024)}MB)\n"
                "الحد الأقصى 50MB.\n"
                "جاري إرساله كملف مستند..."
            )

        await status_msg.edit_text("📤 جاري الإرسال...")

        with open(filepath, 'rb') as f:
            if is_video:
                await update.message.reply_video(
                    video=f,
                    caption="✅ تم التحميل بالجودة الأصلية",
                    supports_streaming=True
                )
            else:
                await update.message.reply_photo(
                    photo=f,
                    caption="✅ تم التحميل"
                )

        await status_msg.delete()

    except yt_dlp.utils.DownloadError as e:
        await status_msg.edit_text(
            "❌ فشل التحميل.\n"
            "الأسباب:\n"
            "• الرابط خاص أو محذوف\n"
            "• الموقع يطلب تسجيل دخول\n"
            "• الرابط غير مدعوم"
        )
        logging.error(f"Download error: {e}")

    except Exception as e:
        await status_msg.edit_text("❌ حدث خطأ غير متوقع.")
        logging.exception(e)

    finally:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass


# ===== التشغيل =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    print("✅ البوت يعمل...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
