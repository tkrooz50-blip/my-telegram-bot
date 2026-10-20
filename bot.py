import os
import re
import uuid
import shutil
import tempfile
import threading

import telebot
import yt_dlp

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==================================================
# الإعدادات
# ==================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "8726449470:AAHuKzKNgk5wbwV1ki6AQnfpeHMSJ2T78fo"
    )

bot = telebot.TeleBot(TOKEN, threaded=True)

# الحد الأقصى التقريبي للإرسال عبر Telegram Bot API.
# يمكن تعديله حسب حدود Telegram وطريقة الاستضافة.
MAX_FILE_SIZE = 49 * 1024 * 1024

SUPPORTED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "facebook.com",
    "fb.watch",
)

# نخزن روابط المستخدمين مؤقتًا باستخدام معرف فريد.
pending_downloads = {}

# منع تكرار تنزيل الطلب نفسه أثناء معالجته.
active_downloads = set()

downloads_lock = threading.Lock()


# ==================================================
# أدوات مساعدة
# ==================================================

def is_supported_url(text):
    """التحقق الأولي من رابط المنصة."""

    if not text:
        return False

    text = text.strip()

    pattern = re.compile(
        r"^https?://[^\s]+$",
        re.IGNORECASE
    )

    if not pattern.match(text):
        return False

    domain_match = re.search(
        r"https?://([^/:?#]+)",
        text,
        re.IGNORECASE
    )

    if not domain_match:
        return False

    hostname = domain_match.group(1).lower()

    return any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in SUPPORTED_DOMAINS
    )


def create_keyboard(url, platform, formats=None):
    """إنشاء قائمة الخيارات المناسبة للرابط."""

    keyboard = InlineKeyboardMarkup(row_width=2)

    if platform == "youtube":
        keyboard.row(
            InlineKeyboardButton(
                "🎬 أفضل جودة متاحة",
                callback_data=f"video_best|{url}"
            )
        )

        # عرض خيارات الجودة بناءً على الصيغ المكتشفة.
        if formats:
            for quality in ("1080", "720", "480", "360"):
                available = any(
                    f.get("height") == int(quality)
                    and f.get("vcodec") != "none"
                    and f.get("acodec") == "none"
                    for f in formats
                )

                if available:
                    keyboard.add(
                        InlineKeyboardButton(
                            f"📹 {quality}p",
                            callback_data=f"video_{quality}|{url}"
                        )
                    )

        keyboard.row(
            InlineKeyboardButton(
                "🎵 تحميل MP3",
                callback_data=f"audio|{url}"
            )
        )

    else:
        keyboard.row(
            InlineKeyboardButton(
                "📹 تحميل الفيديو",
                callback_data=f"video_best|{url}"
            ),
            InlineKeyboardButton(
                "🎵 تحميل MP3",
                callback_data=f"audio|{url}"
            )
        )

    return keyboard


def get_video_options(url):
    """استخراج بيانات الفيديو والصيغ المتاحة دون تنزيله."""

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


def safe_filename(title, extension):
    """إنشاء اسم ملف آمن."""

    title = re.sub(r'[\\/*?:"<>|]', "_", title or "media")
    title = title[:80].strip() or "media"

    return f"{title}.{extension}"


