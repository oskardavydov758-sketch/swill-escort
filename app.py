import os
import telebot
import time
import threading
import requests
import json
import uuid
from datetime import datetime, timedelta, timezone as tz
from flask import Flask, request, send_from_directory

# Конфигурация
TOKEN_MAIN = '8786865345:AAGMia7IGPwKNqjc1BUp1y5W9yh_bf-UNaY'
TOKEN_SUPPORT = '8761438748:AAEGdL24efQbIk9eIC9-bz3nfasPwFR9NjQ'
ADMIN_ID = 5852338439
GROUP_LOGS = -5235487009
GROUP_SUPPORT = -5235487009  # Пока группа логов = группа поддержки, можно разделить
STATIC_URL = 'https://swill-escort.onrender.com'
MINSK = tz(timedelta(hours=3))
USDT_ADDRESS = 'TCFRmpHnmthD8UiENTwvedaRU6kJv2uBdg'
USDT_RATE = 2.82  # Будет обновляться через API

# Инициализация ботов
bot = telebot.TeleBot(TOKEN_MAIN, threaded=False)
support_bot = telebot.TeleBot(TOKEN_SUPPORT, threaded=False)
app = Flask(__name__)

# ===== БАЗЫ ДАННЫХ =====
def load_json(filename, default=None):
    if default is None:
        default = {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Базы
users = load_json('users.json', {})
girls = load_json('girls.json', {"girls": []})
applications = load_json('applications.json', {"apps": []})
banners = load_json('banners.json', {})
support_chats = load_json('support_chats.json', {"active": {}, "archive": {}, "current_chat": None})
promos = load_json('promos.json', {"FIRST30": {"discount": 30, "used_by": []}})
banned = load_json('banned.json', {"banned": []})["banned"]
stats = load_json('stats.json', {"total_deposits": 0, "total_bookings": 0})

# ===== УТИЛИТЫ =====
def get_username(uid):
    try:
        user = bot.get_chat(uid)
        return f"@{user.username}" if user.username else f"ID:{uid}"
    except:
        return f"ID:{uid}"

def update_course():
    global USDT_RATE
    try:
        resp = requests.get('https://belarusbank.by/api/kursExchange', timeout=5)
        data = resp.json()
        USD_in = float(data[0]['USD_in'])
        USDT_RATE = round(USD_in, 2)
        print(f"Курс USDT обновлён: {USDT_RATE}")
    except Exception as e:
        print(f"Ошибка курса: {e}")

def get_usdt_amount(byn_amount):
    return round(byn_amount / USDT_RATE, 2)

def log_to_group(text, photo=None):
    try:
        if photo:
            bot.send_photo(GROUP_LOGS, photo, caption=text)
        else:
            bot.send_message(GROUP_LOGS, text)
    except:
        pass

def is_banned(uid):
    return str(uid) in banned

def generate_promo(uid):
    return f"SWILL{uid[-4:].upper()}"

def apply_promo(uid, code, amount):
    if code == "FIRST30" and uid not in promos["FIRST30"]["used_by"]:
        promos["FIRST30"]["used_by"].append(uid)
        save_json('promos.json', promos)
        return int(amount * 0.7)  # Скидка 30%
    
    # Проверка личных промокодов
    for user_uid, user_data in users.items():
        if user_data.get('promo_code') == code and user_uid != uid:
            # Начисляем бонус владельцу
            users[user_uid]['invited'] = users[user_uid].get('invited', 0) + 1
            save_json('users.json', users)
            return int(amount * 0.8)  # Скидка 20%
    
    return amount  # Без скидки

# Обновляем курс при старте
update_course()

# ===== WEBAPP ДАННЫЕ =====
@app.route('/api/user/<uid>')
def api_user(uid):
    if uid not in users:
        return json.dumps({"error": "not found"})
    return json.dumps(users[uid])

@app.route('/api/girls')
def api_girls():
    return json.dumps(girls["girls"])

@app.route('/api/rate')
def api_rate():
    return json.dumps({"rate": USDT_RATE, "address": USDT_ADDRESS})

@app.route('/api/check_promo/<code>')
def api_check_promo(code):
    if code == "FIRST30":
        return json.dumps({"valid": True, "discount": 30})
    for uid, data in users.items():
        if data.get('promo_code') == code:
            return json.dumps({"valid": True, "discount": 20, "owner_uid": uid})
    return json.dumps({"valid": False})

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    uid = str(data.get('uid'))
    name = data.get('name', 'Гость')
    birthday = data.get('birthday', '')
    pin = data.get('pin', '0000')
    promo_input = data.get('promo', '')
    
    if uid in users:
        return json.dumps({"success": False, "error": "already exists"})
    
    promo_code = generate_promo(uid)
    
    # Если ввели чужой промокод — начисляем бонус
    if promo_input and promo_input != promo_code:
        for u, ud in users.items():
            if ud.get('promo_code') == promo_input:
                users[u]['invited'] = users[u].get('invited', 0) + 1
                save_json('users.json', users)
                log_to_group(f"👥 @{name} зарегистрировался по коду {promo_input} (владелец: {get_username(u)})")
    
    users[uid] = {
        "name": name,
        "birthday": birthday,
        "pin": pin,
        "promo_code": promo_code,
        "balance": 0,
        "invited": 0,
        "history": [],
        "created": datetime.now(MINSK).strftime('%d.%m.%Y %H:%M')
    }
    
    save_json('users.json', users)
    log_to_group(f"🆕 Новый пользователь: {name} ({uid})\n🎂 {birthday}\n🎟 Промокод: {promo_code}")
    
    return json.dumps({"success": True, "promo_code": promo_code})

@app.route('/api/deposit', methods=['POST'])
def api_deposit():
    data = request.json
    uid = str(data.get('uid'))
    amount = int(data.get('amount', 0))
    
    if uid not in users:
        return json.dumps({"success": False, "error": "not found"})
    
    # Не пополняем баланс!
    users[uid]['history'].append({
        "action": "deposit",
        "amount": amount,
        "date": datetime.now(MINSK).strftime('%d.%m.%Y %H:%M')
    })
    save_json('users.json', users)
    
    stats['total_deposits'] = stats.get('total_deposits', 0) + amount
    
    name = get_username(uid)
    log_to_group(f"💰 {name} ({uid}) пополнил баланс на {amount} BYN")
    
    return json.dumps({"success": True, "balance": users[uid]['balance']})

@app.route('/api/book', methods=['POST'])
def api_book():
    data = request.json
    uid = str(data.get('uid'))
    girl_id = int(data.get('girl_id', 0))
    hours = int(data.get('hours', 1))
    promo_code = data.get('promo', '')
    
    girl = None
    for g in girls['girls']:
        if g['id'] == girl_id:
            girl = g
            break
    
    if not girl:
        return json.dumps({"success": False, "error": "girl not found"})
    
    price = girl['price_1h'] * hours
    final_price = apply_promo(uid, promo_code, price)
    
    # Баланс всегда 0, поэтому "недостаточно средств"
    if users[uid]['balance'] < final_price:
        return json.dumps({"success": False, "error": "insufficient_funds", "price": final_price})
    
    # Теоретически недостижимо, но пусть будет
    users[uid]['balance'] -= final_price
    users[uid]['history'].append({
        "action": "booking",
        "girl": girl['name'],
        "price": final_price,
        "date": datetime.now(MINSK).strftime('%d.%m.%Y %H:%M')
    })
    save_json('users.json', users)
    
    stats['total_bookings'] = stats.get('total_bookings', 0) + 1
    
    name = get_username(uid)
    log_to_group(f"👩 {name} ({uid}) забронировал {girl['name']} за {final_price} BYN")
    
    return json.dumps({"success": True, "girl": girl['name'], "price": final_price})

@app.route('/api/support', methods=['POST'])
def api_support():
    data = request.json
    uid = str(data.get('uid'))
    text = data.get('text', '')
    topic = data.get('topic', 'Другое')
    
    name = users.get(uid, {}).get('name', get_username(uid))
    
    # Отправляем в группу поддержки
    msg = f"🔔 Новое обращение!\n👤 {name} ({uid})\n📂 Тема: {topic}\n💬 {text}\n\nДля подключения: /connect {uid}"
    support_bot.send_message(GROUP_SUPPORT, msg)
    
    # Сохраняем чат
    if uid not in support_chats['active']:
        support_chats['active'][uid] = {
            "name": name,
            "topic": topic,
            "messages": [],
            "status": "waiting"
        }
    support_chats['active'][uid]['messages'].append({"from": "user", "text": text})
    save_json('support_chats.json', support_chats)
    
    return json.dumps({"success": True})

@app.route('/api/check_messages/<uid>')
def api_check_messages(uid):
    if uid in support_chats['active']:
        msgs = support_chats['active'][uid]['messages']
        # Отдаём только новые сообщения от поддержки
        support_msgs = [m for m in msgs if m['from'] == 'support']
        return json.dumps({"messages": support_msgs, "status": support_chats['active'][uid]['status']})
    return json.dumps({"messages": [], "status": "offline"})

@app.route('/api/apply', methods=['POST'])
def api_apply():
    data = request.json
    uid = str(data.get('uid', ''))
    
    # Проверка на повторную заявку
    for app in applications['apps']:
        if app['uid'] == uid:
            return json.dumps({"success": False, "error": "already_applied"})
    
    app_data = {
        "uid": uid,
        "name": data.get('name', ''),
        "age": data.get('age', ''),
        "city": data.get('city', 'Минск'),
        "height": data.get('height', ''),
        "weight": data.get('weight', ''),
        "chest": data.get('chest', ''),
        "date": datetime.now(MINSK).strftime('%d.%m.%Y %H:%M')
    }
    applications['apps'].append(app_data)
    save_json('applications.json', applications)
    
    log_to_group(f"📩 Новая заявка от девушки!\n👤 {app_data['name']}\n📏 {app_data['height']}/{app_data['weight']}/{app_data['chest']}\n🏙 {app_data['city']}")
    
    return json.dumps({"success": True})

# ===== КОМАНДЫ ОСНОВНОГО БОТА =====
@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = str(message.chat.id)
    if is_banned(uid):
        bot.send_message(uid, '⛔ Вы заблокированы.')
        return
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton(
        "🔥 Открыть приложение",
        web_app=telebot.types.WebAppInfo(url=STATIC_URL)
    ))
    bot.send_message(uid, "Добро пожаловать в SWILL ESCORT!", reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    uid = str(message.chat.id)
    if uid != str(ADMIN_ID):
        return
    
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("👩 Девушки", callback_data='admin_girls'),
        telebot.types.InlineKeyboardButton("📊 Статистика", callback_data='admin_stats'),
        telebot.types.InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'),
        telebot.types.InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast'),
        telebot.types.InlineKeyboardButton("🖼 Баннеры", callback_data='admin_banners'),
        telebot.types.InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')
    )
    bot.send_message(uid, "🛠 Панель управления", reply_markup=markup)

