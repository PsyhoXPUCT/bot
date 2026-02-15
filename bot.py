import asyncio
import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
import os
import sys
import signal
import random
import string
import time
from threading import Thread
import requests

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = "8156792525:AAGOdtBOxsSp-N5O-suyFmejVNXUmX0R0Dg"
ADMIN_ID = 7839284712
PROTECTED_ID = 7839284712

# Реферальные ссылки бота
BOT_LINKS = [
    {"num": 1, "name": "AtlantaVPN", "url": "https://t.me/AtlantaVPN_bot?start=ref_7839284712"},
    {"num": 2, "name": "Nursultan VPN", "url": "https://t.me/nursultan_vpn_bot?start=ref_7839284712"}
]

# Текст правил
RULES_TEXT = """
📜 ПРАВИЛА ВЗАИМНОГО РЕФЕРАЛА:

1️⃣ Взаимный реферал 1:1
2️⃣ Порядок выполнения согласовывается заранее
3️⃣ Обсуждаются все условия
4️⃣ После выполнения отправляется скриншот
5️⃣ Отказ после согласования → ЧС
6️⃣ Неуважительное общение → отказ
7️⃣ Игнор после получения реферала → ЧС
8️⃣ Выполнение в оговорённое время
9️⃣ Реф считается выполненным при фактическом зачислении

📌 ДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА:
• Вы выполняете 2 бота, если были в одном — предупреждайте
• Не спрашивать был ли я в боте — доп ссылка запрашивается автоматически

✅ Нажимая "Продолжить", вы соглашаетесь с правилами
"""

# Причины для временного бана
BAN_REASONS = [
    "Нарушение правил",
    "Спам",
    "Оскорбления",
    "Мошенничество",
    "Невыполнение условий",
    "Другое"
]

# ==================== БАЗА ДАННЫХ ====================
users_db: Dict[int, Dict[str, Any]] = {}
blacklist: set = set()
temp_bans: Dict[int, datetime] = {}
admins: set = {ADMIN_ID}
moderators: set = set()
whitelist: set = {ADMIN_ID, PROTECTED_ID}

# Режим технических работ
maintenance_mode = False
maintenance_end_time: Optional[datetime] = None
maintenance_reason: str = ""
maintenance_message_text: str = "🚧 Ведутся технические работы. Бот временно недоступен."
maintenance_history: List[Dict] = []

# Поддержка пользователей
support_chats: List[Dict] = []

# Время запуска
start_time = datetime.now()
last_ping_time = datetime.now()

# ==================== FSM СОСТОЯНИЯ ====================
class ReferralStates(StatesGroup):
    waiting_for_agreement = State()
    waiting_for_my_links_view = State()
    waiting_for_link1 = State()
    waiting_for_link2 = State()
    waiting_for_screenshot1 = State()
    waiting_for_screenshot2 = State()
    waiting_for_support_message = State()
    waiting_for_support_reply = State()
    waiting_for_ban_id = State()
    waiting_for_temp_ban_time = State()
    waiting_for_temp_ban_reason = State()
    waiting_for_unban_id = State()
    waiting_for_blacklist_id = State()
    waiting_for_unblacklist_id = State()
    waiting_for_moder_id = State()
    waiting_for_admin_id = State()
    waiting_for_whitelist_id = State()
    waiting_for_maintenance_time = State()
    waiting_for_maintenance_reason = State()
    waiting_for_already_in_bot_choice = State()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_moscow_time() -> str:
    """Возвращает текущее время по МСК"""
    tz = timedelta(hours=3)
    msk_time = datetime.utcnow() + tz
    return msk_time.strftime('%d.%m.%Y %H:%M:%S')

def is_admin(user_id: int) -> bool:
    """Проверка на администратора"""
    return user_id in admins

def is_moderator(user_id: int) -> bool:
    """Проверка на модератора"""
    return user_id in moderators or is_admin(user_id)

def is_banned(user_id: int) -> bool:
    """Проверка на бан"""
    if user_id in blacklist:
        return True
    if user_id in temp_bans:
        if datetime.now() < temp_bans[user_id]:
            return True
        else:
            del temp_bans[user_id]
    return False

def can_access_during_maintenance(user_id: int) -> bool:
    """Проверка доступа во время технических работ"""
    return user_id in whitelist or is_admin(user_id) or is_moderator(user_id)

def check_protected_id(user_id: int) -> bool:
    """Проверка защищенного ID и автоматический разбан"""
    if user_id == PROTECTED_ID:
        if user_id in blacklist:
            blacklist.remove(user_id)
            logger.info(f"Автоматический разбан защищенного ID: {user_id}")
        if user_id in temp_bans:
            del temp_bans[user_id]
            logger.info(f"Автоматическое снятие временного бана с защищенного ID: {user_id}")
        whitelist.add(user_id)
        return True
    return False

def get_user_status_emoji(user_id: int) -> Tuple[str, str]:
    """Возвращает статус ссылок пользователя"""
    if user_id not in users_db:
        return "🔴", "🔴"
    user_data = users_db[user_id]
    status1 = "🟢" if user_data.get('link1_done', False) else "🔴"
    status2 = "🟢" if user_data.get('link2_done', False) else "🔴"
    return status1, status2

def get_bot_status_text(user_data: Dict) -> str:
    """Возвращает текст статуса по ботам"""
    text = ""
    if user_data.get('link1_done'):
        text += f"✅ {BOT_LINKS[0]['name']}: ВЫПОЛНЕН\n"
    elif user_data.get('link1_rejected'):
        text += f"❌ {BOT_LINKS[0]['name']}: ОТКЛОНЕН\n"
    elif user_data.get('already_in_bot_1'):
        text += f"🔄 {BOT_LINKS[0]['name']}: УЖЕ БЫЛ В БОТЕ\n"
    else:
        text += f"⏳ {BOT_LINKS[0]['name']}: В ОЖИДАНИИ\n"
    
    if user_data.get('link2_done'):
        text += f"✅ {BOT_LINKS[1]['name']}: ВЫПОЛНЕН\n"
    elif user_data.get('link2_rejected'):
        text += f"❌ {BOT_LINKS[1]['name']}: ОТКЛОНЕН\n"
    elif user_data.get('already_in_bot_2'):
        text += f"🔄 {BOT_LINKS[1]['name']}: УЖЕ БЫЛ В БОТЕ\n"
    else:
        text += f"⏳ {BOT_LINKS[1]['name']}: В ОЖИДАНИИ\n"
    return text

def format_time_delta(seconds: int) -> str:
    """Форматирует время для отображения"""
    if seconds < 60:
        return f"{seconds} сек"
    elif seconds < 3600:
        return f"{seconds // 60} мин"
    elif seconds < 86400:
        return f"{seconds // 3600} ч"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        if hours > 0:
            return f"{days} д {hours} ч"
        return f"{days} д"