def download_media(url, mode, quality=None):
    """
    تنزيل الفيديو أو الصوت في مجلد مؤقت مستقل.
    تعيد الدالة مسار الملف وعنوانه والمجلد المؤقت.
    """

    temp_dir = tempfile.mkdtemp(prefix="telegram_media_")

    try:
        output_template = os.path.join(
            temp_dir,
            "%(title).80s_%(id)s.%(ext)s"
        )

        ydl_opts = {
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "socket_timeout": 30,
        }

        if mode == "audio":
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })

        else:
            if quality:
                format_selector = (
                    f"bestvideo[height<={quality}]"
                    f"+bestaudio/best[height<={quality}]"
                    f"/best[height<={quality}]"
                    f"/best"
                )
            else:
                format_selector = "bestvideo+bestaudio/best"

            ydl_opts.update({
                "format": format_selector,
                "merge_output_format": "mp4",
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "media")

            files = [
                os.path.join(temp_dir, filename)
                for filename in os.listdir(temp_dir)
                if os.path.isfile(os.path.join(temp_dir, filename))
            ]

            # استبعاد الملفات الجزئية.
            files = [
                path for path in files
                if not path.endswith((".part", ".ytdl"))
            ]

            if not files:
                raise FileNotFoundError(
                    "لم يتم العثور على الملف بعد انتهاء التنزيل."
                )

            # اختيار الملف النهائي الأكبر حجمًا.
            file_path = max(files, key=os.path.getsize)

            if os.path.getsize(file_path) > MAX_FILE_SIZE:
                raise ValueError(
                    "حجم الملف أكبر من الحد المحدد للإرسال. "
                    "اختر جودة أقل أو ملفًا أصغر."
                )

            return file_path, title, temp_dir

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def send_download(chat_id, url, mode, quality=None):
    """تنزيل الملف وإرساله إلى المستخدم."""

    job_key = (chat_id, url, mode, quality)

    with downloads_lock:
        if job_key in active_downloads:
            bot.send_message(
                chat_id,
                "⏳ هذا الطلب قيد التنفيذ بالفعل."
            )
            return

        active_downloads.add(job_key)

    temp_dir = None
    status = bot.send_message(
        chat_id,
        "⏳ جارٍ تجهيز الملف، يرجى الانتظار..."
    )

    try:
        file_path, title, temp_dir = download_media(
            url,
            mode,
            quality
        )

        bot.edit_message_text(
            "📤 جارٍ إرسال الملف...",
            chat_id,
            status.message_id
        )

        filename = os.path.basename(file_path)

        with open(file_path, "rb") as media:
            if mode == "audio":
                bot.send_audio(
                    chat_id,
                    media,
                    title=title,
                    caption="🎵 تم تحميل الصوت بنجاح."
                )

            else:
                bot.send_video(
                    chat_id,
                    media,
                    caption=f"🎬 {title}"
                )

        # إرسال الصوت بعد الفيديو تلقائيًا.
        # يُطبّق هذا السلوك على فيديوهات يوتيوب وتيك توك وفيسبوك.
        if mode == "video":
            bot.send_message(
                chat_id,
                "🎵 جارٍ استخراج المقطع الصوتي وإرساله..."
            )

            audio_path, audio_title, audio_dir = download_media(
                url,
                "audio"
            )

            try:
                with open(audio_path, "rb") as audio:
                    bot.send_audio(
                        chat_id,
                        audio,
                        title=audio_title,
                        caption="🎵 المقطع الصوتي للفيديو."
                    )
            finally:
                shutil.rmtree(audio_dir, ignore_errors=True)

        bot.delete_message(chat_id, status.message_id)

    except Exception as error:
        print(f"Download error: {error}")

        try:
            bot.edit_message_text(
                "❌ تعذر تحميل الملف أو إرساله.\n"
                "قد يكون الرابط غير متاح، أو الصيغة غير مدعومة، "
                "أو حجم الملف أكبر من الحد المسموح.\n"
                "جرّب رابطًا آخر أو اختر جودة أقل.",
                chat_id,
                status.message_id
            )
        except Exception:
            pass

    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

        with downloads_lock:
            active_downloads.discard(job_key)


# ==================================================
# أمر البداية
# ==================================================

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(
        message,
        "مرحبًا بك في بوت تحميل الفيديو والصوت! 🎬🎵\n\n"
        "أرسل رابطًا من إحدى المنصات التالية:\n"
        "• YouTube\n"
        "• TikTok\n"
        "• Facebook\n\n"
        "سأعرض لك خيارات التحميل المتاحة."
    )


# ==================================================
# استقبال الروابط وعرض الخيارات
# ==================================================

@bot.message_handler(
    func=lambda message: bool(message.text)
    and is_supported_url(message.text)
)
def handle_url(message):
    url = message.text.strip()

    try:
        bot.send_chat_action(message.chat.id, "typing")

        info = get_video_options(url)

        extractor = (
            info.get("extractor_key", "")
            or info.get("extractor", "")
        ).lower()

        if "youtube" in extractor:
            platform = "youtube"
        else:
            platform = "other"

        formats = info.get("formats", [])

        keyboard = create_keyboard(
            url,
            platform,
            formats
        )

        title = info.get("title", "الفيديو")

        bot.reply_to(
            message,
            f"🎬 <b>{title}</b>\n\n"
            "اختر ما تريد تحميله:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    except Exception as error:
        print(f"Info error: {error}")

        bot.reply_to(
            message,
            "❌ تعذر قراءة الرابط.\n"
            "تأكد من أن الفيديو متاح وحاول مرة أخرى."
        )


# ==================================================
# معالجة ضغط الأزرار
# ==================================================

@bot.callback_query_handler(
    func=lambda call: call.data and "|" in call.data
)
def handle_download_callback(call):
    try:
        action, url = call.data.split("|", 1)

        bot.answer_callback_query(
            call.id,
            "تم استلام طلبك، جارٍ التجهيز..."
        )

        if action == "audio":
            mode = "audio"
            quality = None

        elif action == "video_best":
            mode = "video"
            quality = None

        elif action.startswith("video_"):
            mode = "video"
            quality = action.replace("video_", "")

            if quality not in ("1080", "720", "480", "360"):
                bot.send_message(
                    call.message.chat.id,
                    "❌ خيار الجودة غير صالح."
                )
                return

        else:
            return

        # تشغيل التنزيل في مسار منفصل حتى لا تتوقف استجابة البوت.
        worker = threading.Thread(
            target=send_download,
            args=(
                call.message.chat.id,
                url,
                mode,
                quality
            ),
            daemon=True
        )

        worker.start()

    except Exception as error:
        print(f"Callback error: {error}")

        try:
            bot.answer_callback_query(
                call.id,
                "حدث خطأ، يرجى المحاولة مجددًا.",
                show_alert=True
            )
        except Exception:
            pass


# ==================================================
# الرد على الرسائل غير المدعومة
# ==================================================

@bot.message_handler(func=lambda message: True)
def default_response(message):
    bot.reply_to(
        message,
        "⚠️ يرجى إرسال رابط صالح من التطبيق الاحمر أو تيك توك أو فيسبوك."
    )


# ==================================================
# تشغيل البوت
# ==================================================

print("البوت يعمل الآن وجاهز لاستقبال الروابط...")

bot.infinity_polling(skip_pending=True)