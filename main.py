import sqlite3
import json
import time
from vk_api import VkApi
from vk_api.longpoll import VkLongPoll, VkEventType

import os  # Добавь этот импорт в самый верх кода, если его там нет

# ================= НАСТРОЙКИ БОТА =================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6721265"))  # Если переменной нет, возьмет этот ID
STORAGE_NICK = os.getenv("STORAGE_NICK", "yuked")

# Инициализация VK API
vk_session = VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

# ================= РАБОТА С БАЗОЙ ДАННЫХ =================
def init_db():
    conn = sqlite3.connect("vimeworld_bot.db")
    cursor = conn.cursor()
    
    # Таблица конфигурации (бюджеты)
    cursor.execute('''CREATE TABLE IF NOT EXISTS config (param TEXT PRIMARY KEY, val REAL)''')
    cursor.execute("INSERT OR IGNORE INTO config VALUES ('budget_rub', 10000.0)")
    cursor.execute("INSERT OR IGNORE INTO config VALUES ('budget_vim', 5000.0)")
    cursor.execute("INSERT OR IGNORE INTO config VALUES ('min_buy_amount', 10.0)")
    
    # Таблица пользователей (состояния, скидки, статусы)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY, 
                        status TEXT DEFAULT 'User', 
                        discount REAL DEFAULT 0.0,
                        state TEXT DEFAULT 'menu',
                        temp_amount REAL DEFAULT 0.0
                    )''')
    
    # Таблица сделок (для статистики)
    cursor.execute('''CREATE TABLE IF NOT EXISTS deals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        type TEXT,
                        amount_vim REAL,
                        amount_rub REAL,
                        date TEXT
                    )''')
    conn.commit()
    conn.close()

def get_config(param):
    conn = sqlite3.connect("vimeworld_bot.db")
    res = conn.execute("SELECT val FROM config WHERE param = ?", (param,)).fetchone()[0]
    conn.close()
    return res

def update_config(param, value):
    conn = sqlite3.connect("vimeworld_bot.db")
    conn.execute("UPDATE config SET val = ? WHERE param = ?", (value, param))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("vimeworld_bot.db")
    user = conn.execute("SELECT status, discount, state, temp_amount FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not user:
        status = 'Admin' if user_id == ADMIN_ID else 'User'
        conn.execute("INSERT INTO users (user_id, status) VALUES (?, ?)", (user_id, status))
        conn.commit()
        user = (status, 0.0, 'menu', 0.0)
    conn.close()
    return {"status": user[0], "discount": user[1], "state": user[2], "temp_amount": user[3]}

def update_user(user_id, **kwargs):
    conn = sqlite3.connect("vimeworld_bot.db")
    for key, value in kwargs.items():
        conn.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================
def send_msg(user_id, text, keyboard=None):
    params = {
        "user_id": user_id,
        "message": text,
        "random_id": 0
    }
    if keyboard:
        params["keyboard"] = json.dumps(keyboard, ensure_ascii=False)
    vk.messages.send(**params)

def get_vk_name(user_id):
    try:
        res = vk.users.get(user_ids=user_id)[0]
        return f"{res['first_name']} {res['last_name']}"
    except:
        return f"User_{user_id}"

def get_current_date():
    return time.strftime("%Y-%m-%d")

# ================= КЛАВИАТУРЫ (KEYBOARDS) =================
main_keyboard = {
    "one_time": False,
    "buttons": [
        [
            {"action": {"type": "text", "label": "🔮 Купить Вимеры"}, "color": "positive"},
            {"action": {"type": "text", "label": "💰 Продать Вимеры"}, "color": "negative"}
        ],
        [
            {"action": {"type": "text", "label": "📊 Информация"}, "color": "primary"},
            {"action": {"type": "text", "label": "👤 Профиль"}, "color": "primary"}
        ],
        [
            {"action": {"type": "open_link", "link": "https://vk.com/topic-123_456", "label": "⭐ Отзывы"}},
            {"action": {"type": "open_link", "link": "https://vk.com/rejiboy", "label": "🆘 Поддержка"}}
        ]
    ]
}

cancel_keyboard = {
    "one_time": False,
    "buttons": [[{"action": {"type": "text", "label": "❌ Отмена"}, "color": "secondary"}]]
}

# Обновленная клавиатура с добавлением кнопки-ссылки FunPay
pay_methods_keyboard = {
    "one_time": False,
    "buttons": [
        [
            {"action": {"type": "text", "label": "📱 СБП"}, "color": "primary"},
            {"action": {"type": "text", "label": "💳 Банковская карта"}, "color": "primary"},
            {"action": {"type": "text", "label": "🤖 Cryptobot"}, "color": "primary"}
        ],
        [
            {"action": {"type": "open_link", "link": "https://funpay.com/users/19311544/", "label": "🛒 Купить через FunPay"}}
        ],
        [{"action": {"type": "text", "label": "❌ Отмена"}, "color": "secondary"}]
    ]
}

def make_admin_inline(deal_id):
    return {
        "inline": True,
        "buttons": [
            [
                {"action": {"type": "text", "label": f"✅ Принять {deal_id}"}, "color": "positive"},
                {"action": {"type": "text", "label": f"❌ Отклонить {deal_id}"}, "color": "negative"}
            ]
        ]
    }

# ================= ЛОГИКА МАТЕМАТИКИ =================
def calc_buy(user_id, amount):
    u = get_user(user_id)
    base_rate = 0.35
    personal_rate = base_rate * (1 - u["discount"] / 100)
    final_rate = min(0.3, personal_rate) if amount >= 15000 else personal_rate
    return round(amount * final_rate, 2), round(final_rate, 2)

def calc_sell(user_id, amount):
    u = get_user(user_id)
    base_rate = 0.22
    personal_rate = base_rate * (1 + u["discount"] / 100)
    final_rate = max(0.25, personal_rate) if amount >= 10000 else personal_rate
    return round(amount * final_rate, 2), round(final_rate, 2)

# ================= ОСНОВНОЙ ЦИКЛ БОТА =================
init_db()
print("🚀 Бот успешно запущен и слушает сервер VK...")

for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        user_id = event.user_id
        text = event.text.strip()
        text_lower = text.lower()
        
        u = get_user(user_id)
        
        # --- ОБРАБОТКА КНОПКИ «ОТМЕНА» ---
        if text_lower == "❌ отмена" or text_lower in ["начать", "старт", "меню"]:
            update_user(user_id, state="menu", temp_amount=0.0)
            send_msg(user_id, "👋 Вы вернулись в главное меню. Выберите интересующий раздел:", main_keyboard)
            continue

        # --- СОСТОЯНИЕ: ОЖИДАНИЕ ВВОДА СУММЫ ДЛЯ ПОКУПКИ ---
        if u["state"] == "wait_buy_amount":
            try:
                amount = float(text)
                
                min_buy = get_config("min_buy_amount")
                if amount < min_buy:
                    send_msg(user_id, f"⚠️ Минимальная сумма покупки сейчас составляет — {int(min_buy)} Вимеров. Введите другое число:")
                    continue
                
                b_vim = get_config("budget_vim")
                if amount > b_vim:
                    send_msg(user_id, f"⚠️ Извини, на балансе бота нет столько вимеров. Доступно: {b_vim} вим.\nВведите сумму меньше:")
                    continue
                
                update_user(user_id, state="wait_buy_nickname", temp_amount=amount)
                
                nick_msg = ("🎮 **Введите ваш никнейм на VimeWorld**, на который нужно зачислить Вимеры:\n\n"
                            "⚠️ **ВАЖНОЕ ПРЕДУПРЕЖДЕНИЕ:**\n"
                            "Пожалуйста, будьте максимально внимательны и осторожны! "
                            "Если вы укажете никнейм с ошибкой, **вернуть Вимеры будет невозможно**, "
                            "так как они уйдут на чужой аккаунт.")
                send_msg(user_id, nick_msg, cancel_keyboard)
            except ValueError:
                send_msg(user_id, "❌ Пожалуйста, введите корректное число (например: 500):")
            continue

        # --- СОСТОЯНИЕ: ОЖИДАНИЕ НИКНЕЙМА ДЛЯ ПОКУПКИ ---
        if u["state"] == "wait_buy_nickname":
            user_nickname = text
            update_user(user_id, state=f"wait_pay_method:{user_nickname}")
            
            pay_msg = ("💳 **Выберите удобный способ оплаты:**\n\n"
                       "ℹ️ *Вы можете оплатить напрямую по реквизитам (СБП, Карта, Крипта) "
                       "или провести безопасную сделку через торговую площадку FunPay по кнопке ниже.*")
            send_msg(user_id, pay_msg, pay_methods_keyboard)
            continue

        # --- СОСТОЯНИЕ: ВЫБОР СПОСОБА ОПЛАТЫ ДЛЯ ПОКУПКИ ---
        if u["state"].startswith("wait_pay_method:"):
            user_nickname = u["state"].split(":")[1]
            
            if text in ["📱 СБП", "💳 Банковская карта", "🤖 Cryptobot"]:
                amount = u["temp_amount"]
                total_rub, rate = calc_buy(user_id, amount)
                method_name = text.replace("📱 ", "").replace("💳 ", "").replace("🤖 ", "")
                
                conn = sqlite3.connect("vimeworld_bot.db")
                cursor = conn.cursor()
                cursor.execute("INSERT INTO deals (user_id, type, amount_vim, amount_rub, date) VALUES (?, ?, ?, ?, ?)", 
                               (user_id, f"buy_wait_{method_name}:{user_nickname}", amount, total_rub, get_current_date()))
                deal_id = cursor.lastrowid
                conn.commit()
                conn.close()
                
                if text == "📱 СБП":
                    req_text = "📱 **Реквизиты СБП:**\n• Номер: `+33768709358` (ЮМани)\n• Получатель: `Мария Михайловна`\n⚠️ *Перепроверяйте информацию при переводе!*"
                elif text == "💳 Банковская карта":
                    req_text = "💳 **Реквизиты Банковской карты:**\n• Номер карты: `5599002133764888` (ЮМани)"
                else: 
                    req_text = "🤖 **Реквизиты Cryptobot:**\n• Пожалуйста, обратитесь к менеджеру: https://t.me/tewder\n🕒 *Рабочие часы: 9:00 - 0:00 МСК*"
                
                invoice_msg = (f"🔮 **Заявка #{deal_id} успешно создана!**\n\n"
                               f"🎮 Ник на VimeWorld: **{user_nickname}**\n"
                               f"📦 Товар: **{amount} Вимеров**\n"
                               f"💵 К оплате: **{total_rub} ₽**\n\n"
                               f"{req_text}\n\n"
                               f"👉 После того как выполните перевод, обязательно нажмите кнопку ниже:")
                
                pay_kb = {"one_time": False, "buttons": [[{"action": {"type": "text", "label": f"✅ Я оплатил #{deal_id}"}, "color": "positive"}]]}
                update_user(user_id, state="menu", temp_amount=0.0)
                send_msg(user_id, invoice_msg, pay_kb)
            else:
                send_msg(user_id, "❌ Пожалуйста, выберите способ оплаты, используя кнопки ниже:", pay_methods_keyboard)
            continue

        # --- СОСТОЯНИЕ: ОЖИДАНИЕ ВВОДА СУММЫ ДЛЯ ПРОДАЖИ ---
        if u["state"] == "wait_sell_amount":
            try:
                amount = float(text)
                if amount < 10:
                    send_msg(user_id, "⚠️ Минимальная сумма продажи — 10 Вимеров. Введите другое число:")
                    continue
                
                total_rub, rate = calc_sell(user_id, amount)
                b_rub = get_config("budget_rub")
                
                if total_rub > b_rub:
                    send_msg(user_id, f"⚠️ У бота нет столько рублей для выплаты. Наш бюджет: {b_rub} ₽. Введите сумму меньше:")
                    continue
                
                update_user(user_id, state="wait_sell_requisites", temp_amount=amount)
                send_msg(user_id, f"💰 Вы получите **{total_rub} ₽** за **{amount} Вимеров**.\n\n"
                                  f"👉 Напишите свои реквизиты (Номер карты / СБП с банком / ЮMoney) куда отправить рубли:", cancel_keyboard)
            except ValueError:
                send_msg(user_id, "❌ Пожалуйста, введите корректное число (например: 2000):")
            continue

        # --- СОСТОЯНИЕ: ОЖИДАНИЕ РЕКВИЗИТОВ ДЛЯ ВЫПЛАТЫ ---
        if u["state"] == "wait_sell_requisites":
            amount = u["temp_amount"]
            total_rub, rate = calc_sell(user_id, amount)
            
            conn = sqlite3.connect("vimeworld_bot.db")
            cursor = conn.cursor()
            cursor.execute("INSERT INTO deals (user_id, type, amount_vim, amount_rub, date) VALUES (?, 'sell_wait', ?, ?, ?)", 
                           (user_id, amount, total_rub, get_current_date()))
            deal_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            user_msg = (f"🔮 **Заявка #{deal_id} на продажу создана!**\n\n"
                        f"👉 Переведите **{amount} Вимеров** на аккаунт VimeWorld: `{STORAGE_NICK}`.\n\n"
                        f"📌 Ваши реквизиты для выплаты: {text}\n"
                        f"После того как переведете вимеры в игре, нажмите кнопку ниже:")
            
            send_kb = {"one_time": False, "buttons": [[{"action": {"type": "text", "label": f"✅ Я перевел вимеры #{deal_id}"}, "color": "positive"}]]}
            update_user(user_id, state="menu", temp_amount=0.0)
            send_msg(user_id, user_msg, send_kb)
            continue


        # ================= ОБРАБОТКА ОБЫЧНЫХ КНОПОК МЕНЮ =================
        
        if text == "🔮 Купить Вимеры":
            b_vim = get_config("budget_vim")
            update_user(user_id, state="wait_buy_amount")
            msg = (f"🔮 **Покупка Вимеров**\n\n"
                   f"📈 Актуальный курс: **0.35 ₽** за 1 Вимер\n"
                   f"👤 Ваша персональная скидка: **{u['discount']}%**\n\n"
                   f"🔥 **Выгодное предложение:**\n"
                   f"При покупке от **15 000 Вимеров**, цена снижается! Курс составит всего **0.3 ₽** за 1 Вимер.\n\n"
                   f"🏪 Доступно в магазине: **{b_vim} Вимеров**\n"
                   f"⚙️ *Минимальная сумма заказа — 10 Вимеров.*\n\n"
                   f"⬇️ **Введите желаемое количество Вимеров для покупки:**")
            send_msg(user_id, msg, cancel_keyboard)

        elif text == "💰 Продать Вимеры":
            b_rub = get_config("budget_rub")
            update_user(user_id, state="wait_sell_amount")
            msg = (f"💰 **Продажа Вимеров**\n\n"
                   f"📈 Базовый курс скупки: **0.22 ₽** за 1 Вимер\n"
                   f"➕ Ваша персональная надбавка: **+{u['discount']}%**\n\n"
                   f"🔥 **Оптовый бонус:**\n"
                   f"При продаже от **10 000 Вимеров**, ваш курс увеличивается! Цена составит **0.25 ₽** за 1 Вимер.\n\n"
                   f"🏦 Бюджет рублей у бота: **{b_rub} ₽**\n\n"
                   f"⬇️ **Введите количество Вимеров, которое хотите продать:**")
            send_msg(user_id, msg, cancel_keyboard)

        elif text == "📊 Информация":
            conn = sqlite3.connect("vimeworld_bot.db")
            total_vim = conn.execute("SELECT SUM(amount_vim) FROM deals WHERE type IN ('buy', 'sell')").fetchone()[0] or 0.0
            daily_vim = conn.execute("SELECT SUM(amount_vim) FROM deals WHERE type IN ('buy', 'sell') AND date = ?", (get_current_date(),)).fetchone()[0] or 0.0
            total_deals = conn.execute("SELECT COUNT(id) FROM deals WHERE type IN ('buy', 'sell')").fetchone()[0] or 0
            daily_deals = conn.execute("SELECT COUNT(id) FROM deals WHERE type IN ('buy', 'sell') AND date = ?", (get_current_date(),)).fetchone()[0] or 0
            conn.close()
            
            info_msg = (f"📊 **Общая информация и статистика бота**\n\n"
                        f"🔄 **Оборот Вимеров:**\n"
                        f"• За всё время: **{total_vim} Вимеров**\n"
                        f"• За сегодня: **{daily_vim} Вимеров**\n\n"
                        f"🤝 **Успешные сделки:**\n"
                        f"• Всего проведено: **{total_deals} шт.**\n"
                        f"• Проведено за сегодня: **{daily_deals} шт.**\n\n"
                        f"📈 **Текущие курсы:**\n"
                        f"• Магазин продает: **0.35 ₽** *(от 15к — 0.3 ₽)*\n"
                        f"• Магазин скупает: **0.22 ₽** *(от 10к — 0.25 ₽)*")
            send_msg(user_id, info_msg, main_keyboard)

        elif text == "👤 Профиль":
            conn = sqlite3.connect("vimeworld_bot.db")
            u_vim = conn.execute("SELECT SUM(amount_vim) FROM deals WHERE user_id = ? AND type IN ('buy', 'sell')", (user_id,)).fetchone()[0] or 0.0
            u_deals = conn.execute("SELECT COUNT(id) FROM deals WHERE user_id = ? AND type IN ('buy', 'sell')", (user_id,)).fetchone()[0] or 0
            conn.close()
            
            name = get_vk_name(user_id)
            prof_msg = (f"👤 **Ваш личный профиль**\n\n"
                        f"📝 **Данные аккаунта:**\n"
                        f"• Клиент: **{name}**\n"
                        f"• Ваш статус: **{u['status']}**\n"
                        f"• Персональная скидка/надбавка: **{u['discount']}%**\n\n"
                        f"📈 **Ваша активность:**\n"
                        f"• Личный оборот: **{u_vim} Вимеров**\n"
                        f"• Успешных сделок: **{u_deals} шт.**\n\n"
                        f"⚙️ *ID для поддержки: {user_id}*")
            send_msg(user_id, prof_msg, main_keyboard)


        # ================= КЛИКИ ПО КНОПКАМ ПОДТВЕРЖДЕНИЯ (ЮЗЕРЫ) =================
        
        elif text_lower.startswith("✅ я оплатил #"):
            try:
                d_id = int(text_lower.split("#")[1])
                conn = sqlite3.connect("vimeworld_bot.db")
                deal = conn.execute("SELECT amount_vim, amount_rub, type FROM deals WHERE id = ?", (d_id,)).fetchone()
                conn.close()
                
                if deal and "buy_wait" in deal[2]:
                    raw_type = deal[2].replace("buy_wait_", "") 
                    method, nick = raw_type.split(":")
                    
                    send_msg(user_id, "⏳ Ваша заявка передана менеджеру, ожидайте. Примерное время ожидания: 5 минут", main_keyboard)
                    
                    adm_msg = (f"🔔 **Новая заявка на ПОКУПКУ (#{d_id})**\n"
                               f"👤 От: {get_vk_name(user_id)} (ID: {user_id})\n"
                               f"🎮 Ник для зачисления: **{nick}**\n"
                               f"🔮 Количество: **{deal[0]} Вимеров**\n"
                               f"💵 К получению: **{deal[1]} ₽**\n"
                               f"💳 Способ оплаты: **{method}**\n\n"
                               f"Проверь баланс. Если пришли деньги, зачисли вимеры на ник и нажми кнопку:")
                    send_msg(ADMIN_ID, adm_msg, make_admin_inline(d_id))
            except Exception as e:
                print(f"Ошибка в подтверждении оплаты: {e}")

        elif text_lower.startswith("✅ я перевел вимеры #"):
            try:
                d_id = int(text_lower.split("#")[1])
                
                conn = sqlite3.connect("vimeworld_bot.db")
                deal = conn.execute("SELECT amount_vim, amount_rub FROM deals WHERE id = ? AND type = 'sell_wait'", (d_id,)).fetchone()
                conn.close()
                
                if deal:
                    send_msg(user_id, "⏳ Ваша заявка передана менеджеру, ожидайте. Примерное время ожидания: 5 минут", main_keyboard)
                    
                    adm_msg = (f"🔔 **Новая заявка на ПРОДАЖУ (#{d_id})**\n"
                               f"👤 От: {get_vk_name(user_id)} (ID: {user_id})\n"
                               f"🔮 Юзер перевел: **{deal[0]} Вимеров**\n"
                               f"💵 К выплате: **{deal[1]} ₽**\n"
                               f"🏦 *Реквизиты юзер указал шагом ранее в диалоге.*\n\n"
                               f"Проверь VimeWorld. Если вимеры пришли, отправь рубли и нажми кнопку:")
                    send_msg(ADMIN_ID, adm_msg, make_admin_inline(d_id))
            except Exception as e:
                print(f"Ошибка в подтверждении продажи: {e}")


        # ================= АДМИН-ПАНЕЛЬ И ОБРАБОТКА ДЕЙСТВИЙ АДМИНА =================
        
        if u["status"] == "Admin":
            if "принять" in text_lower or "отклонить" in text_lower:
                try:
                    d_id = int(text.split()[-1])
                except:
                    continue
                
                conn = sqlite3.connect("vimeworld_bot.db")
                deal = conn.execute("SELECT user_id, type, amount_vim, amount_rub FROM deals WHERE id = ?", (d_id,)).fetchone()
                conn.close()
                
                if not deal or "buy_wait" not in deal[1] and deal[1] != 'sell_wait':
                    send_msg(user_id, "❌ Ошибка: Заявка уже была обработана или не существует.")
                    continue
                
                u_client = deal[0]
                d_type = deal[1]
                amount_v = deal[2]
                amount_r = deal[3]
                
                if "принять" in text_lower:
                    b_rub = get_config("budget_rub")
                    b_vim = get_config("budget_vim")
                    
                    if "buy_wait" in d_type:
                        update_config("budget_vim", b_vim - amount_v)
                        update_config("budget_rub", b_rub + amount_r)
                        new_type = 'buy'
                        client_text = f"🎉 Администратор подтвердил оплату! **{amount_v} Вимеров** отправлены на ваш аккаунт. Спасибо!"
                    else: 
                        update_config("budget_vim", b_vim + amount_v)
                        update_config("budget_rub", b_rub - amount_r)
                        new_type = 'sell'
                        client_text = f"🎉 Рубли в размере **{amount_r} ₽** успешно отправлены на ваши реквизиты за **{amount_v} Вимеров**!"
                    
                    conn = sqlite3.connect("vimeworld_bot.db")
                    conn.execute("UPDATE deals SET type = ? WHERE id = ?", (new_type, d_id))
                    conn.commit()
                    conn.close()
                    
                    send_msg(ADMIN_ID, f"✅ Заявка #{d_id} успешно ОДОБРЕНА.")
                    send_msg(u_client, client_text, main_keyboard)
                    
                elif "отклонить" in text_lower:
                    conn = sqlite3.connect("vimeworld_bot.db")
                    conn.execute("UPDATE deals SET type = 'rejected' WHERE id = ?", (d_id,))
                    conn.commit()
                    conn.close()
                    
                    send_msg(ADMIN_ID, f"❌ Заявка #{d_id} ОТКЛОНЕНА.")
                    send_msg(u_client, f"❌ Ваша заявка #{d_id} была отклонена администратором. Если это ошибка — обратитесь в поддержку.", main_keyboard)
                continue

            if text_lower == "админ":
                b_rub = get_config("budget_rub")
                b_vim = get_config("budget_vim")
                min_buy = get_config("min_buy_amount")
                adm_panel = (f"⚙️ **Панель Администратора**\n\n"
                             f"💰 Бюджет рублей: **{b_rub} ₽**\n"
                             f"🔮 Бюджет вимеров: **{b_vim} вим.**\n"
                             f"📦 Мин. покупка: **{int(min_buy)} вим.**\n\n"
                             f"📌 **Команды управления (писать в чат):**\n"
                             f"• `+мин [число]` — изменить минимальную сумму покупки\n"
                             f"📌 **Команды управления (писать в чат):**\n"
                             f"• `+руб [число]` или `-руб [число]` — изменить баланс руб.\n"
                             f"• `+вим [число]` или `-вим [число]` — изменить баланс вим.\n"
                             f"• `скидка [ID] [процент]` — выдать персональную скидку.\n"
                             f"• `статус [ID] [User/VIP/Admin]` — изменить статус юзеру.\n"
                             f"• `рассылка [текст]` — сделать массовую рассылку.")
                send_msg(user_id, adm_panel)
                continue

            elif text_lower.startswith("+руб ") or text_lower.startswith("-руб "):
                val = float(text.split(" ")[1])
                current = get_config("budget_rub")
                new_val = (current + val) if text.startswith("+") else (current - val)
                update_config("budget_rub", max(0.0, new_val))
                send_msg(user_id, f"✅ Бюджет рублей изменен. Теперь: {get_config('budget_rub')} ₽")
                continue

            elif text_lower.startswith("+вим ") or text_lower.startswith("-вим "):
                val = float(text.split(" ")[1])
                current = get_config("budget_vim")
                new_val = (current + val) if text.startswith("+") else (current - val)
                update_config("budget_vim", max(0.0, new_val))
                send_msg(user_id, f"✅ Бюджет вимеров изменен. Теперь: {get_config('budget_vim')} вим.")
                continue
            elif text_lower.startswith("+мин "):
                try:
                    val = float(text.split(" ")[1])
                    update_config("min_buy_amount", val)
                    send_msg(user_id, f"✅ Минимальная сумма покупки успешно изменена на: {val} вим.")
                except:
                    send_msg(user_id, "❌ Ошибка. Пример команды: +мин 10000")
                continue

            elif text_lower.startswith("скидка "):
                try:
                    _, target_id, disc = text.split(" ")
                    update_user(int(target_id), discount=float(disc))
                    send_msg(user_id, f"✅ Пользователю {target_id} установлена персональная скидка/надбавка {disc}%")
                except:
                    send_msg(user_id, "Ошибка. Пример: скидка 1234567 5")
                continue

            elif text_lower.startswith("статус "):
                try:
                    _, target_id, new_status = text.split(" ")
                    if new_status in ['User', 'VIP', 'Admin']:
                        update_user(int(target_id), status=new_status)
                        send_msg(user_id, f"✅ Пользователю {target_id} выдан статус {new_status}")
                    else:
                        send_msg(user_id, "Допустимые статусы: User, VIP, Admin")
                except:
                    send_msg(user_id, "Ошибка. Пример: статус 1234567 VIP")
                continue

            elif text_lower.startswith("рассылка "):
                broadcast_text = text[9:]
                conn = sqlite3.connect("vimeworld_bot.db")
                all_users = conn.execute("SELECT user_id FROM users").fetchall()
                conn.close()
                
                send_msg(user_id, f"⏳ Запущена рассылка для {len(all_users)} пользователей...")
                success = 0
                for u_row in all_users:
                    try:
                        send_msg(u_row[0], broadcast_text, main_keyboard)
                        success += 1
                        time.sleep(0.3)
                    except:
                        pass
                send_msg(user_id, f"✅ Рассылка завершена. Успешно доставлено: {success} сообщений.")
                continue
