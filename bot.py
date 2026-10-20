import os
import re
import uuid
import shutil
import logging
import telebot
import yt_dlp

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# 🔑 ضع رمز البوت الخاص بك هنا
TOKEN = "8726449470:AAHuKzKNgk5wbwV1ki6AQnfpeHMSJ2T78fo"

# إعداد السجلات
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise RuntimeError("يرجى وضع توكن البوت الصحيح في متغير TOKEN.")

bot = telebot.TeleBot(TOKEN, parse_mode=None)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# نخزن الرابط منفصلًا عن callback_data لتجنب تجاوز حد تيليجرام
user_jobs = {}

# حد حجم الملفات لتيليجرام (49 ميجابايت لتفادي تجاوز 50MB)
MAX_FILE_SIZE = 49 * 1024 * 1024


def valid_url(url):
    pattern = re.compile(
        r"^https?://",
        re.IGNORECASE
    )
    return bool(pattern.match(url))


def find_ffmpeg():
    return shutil.which("ffmpeg")


def get_video_info(url):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "extractor_retries": 2,
        "socket_timeout": 20,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


def get_quality_keyboard(url, info):
    keyboard = InlineKeyboardMarkup(row_width=2)
    job_id = uuid.uuid4().hex[:12]

    formats = info.get("formats", [])
    available_heights = set()

    for fmt in formats:
        if fmt.get("vcodec") in (None, "none"):
            continue

        height = fmt.get("height")
        if height and height >= 144:
            available_heights.add(height)

    # حفظ الرابط في الذاكرة
    user_jobs[job_id] = url

    heights = sorted(available_heights, reverse=True)

    for height in heights:
        keyboard.add(
            InlineKeyboardButton(
                f"📹 {height}p",
                callback_data=f"video:{job_id}:{height}"
            )
        )

    keyboard.add(
        InlineKeyboardButton(
            "🎬 أفضل جودة متاحة",
            callback_data=f"best:{job_id}"
        ),
        InlineKeyboardButton(
            "🎵 تحميل MP3",
            callback_data=f"mp3:{job_id}"
        )
    )

    return keyboard


@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.reply_to(
        message,
        "👋 أهلًا بك في بوت تحميل الفيديو والصوت!\n\n"
        "أرسل رابط فيديو من YouTube أو TikTok أو Facebook.\n"
        "ستظهر لك خيارات الجودة والصوت إذا كان الموقع يدعم ذلك.\n\n"
        "⚠️ قد لا تعمل بعض الروابط إذا تطلب الموقع تسجيل الدخول "
        "أو منع الوصول من الخادم."
    )


@bot.message_handler(
    content_types=["text"],
    func=lambda message: not message.text.startswith("/")
)
def handle_url(message):
    url = message.text.strip()

    if not valid_url(url):
        bot.reply_to(message, "❌ أرسل رابطًا يبدأ بـ http:// أو https://")
        return

    status = bot.reply_to(message, "⏳ أفحص الرابط، انتظر قليلًا...")

    try:
        info = get_video_info(url)
        title = info.get("title", "فيديو")
        keyboard = get_quality_keyboard(url, info)

        bot.edit_message_text(
            f"🎬 {title}\n\nاختر الجودة أو صيغة الصوت:",
            chat_id=message.chat.id,
            message_id=status.message_id,
            reply_markup=keyboard
        )

    except Exception as exc:
        logging.exception("تعذر فحص الرابط")
        bot.edit_message_text(
            "❌ لم أستطع قراءة الرابط.\n\n"
            "قد يكون الرابط خاصًا أو غير مدعوم أو يتطلب تسجيل الدخول.\n"
            "التفاصيل: " + str(exc)[:700],
            chat_id=message.chat.id,
            message_id=status.message_id
        )


