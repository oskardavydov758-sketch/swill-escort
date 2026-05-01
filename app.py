import os
import telebot
import time
import json
import requests
from datetime import datetime, timedelta, timezone as tz
from flask import Flask, request, send_from_directory

# Конфигурация
TOKEN_MAIN = '8786865345:AAGMia7IGPwKNqjc1BUp1y5W9yh_bf-UNaY'
TOKEN_SUPPORT = '8761438748:AAEGdL24efQbIk9eIC9-bz3nfasPwFR9NjQ'
ADMIN_ID = 5852338439
GROUP_LOGS = -5235487009
GROUP_SUPPORT = -5235487009
STATIC_URL = 'https://swill-escort.onrender.com'
MINSK = tz(timedelta(hours=3))
USDT_ADDRESS = 'TCFRmpHnmthD8UiENTwvedaRU6kJv2uBdg'
USDT_RATE = 2.82

bot = telebot.TeleBot(TOKEN_MAIN, threaded=False)
support_bot = telebot.TeleBot(TOKEN_SUPPORT, threaded=False)
app = Flask(__name__)

# ===== БАЗЫ =====
def load_json(filename, default=None):
    if default is None: default = {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users = load_json('users.json', {})
girls = load_json('girls.json', {"girls": []})
applications = load_json('applications.json', {"apps": []})
banners = load_json('banners.json', {})
support_chats = load_json('support_chats.json', {"active": {}, "archive": {}, "current_chat": None})
promos = load_json('promos.json', {"FIRST30": {"discount": 30, "used_by": []}})
banned = load_json('banned.json', {"banned": []})["banned"]
stats = load_json('stats.json', {"total_deposits": 0, "total_bookings": 0})
admin_states = {}

def update_course():
    global USDT_RATE
    try:
        resp = requests.get('https://belarusbank.by/api/kursExchange', timeout=5)
        USD_in = float(resp.json()[0]['USD_in'])
        USDT_RATE = round(USD_in, 2)
    except: pass

def log_to_group(text): 
    try: bot.send_message(GROUP_LOGS, text)
    except: pass

def get_username(uid):
    try:
        u = bot.get_chat(uid)
        return f"@{u.username}" if u.username else f"ID:{uid}"
    except: return f"ID:{uid}"

def generate_promo(uid): return f"SWILL{uid[-4:].upper()}"

def back_button(data):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data=data))
    return markup

update_course()

# ===== API =====
@app.route('/api/user/<uid>')
def api_user(uid):
    if uid not in users: return json.dumps({"error": "not found"})
    return json.dumps(users[uid])

@app.route('/api/girls')
def api_girls():
    return json.dumps(girls["girls"])

@app.route('/api/rate')
def api_rate():
    return json.dumps({"rate": USDT_RATE, "address": USDT_ADDRESS})

@app.route('/api/register', methods=['POST'])
def api_register():
    d = request.json
    uid = str(d.get('uid'))
    if uid in users: return json.dumps({"success": False})
    promo_code = generate_promo(uid)
    if d.get('promo'):
        for u, ud in users.items():
            if ud.get('promo_code') == d['promo']:
                users[u]['invited'] = users[u].get('invited', 0) + 1
                save_json('users.json', users)
    users[uid] = {"name": d.get('name',''), "birthday": d.get('birthday',''), "pin": d.get('pin','0000'), "promo_code": promo_code, "balance": 0, "invited": 0, "history": [], "created": datetime.now(MINSK).strftime('%d.%m.%Y %H:%M')}
    save_json('users.json', users)
    log_to_group(f"🆕 {d.get('name')} ({uid}) | Промокод: {promo_code}")
    return json.dumps({"success": True, "promo_code": promo_code})

@app.route('/api/deposit', methods=['POST'])
def api_deposit():
    d = request.json
    uid = str(d.get('uid'))
    amt = int(d.get('amount', 0))
    if uid not in users: return json.dumps({"success": False})
    users[uid]['history'].append({"action": "deposit", "amount": amt, "date": datetime.now(MINSK).strftime('%d.%m.%Y %H:%M')})
    save_json('users.json', users)
    stats['total_deposits'] = stats.get('total_deposits', 0) + amt
    save_json('stats.json', stats)
    log_to_group(f"💰 {get_username(uid)} пополнил {amt} BYN")
    return json.dumps({"success": True, "balance": users[uid]['balance']})

@app.route('/api/book', methods=['POST'])
def api_book():
    d = request.json
    uid = str(d.get('uid'))
    gid = int(d.get('girl_id', 0))
    girl = next((g for g in girls['girls'] if g['id'] == gid), None)
    if not girl: return json.dumps({"success": False})
    price = girl['price_1h'] * int(d.get('hours', 1))
    users[uid]['history'].append({"action": "booking", "girl": girl['name'], "price": price, "date": datetime.now(MINSK).strftime('%d.%m.%Y %H:%M')})
    save_json('users.json', users)
    stats['total_bookings'] = stats.get('total_bookings', 0) + 1
    save_json('stats.json', stats)
    log_to_group(f"👩 {get_username(uid)} → {girl['name']} ({price} BYN)")
    return json.dumps({"success": False, "error": "insufficient_funds", "price": price})

@app.route('/api/support', methods=['POST'])
def api_support():
    d = request.json
    uid, text, topic = str(d.get('uid')), d.get('text',''), d.get('topic','')
    name = users.get(uid, {}).get('name', get_username(uid))
    support_bot.send_message(GROUP_SUPPORT, f"🔔 {name} ({uid})\n📂 {topic}\n💬 {text}\n\n/connect {uid}")
    if uid not in support_chats['active']:
        support_chats['active'][uid] = {"name": name, "topic": topic, "messages": [], "status": "waiting"}
    support_chats['active'][uid]['messages'].append({"from": "user", "text": text})
    save_json('support_chats.json', support_chats)
    return json.dumps({"success": True})

@app.route('/api/apply', methods=['POST'])
def api_apply():
    d = request.json
    uid = str(d.get('uid',''))
    if any(a['uid'] == uid for a in applications['apps']):
        return json.dumps({"success": False, "error": "already_applied"})
    applications['apps'].append({"uid": uid, "name": d.get('name',''), "age": d.get('age',''), "city": d.get('city','Минск'), "height": d.get('height',''), "weight": d.get('weight',''), "chest": d.get('chest',''), "date": datetime.now(MINSK).strftime('%d.%m.%Y %H:%M')})
    save_json('applications.json', applications)
    log_to_group(f"📩 Заявка: {d.get('name')} | {d.get('height')}/{d.get('weight')}/{d.get('chest')}")
    return json.dumps({"success": True})

# ===== БОТ =====
@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if str(msg.chat.id) in banned: return bot.send_message(msg.chat.id, '⛔ Бан')
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🔥 Открыть приложение", web_app=telebot.types.WebAppInfo(url=STATIC_URL)))
    bot.send_message(msg.chat.id, "SWILL ESCORT", reply_markup=markup)

@bot.message_handler(commands=['admin'])
def admin_cmd(msg):
    if str(msg.chat.id) != str(ADMIN_ID): return
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("👩 Девушки", callback_data='admin_girls'),
        telebot.types.InlineKeyboardButton("📊 Статистика", callback_data='admin_stats'),
        telebot.types.InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'),
        telebot.types.InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast'),
        telebot.types.InlineKeyboardButton("🖼 Баннеры", callback_data='admin_banners'),
        telebot.types.InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings'))
    bot.send_message(msg.chat.id, "🛠 Админ-панель", reply_markup=markup)