# ===== CALLBACKS АДМИНКИ =====
@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callbacks(call):
    uid = str(call.message.chat.id)
    if uid != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "❌")
        return
    
    action = call.data
    
    if action == 'admin_girls':
        show_girls_list(uid, call.message.message_id)
    
    elif action == 'admin_stats':
        total_users = len(users)
        total_dep = stats.get('total_deposits', 0)
        total_book = stats.get('total_bookings', 0)
        text = f"📊 Статистика:\n\n👥 Юзеров: {total_users}\n💰 Пополнений: {total_dep} BYN\n👩 Броней: {total_book}\n📩 Заявок: {len(applications['apps'])}"
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=back_button('admin'))
    
    elif action == 'admin_users':
        text = "👥 Пользователи:\n\n"
        for u, data in list(users.items())[:10]:
            text += f"• {data['name']} ({u}) — {data.get('invited', 0)} приглашено\n"
        if len(users) > 10:
            text += f"\n... и ещё {len(users) - 10}"
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=back_button('admin'))
    
    elif action == 'admin_banners':
        show_banners_menu(uid, call.message.message_id)
    
    elif action == 'admin_settings':
        text = f"⚙️ Настройки:\n\n💱 Курс USDT: {USDT_RATE} BYN\n💰 Адрес: {USDT_ADDRESS[:10]}..."
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🔄 Обновить курс", callback_data='admin_update_course'))
        markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data='admin'))
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=markup)
    
    elif action == 'admin_update_course':
        update_course()
        bot.answer_callback_query(call.id, f"✅ Курс обновлён: {USDT_RATE}")
        admin_callbacks(call)
    
    elif action == 'admin_broadcast':
        bot.edit_message_text("Введите текст рассылки:\n(отправьте сообщение после этого)", uid, call.message.message_id)
        bot.register_next_step_handler(call.message, process_broadcast)
    
    elif action == 'admin':
        admin_cmd(call.message)
    
    bot.answer_callback_query(call.id)