def parse_time_string(time_str: str) -> Optional[int]:
    """Парсит время в формате: 30m, 2h, 5d, 100d, 71536d"""
    match = re.match(r'^(\d+)([mhd])$', time_str.lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 3600
    elif unit == 'd':
        return value * 86400
    return None

def is_valid_referral_link(text: str) -> bool:
    """Проверяет корректность реферальной ссылки"""
    if not text:
        return False
    text = text.strip()
    return 't.me/' in text and '?start=' in text

def is_callback_fresh(callback: CallbackQuery) -> bool:
    """Проверяет, не слишком ли старый callback"""
    if not callback.message or not callback.message.date:
        return True
    callback_time = callback.message.date.replace(tzinfo=None)
    now = datetime.now()
    time_diff = now - callback_time
    return time_diff.total_seconds() < 3600  # 1 час

# ==================== ВЕБ-СЕРВЕР ДЛЯ ПИНГОВ ====================
from flask import Flask, jsonify
from threading import Thread
import requests

app = Flask(__name__)

@app.route('/')
def home():
    uptime = datetime.now() - start_time
    uptime_str = str(uptime).split('.')[0]
    return jsonify({
        'status': 'running',
        'uptime': uptime_str,
        'users': len(users_db),
        'time': get_moscow_time()
    })

@app.route('/ping')
def ping():
    global last_ping_time
    last_ping_time = datetime.now()
    return 'pong'

def run_flask():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False, threaded=True)

def keep_alive():
    """Запускает Flask сервер в отдельном потоке"""
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    logger.info("🌐 Веб-сервер запущен на порту 8080")

# ==================== ПИНГОВАЛКА ДЛЯ REPLIT ====================
def ping_self():
    """Пингует сам себя, чтобы Replit не вырубал бота"""
    while True:
        try:
            time.sleep(300)  # Каждые 5 минут
            requests.get('http://localhost:8080/ping', timeout=5)
            logger.debug("🏓 Self-ping успешен")
        except Exception as e:
            logger.error(f"❌ Self-ping ошибка: {e}")

def start_pinger():
    """Запускает пинговалку в отдельном потоке"""
    t = Thread(target=ping_self)
    t.daemon = True
    t.start()
    logger.info("🔄 Пинговалка запущена (каждые 5 минут)")

# ==================== ИНИЦИАЛИЗАЦИЯ БОТА ====================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== МИДЛВАРЬ ДЛЯ ПРОВЕРКИ УСТАРЕВШИХ CALLBACK ====================
@dp.callback_query.middleware()
async def callback_freshness_middleware(handler, event, data):
    """Проверяет свежесть callback перед обработкой"""
    if not is_callback_fresh(event):
        await event.answer("❌ Эта кнопка устарела. Нажмите /start заново.", show_alert=True)
        return
    return await handler(event, data)

# ==================== MIDDLEWARE ТЕХРАБОТ ====================
@dp.message.middleware()
@dp.callback_query.middleware()
async def maintenance_middleware(handler, event, data):
    """Middleware для проверки режима технических работ"""
    if not maintenance_mode:
        return await handler(event, data)
    
    user_id = None
    if isinstance(event, Message):
        user_id = event.from_user.id
    elif isinstance(event, CallbackQuery):
        user_id = event.from_user.id
    
    if user_id and can_access_during_maintenance(user_id):
        return await handler(event, data)
    
    end_time_str = maintenance_end_time.strftime('%d.%m.%Y %H:%M') if maintenance_end_time else "неизвестно"
    
    msg = (f"⛔️ ТЕХНИЧЕСКИЕ РАБОТЫ\n\n"
           f"{maintenance_message_text}\n\n"
           f"🕐 МСК: {get_moscow_time()}\n"
           f"⏳ Окончание: {end_time_str} МСК")
    
    if maintenance_reason:
        msg += f"\n📝 Причина: {maintenance_reason}"
    
    if isinstance(event, Message):
        await event.answer(msg)
    elif isinstance(event, CallbackQuery):
        await event.answer()
        if event.message:
            await event.message.answer(msg)
    return

# ==================== КЛАВИАТУРЫ ====================

def get_main_keyboard(user_id: int = None):
    """Главное меню"""
    buttons = [
        [InlineKeyboardButton(text="🚀 Старт", callback_data="start_process")],
        [InlineKeyboardButton(text="📜 Правила", callback_data="show_rules")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="support")]
    ]
    if user_id and (is_admin(user_id) or is_moderator(user_id)):
        buttons.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_simple_back_keyboard():
    """Только кнопка назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])

def get_back_keyboard():
    """Кнопка назад в админ-панель"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])

def get_rules_keyboard():
    """Кнопка продолжения после правил"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Продолжить", callback_data="accept_rules")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])

def get_my_links_keyboard():
    """Кнопка после перехода по ссылкам"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Я перешел по ссылкам", callback_data="i_clicked_links")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])

def get_links_keyboard(has_link1: bool = False):
    """Кнопки для отправки ссылок"""
    buttons = []
    if not has_link1:
        buttons.append([InlineKeyboardButton(text="📎 Отправить ссылку №1", callback_data="send_link1")])
        buttons.append([InlineKeyboardButton(text="🔄 Я уже был в боте", callback_data="already_in_bot_menu")])
    else:
        buttons.append([InlineKeyboardButton(text="📎 Отправить ссылку №2", callback_data="send_link2")])
        buttons.append([InlineKeyboardButton(text="✅ Не отправлять вторую ссылку", callback_data="skip_link2")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_already_in_bot_keyboard():
    """Выбор бота, где уже был"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"№1 – {BOT_LINKS[0]['name']}", callback_data="already_in_bot_1")],
        [InlineKeyboardButton(text=f"№2 – {BOT_LINKS[1]['name']}", callback_data="already_in_bot_2")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_links")]
    ])

def get_completion_keyboard():
    """Кнопки выполнения"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ссылку №1 выполнил", callback_data="completed_1")],
        [InlineKeyboardButton(text="✅ Ссылку №2 выполнил", callback_data="completed_2")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")]
    ])