# ===== CALLBACKS =====
@bot.callback_query_handler(func=lambda c: True)
def all_callbacks(call):
    uid = str(call.message.chat.id)
    if uid != str(ADMIN_ID): return bot.answer_callback_query(call.id)
    data = call.data
    
    # Админ-главная
    if data == 'admin': admin_cmd(call.message)
    elif data == 'admin_girls': show_girls(uid, call.message.message_id)
    elif data == 'admin_stats':
        text = f"📊 Юзеров: {len(users)}\n💰 Пополнений: {stats.get('total_deposits',0)} BYN\n👩 Броней: {stats.get('total_bookings',0)}\n📩 Заявок: {len(applications['apps'])}"
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=back_button('admin'))
    elif data == 'admin_users':
        text = "👥 Пользователи:\n\n" + "\n".join(f"• {v['name']} ({k})" for k,v in list(users.items())[:15])
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=back_button('admin'))
    elif data == 'admin_banners': show_banners(uid, call.message.message_id)
    elif data == 'admin_broadcast':
        bot.edit_message_text("Отправьте текст рассылки:", uid, call.message.message_id)
        bot.register_next_step_handler(call.message, lambda m: broadcast(m))
    elif data == 'admin_settings':
        text = f"⚙️ Курс USDT: {USDT_RATE} BYN\nАдрес: {USDT_ADDRESS[:10]}..."
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🔄 Обновить курс", callback_data='admin_update_course'))
        markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data='admin'))
        bot.edit_message_text(text, uid, call.message.message_id, reply_markup=markup)
    elif data == 'admin_update_course':
        update_course()
        bot.answer_callback_query(call.id, f"✅ {USDT_RATE}")
        all_callbacks(call)
    
    # Девушки
    elif data == 'girl_add':
        admin_states[uid] = 'adding_girl'
        bot.edit_message_text("Введите имя девушки:", uid, call.message.message_id)
    elif data.startswith('girl_edit_'):
        gid = int(data.replace('girl_edit_',''))
        girl = next((g for g in girls['girls'] if g['id'] == gid), None)
        if girl:
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🗑 Удалить", callback_data=f'girl_delete_{gid}'))
            markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data='admin_girls'))
            bot.edit_message_text(f"👩 {girl['name']}, {girl['age']} лет\n{girl['height']}/{girl['weight']}/{girl['chest']}\n💰 {girl['price_1h']} BYN", uid, call.message.message_id, reply_markup=markup)
    elif data.startswith('girl_delete_'):
        gid = int(data.replace('girl_delete_',''))
        girls['girls'] = [g for g in girls['girls'] if g['id'] != gid]
        save_json('girls.json', girls)
        bot.answer_callback_query(call.id, "✅ Удалена")
        show_girls(uid, call.message.message_id)
    
    # Баннеры
    elif data.startswith('banner_set_'):
        key = data.replace('banner_set_', '')
        admin_states[uid] = f'banner_{key}'
        bot.edit_message_text(f"🖼 Отправьте фото для баннера '{key}':", uid, call.message.message_id)
    
    bot.answer_callback_query(call.id)

def show_girls(chat_id, msg_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    for g in girls['girls']:
        markup.add(telebot.types.InlineKeyboardButton(f"{g['name']} ({g['age']})", callback_data=f'girl_edit_{g["id"]}'))
    markup.add(telebot.types.InlineKeyboardButton("➕ Добавить", callback_data='girl_add'))
    markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data='admin'))
    bot.edit_message_text("👩 Девушки:", chat_id, msg_id, reply_markup=markup)

def show_banners(chat_id, msg_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for key, name in {'register':'📱 Регистрация','login':'🔑 Вход','catalog':'🏠 Каталог','profile':'👤 Профиль','chat':'💬 Чат','deposit':'💳 Пополнение'}.items():
        markup.add(telebot.types.InlineKeyboardButton(name, callback_data=f'banner_set_{key}'))
    markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data='admin'))
    bot.edit_message_text("🖼 Баннеры:", chat_id, msg_id, reply_markup=markup)

def broadcast(msg):
    c = sum(1 for u in users if not bot.send_message(u, msg.text).json.get('ok'))
    bot.send_message(msg.chat.id, f"📢 Отправлено ~{len(users)-c}")

# ===== ОБРАБОТКА ФОТО/ТЕКСТА ДЛЯ АДМИНА =====
@bot.message_handler(content_types=['photo', 'text'])
def admin_input(msg):
    uid = str(msg.chat.id)
    if uid != str(ADMIN_ID): return
    
    state = admin_states.get(uid, '')
    
    if state == 'adding_girl':
        # Пошаговое добавление
        admin_states[uid] = {'step': 1, 'name': msg.text}
        bot.send_message(uid, "Возраст:")
    elif isinstance(state, dict):
        step = state['step']
        if step == 1:
            state['age'] = int(msg.text)
            state['step'] = 2
            bot.send_message(uid, "Рост:")
        elif step == 2:
            state['height'] = int(msg.text)
            state['step'] = 3
            bot.send_message(uid, "Вес:")
        elif step == 3:
            state['weight'] = int(msg.text)
            state['step'] = 4
            bot.send_message(uid, "Размер груди:")
        elif step == 4:
            state['chest'] = msg.text
            state['step'] = 5
            bot.send_message(uid, "Цена за 1 час:")
        elif step == 5:
            state['price_1h'] = int(msg.text)
            state['step'] = 6
            bot.send_message(uid, "Описание:")
        elif step == 6:
            state['desc'] = msg.text
            state['step'] = 7
            bot.send_message(uid, "Отправьте фото девушки:")
        elif step == 7 and msg.photo:
            new_id = max([g['id'] for g in girls['girls']], default=0) + 1
            girls['girls'].append({
                "id": new_id, "name": state['name'], "age": state['age'],
                "height": state['height'], "weight": state['weight'], "chest": state['chest'],
                "price_1h": state['price_1h'], "description": state.get('desc',''),
                "photos": [msg.photo[-1].file_id], "rating": 4.8, "reviews": []
            })
            save_json('girls.json', girls)
            admin_states.pop(uid)
            bot.send_message(uid, f"✅ Девушка #{new_id} добавлена!")
    
    elif state.startswith('banner_'):
        key = state.replace('banner_', '')
        if msg.photo:
            banners[key] = msg.photo[-1].file_id
            save_json('banners.json', banners)
            admin_states.pop(uid)
            bot.send_message(uid, f"✅ Баннер '{key}' обновлён!")