def download_media(url, mode, height=None):
    job_dir = os.path.join(DOWNLOAD_DIR, uuid.uuid4().hex)
    os.makedirs(job_dir, exist_ok=True)

    output_template = os.path.join(job_dir, "%(title).80s_%(id)s.%(ext)s")

    options = {
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 2,
        "fragment_retries": 2,
        "socket_timeout": 30,
    }

    if mode == "mp3":
        if not find_ffmpeg():
            shutil.rmtree(job_dir, ignore_errors=True)
            raise RuntimeError(
                "FFmpeg غير مثبت على الاستضافة، لذلك لا يمكن تحويل الصوت إلى MP3."
            )

        options.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })

    elif mode == "best":
        options["format"] = "best[ext=mp4]/best"

    elif mode == "video":
        options["format"] = (
            f"best[height<={height}][ext=mp4]/"
            f"best[height<={height}]/best"
        )

    else:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise ValueError("صيغة تحميل غير معروفة.")

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        files = [
            os.path.join(job_dir, name)
            for name in os.listdir(job_dir)
            if os.path.isfile(os.path.join(job_dir, name))
        ]

        if not files:
            raise RuntimeError("لم يتم العثور على الملف بعد التحميل.")

        # استبعاد الملفات المؤقتة
        files = [
            path for path in files
            if not path.endswith((".part", ".ytdl"))
        ]

        if not files:
            raise RuntimeError("لم يكتمل تنزيل الملف.")

        result = max(files, key=os.path.getsize)
        return result, job_dir

    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise


@bot.callback_query_handler(
    func=lambda call: call.data.startswith(("video:", "best:", "mp3:"))
)
def handle_choice(call):
    parts = call.data.split(":")
    mode = parts[0]
    job_id = parts[1]

    url = user_jobs.get(job_id)

    if not url:
        bot.answer_callback_query(
            call.id,
            "انتهت صلاحية الرابط. أرسل الرابط من جديد.",
            show_alert=True
        )
        return

    height = int(parts[2]) if mode == "video" and len(parts) > 2 else None

    bot.answer_callback_query(call.id, "بدأ التحميل...")
    status = bot.send_message(
        call.message.chat.id,
        "⏬ جارٍ التحميل، يرجى الانتظار..."
    )

    job_dir = None

    try:
        file_path, job_dir = download_media(url, mode, height)
        size = os.path.getsize(file_path)

        if size > MAX_FILE_SIZE:
            bot.send_message(
                call.message.chat.id,
                f"⚠️ حجم الملف ({size / (1024 * 1024):.1f} ميجابايت) يتجاوز الحد المسموح للإرسال عبر البوت (50 ميجابايت)."
            )
            return

        with open(file_path, "rb") as media:
            if mode == "mp3":
                bot.send_audio(
                    call.message.chat.id,
                    media,
                    title=os.path.splitext(os.path.basename(file_path))[0]
                )
            else:
                bot.send_video(
                    call.message.chat.id,
                    media,
                    supports_streaming=True,
                    timeout=120
                )

        bot.send_message(call.message.chat.id, "✅ اكتمل الإرسال.")

    except Exception as exc:
        logging.exception("فشل التحميل أو الإرسال")
        bot.send_message(
            call.message.chat.id,
            "❌ فشل التحميل أو الإرسال.\n\n"
            "قد يكون السبب منع الموقع للتنزيل أو عدم دعم الرابط "
            "أو عدم توفر FFmpeg أو تجاوز حجم الملف.\n\n"
            f"التفاصيل: {str(exc)[:700]}"
        )

    finally:
        # حذف رسالة التنزيل المعلقة
        try:
            bot.delete_message(
                call.message.chat.id,
                status.message_id
            )
        except Exception:
            pass

        # تنظيف المجلد والذاكرة
        if job_dir:
            shutil.rmtree(job_dir, ignore_errors=True)

        user_jobs.pop(job_id, None)


if __name__ == "__main__":
    logging.info("البوت يعمل الآن...")
    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )
