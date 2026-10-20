
import telebot
import yt_dlp
import os

TOKEN = '8726449470:AAHuKzKNgk5wbwV1ki6AQnfpeHMSJ2T78fo'
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "مرحباً بك! 🎬\n"
        "أرسل لي رابط فيديو من يختيوب، تيك توك، أو فيسبوك وسأقوم بتحميله وإرساله لك."
    )

@bot.message_handler(func=lambda message: any(domain in message.text for domain in ["youtube.com", "youtu.be", "tiktok.com", "facebook.com", "fb.watch"]))
def download_media(message):
    url = message.text.strip()
    processing_msg = bot.reply_to(message, "⏳ جاري تحميل الفيديو، يرجى الانتظار...")
    
    output_template = 'video_temp.mp4'
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': output_template,
        'noplaylist': True,
        'geo_bypass': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        if os.path.exists(output_template):
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=processing_msg.message_id,
                text="📤 جاري إرسال الفيديو..."
            )
            
            with open(output_template, 'rb') as video_file:
                bot.send_video(message.chat.id, video_file, caption="✅ تم التحميل بنجاح.")
                
            os.remove(output_template)
            bot.delete_message(message.chat.id, processing_msg.message_id)
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=processing_msg.message_id, text="❌ لم يتم إنشاء ملف الفيديو.")
            
    except Exception as e:
        print(f"Error details: {e}")
        if os.path.exists(output_template):
            os.remove(output_template)
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=processing_msg.message_id,
            text=f"❌ حدث خطأ أثناء التحميل من هذا الرابط."
        )

@bot.message_handler(func=lambda message: True)
def default_response(message):
    bot.reply_to(message, "⚠️ يرجى إرسال رابط صالح من يوتيوب، تيك توك، أو فيسبوك.")

print("البوت يعمل الآن وجاهز...")
bot.infinity_polling()