def get_admin_link_keyboard(user_id: int, link_num: int, has_second: bool = False):
    """Кнопки для админа при проверке ссылки"""
    buttons = []
    # Используем случайную строку, чтобы избежать кеширования старых callback
    rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    buttons.append([InlineKeyboardButton(text=f"✅ Принять ссылку №{link_num}", callback_data=f"accept_link_{user_id}_{link_num}_{rand}")])
    buttons.append([
        InlineKeyboardButton(text="📊 >6 спонсоров", callback_data=f"reject_reason_{user_id}_{link_num}_more_6_{rand}"),
        InlineKeyboardButton(text="🔄 Был в боте", callback_data=f"reject_reason_{user_id}_{link_num}_already_in_bot_{rand}")
    ])
    buttons.append([
        InlineKeyboardButton(text="❌ Плохой скрин", callback_data=f"reject_reason_{user_id}_{link_num}_bad_screenshot_{rand}"),
        InlineKeyboardButton(text="🤔 Другое", callback_data=f"reject_reason_{user_id}_{link_num}_other_{rand}")
    ])
    if has_second:
        buttons.append([InlineKeyboardButton(text="⏭ Пропустить вторую", callback_data=f"skip_second_{user_id}_{rand}")])
    buttons.append([InlineKeyboardButton(text="🚫 В ЧС", callback_data=f"admin_ban_{user_id}_{rand}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_panel_keyboard():
    """Админ-панель"""
    buttons = [
        [InlineKeyboardButton(text="🔨 Бан / Разбан", callback_data="admin_ban_menu")],
        [InlineKeyboardButton(text="⏰ Временный бан", callback_data="admin_temp_ban")],
        [InlineKeyboardButton(text="⛔ Управление ЧС", callback_data="admin_blacklist_menu")],
        [InlineKeyboardButton(text="👥 Модераторы", callback_data="admin_moder_menu")],
        [InlineKeyboardButton(text="👑 Администраторы", callback_data="admin_admin_menu")],
        [InlineKeyboardButton(text="📋 Белый список", callback_data="admin_whitelist_menu")],
    ]
    if maintenance_mode:
        buttons.append([InlineKeyboardButton(text="🔧 Выключить техработы", callback_data="admin_maintenance_off")])
    else:
        buttons.append([InlineKeyboardButton(text="🔧 Включить техработы", callback_data="admin_maintenance_on")])
    buttons.append([InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")])
    buttons.append([InlineKeyboardButton(text="📜 История техработ", callback_data="admin_maintenance_history")])
    buttons.append([InlineKeyboardButton(text="📊 Статус бота", callback_data="admin_bot_status")])
    buttons.append([InlineKeyboardButton(text="🔄 Перезапустить бота", callback_data="admin_restart_bot")])
    buttons.append([InlineKeyboardButton(text="🛑 Остановить бота", callback_data="admin_shutdown_bot")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_ban_keyboard():
    """Кнопки для бана/разбана"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔨 Забанить навсегда", callback_data="admin_ban_permanent")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])

def get_admin_moder_keyboard():
    """Кнопки для модераторов"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выдать модератора", callback_data="admin_give_moder")],
        [InlineKeyboardButton(text="➖ Забрать модератора", callback_data="admin_remove_moder")],
        [InlineKeyboardButton(text="📋 Список модераторов", callback_data="admin_list_moders")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])

def get_admin_admin_keyboard():
    """Кнопки для администраторов"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выдать администратора", callback_data="admin_give_admin")],
        [InlineKeyboardButton(text="➖ Забрать администратора", callback_data="admin_remove_admin")],
        [InlineKeyboardButton(text="📋 Список администраторов", callback_data="admin_list_admins")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])

def get_admin_blacklist_keyboard():
    """Кнопки для ЧС"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛔ Добавить в ЧС", callback_data="admin_blacklist_add")],
        [InlineKeyboardButton(text="✅ Удалить из ЧС", callback_data="admin_blacklist_remove")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])

def get_admin_whitelist_keyboard():
    """Кнопки для белого списка"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в белый список", callback_data="admin_whitelist_add")],
        [InlineKeyboardButton(text="➖ Удалить из белого списка", callback_data="admin_whitelist_remove")],
        [InlineKeyboardButton(text="📋 Показать белый список", callback_data="admin_whitelist_show")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])

def get_support_keyboard(user_id: int):
    """Кнопка ответа в поддержке"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"support_reply_{user_id}")]
    ])

# ==================== ОБРАБОТЧИКИ ПОЛЬЗОВАТЕЛЕЙ ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    check_protected_id(user_id)
    
    if is_banned(user_id):
        await message.answer("⛔ Вы заблокированы.")
        return
    
    if user_id not in users_db:
        users_db[user_id] = {
            'username': message.from_user.username,
            'first_name': message.from_user.first_name,
            'link1': None,
            'link2': None,
            'link1_done': False,
            'link2_done': False,
            'link1_screenshot': None,
            'link2_screenshot': None,
            'link1_rejected': False,
            'link2_rejected': False,
            'already_in_bot_1': False,
            'already_in_bot_2': False,
            'active_refs': 0,
            'attempts': 0
        }
    
    await state.clear()
    status1, status2 = get_user_status_emoji(user_id)
    
    text = (f"🔰 Здравствуй, {message.from_user.first_name}!\n"
            f"Добро пожаловать в бот взаимного реферала!\n\n"
            f"📊 МОИ РЕФЕРАЛЬНЫЕ ССЫЛКИ:\n\n"
            f"№1 – {BOT_LINKS[0]['name']}\n{BOT_LINKS[0]['url']}\nСтатус: {status1}\n\n"
            f"№2 – {BOT_LINKS[1]['name']}\n{BOT_LINKS[1]['url']}\nСтатус: {status2}")
    
    await message.answer(text, reply_markup=get_main_keyboard(user_id))

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Команда /admin для открытия админ-панели"""
    user_id = message.from_user.id
    if not is_admin(user_id) and not is_moderator(user_id):
        await message.answer("⛔ Нет доступа.")
        return
    await message.answer("👑 АДМИН-ПАНЕЛЬ", reply_markup=get_admin_panel_keyboard())

# ==================== ОСНОВНЫЕ КНОПКИ ====================

@dp.callback_query(F.data == "start_process")
async def start_process(callback: CallbackQuery, state: FSMContext):
    """Начало процесса"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    await callback.message.edit_text(RULES_TEXT, reply_markup=get_rules_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await state.clear()
    await cmd_start(callback.message, state)

@dp.callback_query(F.data == "back_to_links")
async def back_to_links(callback: CallbackQuery, state: FSMContext):
    """Возврат к меню ссылок"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    user_id = callback.from_user.id
    user_data = users_db.get(user_id, {})
    has_link1 = user_data.get('link1') is not None
    await callback.message.edit_text("📎 Отправьте свои ссылки:", reply_markup=get_links_keyboard(has_link1))
    await state.set_state(ReferralStates.waiting_for_links)
    await callback.answer()

@dp.callback_query(F.data == "show_rules")
async def show_rules(callback: CallbackQuery):
    """Показать правила"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text(RULES_TEXT, reply_markup=get_rules_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "accept_rules")
async def accept_rules(callback: CallbackQuery, state: FSMContext):
    """Принятие правил"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    user_id = callback.from_user.id
    status1, status2 = get_user_status_emoji(user_id)
    
    text = (f"🔗 МОИ РЕФЕРАЛЬНЫЕ ССЫЛКИ:\n\n"
            f"№1 – {BOT_LINKS[0]['name']}\n{BOT_LINKS[0]['url']}\nСтатус: {status1}\n\n"
            f"№2 – {BOT_LINKS[1]['name']}\n{BOT_LINKS[1]['url']}\nСтатус: {status2}\n\n"
            f"✅ Перейдите по ссылкам и нажмите кнопку ниже")
    
    await callback.message.edit_text(text, reply_markup=get_my_links_keyboard())
    await state.set_state(ReferralStates.waiting_for_my_links_view)
    await callback.answer()

@dp.callback_query(F.data == "i_clicked_links")
async def i_clicked_links(callback: CallbackQuery, state: FSMContext):
    """Пользователь перешел по ссылкам"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("📎 Отправьте ВАШИ ссылки:", reply_markup=get_links_keyboard())
    await state.set_state(ReferralStates.waiting_for_links)
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    """Показать профиль"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    user_id = callback.from_user.id
    if user_id not in users_db:
        await callback.message.edit_text("❌ Профиль не найден.", reply_markup=get_simple_back_keyboard())
        return
    
    user_data = users_db[user_id]
    status1, status2 = get_user_status_emoji(user_id)
    in_blacklist = "Да" if user_id in blacklist else "Нет"
    in_temp_ban = "Да" if user_id in temp_bans else "Нет"
    
    text = (f"👤 ПРОФИЛЬ\n\n"
            f"🆔 ID: {user_id}\n"
            f"📝 Имя: {user_data.get('first_name', '')}\n\n"
            f"📊 Активные рефералы: {user_data.get('active_refs', 0)}\n"
            f"🔄 Попыток: {user_data.get('attempts', 0)}\n"
            f"🔗 СТАТУС:\n{get_bot_status_text(user_data)}\n"
            f"⛔ В ЧС: {in_blacklist}\n"
            f"⏰ Временный бан: {in_temp_ban}\n\n")
    
    if user_data.get('link1'):
        text += f"🔗 Ссылка №1: {user_data['link1']}\n"
    if user_data.get('link2'):
        text += f"🔗 Ссылка №2: {user_data['link2']}\n"
    
    await callback.message.edit_text(text, reply_markup=get_simple_back_keyboard())
    await callback.answer()

# ==================== ПОДДЕРЖКА ====================

@dp.callback_query(F.data == "support")
async def support_action(callback: CallbackQuery, state: FSMContext):
    """Обращение в поддержку"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("💬 Напишите ваше сообщение:", reply_markup=get_simple_back_keyboard())
    await state.set_state(ReferralStates.waiting_for_support_message)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_support_message)
