import os
import re
import uuid
import asyncio
import logging
import subprocess
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
MAX_FILE_SIZE = 50 * 1024 * 1024

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ⬇️⬇️⬇️ المكان 1: استبدل كلمة example باسم الموقع (بحروف صغيرة، بدون .com) ⬇️⬇️⬇️
SITE_NAME = "pornhub"
# ⬆️⬆️⬆️ لا تغير أي شي آخر ⬆️⬆️⬆️

# ⬇️⬇️⬇️ المكان 2: استبدل كلمة MODULE_NAME باسم المكتبة (نفس اسم الموقع بحروف صغيرة) ⬇️⬇️⬇️
MODULE_NAME = "pornhub"
# ⬆️⬆️⬆️ لا تغير أي شي آخر ⬆️⬆️⬆️

# ===== التحقق من الرابط =====
URL_REGEX = re.compile(
    r'https?://([a-zA-Z0-9-]+\.)*'
    r'(twitter\.com|x\.com|instagram\.com|tiktok\.com|'
    r'youtube\.com|youtu\.be|facebook\.com|fb\.watch|'
    r'reddit\.com|pinterest\.com|snapchat\.com|'
    r'tumblr\.com|vimeo\.com|dailymotion\.com|'
    + re.escape(SITE_NAME) + r'\.com)'
    r'[^\s]*',
    re.IGNORECASE
)

def extract_url(text: str):
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