# ===== SUPPORT BOT =====
@support_bot.message_handler(commands=['connect'])
def support_connect(msg):
    args = msg.text.split()
    if len(args) < 2: return support_bot.reply_to(msg, "/connect <uid>")
    uid = args[1]
    if uid in support_chats['active']:
        support_chats['current_chat'] = uid
        support_chats['active'][uid]['status'] = 'active'
        save_json('support_chats.json', support_chats)
        support_bot.reply_to(msg, f"✅ Подключён к {uid}")

@support_bot.message_handler(commands=['endchat'])
def support_end(msg):
    args = msg.text.split()
    if len(args) < 2: return support_bot.reply_to(msg, "/endchat <uid>")
    uid = args[1]
    if uid in support_chats['active']:
        support_chats['active'][uid]['status'] = 'ended'
        support_chats['active'][uid]['messages'].append({"from": "support", "text": "Оператор закончил связь."})
        support_chats['archive'][uid] = support_chats['active'].pop(uid)
        support_chats['current_chat'] = None
        save_json('support_chats.json', support_chats)
        support_bot.reply_to(msg, f"✅ Чат с {uid} завершён")

@support_bot.message_handler(commands=['switch'])
def support_switch(msg):
    args = msg.text.split()
    if len(args) < 2: return support_bot.reply_to(msg, "/switch <uid>")
    uid = args[1]
    if uid in support_chats['active']:
        support_chats['current_chat'] = uid
        save_json('support_chats.json', support_chats)
        support_bot.reply_to(msg, f"🔄 Переключён на {uid}")

@support_bot.message_handler(commands=['active'])
def support_active(msg):
    text = "📋 Активные чаты:\n\n"
    for uid, data in support_chats['active'].items():
        text += f"{'🟢' if uid == support_chats.get('current_chat') else '🟡'} {data['name']} ({uid}) — {data['topic']}\n"
    support_bot.reply_to(msg, text or "Нет активных чатов")

# ===== WEBHOOKS =====
@app.route('/' + TOKEN_MAIN, methods=['POST'])
def wh_main():
    if request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([telebot.types.Update.de_json(request.get_data().decode('utf-8'))])
        return '!', 200
    return 'Bad request', 400

@app.route('/support/' + TOKEN_SUPPORT, methods=['POST'])
def wh_support():
    if request.headers.get('content-type') == 'application/json':
        support_bot.process_new_updates([telebot.types.Update.de_json(request.get_data().decode('utf-8'))])
        return '!', 200
    return 'Bad request', 400

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/setup')
def setup():
    bot.remove_webhook(); time.sleep(1); bot.set_webhook(STATIC_URL + '/' + TOKEN_MAIN)
    support_bot.remove_webhook(); time.sleep(1); support_bot.set_webhook(STATIC_URL + '/support/' + TOKEN_SUPPORT)
    return 'Webhooks set!'

@app.route('/<path:fn>')
def static_files(fn):
    return send_from_directory('static', fn)

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    bot.remove_webhook(); time.sleep(1); bot.set_webhook(STATIC_URL + '/' + TOKEN_MAIN)
    support_bot.remove_webhook(); time.sleep(1); support_bot.set_webhook(STATIC_URL + '/support/' + TOKEN_SUPPORT)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