async def process_support_message(message: Message, state: FSMContext):
    """Обработка сообщения в поддержку"""
    user_id = message.from_user.id
    username = message.from_user.username or "нет username"
    
    support_chats.append({
        'user_id': user_id,
        'username': username,
        'time': datetime.now().strftime('%d.%m.%Y %H:%M'),
        'text': message.text
    })
    
    for admin_id in admins.union(moderators):
        try:
            await bot.send_message(
                admin_id,
                f"💬 НОВОЕ ОБРАЩЕНИЕ\n\n👤 @{username}\n🆔 {user_id}\n📝 {message.text}",
                reply_markup=get_support_keyboard(user_id)
            )
        except:
            pass
    
    await message.answer("✅ Отправлено!", reply_markup=get_simple_back_keyboard())
    await state.clear()

@dp.callback_query(F.data.startswith("support_reply_"))
async def support_reply(callback: CallbackQuery, state: FSMContext):
    """Ответ на обращение"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    parts = callback.data.split('_')
    if len(parts) < 3:
        await callback.answer("Ошибка")
        return
    
    try:
        user_id = int(parts[2])
    except:
        await callback.answer("Ошибка")
        return
    
    await callback.message.edit_text(f"✍️ Ответ пользователю {user_id}:")
    await state.update_data(reply_to_user=user_id)
    await state.set_state(ReferralStates.waiting_for_support_reply)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_support_reply)
async def process_support_reply(message: Message, state: FSMContext):
    """Отправка ответа пользователю"""
    data = await state.get_data()
    target_user = data.get('reply_to_user')
    
    if not target_user:
        await message.answer("❌ Ошибка")
        await state.clear()
        return
    
    try:
        await bot.send_message(target_user, f"💬 ОТВЕТ:\n\n{message.text}")
        await message.answer("✅ Отправлено!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    
    await state.clear()

# ==================== ССЫЛКИ ====================

@dp.callback_query(F.data == "send_link1")
async def send_link1(callback: CallbackQuery, state: FSMContext):
    """Отправка первой ссылки"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("📎 Отправьте ссылку №1:\nФормат: https://t.me/...?start=...")
    await state.set_state(ReferralStates.waiting_for_link1)
    await callback.answer()

@dp.callback_query(F.data == "send_link2")
async def send_link2(callback: CallbackQuery, state: FSMContext):
    """Отправка второй ссылки"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("📎 Отправьте ссылку №2:\nФормат: https://t.me/...?start=...")
    await state.set_state(ReferralStates.waiting_for_link2)
    await callback.answer()

@dp.callback_query(F.data == "skip_link2")
async def skip_link2(callback: CallbackQuery, state: FSMContext):
    """Пропуск второй ссылки"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("✅ Отправьте скриншот для ссылки №1:", reply_markup=get_completion_keyboard())
    await state.set_state(ReferralStates.waiting_for_screenshot1)
    await callback.answer()

@dp.callback_query(F.data == "already_in_bot_menu")
async def already_in_bot_menu(callback: CallbackQuery, state: FSMContext):
    """Меню выбора бота, где уже был"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("🔄 Где уже были?", reply_markup=get_already_in_bot_keyboard())
    await state.set_state(ReferralStates.waiting_for_already_in_bot_choice)
    await callback.answer()

@dp.callback_query(F.data == "already_in_bot_1")
async def already_in_bot_1(callback: CallbackQuery, state: FSMContext):
    """Уже был в боте №1"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    user_id = callback.from_user.id
    if user_id in users_db:
        users_db[user_id]['already_in_bot_1'] = True
    await callback.message.edit_text(f"🔄 Вы уже были в {BOT_LINKS[0]['name']}.\nОтправьте ссылку для {BOT_LINKS[1]['name']}:", reply_markup=get_links_keyboard())
    await state.set_state(ReferralStates.waiting_for_links)
    await callback.answer()

@dp.callback_query(F.data == "already_in_bot_2")
async def already_in_bot_2(callback: CallbackQuery, state: FSMContext):
    """Уже был в боте №2"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    user_id = callback.from_user.id
    if user_id in users_db:
        users_db[user_id]['already_in_bot_2'] = True
    await callback.message.edit_text(f"🔄 Вы уже были в {BOT_LINKS[1]['name']}.\nОтправьте ссылку для {BOT_LINKS[0]['name']}:", reply_markup=get_links_keyboard())
    await state.set_state(ReferralStates.waiting_for_links)
    await callback.answer()

# ==================== ОБРАБОТКА ССЫЛОК ====================

@dp.message(ReferralStates.waiting_for_link1)
async def process_link1(message: Message, state: FSMContext):
    """Обработка первой ссылки"""
    user_id = message.from_user.id
    
    if not is_valid_referral_link(message.text):
        await message.answer("❌ Неверный формат. Используйте: https://t.me/...?start=...")
        return
    
    if user_id not in users_db:
        users_db[user_id] = users_db.get(user_id, {})
    
    users_db[user_id]['link1'] = message.text
    users_db[user_id]['attempts'] = users_db[user_id].get('attempts', 0) + 1
    
    await message.answer("✅ Ссылка №1 принята!", reply_markup=get_links_keyboard(has_link1=True))
    await state.set_state(ReferralStates.waiting_for_links)

@dp.message(ReferralStates.waiting_for_link2)
async def process_link2(message: Message, state: FSMContext):
    """Обработка второй ссылки"""
    user_id = message.from_user.id
    
    if not is_valid_referral_link(message.text):
        await message.answer("❌ Неверный формат. Используйте: https://t.me/...?start=...")
        return
    
    if user_id not in users_db:
        users_db[user_id] = users_db.get(user_id, {})
    
    users_db[user_id]['link2'] = message.text
    users_db[user_id]['attempts'] = users_db[user_id].get('attempts', 0) + 1
    
    await message.answer("✅ Ссылка №2 принята!", reply_markup=get_completion_keyboard())
    await state.set_state(ReferralStates.waiting_for_links)

# ==================== СКРИНШОТЫ ====================

@dp.callback_query(F.data == "completed_1")
async def completed_link1(callback: CallbackQuery, state: FSMContext):
    """Выполнение первой ссылки"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("📸 Отправьте скриншот для ссылки №1")
    await state.set_state(ReferralStates.waiting_for_screenshot1)
    await callback.answer()