# ===== التحميل عبر yt-dlp =====
def download_with_ytdlp(url: str, job_id: str):
    output_template = str(DOWNLOAD_DIR / f"{job_id}.%(ext)s")
    ydl_opts = {
        'outtmpl': output_template,
        'format': 'bestvideo+bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'cookiefile': 'x.com_cookies.txt',
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
    return filepath


# ===== التحميل عبر المكتبة المخصصة =====
def download_with_custom_module(url: str, job_id: str):
    output_dir = DOWNLOAD_DIR / job_id
    output_dir.mkdir(exist_ok=True)

    # سكربت صغير يشغّل المكتبة
    script = f'''
import sys
try:
    from {MODULE_NAME} import {MODULE_NAME.capitalize()}
except ImportError:
    import {MODULE_NAME}
    {MODULE_NAME.capitalize()} = {MODULE_NAME}.{MODULE_NAME.capitalize()}

client = {MODULE_NAME.capitalize()}()
client.download("{url}", output_dir="{output_dir}")
'''
    script_path = output_dir / "run.py"
    script_path.write_text(script)

    result = subprocess.run(
        ['python', str(script_path)],
        capture_output=True, text=True, timeout=600
    )

    logging.info(f"custom module stdout: {result.stdout}")
    logging.error(f"custom module stderr: {result.stderr}")

    files = [f for f in output_dir.glob('*') if f.is_file() and f.suffix != '.py']
    if not files:
        return None

    filepath = max(files, key=lambda f: f.stat().st_size)
    return str(filepath)


# ===== التحميل عبر gallery-dl =====
def download_with_gallerydl(url: str, job_id: str):
    output_dir = DOWNLOAD_DIR / job_id
    output_dir.mkdir(exist_ok=True)

    result = subprocess.run([
        'gallery-dl',
        '--cookies', 'x.com_cookies.txt',
        '--dest', str(output_dir),
        '--filename', '{num}.{extension}',
        url
    ], capture_output=True, text=True, timeout=180)

    logging.info(f"gallery-dl output: {result.stdout}")
    logging.error(f"gallery-dl error: {result.stderr}")

    files = [f for f in output_dir.glob('*') if f.stat().st_size > 0]
    if not files:
        return None

    filepath = max(files, key=lambda f: f.stat().st_size)
    return str(filepath)


# ===== ضغط الفيديو =====
def compress_video(input_path: str, max_size_mb: int = 45):
    output_path = input_path.rsplit('.', 1)[0] + '_compressed.mp4'

    probe = subprocess.run([
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        input_path
    ], capture_output=True, text=True)

    try:
        duration = float(probe.stdout.strip())
    except (ValueError, AttributeError):
        duration = 60

    target_bitrate_kbps = int((max_size_mb * 8 * 1024) / duration) - 128
    if target_bitrate_kbps < 100:
        target_bitrate_kbps = 100

    subprocess.run([
        'ffmpeg', '-i', input_path,
        '-b:v', f'{target_bitrate_kbps}k',
        '-b:a', '128k',
        '-vf', 'scale=-2:480',
        '-preset', 'fast',
        '-y', output_path
    ], capture_output=True)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return output_path
    return input_path


# ===== التحميل الرئيسي =====
def download_media(url: str, job_id: str):
    # إذا الرابط من الموقع المخصص
    if SITE_NAME.lower() in url.lower():
        try:
            filepath = download_with_custom_module(url, job_id)
            if filepath:
                is_video = filepath.lower().endswith(('.mp4', '.mkv', '.webm', '.mov', '.flv'))
                return filepath, is_video
        except Exception as e:
            logging.warning(f"custom module failed: {e}")

    # 1) جرّب yt-dlp
    try:
        filepath = download_with_ytdlp(url, job_id)
        is_video = filepath.lower().endswith(('.mp4', '.mkv', '.webm', '.mov'))
        return filepath, is_video
    except Exception as e:
        logging.warning(f"yt-dlp failed: {e}")

    # 2) جرّب gallery-dl
    try:
        filepath = download_with_gallerydl(url, job_id)
        if filepath:
            is_video = filepath.lower().endswith(('.mp4', '.mkv', '.webm', '.mov', '.gif'))
            return filepath, is_video
    except Exception as e:
        logging.warning(f"gallery-dl failed: {e}")

    raise Exception("فشل التحميل بكل الطرق")


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
        "وسأحمّلها لك 📥"
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    url = extract_url(text)

    if not url:
        await update.message.reply_text("❌ لم أجد رابطاً مدعوماً.")
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
        logging.info(f"Downloaded: {filepath} ({size // (1024*1024)}MB)")

        if is_video and size > MAX_FILE_SIZE:
            await status_msg.edit_text(
                f"⚠️ الحجم كبير ({size // (1024*1024)}MB)\n"
                f"🔄 جاري الضغط..."
            )
            loop = asyncio.get_event_loop()
            compressed = await loop.run_in_executor(
                None, compress_video, filepath, 45
            )
            if compressed != filepath and os.path.exists(compressed):
                os.remove(filepath)
                filepath = compressed
                size = os.path.getsize(filepath)

        if not is_video and size > MAX_FILE_SIZE:
            await status_msg.edit_text(
                f"⚠️ حجم الصورة كبير ({size // (1024*1024)}MB)"
            )
            return

        if size > MAX_FILE_SIZE:
            await status_msg.edit_text(
                f"⚠️ الحجم ما زال كبير ({size // (1024*1024)}MB)"
            )
            return

        await status_msg.edit_text("📤 جاري الإرسال...")

        with open(filepath, 'rb') as f:
            if is_video:
                await update.message.reply_video(
                    video=f,
                    caption="✅ تم التحميل",
                    supports_streaming=True
                )
            else:
                await update.message.reply_photo(
                    photo=f,
                    caption="✅ تم التحميل"
                )

        await status_msg.delete()

    except Exception as e:
        error_str = str(e)
        logging.exception(e)
        await status_msg.edit_text(
            f"❌ فشل التحميل.\n\n"
            f"تفاصيل الخطأ:\n{error_str[:500]}"
        )

    finally:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
        gallery_dir = DOWNLOAD_DIR / job_id
        if gallery_dir.exists():
            import shutil
            shutil.rmtree(gallery_dir, ignore_errors=True)


# ===== التشغيل =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    print("✅ البوت يعمل...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