def show_girls_list(chat_id, msg_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    for g in girls['girls']:
        markup.add(telebot.types.InlineKeyboardButton(
            f"{g['name']} ({g['age']} лет)",
            callback_data=f'girl_edit_{g["id"]}'
        ))
    markup.add(telebot.types.InlineKeyboardButton("➕ Добавить", callback_data='girl_add'))
    markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data='admin'))
    bot.edit_message_text("👩 Девушки:", chat_id, msg_id, reply_markup=markup)

def show_banners_menu(chat_id, msg_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    keys = {
        'register': '📱 Регистрация',
        'login': '🔑 Вход',
        'catalog': '🏠 Каталог',
        'profile': '👤 Профиль',
        'chat': '💬 Чат',
        'deposit': '💳 Пополнение'
    }
    for key, name in keys.items():
        markup.add(telebot.types.InlineKeyboardButton(name, callback_data=f'banner_set_{key}'))
    markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data='admin'))
    bot.edit_message_text("🖼 Выберите экран для смены баннера\n(отправьте фото после выбора)", chat_id, msg_id, reply_markup=markup)

def back_button(data):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data=data))
    return markup

def process_broadcast(message):
    text = message.text
    sent = 0
    for uid in users:
        try:
            bot.send_message(uid, text)
            sent += 1
        except:
            pass
    bot.send_message(message.chat.id, f"📢 Отправлено {sent} пользователям")