@dp.callback_query(F.data == "completed_2")
async def completed_link2(callback: CallbackQuery, state: FSMContext):
    """Выполнение второй ссылки"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    user_id = callback.from_user.id
    user_data = users_db.get(user_id, {})
    if not user_data or not user_data.get('link2'):
        await callback.message.edit_text("❌ Сначала отправьте ссылку №2")
        await callback.answer()
        return
    await callback.message.edit_text("📸 Отправьте скриншот для ссылки №2")
    await state.set_state(ReferralStates.waiting_for_screenshot2)
    await callback.answer()

@dp.message(F.photo, ReferralStates.waiting_for_screenshot1)
async def process_screenshot1(message: Message, state: FSMContext):
    """Обработка скриншота для первой ссылки"""
    user_id = message.from_user.id
    
    if user_id not in users_db:
        users_db[user_id] = users_db.get(user_id, {})
    
    photo = message.photo[-1]
    users_db[user_id]['link1_screenshot'] = photo.file_id
    
    user_data = users_db.get(user_id, {})
    has_link2 = user_data.get('link2') is not None
    
    if has_link2 and not user_data.get('link2_screenshot'):
        await message.answer("✅ Скриншот №1 принят! Теперь отправьте для №2")
        await state.set_state(ReferralStates.waiting_for_screenshot2)
    else:
        await send_screenshots_to_admin(user_id, message)
        await message.answer("✅ Отправлено на проверку!", reply_markup=get_simple_back_keyboard())
        await state.clear()

@dp.message(F.photo, ReferralStates.waiting_for_screenshot2)
async def process_screenshot2(message: Message, state: FSMContext):
    """Обработка скриншота для второй ссылки"""
    user_id = message.from_user.id
    
    if user_id not in users_db:
        users_db[user_id] = users_db.get(user_id, {})
    
    photo = message.photo[-1]
    users_db[user_id]['link2_screenshot'] = photo.file_id
    
    await send_screenshots_to_admin(user_id, message)
    await message.answer("✅ Отправлено на проверку!", reply_markup=get_simple_back_keyboard())
    await state.clear()

async def send_screenshots_to_admin(user_id: int, message: Message):
    """Отправляет скриншоты админам"""
    if user_id not in users_db:
        return
    
    user_data = users_db[user_id]
    username = message.from_user.username or "нет username"
    
    text = (f"📊 ПОЛЬЗОВАТЕЛЬ\n"
            f"👤 @{username}\n"
            f"🆔 {user_id}\n\n"
            f"🔗 ССЫЛКИ:\n")
    
    if user_data.get('link1'):
        text += f"№1: {user_data['link1']}\n"
    if user_data.get('link2'):
        text += f"№2: {user_data['link2']}\n"
    text += f"\n{get_bot_status_text(user_data)}"
    
    media = []
    if user_data.get('link1_screenshot'):
        media.append(InputMediaPhoto(
            media=user_data['link1_screenshot'],
            caption=f"Скрин №1 ({BOT_LINKS[0]['name']})"
        ))
    if user_data.get('link2_screenshot'):
        media.append(InputMediaPhoto(
            media=user_data['link2_screenshot'],
            caption=f"Скрин №2 ({BOT_LINKS[1]['name']})"
        ))
    
    for admin_id in admins.union(moderators):
        try:
            if len(media) == 1:
                await bot.send_photo(
                    admin_id,
                    photo=media[0].media,
                    caption=f"{text}\n\n{media[0].caption}",
                    reply_markup=get_admin_link_keyboard(
                        user_id, 
                        1 if "№1" in media[0].caption else 2,
                        has_second=bool(user_data.get('link2') and not user_data.get('link2_screenshot'))
                    )
                )
            elif len(media) == 2:
                await bot.send_media_group(admin_id, media)
                await bot.send_message(
                    admin_id,
                    text,
                    reply_markup=get_admin_link_keyboard(user_id, 1, has_second=True)
                )
        except Exception as e:
            logger.error(f"Ошибка отправки админу {admin_id}: {e}")

# ==================== ПОДТВЕРЖДЕНИЕ ССЫЛОК ====================

@dp.callback_query(F.data.startswith("accept_link_"))
async def accept_link(callback: CallbackQuery):
    """Принятие ссылки админом"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    parts = callback.data.split('_')
    if len(parts) < 4:
        await callback.answer("Ошибка")
        return
    
    try:
        user_id = int(parts[2])
        link_num = int(parts[3])
    except:
        await callback.answer("Ошибка")
        return
    
    if not is_moderator(callback.from_user.id):
        await callback.answer("⛔ Нет прав")
        return
    
    if user_id not in users_db:
        await callback.answer("❌ Нет пользователя")
        return
    
    users_db[user_id][f'link{link_num}_done'] = True
    users_db[user_id]['active_refs'] = users_db[user_id].get('active_refs', 0) + 1
    
    try:
        await bot.send_message(user_id, f"✅ Ссылка №{link_num} принята!")
    except:
        pass
    
    user_data = users_db[user_id]
    has_link2 = user_data.get('link2') is not None
    
    if has_link2 and not user_data.get('link2_done'):
        await callback.message.answer(
            f"✅ Ссылка №{link_num} принята!\n\nТеперь проверьте №2:",
            reply_markup=get_admin_link_keyboard(user_id, 2, has_second=False)
        )
    else:
        status_text = get_bot_status_text(user_data)
        try:
            await bot.send_message(user_id, f"📊 РЕЗУЛЬТАТ:\n\n{status_text}")
        except:
            pass
        await callback.message.answer(f"✅ Все ссылки обработаны!\n\n{status_text}")
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✅ Принято")

@dp.callback_query(F.data.startswith("reject_reason_"))
async def reject_with_reason(callback: CallbackQuery):
    """Отклонение ссылки с причиной"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    parts = callback.data.split('_')
    if len(parts) < 5:
        await callback.answer("Ошибка")
        return
    
    try:
        user_id = int(parts[2])
        link_num = int(parts[3])
        reason_code = parts[4]
    except:
        await callback.answer("Ошибка")
        return
    
    reason_texts = {
        "more_6": "Больше 6 спонсоров",
        "already_in_bot": "Уже был в боте",
        "bad_screenshot": "Плохой скрин",
        "other": "Другая причина"
    }
    reason_text = reason_texts.get(reason_code, "Не указана")
    
    if user_id in users_db:
        users_db[user_id][f'link{link_num}_rejected'] = True
    
    try:
        await bot.send_message(user_id, f"❌ Ссылка №{link_num} отклонена: {reason_text}")
    except:
        pass
    
    user_data = users_db.get(user_id, {})
    has_link2 = user_data.get('link2') is not None
    
    if has_link2 and not user_data.get('link2_rejected') and not user_data.get('link2_done'):
        await callback.message.answer(
            f"❌ Ссылка №{link_num} отклонена\n\nТеперь проверьте №2:",
            reply_markup=get_admin_link_keyboard(user_id, 2, has_second=False)
        )
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer(f"❌ Отклонено")

@dp.callback_query(F.data.startswith("skip_second_"))
async def skip_second_link(callback: CallbackQuery):
    """Пропуск второй ссылки"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    parts = callback.data.split('_')
    if len(parts) < 3:
        await callback.answer("Ошибка")
        return
    
    try:
        user_id = int(parts[2])
    except:
        await callback.answer("Ошибка")
        return
    
    user_data = users_db.get(user_id, {})
    status_text = get_bot_status_text(user_data)
    
    try:
        await bot.send_message(user_id, f"📊 РЕЗУЛЬТАТ:\n\n{status_text}")
    except:
        pass
    
    await callback.message.answer(f"✅ Обработка завершена!\n\n{status_text}")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✅ Готово")

