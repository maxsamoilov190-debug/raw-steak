import os
import re
import json
import logging
import requests
from dotenv import load_dotenv
from flask import Flask, request
import telebot
from telebot import util

logging.basicConfig(level=logging.INFO)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("API_KEY")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

MAX_LEN = 4096

# ================== HTML ==================
def convert_markdown_to_html(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'__(.*?)__', r'<u>\1</u>', text)
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', text)
    return text


def send_long_message(chat_id, text):
    try:
        safe_text = convert_markdown_to_html(str(text))
        for part in util.smart_split(safe_text, MAX_LEN):
            bot.send_message(chat_id, part, parse_mode='HTML')
    except Exception as e:
        logging.exception("Ошибка отправки")


# ================== WEBHOOK ==================
@app.route('/')
def index():
    return "bot is running!"


@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data(as_text=True)
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception:
        logging.exception("Webhook error")
    return '', 200


# ================== HISTORY ==================
history_file = "history.json"
history = {}

if os.path.exists(history_file):
    try:
        with open(history_file, "r", encoding='utf-8') as f:
            history = json.load(f)
    except:
        history = {}


def save_history():
    with open(history_file, "w", encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ================== CHAT ==================
def chat(user_id, text):
    try:
        uid = str(user_id)

        if uid not in history:
            history[uid] = [{"role": "system", "content": "Ты грубый помощник"}]

        history[uid].append({"role": "user", "content": text})

        url = "https://api.intelligence.io.solutions/api/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        }

        data = {
            "model": "deepseek-ai/DeepSeek-R1-0528",
            "messages": history[uid]
        }

        response = requests.post(url, headers=headers, json=data, timeout=30)

        if response.status_code != 200:
            return "Ошибка API"

        res = response.json()

        if "choices" not in res:
            return "Ошибка ответа модели"

        content = res["choices"][0]["message"]["content"]

        history[uid].append({"role": "assistant", "content": content})

        if len(history[uid]) > 16:
            history[uid] = [history[uid][0]] + history[uid][-15:]

        save_history()

        return content

    except Exception as e:
        logging.exception("CHAT ERROR")
        return f"Ошибка: {e}"


# ================== DB ==================
db_path = "db.json"

if os.path.exists(db_path):
    with open(db_path, "r", encoding='utf-8') as f:
        db = json.load(f)
else:
    db = {"users": {}}


def save_db():
    with open(db_path, "w", encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=4)


# ================== START ==================
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id

    user = db["users"].get(user_id)

    if not user or user.get("awaiting") == "name":
        db["users"][user_id] = {"awaiting": "name"}
        save_db()
        bot.send_message(user_id, "Введи имя")
        return

    db["users"][user_id]["money"] = 20000

    keyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("Игровой автомат", "Игральный кубик")

    bot.send_message(user_id, f"Привет, {user.get('name')}", reply_markup=keyboard)


# ================== TEXT ==================
@bot.message_handler(content_types=['text'])
def text_handler(message):
    user_id = message.chat.id
    user = db["users"].get(user_id)

    if not user:
        start(message)
        return

    if user.get("awaiting") == "name":
        user["name"] = message.text
        user["awaiting"] = None
        user["money"] = 10000
        save_db()
        start(message)
        return

    if message.text == "Игровой автомат":
        slot_game(message)
    elif message.text == "Игральный кубик":
        dice_game(message)
    else:
        msg = bot.send_message(user_id, "Думаю...")
        answer = chat(user_id, message.text)
        send_long_message(user_id, answer)

        try:
            bot.delete_message(user_id, msg.message_id)
        except:
            pass


# ================== DICE ==================
def dice_game(message):
    keyboard = telebot.types.InlineKeyboardMarkup()

    buttons = [
        telebot.types.InlineKeyboardButton(str(i), callback_data=str(i))
        for i in range(1, 7)
    ]

    keyboard.add(*buttons)

    bot.send_message(message.chat.id, "Угадай число", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: True)
def dice_callback(call):
    value = bot.send_dice(call.message.chat.id).dice.value

    if str(value) == call.data:
        bot.send_message(call.message.chat.id, "Ты выиграл")
    else:
        bot.send_message(call.message.chat.id, f"Выпало {value}")


# ================== SLOT ==================
def slot_game(message):
    user = db["users"][message.chat.id]

    value = bot.send_dice(message.chat.id, emoji="🎰").dice.value

    if value in (1, 22, 43):
        user["money"] += 3000
    elif value in (16, 32, 48):
        user["money"] += 5000
    elif value == 64:
        user["money"] += 10000
    else:
        bot.send_message(message.chat.id, "Проигрыш")
        return

    save_db()

    bot.send_message(message.chat.id, f"Баланс: {user['money']}")


# ================== RUN ==================
if __name__ == "__main__":
    server_url = os.getenv("RENDER_EXTERNAL_URL")

    if server_url:
        webhook_url = f"{server_url}/{TOKEN}"

        requests.get(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            params={"url": webhook_url},
            timeout=10
        )

        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))