# ===== WEBHOOK ОСНОВНОГО БОТА =====
@app.route('/' + TOKEN_MAIN, methods=['POST'])
def webhook_main():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '!', 200
    return 'Bad request', 400

# ===== WEBHOOK СУППОРТ БОТА =====
@app.route('/support/' + TOKEN_SUPPORT, methods=['POST'])
def webhook_support():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        support_bot.process_new_updates([update])
        return '!', 200
    return 'Bad request', 400

# ===== ГЛАВНАЯ СТРАНИЦА =====
@app.route('/')
def webapp():
    return send_from_directory('static', 'index.html')

# ===== УСТАНОВКА ВЕБХУКОВ =====
@app.route('/setup')
def setup():
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(STATIC_URL + '/' + TOKEN_MAIN)
        
        support_bot.remove_webhook()
        time.sleep(1)
        support_bot.set_webhook(STATIC_URL + '/support/' + TOKEN_SUPPORT)
        
        return 'Webhooks set!', 200
    except Exception as e:
        return f'Error: {e}', 500

# ===== СТАТИКА =====
@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# ===== ЗАПУСК =====
if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    
    # Устанавливаем вебхуки при старте
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(STATIC_URL + '/' + TOKEN_MAIN)
        print("Основной бот: вебхук установлен")
    except Exception as e:
        print(f"Ошибка основного вебхука: {e}")
    
    try:
        support_bot.remove_webhook()
        time.sleep(1)
        support_bot.set_webhook(STATIC_URL + '/support/' + TOKEN_SUPPORT)
        print("Бот поддержки: вебхук установлен")
    except Exception as e:
        print(f"Ошибка вебхука поддержки: {e}")
    
    print("Сервер запущен!")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