@dp.callback_query(F.data.startswith("admin_ban_"))
async def admin_ban_user(callback: CallbackQuery):
    """Бан пользователя из админки"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    parts = callback.data.split('_')
    if len(parts) < 3:
        await callback.answer("Ошибка")
        return
    
    try:
        user_id = int(parts[2])
    except:
        await callback.answer("Ошибка")
        return
    
    if not is_moderator(callback.from_user.id):
        await callback.answer("⛔ Нет прав")
        return
    
    if check_protected_id(user_id):
        await callback.answer("⚠️ Защищен")
        return
    
    if is_admin(user_id):
        await callback.answer("⚠️ Админ")
        return
    
    blacklist.add(user_id)
    
    try:
        await bot.send_message(user_id, "⛔ Вы забанены")
    except:
        pass
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✅ Забанен")

# ==================== АДМИН-ПАНЕЛЬ ====================

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_cb(callback: CallbackQuery):
    """Открытие админ-панели"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    if not is_moderator(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return
    await callback.message.edit_text("👑 АДМИН-ПАНЕЛЬ", reply_markup=get_admin_panel_keyboard())
    await callback.answer()

# ==================== БАНЫ ====================

@dp.callback_query(F.data == "admin_ban_menu")
async def admin_ban_menu(callback: CallbackQuery, state: FSMContext):
    """Меню банов"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("🔨 УПРАВЛЕНИЕ БАНАМИ", reply_markup=get_admin_ban_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_ban_permanent")
async def admin_ban_permanent(callback: CallbackQuery, state: FSMContext):
    """Постоянный бан"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("🔨 Введите ID для постоянного бана:")
    await state.set_state(ReferralStates.waiting_for_ban_id)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_ban_id)
async def process_ban_id(message: Message, state: FSMContext):
    """Обработка ID для бана"""
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    if check_protected_id(user_id):
        await message.answer("⚠️ Защищен")
        await state.clear()
        return
    
    if is_admin(user_id):
        await message.answer("⚠️ Админ")
        await state.clear()
        return
    
    blacklist.add(user_id)
    
    try:
        await bot.send_message(user_id, "⛔ Вы забанены")
    except:
        pass
    
    await message.answer(f"✅ Пользователь {user_id} забанен")
    await state.clear()

@dp.callback_query(F.data == "admin_unban")
async def admin_unban(callback: CallbackQuery, state: FSMContext):
    """Разбан"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("✅ Введите ID для разбана:")
    await state.set_state(ReferralStates.waiting_for_unban_id)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_unban_id)
async def process_unban(message: Message, state: FSMContext):
    """Обработка разбана"""
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    unbanned = False
    if user_id in blacklist:
        blacklist.remove(user_id)
        unbanned = True
    if user_id in temp_bans:
        del temp_bans[user_id]
        unbanned = True
    
    if unbanned:
        await message.answer(f"✅ Пользователь {user_id} разбанен")
        try:
            await bot.send_message(user_id, "✅ Вы разбанены")
        except:
            pass
    else:
        await message.answer(f"⚠️ Пользователь {user_id} не в бане")
    
    await state.clear()

@dp.callback_query(F.data == "admin_temp_ban")
async def admin_temp_ban(callback: CallbackQuery, state: FSMContext):
    """Временный бан"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text(
        "⏰ Введите ID и время (пример: 123456789 30m)\n\n"
        "Форматы: 30m, 2h, 5d, 100d, 71536d"
    )
    await state.set_state(ReferralStates.waiting_for_temp_ban_time)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_temp_ban_time)
async def process_temp_ban(message: Message, state: FSMContext):
    """Обработка временного бана"""
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Формат: <id> <время>")
        return
    
    try:
        user_id = int(parts[0])
        time_str = parts[1]
    except:
        await message.answer("❌ Неверный ID")
        return
    
    if check_protected_id(user_id):
        await message.answer("⚠️ Защищен")
        await state.clear()
        return
    
    if is_admin(user_id):
        await message.answer("⚠️ Админ")
        await state.clear()
        return
    
    seconds = parse_time_string(time_str)
    if not seconds:
        await message.answer("❌ Формат: 30m, 2h, 5d, 100d")
        return
    
    ban_until = datetime.now() + timedelta(seconds=seconds)
    temp_bans[user_id] = ban_until
    
    try:
        await bot.send_message(user_id, f"⏰ Вы забанены до {ban_until.strftime('%d.%m.%Y %H:%M')} МСК")
    except:
        pass
    
    await message.answer(f"✅ Пользователь {user_id} забанен на {format_time_delta(seconds)}")
    await state.clear()

# ==================== МОДЕРАТОРЫ ====================

@dp.callback_query(F.data == "admin_moder_menu")
async def admin_moder_menu(callback: CallbackQuery):
    """Меню модераторов"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Только для админов")
        return
    await callback.message.edit_text("👥 УПРАВЛЕНИЕ МОДЕРАТОРАМИ", reply_markup=get_admin_moder_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_give_moder")
async def admin_give_moder(callback: CallbackQuery, state: FSMContext):
    """Выдача модератора"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав")
        return
    await callback.message.edit_text("🛡 Введите ID для выдачи модератора:")
    await state.set_state(ReferralStates.waiting_for_moder_id)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_moder_id)
async def process_give_moder(message: Message, state: FSMContext):
    """Обработка выдачи модератора"""
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    moderators.add(user_id)
    
    try:
        await bot.send_message(user_id, "🛡 Вы модератор!")
    except:
        pass
    
    await message.answer(f"✅ Пользователь {user_id} теперь модератор")
    await state.clear()

@dp.callback_query(F.data == "admin_remove_moder")
async def admin_remove_moder(callback: CallbackQuery, state: FSMContext):
    """Забор модератора"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав")
        return
    await callback.message.edit_text("➖ Введите ID для забора модератора:")
    await state.set_state(ReferralStates.waiting_for_moder_id)
    await state.update_data(action="remove_moder")
    await callback.answer()

@dp.message(ReferralStates.waiting_for_moder_id)
async def process_remove_moder(message: Message, state: FSMContext):
    """Обработка забора модератора"""
    data = await state.get_data()
    action = data.get('action')
    
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    if action == "remove_moder" and user_id in moderators:
        moderators.remove(user_id)
        await message.answer(f"✅ У пользователя {user_id} забраны права модератора")
        try:
            await bot.send_message(user_id, "❌ Права модератора отозваны")
        except:
            pass
    else:
        await message.answer(f"⚠️ Пользователь {user_id} не модератор")
    
    await state.clear()

@dp.callback_query(F.data == "admin_list_moders")
async def admin_list_moders(callback: CallbackQuery):
    """Список модераторов"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    text = "📋 СПИСОК МОДЕРАТОРОВ:\n\n"
    for uid in sorted(moderators):
        user_info = users_db.get(uid, {})
        username = user_info.get('username', 'нет')
        text += f"• {uid} (@{username})\n"
    text += f"\nВсего: {len(moderators)}"
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

# ==================== АДМИНИСТРАТОРЫ ====================

@dp.callback_query(F.data == "admin_admin_menu")
async def admin_admin_menu(callback: CallbackQuery):
    """Меню администраторов"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Только для админов")
        return
    await callback.message.edit_text("👑 УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ", reply_markup=get_admin_admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_give_admin")
async def admin_give_admin(callback: CallbackQuery, state: FSMContext):
    """Выдача админа"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав")
        return
    await callback.message.edit_text("👑 Введите ID для выдачи админа:")
    await state.set_state(ReferralStates.waiting_for_admin_id)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_admin_id)
async def process_give_admin(message: Message, state: FSMContext):
    """Обработка выдачи админа"""
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    admins.add(user_id)
    whitelist.add(user_id)
    
    try:
        await bot.send_message(user_id, "👑 Вы администратор!")
    except:
        pass
    
    await message.answer(f"✅ Пользователь {user_id} теперь админ")
    await state.clear()

@dp.callback_query(F.data == "admin_remove_admin")
async def admin_remove_admin(callback: CallbackQuery, state: FSMContext):
    """Забор админа"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    if not is_admin(callback.from_user.id) or callback.from_user.id == ADMIN_ID:
        await callback.answer("⛔ Нельзя забрать у главного")
        return
    await callback.message.edit_text("➖ Введите ID для забора админа:")
    await state.set_state(ReferralStates.waiting_for_admin_id)
    await state.update_data(action="remove_admin")
    await callback.answer()

@dp.message(ReferralStates.waiting_for_admin_id)
async def process_remove_admin(message: Message, state: FSMContext):
    """Обработка забора админа"""
    data = await state.get_data()
    action = data.get('action')
    
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    if action == "remove_admin" and user_id in admins and user_id != ADMIN_ID:
        admins.remove(user_id)
        if user_id in whitelist:
            whitelist.remove(user_id)
        await message.answer(f"✅ У пользователя {user_id} забраны права админа")
        try:
            await bot.send_message(user_id, "❌ Права администратора отозваны")
        except:
            pass
    else:
        await message.answer(f"⚠️ Нельзя забрать")
    
    await state.clear()

@dp.callback_query(F.data == "admin_list_admins")
async def admin_list_admins(callback: CallbackQuery):
    """Список администраторов"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    text = "📋 СПИСОК АДМИНИСТРАТОРОВ:\n\n"
    for uid in sorted(admins):
        user_info = users_db.get(uid, {})
        username = user_info.get('username', 'нет')
        text += f"• {uid} (@{username}){' (главный)' if uid == ADMIN_ID else ''}\n"
    text += f"\nВсего: {len(admins)}"
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

# ==================== ЧЕРНЫЙ СПИСОК ====================

@dp.callback_query(F.data == "admin_blacklist_menu")
async def admin_blacklist_menu(callback: CallbackQuery):
    """Меню ЧС"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("⛔ УПРАВЛЕНИЕ ЧС", reply_markup=get_admin_blacklist_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_blacklist_add")
async def admin_blacklist_add(callback: CallbackQuery, state: FSMContext):
    """Добавление в ЧС"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("⛔ Введите ID для ЧС:")
    await state.set_state(ReferralStates.waiting_for_blacklist_id)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_blacklist_id)
async def process_blacklist_add(message: Message, state: FSMContext):
    """Обработка добавления в ЧС"""
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    if check_protected_id(user_id):
        await message.answer("⚠️ Защищен")
        await state.clear()
        return
    
    if is_admin(user_id):
        await message.answer("⚠️ Админ")
        await state.clear()
        return
    
    blacklist.add(user_id)
    
    try:
        await bot.send_message(user_id, "⛔ Вы в ЧС")
    except:
        pass
    
    await message.answer(f"✅ {user_id} в ЧС")
    await state.clear()

@dp.callback_query(F.data == "admin_blacklist_remove")
async def admin_blacklist_remove(callback: CallbackQuery, state: FSMContext):
    """Удаление из ЧС"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("✅ Введите ID для удаления из ЧС:")
    await state.set_state(ReferralStates.waiting_for_unblacklist_id)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_unblacklist_id)
async def process_blacklist_remove(message: Message, state: FSMContext):
    """Обработка удаления из ЧС"""
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    if user_id in blacklist:
        blacklist.remove(user_id)
        await message.answer(f"✅ {user_id} удален из ЧС")
        try:
            await bot.send_message(user_id, "✅ Вы удалены из ЧС")
        except:
            pass
    else:
        await message.answer(f"⚠️ {user_id} не в ЧС")
    
    await state.clear()

# ==================== БЕЛЫЙ СПИСОК ====================

@dp.callback_query(F.data == "admin_whitelist_menu")
async def admin_whitelist_menu(callback: CallbackQuery):
    """Меню белого списка"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("📋 УПРАВЛЕНИЕ БЕЛЫМ СПИСКОМ", reply_markup=get_admin_whitelist_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_whitelist_add")
async def admin_whitelist_add(callback: CallbackQuery, state: FSMContext):
    """Добавление в белый список"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("➕ Введите ID для белого списка:")
    await state.set_state(ReferralStates.waiting_for_whitelist_id)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_whitelist_id)
async def process_whitelist_add(message: Message, state: FSMContext):
    """Обработка добавления в белый список"""
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    whitelist.add(user_id)
    
    try:
        await bot.send_message(user_id, "💘 Вы в белом списке!")
    except:
        pass
    
    await message.answer(f"✅ {user_id} в белом списке")
    await state.clear()

@dp.callback_query(F.data == "admin_whitelist_remove")
async def admin_whitelist_remove(callback: CallbackQuery, state: FSMContext):
    """Удаление из белого списка"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text("➖ Введите ID для удаления из белого списка:")
    await state.set_state(ReferralStates.waiting_for_whitelist_id)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_whitelist_id)
async def process_whitelist_remove(message: Message, state: FSMContext):
    """Обработка удаления из белого списка"""
    try:
        user_id = int(message.text)
    except:
        await message.answer("❌ Неверный ID")
        await state.clear()
        return
    
    if user_id in whitelist and user_id != PROTECTED_ID and user_id != ADMIN_ID:
        whitelist.remove(user_id)
        await message.answer(f"✅ {user_id} удален из белого списка")
    else:
        await message.answer(f"⚠️ Нельзя удалить защищенный ID")
    
    await state.clear()

@dp.callback_query(F.data == "admin_whitelist_show")
async def admin_whitelist_show(callback: CallbackQuery):
    """Показать белый список"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    text = "📋 БЕЛЫЙ СПИСОК:\n\n"
    for uid in sorted(whitelist):
        user_info = users_db.get(uid, {})
        username = user_info.get('username', 'нет')
        text += f"• {uid} (@{username})\n"
    text += f"\nВсего: {len(whitelist)}"
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

# ==================== ТЕХНИЧЕСКИЕ РАБОТЫ ====================

@dp.callback_query(F.data == "admin_maintenance_on")
async def admin_maintenance_on(callback: CallbackQuery, state: FSMContext):
    """Включение техработ"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    await callback.message.edit_text(
        "🔧 ВКЛЮЧЕНИЕ ТЕХРАБОТ\n\n"
        "Введите время окончания:\n"
        "• ЧЧ:ММ (23:59)\n"
        "• ДД.ММ.ГГГГ ЧЧ:ММ (31.12.2024 23:59)\n"
        "• 30m, 2h, 1d"
    )
    await state.set_state(ReferralStates.waiting_for_maintenance_time)
    await callback.answer()

@dp.message(ReferralStates.waiting_for_maintenance_time)
async def process_maintenance_time(message: Message, state: FSMContext):
    """Обработка времени техработ"""
    global maintenance_mode, maintenance_end_time, maintenance_message_text
    
    time_text = message.text.lower()
    end_time = None
    
    if re.match(r'^\d{1,2}:\d{2}$', time_text):
        hours, minutes = map(int, time_text.split(':'))
        now = datetime.now()
        end_time = datetime(now.year, now.month, now.day, hours, minutes)
        if end_time < now:
            end_time += timedelta(days=1)
        maintenance_message_text = f"🚧 До {end_time.strftime('%d.%m.%Y %H:%M')} МСК"
    
    elif re.match(r'^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$', time_text):
        end_time = datetime.strptime(time_text, '%d.%m.%Y %H:%M')
        maintenance_message_text = f"🚧 До {end_time.strftime('%d.%m.%Y %H:%M')} МСК"
    
    else:
        seconds = parse_time_string(time_text)
        if seconds:
            end_time = datetime.now() + timedelta(seconds=seconds)
            maintenance_message_text = f"🚧 На {format_time_delta(seconds)}"
        else:
            await message.answer("❌ Неверный формат")
            return
    
    await state.update_data(end_time=end_time)
    await message.answer("📝 Причина (или 'нет'):")
    await state.set_state(ReferralStates.waiting_for_maintenance_reason)

@dp.message(ReferralStates.waiting_for_maintenance_reason)
async def process_maintenance_reason(message: Message, state: FSMContext):
    """Обработка причины техработ"""
    global maintenance_mode, maintenance_end_time, maintenance_reason
    
    data = await state.get_data()
    end_time = data.get('end_time')
    reason = "" if message.text.lower() == 'нет' else message.text
    
    maintenance_mode = True
    maintenance_end_time = end_time
    maintenance_reason = reason
    
    maintenance_history.append({
        'admin': message.from_user.id,
        'admin_name': message.from_user.first_name,
        'start': datetime.now(),
        'end': end_time,
        'reason': reason,
        'status': 'active'
    })
    
    await message.answer(f"✅ Техработы включены!\n{maintenance_message_text}\n{reason}")
    await state.clear()

@dp.callback_query(F.data == "admin_maintenance_off")
async def admin_maintenance_off(callback: CallbackQuery):
    """Выключение техработ"""
    global maintenance_mode, maintenance_end_time, maintenance_reason, maintenance_message_text
    
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    if maintenance_history:
        maintenance_history[-1]['status'] = 'completed'
        maintenance_history[-1]['actual_end'] = datetime.now()
    
    maintenance_mode = False
    maintenance_end_time = None
    maintenance_reason = ""
    maintenance_message_text = "🚧 Ведутся технические работы. Бот временно недоступен."
    
    await callback.message.edit_text("✅ Техработы выключены")
    await callback.answer()

@dp.callback_query(F.data == "admin_maintenance_history")
async def admin_maintenance_history(callback: CallbackQuery):
    """История техработ"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    if not maintenance_history:
        await callback.message.edit_text("📜 История пуста", reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    text = "📜 ИСТОРИЯ ТЕХРАБОТ:\n\n"
    for i, record in enumerate(reversed(maintenance_history[-10:]), 1):
        admin = record.get('admin_name', f"ID: {record['admin']}")
        start = record['start'].strftime('%d.%m.%Y %H:%M')
        end = record['end'].strftime('%d.%m.%Y %H:%M') if record['end'] else "?"
        status = "✅" if record.get('status') == 'completed' else "⏳"
        
        text += f"{status} {i}. {start} - {end}\n"
        text += f"   👤 {admin}\n"
        if record.get('reason'):
            text += f"   📝 {record['reason']}\n"
        text += "\n"
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

# ==================== СТАТИСТИКА ====================

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    """Статистика"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    total = len(users_db)
    active = sum(1 for u in users_db.values() if u.get('active_refs', 0) > 0)
    links_done = sum(1 for u in users_db.values() if u.get('link1_done') or u.get('link2_done'))
    
    text = (f"📊 СТАТИСТИКА\n\n"
            f"👥 Всего: {total}\n"
            f"📊 Активных: {active}\n"
            f"✅ Выполнено: {links_done}\n"
            f"⛔ В ЧС: {len(blacklist)}\n"
            f"⏰ В бане: {len(temp_bans)}\n"
            f"💘 Белый список: {len(whitelist)}\n"
            f"👑 Админов: {len(admins)}\n"
            f"🛡 Модераторов: {len(moderators)}\n"
            f"🔧 Техработы: {'ВКЛ' if maintenance_mode else 'ВЫКЛ'}")
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_bot_status")
async def admin_bot_status(callback: CallbackQuery):
    """Статус бота"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    
    uptime = datetime.now() - start_time
    uptime_str = str(uptime).split('.')[0]
    
    text = (f"📊 СТАТУС БОТА\n\n"
            f"✅ Работает\n"
            f"⏱ Аптайм: {uptime_str}\n"
            f"👥 Пользователей: {len(users_db)}\n"
            f"👑 Админов: {len(admins)}\n"
            f"🛡 Модераторов: {len(moderators)}\n"
            f"⛔ В ЧС: {len(blacklist)}\n"
            f"💘 Белый список: {len(whitelist)}\n"
            f"🔧 Техработы: {'ВКЛ' if maintenance_mode else 'ВЫКЛ'}")
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())
    await callback.answer()

# ==================== УПРАВЛЕНИЕ БОТОМ ====================

@dp.message(Command("restart"))
@dp.message(Command("reboot"))
async def cmd_restart(message: Message):
    """Перезапуск бота"""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.answer("⛔ Нет прав")
        return
    
    await message.answer("🔄 Перезапуск...")
    await asyncio.sleep(1)
    os.execl(sys.executable, sys.executable, *sys.argv)

@dp.message(Command("shutdown"))
@dp.message(Command("stop"))
async def cmd_shutdown(message: Message):
    """Остановка бота"""
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.answer("⛔ Нет прав")
        return
    
    await message.answer("🛑 Остановка...")
    await asyncio.sleep(1)
    await bot.session.close()
    sys.exit(0)

@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Статус бота"""
    user_id = message.from_user.id
    if not is_admin(user_id) and not is_moderator(user_id):
        await message.answer("⛔ Нет прав")
        return
    
    uptime = datetime.now() - start_time
    uptime_str = str(uptime).split('.')[0]
    
    text = (f"📊 СТАТУС\n\n"
            f"✅ Работает\n"
            f"⏱ Аптайм: {uptime_str}\n"
            f"👥 Пользователей: {len(users_db)}\n"
            f"🔧 Техработы: {'ВКЛ' if maintenance_mode else 'ВЫКЛ'}\n\n"
            f"/restart - перезапуск\n"
            f"/shutdown - остановка")
    
    await message.answer(text)

@dp.callback_query(F.data == "admin_restart_bot")
async def admin_restart_bot(callback: CallbackQuery):
    """Перезапуск через админку"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет прав")
        return
    
    await callback.message.edit_text("🔄 Перезапуск...")
    await callback.answer()
    await asyncio.sleep(1)
    os.execl(sys.executable, sys.executable, *sys.argv)

@dp.callback_query(F.data == "admin_shutdown_bot")
async def admin_shutdown_bot(callback: CallbackQuery):
    """Остановка через админку"""
    if not callback.message:
        await callback.answer("Ошибка")
        return
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет прав")
        return
    
    await callback.message.edit_text("🛑 Остановка...")
    await callback.answer()
    await asyncio.sleep(1)
    await bot.session.close()
    sys.exit(0)

# ==================== ВСЕ ОСТАЛЬНЫЕ СООБЩЕНИЯ ====================

@dp.message()
async def handle_other_messages(message: Message, state: FSMContext):
    """Просто игнорируем все остальные сообщения"""
    pass

# ==================== ЗАПУСК ====================

async def main():
    """Запуск бота"""
    logger.info("🚀 Запуск бота...")
    logger.info(f"👑 Главный админ: {ADMIN_ID}")
    logger.info(f"🛡 Защищенный ID: {PROTECTED_ID}")
    
    # Запускаем веб-сервер для бесконечной работы
    keep_alive()
    
    # Запускаем пинговалку
    start_pinger()
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())