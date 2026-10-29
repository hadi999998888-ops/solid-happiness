import json
import os
import secrets
import logging
import asyncio
import time
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================================================
# EXTRA CHEAT 🐍 — НАСТРОЙКИ
# ==================================================

TOKEN = "8757046363:AAFcqTiRJl5CD9C_Enb9QVzsEV5EVIMd_fQ"

ADMIN_ID = 7608889836

MAIN_CHANNEL_ID = -1003957801744
MAIN_CHANNEL_URL = "https://t.me/ExtraCheatStanddof2"

DISCUSSION_CHAT_ID = 0  # ID группы комментариев
MANAGER_URL = "https://t.me/True_Nvalny"
BOT_USERNAME = "ExtraCheatbot"

POSTS_FILE = "posts.json"
CHANNELS_FILE = "channels.json"
USERS_FILE = "users.json"
EXTRA_FILE = "extra_data.json"

# Дополнительные администраторы добавляются через панель по Telegram ID.

START_IMAGE = "Start.jpg"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

posts = {}
channels = {}
users = set()
states = {}
extra = {}


def is_admin(user_id):
    return int(user_id) == int(ADMIN_ID) or str(user_id) in extra.get("admins", [])


def save_extra():
    save_json(EXTRA_FILE, extra)


# ==================================================
# СОХРАНЕНИЕ ДАННЫХ
# ==================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        log.exception("Ошибка чтения %s", filename)
        return default


def save_json(filename, data):
    temp = filename + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(temp, filename)


def load_data():
    global posts, channels, users, extra

    posts = load_json(POSTS_FILE, {})
    channels = load_json(CHANNELS_FILE, {})
    users = set(int(x) for x in load_json(USERS_FILE, []))
    extra = load_json(EXTRA_FILE, {"admins": [], "profiles": {}, "promos": {}, "bans": [], "mutes": {}, "notifications": True})
    for key, value in {"admins": [], "profiles": {}, "promos": {}, "bans": [], "mutes": {}, "notifications": True}.items():
        extra.setdefault(key, value)

    # Главный канал всегда обязателен.
    channels[str(MAIN_CHANNEL_ID)] = {
        "id": MAIN_CHANNEL_ID,
        "title": "EXTRA CHEAT",
        "url": MAIN_CHANNEL_URL,
        "main": True,
    }

    save_json(CHANNELS_FILE, channels)


def save_users():
    save_json(USERS_FILE, sorted(users))


def save_posts():
    save_json(POSTS_FILE, posts)


def save_channels():
    save_json(CHANNELS_FILE, channels)


# ==================================================
# КЛАВИАТУРЫ
# ==================================================

def main_menu_keyboard(is_admin=False):
    rows = [["⌨️ Главное меню"], ["⚙️ Промокоды"]]
    if is_admin:
        rows.append(["⚙️ Админ-панель"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def admin_keyboard():
    return main_menu_keyboard(is_admin=True)


def panel_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🐍 Создать пост", "🎟️ Создать промокод"],
            ["⚙️ Бан лист", "👥 Администраторы"],
            ["🔔 Уведомления", "📡 Подписки"],
            ["📨 Рассылка"],
            ["🚪 Выйти"],
        ],
        resize_keyboard=True,
    )


def subscription_keyboard(post_id=None):
    buttons = []

    for channel in channels.values():
        url = channel.get("url")
        if url:
            buttons.append([
                InlineKeyboardButton(
                    f"📢 {channel.get('title', 'Канал')}",
                    url=url,
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            "✅ Я подписался — проверить",
            callback_data=(f"check_post:{post_id}" if post_id else "check_subscriptions"),
        )
    ])

    return InlineKeyboardMarkup(buttons)


def password_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Нет", callback_data="password_no"),
        InlineKeyboardButton("🔐 Да", callback_data="password_yes"),
    ]])


def generate_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🐍 Сгенерировать ссылку",
            callback_data="generate",
        )
    ]])


def channel_management_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Добавить канал",
                callback_data="channel_add",
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Список каналов",
                callback_data="channel_list",
            )
        ],
    ])


def channel_list_keyboard():
    buttons = []

    for channel in channels.values():
        channel_id = channel["id"]
        title = channel.get("title", str(channel_id))

        if channel.get("main"):
            buttons.append([
                InlineKeyboardButton(
                    f"🔒 {title} (главный)",
                    callback_data="channel_main",
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    f"🗑 Удалить: {title}",
                    callback_data=f"channel_remove:{channel_id}",
                )
            ])

    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="channel_back")
    ])

    return InlineKeyboardMarkup(buttons)


def post_channel_keyboard(post_id=None):
    buttons = []

    for channel in channels.values():
        url = channel.get("url")
        if url:
            buttons.append([
                InlineKeyboardButton(
                    f"🐍 {channel.get('title', 'Наш канал')}",
                    url=url,
                )
            ])

    if post_id:
        buttons.append([
            InlineKeyboardButton(
                "✅ Проверить подписки",
                callback_data=f"check_post:{post_id}",
            )
        ])

    return InlineKeyboardMarkup(buttons)


# ==================================================
# ПОДПИСКИ
# ==================================================

async def check_channel(bot, user_id, channel_id):
    try:
        member = await bot.get_chat_member(
            chat_id=channel_id,
            user_id=user_id,
        )

        if member.status in ("creator", "administrator", "member"):
            return True

        if member.status == "restricted":
            return bool(getattr(member, "is_member", False))

        return False

    except Exception:
        log.exception("Не удалось проверить канал %s", channel_id)
        return False


async def missing_subscriptions(bot, user_id):
    missing = []

    for channel in channels.values():
        channel_id = channel["id"]

        if not await check_channel(bot, user_id, channel_id):
            missing.append(channel)

    return missing


async def send_subscription_required(bot, chat_id, post_id=None):
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🐍 Подпишитесь для продолжения\n"
            "Кнопки для перехода 👇🏻"
        ),
        reply_markup=subscription_keyboard(post_id),
    )


# ==================================================
# МАТЕРИАЛЫ
# ==================================================

def get_material_type(message):
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.document:
        return "document"
    if message.animation:
        return "animation"
    if message.audio:
        return "audio"
    if message.voice:
        return "voice"
    if message.video_note:
        return "video_note"
    if message.sticker:
        return "sticker"
    if message.text is not None:
        return "text"

    return "other"


async def send_material(bot, chat_id, post):
    material_type = post["type"]
    source_chat_id = post["source_chat_id"]
    source_message_id = post["source_message_id"]
    description = post.get("description", "")

    if material_type == "text":
        text = post.get("original_text", "")

        if description:
            text += "\n\n" + description

        await bot.send_message(
            chat_id=chat_id,
            text=text or "🐍 EXTRA CHEAT",
            reply_markup=post_channel_keyboard(),
        )
        return

    if material_type in ("sticker", "video_note", "other"):
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=source_chat_id,
            message_id=source_message_id,
        )

        if description:
            await bot.send_message(
                chat_id=chat_id,
                text=description,
                reply_markup=post_channel_keyboard(),
            )
        return

    caption = post.get("original_caption", "")

    if description:
        caption = f"{caption}\n\n{description}" if caption else description

    await bot.copy_message(
        chat_id=chat_id,
        from_chat_id=source_chat_id,
        message_id=source_message_id,
        caption=caption or None,
        reply_markup=post_channel_keyboard(),
    )


async def deliver_post(bot, chat_id, post_id):
    post = posts.get(post_id)

    if not post:
        await bot.send_message(chat_id, "❌ Материал не найден.")
        return

    loading = await bot.send_message(chat_id, "⏳Узнаю что вы хотите получить🤔")
    await asyncio.sleep(2)
    try:
        await loading.edit_text("⌛Отправляю вам материал✅")
    except Exception:
        pass
    await asyncio.sleep(2)
    try:
        await send_material(bot, chat_id, post)
        try: await loading.delete()
        except Exception: pass
    except Exception:
        try: await loading.delete()
        except Exception: pass
        log.exception("Ошибка выдачи поста %s", post_id)
        await bot.send_message(
            chat_id,
            "❌ Не удалось отправить материал. Попробуй позже.",
        )


async def request_post(bot, chat_id, user_id, post_id):
    post = posts.get(post_id)

    if not post:
        await bot.send_message(chat_id, "❌ Пост не найден.")
        return

    if await enforce_access(bot, chat_id, user_id):
        return
    missing = [] if await premium_active(user_id) else await missing_subscriptions(bot, user_id)

    if missing:
        await bot.send_message(chat_id, "😥 Вы не были подписаны на нужные каналы\n\nПрошу подписаться на каналы", reply_markup=subscription_keyboard(post_id))
        return

    password = post.get("password", "")

    if password:
        states[user_id] = {
            "step": "get_password",
            "post_id": post_id,
        }

        await bot.send_message(
            chat_id,
            "🔐 EXTRA CHEAT — защищённый материал\n\n"
            "Введи код-пароль, чтобы получить файл и описание.",
        )
        return

    states.pop(user_id, None)
    await deliver_post(bot, chat_id, post_id)


# ==================================================
# ПРОМОКОДЫ, ПОЛЬЗОВАТЕЛИ, БАНЫ И УВЕДОМЛЕНИЯ
# ==================================================

def user_label(user):
    return ("@" + user.username) if user.username else (user.full_name or str(user.id))


async def notify_admins(bot, text):
    if not extra.get("notifications", True):
        return
    for aid in [ADMIN_ID] + [int(x) for x in extra.get("admins", []) if str(x).isdigit()]:
        try:
            await bot.send_message(aid, text[:4000])
        except Exception:
            pass


async def enforce_access(bot, chat_id, user_id):
    if is_admin(user_id):
        return False
    if user_id in set(int(x) for x in extra.get("bans", [])):
        await bot.send_message(chat_id, "❗ Вы забанены в боте")
        return True
    mute = extra.get("mutes", {}).get(str(user_id))
    if mute:
        until = int(mute.get("until", 0))
        if until > int(time.time()):
            await bot.send_message(chat_id, "❗ Вы замучены. Прошу обратиться к поддержке или подождать окончания мута. Мут не вечный! ❗")
            return True
        extra["mutes"].pop(str(user_id), None)
        save_extra()
        await bot.send_message(chat_id, "🎉 Вы можете использовать нашего бота!\nВы размучены.")
    return False


def promo_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Месяц", callback_data="promo_period:month"), InlineKeyboardButton("⏳ Неделя", callback_data="promo_period:week")], [InlineKeyboardButton("⏳ День", callback_data="promo_period:day"), InlineKeyboardButton("⏳ Час", callback_data="promo_period:hour")]])


def promo_announce_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Да", callback_data="promo_announce:yes"), InlineKeyboardButton("❌ Нет", callback_data="promo_announce:no")]])


def banlist_keyboard(page=0, query=""):
    profiles = extra.get("profiles", {})
    rows=[]
    matches=[]
    for uid, data in profiles.items():
        name=data.get("username") or data.get("name") or uid
        if query and query.lower() not in str(name).lower() and query.lower() not in uid:
            continue
        matches.append((uid, name))
    matches.sort(key=lambda x: x[1].lower())
    start=page*5
    for uid,name in matches[start:start+5]:
        rows.append([InlineKeyboardButton(str(name)[:50], callback_data=f"user_select:{uid}")])
    nav=[]
    if page>0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"ban_page:{page-1}:{query}"))
    if start+5<len(matches): nav.append(InlineKeyboardButton("➡️", callback_data=f"ban_page:{page+1}:{query}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔎 Найти игрока", callback_data="ban_search")])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="panel_back")])
    return InlineKeyboardMarkup(rows)


async def expiry_worker(app):
    while True:
        now=int(time.time())
        changed=False
        for code,promo in list(extra.get("promos", {}).items()):
            if not promo.get("expired_notice") and int(promo.get("expires", 0)) <= now:
                promo["expired_notice"]=True
                changed=True
                try:
                    await app.bot.send_message(MAIN_CHANNEL_ID, f"🐍 Промокод {code} истёк!\nВы опоздали, ждите новых промокодов.")
                except Exception:
                    log.exception("Не удалось опубликовать истечение промокода")
        for uid,mute in list(extra.get("mutes", {}).items()):
            if not mute.get("notified") and int(mute.get("until",0)) <= now:
                mute["notified"]=True; changed=True
                try:
                    await app.bot.send_message(int(uid), "🎉 Вы можете использовать нашего бота!\nВы размучены.")
                except Exception: pass
                extra["mutes"].pop(uid, None)
        if changed: save_extra()
        await asyncio.sleep(20)


async def activate_promo(message, user_id, code):
    promo=extra.get("promos", {}).get(code.upper())
    now=int(time.time())
    if not promo or promo.get("expires",0)<=now or promo.get("used",0)>=promo.get("limit",0):
        await message.reply_text("🫡 Место закончилось, прошу получить новый промокод.")
        return
    if str(user_id) in promo.setdefault("users", []):
        await message.reply_text("ℹ️ Ты уже активировал этот промокод.")
        return
    seconds={"month":30*86400,"week":7*86400,"day":86400,"hour":3600}[promo["period"]]
    profile=extra.setdefault("profiles",{}).setdefault(str(user_id),{})
    current=max(now,int(profile.get("premium_until",0)))
    profile["premium_until"]=current+seconds
    promo["used"]+=1; promo["users"].append(str(user_id))
    save_extra()
    period={"month":"месяц","week":"неделю","day":"день","hour":"час"}[promo["period"]]
    await message.reply_text(f"🎉 Успешное подключение!\nТы активировал промокод на {period}.\nТеперь тебе не нужно подписываться на нужные каналы — ты можешь пользоваться ботом бесплатно.")
    await notify_admins(message.get_bot(), f"🎟️ Активация промокода {code} пользователем ID {user_id}")


async def premium_active(user_id):
    profile=extra.get("profiles",{}).get(str(user_id),{})
    return int(profile.get("premium_until",0))>int(time.time())


# ==================================================
# START
# ==================================================

async def show_main_menu(message, user_id):
    is_admin_user = is_admin(user_id)
    text = (
        "🐍 Добро пожаловать в главное меню\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "EXTRA CHEAT\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📢 Пожалуйста, подпишитесь на наш канал, чтобы получать материалы.\n"
        "Бот не может работать без подписки.\n\n"
        f"💬 По поводу рекламы пишите менеджеру: {MANAGER_URL}\n"
        "⏳ Менеджер ответит, как только появится возможность — это зависит от его занятости."
    )
    if os.path.exists(START_IMAGE):
        try:
            with open(START_IMAGE, "rb") as photo:
                await message.reply_photo(
                    photo=photo,
                    caption=text,
                    reply_markup=main_menu_keyboard(is_admin_user),
                )
            return
        except Exception:
            log.exception("Не удалось отправить Start.jpg")
    await message.reply_text(text, reply_markup=main_menu_keyboard(is_admin_user))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return

    if user.id not in users:
        users.add(user.id)
        try:
            save_users()
        except OSError:
            log.exception("Не удалось сохранить пользователя")
    profile = extra.setdefault("profiles", {}).setdefault(str(user.id), {})
    profile.update({"id": user.id, "name": user.full_name, "username": user.username or "", "last_seen": int(time.time())})
    save_extra()
    if await enforce_access(context.bot, message.chat_id, user.id):
        return
    await notify_admins(context.bot, f"👤 Пользователь запустил бота: {user_label(user)} | ID: {user.id}")

    # Прямая ссылка на ввод промокода из рекламного поста.
    if context.args and context.args[0] == "promo":
        states[user.id]={"step":"redeem_promo"}
        await message.reply_text("⌨️ Введите промокод\nЕго можно получить в нашем канале")
        return

    # Deep-link на конкретный материал сохраняет прежнее поведение.
    if context.args and context.args[0].startswith("post_"):
        post_id = context.args[0][5:]
        if post_id not in posts:
            await message.reply_text("❌ Материал не найден или ссылка устарела.")
            return
        await request_post(context.bot, message.chat_id, user.id, post_id)
        return

    missing = [] if await premium_active(user.id) else await missing_subscriptions(context.bot, user.id)
    if missing:
        await send_subscription_required(context.bot, message.chat_id)
        return

    states.pop(user.id, None)
    await show_main_menu(message, user.id)


# ==================================================
# ДОБАВЛЕНИЕ КАНАЛА
# ==================================================

async def add_channel_from_id(bot, raw_id):
    try:
        chat = await bot.get_chat(int(raw_id.strip()))
    except Exception:
        return False, (
            "❌ Не удалось найти канал.\n\n"
            "Проверь ID и убедись, что бот добавлен в канал "
            "администратором."
        )

    if chat.type != "channel":
        return False, "❌ Это не канал. Отправь ID именно канала."

    try:
        bot_user = await bot.get_me()
        member = await bot.get_chat_member(chat.id, bot_user.id)
        if member.status not in ("administrator", "creator"):
            return False, (
                "❌ Сначала добавь бота в канал администратором, "
                "затем попробуй снова."
            )
    except Exception:
        return False, (
            "❌ Бот не видит канал. Добавь его администратором "
            "и проверь ID."
        )

    key = str(chat.id)

    if key in channels:
        return False, "ℹ️ Этот канал уже есть в обязательных подписках."

    url = f"https://t.me/{chat.username}" if chat.username else ""

    if not url:
        try:
            invite = await bot.create_chat_invite_link(chat.id)
            url = invite.invite_link
        except Exception:
            return False, (
                "❌ Не удалось создать ссылку на канал.\n"
                "Проверь права бота на приглашение пользователей."
            )

    channels[key] = {
        "id": chat.id,
        "title": chat.title or str(chat.id),
        "url": url,
        "main": False,
    }

    save_channels()

    return True, (
        f"✅ Канал добавлен!\n\n"
        f"📢 {chat.title}\n"
        f"🆔 {chat.id}\n\n"
        "Теперь подписка на него обязательна для получения материалов."
    )


async def add_channel_from_forward(bot, message):
    origin = getattr(message, "forward_origin", None)

    if not origin or getattr(origin, "type", None) != "channel":
        return False, (
            "❌ Не вижу пересланную публикацию канала.\n\n"
            "Перешли сюда сообщение именно из канала "
            "или отправь ID канала."
        )

    chat = origin.chat

    return await add_channel_from_id(bot, str(chat.id))


# ==================================================
# АДМИН-ПАНЕЛЬ
# ==================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return
    if await enforce_access(context.bot, message.chat_id, user.id):
        return
    profile=extra.setdefault("profiles",{}).setdefault(str(user.id),{})
    profile.update({"id":user.id,"name":user.full_name,"username":user.username or "","last_seen":int(time.time())})
    save_extra()
    if not is_admin(user.id):
        safe_state=states.get(user.id,{})
        if safe_state.get("step") not in ("get_password", "redeem_promo"):
            activity=(message.text or message.caption or "[медиа]")[:200]
            await notify_admins(context.bot, f"📩 Действие пользователя: {user_label(user)} | ID {user.id} | {activity}")
        else:
            await notify_admins(context.bot, f"📩 Пользователь {user_label(user)} | ID {user.id} отправил данные для проверки")

    # Пароль пользователя, который получает пост.
    state = states.get(user.id)

    if state and state.get("step") == "get_password":
        if not message.text:
            await message.reply_text("🔐 Отправь код обычным текстом.")
            return

        post = posts.get(state["post_id"])

        if not post:
            states.pop(user.id, None)
            await message.reply_text("❌ Материал больше не найден.")
            return

        entered = message.text.strip()
        correct = str(post.get("password", ""))

        if secrets.compare_digest(entered, correct):
            post_id = state["post_id"]
            states.pop(user.id, None)

            # Повторно проверяем подписки перед выдачей.
            missing = [] if await premium_active(user.id) else await missing_subscriptions(context.bot, user.id)

            if missing:
                await send_subscription_required(
                    context.bot,
                    message.chat_id,
                    post_id,
                )
                return

            await message.reply_text("✅ Код верный! Загружаю материал 🐍")
            await deliver_post(context.bot, message.chat_id, post_id)
        else:
            await message.reply_text("❌ Неверный код. Попробуй ещё раз.")
        return

    text = message.text or ""
    if text == "⚙️ Промокоды" and not is_admin(user.id):
        states[user.id]={"step":"redeem_promo"}
        await message.reply_text("⌨️ Введите промокод\nЕго можно получить в нашем канале")
        return
    if state and state.get("step")=="redeem_promo" and not is_admin(user.id):
        states.pop(user.id,None)
        await activate_promo(message,user.id,text.strip())
        return
    if not is_admin(user.id):
        return

    if text == "🎟️ Создать промокод":
        states[user.id]={"step":"promo_period"}
        await message.reply_text("🐍 Здравствуйте! На какой срок будет промокод?",reply_markup=promo_keyboard())
        return
    if text == "⚙️ Бан лист":
        await message.reply_text("⚙️ Бан лист\nСписок пользователей:",reply_markup=banlist_keyboard())
        return
    if text == "🔔 Уведомления":
        enabled=not extra.get("notifications",True)
        extra["notifications"]=enabled; save_extra()
        await message.reply_text("🔔 Уведомления включены." if enabled else "🔕 Уведомления выключены.",reply_markup=panel_keyboard())
        return
    if text == "👥 Администраторы":
        states[user.id]={"step":"admin_manage"}
        admins=extra.get("admins",[])
        await message.reply_text("👥 Дополнительные администраторы:\n"+ ("\n".join(admins) if admins else "Пока нет") + "\n\nОтправь ID для добавления или напиши: удалить ID")
        return
    if state and state.get("step")=="admin_manage":
        raw=text.strip()
        if raw.lower().startswith("удалить "):
            aid=raw.split(maxsplit=1)[1]
            if aid in extra["admins"]: extra["admins"].remove(aid); save_extra()
            await message.reply_text("✅ Администратор удалён.")
        elif raw.isdigit() and int(raw)!=ADMIN_ID:
            if raw not in extra["admins"]: extra["admins"].append(raw); save_extra()
            await message.reply_text("✅ Администратор добавлен.")
        else: await message.reply_text("❌ Отправь корректный Telegram ID.")
        return
    if state and state.get("step")=="promo_limit":
        if not text.isdigit() or int(text)<1 or int(text)>100000:
            await message.reply_text("Отправь число от 1 до 100000."); return
        state["limit"]=int(text); state["step"]="promo_announce"
        await message.reply_text("🐍 Сообщить о новом промокоде в канал?",reply_markup=promo_announce_keyboard())
        return
    if state and state.get("step")=="ban_search":
        states.pop(user.id,None)
        await message.reply_text("🔎 Результаты поиска:",reply_markup=banlist_keyboard(0,text.strip()))
        return
    if state and state.get("step")=="mute_duration":
        if not text.isdigit() or int(text)<1 or int(text)>525600:
            await message.reply_text("Укажи количество минут от 1 до 525600."); return
        uid=state["target"]; until=int(time.time())+int(text)*60
        extra.setdefault("mutes",{})[str(uid)]={"until":until,"notified":False}; save_extra(); states.pop(user.id,None)
        try: await context.bot.send_message(uid,"❗ Вы замучены. Прошу обратиться к поддержке или же подождать размута. Мут не вечный! ❗")
        except Exception: pass
        await message.reply_text("✅ Мут выдан.",reply_markup=panel_keyboard()); return

    if text == "⌨️ Главное меню":
        missing = await missing_subscriptions(context.bot, user.id)
        if missing:
            await send_subscription_required(context.bot, message.chat_id)
            return
        states.pop(user.id, None)
        await show_main_menu(message, user.id)
        return

    if text == "⚙️ Админ-панель":
        if not is_admin(user.id):
            return
        missing = await missing_subscriptions(context.bot, user.id)
        if missing:
            await send_subscription_required(context.bot, message.chat_id)
            return
        states.pop(user.id, None)
        await message.reply_text(
            "🐍 EXTRA CHEAT — админ-панель",
            reply_markup=panel_keyboard(),
        )
        return

    if text == "🚪 Выйти":
        states.pop(user.id, None)
        await message.reply_text(
            "Ты вышел из админ-панели.",
            reply_markup=admin_keyboard(),
        )
        return

    if text == "📡 Подписки":
        states.pop(user.id, None)
        await message.reply_text(
            "📡 Управление обязательными подписками\n\n"
            "Главный канал EXTRA CHEAT всегда обязателен.\n"
            "Ты можешь добавить дополнительные каналы или удалить их.",
            reply_markup=channel_management_keyboard(),
        )
        return

    if text == "📨 Рассылка":
        states[user.id] = {"step": "broadcast"}
        await message.reply_text(
            "📨 Рассылка EXTRA CHEAT\n\n"
            "Отправь сообщение, фото, видео или файл, "
            "который нужно разослать всем пользователям бота.\n\n"
            "Для отмены напиши: отмена"
        )
        return

    if state and state.get("step") == "broadcast":
        if text.lower().strip() == "отмена":
            states.pop(user.id, None)
            await message.reply_text(
                "❌ Рассылка отменена.",
                reply_markup=panel_keyboard(),
            )
            return

        states.pop(user.id, None)

        sent = 0
        failed = 0

        await message.reply_text("⏳ Начинаю рассылку...")

        for user_id in list(users):
            try:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id,
                )
                sent += 1
            except Exception:
                failed += 1
                log.warning("Не удалось отправить рассылку пользователю %s", user_id)

        await message.reply_text(
            "✅ Рассылка завершена!\n\n"
            f"📨 Доставлено: {sent}\n"
            f"⚠️ Не доставлено: {failed}",
            reply_markup=panel_keyboard(),
        )
        return

    # Добавление канала по ID или пересланной публикации.
    if state and state.get("step") == "add_channel":
        if message.text and message.text.strip().lower() == "отмена":
            states.pop(user.id, None)
            await message.reply_text(
                "Добавление отменено.",
                reply_markup=panel_keyboard(),
            )
            return

        if getattr(message, "forward_origin", None):
            ok, result = await add_channel_from_forward(
                context.bot,
                message,
            )
        elif message.text:
            ok, result = await add_channel_from_id(
                context.bot,
                message.text,
            )
        else:
            await message.reply_text(
                "Отправь ID канала или перешли публикацию из него."
            )
            return

        if ok:
            states.pop(user.id, None)

        await message.reply_text(
            result,
            reply_markup=channel_management_keyboard(),
        )
        return

    if text == "🐍 Создать пост":
        states[user.id] = {"step": "choose_password"}
        await message.reply_text(
            "🐍 EXTRA CHEAT\n\n"
            "Придумать код-пароль для получения материала?",
            reply_markup=password_keyboard(),
        )
        return

    state = states.get(user.id)

    if not state:
        return

    if state.get("step") == "set_password":
        if not message.text:
            await message.reply_text("❌ Пароль нужно отправить текстом.")
            return

        password = message.text.strip()

        if not password or len(password) > 100:
            await message.reply_text(
                "❌ Пароль должен содержать от 1 до 100 символов."
            )
            return

        state["password"] = password
        state["step"] = "material"

        await message.reply_text(
            "🔐 Пароль сохранён!\n\n"
            "📦 Теперь отправь материал: фото, видео, файл или текст."
)
        return

    if state.get("step") == "material":
        material_type = get_material_type(message)
        post_id = secrets.token_hex(4)

        posts[post_id] = {
            "type": material_type,
            "source_chat_id": message.chat_id,
            "source_message_id": message.message_id,
            "password": state.get("password", ""),
            "description": "",
            "original_text": message.text if material_type == "text" else "",
            "original_caption": message.caption if material_type != "text" else "",
        }

        save_posts()
        states[user.id] = {"step": "description", "post_id": post_id}
        await message.reply_text(
            "✅ Материал принят!\n\n"
            "📝 Теперь отправь описание к материалу.\n"
            "Если описание не нужно, напиши: нет"
        )
        return

    if state.get("step") == "description":
        post_id = state.get("post_id")
        if post_id not in posts:
            states.pop(user.id, None)
            await message.reply_text("❌ Материал не найден. Создай пост заново.")
            return
        description = (message.text or message.caption or "").strip()
        if description.lower() == "нет":
            description = ""
        posts[post_id]["description"] = description
        save_posts()
        states[user.id] = {"step": "ready_generate", "post_id": post_id}
        await message.reply_text(
            "✅ Описание сохранено.\n\nНажми кнопку, чтобы создать ссылку:",
            reply_markup=generate_keyboard(),
        )
        return


# ==================================================
# ОБРАБОТЧИК КНОПОК (CALLBACK)
# ==================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    await query.answer()
    data = query.data or ""
    if data.startswith("promo_period:") and is_admin(user.id):
        period=data.split(":",1)[1]
        states[user.id]={"step":"promo_limit","period":period}
        label={"month":"месяц","week":"неделя","day":"день","hour":"час"}[period]
        await query.message.edit_text(f"🐍 Вы выбрали ({label}).\nНа сколько человек он будет? Напишите число снизу.")
        return
    if data.startswith("promo_announce:") and is_admin(user.id):
        state=states.get(user.id,{})
        if state.get("step")!="promo_announce": return
        period=state["period"]; limit=state["limit"]
        code="EXTRA_Code"+str(secrets.randbelow(900000)+100000)
        seconds={"month":30*86400,"week":7*86400,"day":86400,"hour":3600}[period]
        promo={"period":period,"limit":limit,"used":0,"users":[],"expires":int(time.time())+seconds,"expired_notice":False,"announce":data.endswith("yes")}
        extra.setdefault("promos",{})[code]=promo; save_extra(); states.pop(user.id,None)
        await query.message.edit_text("⏳ Генерирую...")
        await asyncio.sleep(2)
        try: await query.message.delete()
        except Exception: pass
        await query.message.reply_text(f"⌛ Промокод сгенерирован!\nВаш промокод: <code>{code}</code>",parse_mode="HTML",reply_markup=panel_keyboard())
        if promo["announce"]:
            period_label={"month":"месяц","week":"неделя","day":"день","hour":"час"}[period]
            await context.bot.send_message(MAIN_CHANNEL_ID,f"🎉 Новый промокод\n<code>{code}</code>\nНа {period_label}; активаций: {limit}\nПиши промокод в бота: https://t.me/{BOT_USERNAME}?start=promo",parse_mode="HTML")
        return
    if data.startswith("ban_page:") and is_admin(user.id):
        _,page,q=data.split(":",2)
        await query.message.edit_reply_markup(reply_markup=banlist_keyboard(int(page),q)); return
    if data=="ban_search" and is_admin(user.id):
        states[user.id]={"step":"ban_search"}; await query.message.reply_text("🔎 Введи имя, username или часть ID:"); return
    if data.startswith("user_select:") and is_admin(user.id):
        uid=data.split(":",1)[1]; states[user.id]={"target":int(uid)}
        prof=extra.get("profiles",{}).get(uid,{})
        label=("@"+prof.get("username")) if prof.get("username") else prof.get("name",uid)
        banned=int(uid) in set(int(x) for x in extra.get("bans",[]))
        muted=uid in extra.get("mutes",{}) and extra["mutes"][uid].get("until",0)>int(time.time())
        rows=[]
        rows.append([InlineKeyboardButton("✅ Разбанить" if banned else "🚫 Забанить",callback_data=f"user_ban:{uid}")])
        rows.append([InlineKeyboardButton("🔊 Снять мут" if muted else "🔇 Замутить",callback_data=f"user_mute:{uid}")])
        rows.append([InlineKeyboardButton("🔙 Назад",callback_data="ban_back")])
        await query.message.edit_text(f"✅ Выбран пользователь: {label}\nID: {uid}\nЧто можно сделать?",reply_markup=InlineKeyboardMarkup(rows)); return
    if data.startswith("user_ban:") and is_admin(user.id):
        uid=int(data.split(":",1)[1]); banned=set(int(x) for x in extra.get("bans",[]))
        if uid in banned: banned.remove(uid); msg="✅ Пользователь разбанен."
        else:
            banned.add(uid); msg="🚫 Пользователь забанен."
            try: await context.bot.send_message(uid,"❗ Вы забанены в боте")
            except Exception: pass
        extra["bans"]=list(banned); save_extra(); await query.message.reply_text(msg); return
    if data.startswith("user_mute:") and is_admin(user.id):
        uid=int(data.split(":",1)[1]); key=str(uid)
        if key in extra.get("mutes",{}) and extra["mutes"][key].get("until",0)>int(time.time()):
            extra["mutes"].pop(key,None); save_extra()
            try: await context.bot.send_message(uid,"🎉 Вы можете использовать нашего бота!\nВы размучены.")
            except Exception: pass
            await query.message.reply_text("✅ Мут снят."); return
        states[user.id]={"step":"mute_duration","target":uid}; await query.message.reply_text("На сколько минут выдать мут? Отправь число."); return
    if data=="ban_back" and is_admin(user.id):
        await query.message.edit_text("⚙️ Бан лист",reply_markup=banlist_keyboard()); return
    if data=="panel_back" and is_admin(user.id):
        await query.message.reply_text("🐍 Админ-панель",reply_markup=panel_keyboard()); return

    if data == "generate":
        state = states.get(user.id, {})
        post_id = state.get("post_id")
        if not is_admin(user.id) or state.get("step") != "ready_generate" or post_id not in posts:
            await query.message.reply_text("❌ Сначала создай материал через админ-панель.")
            return
        post_link = f"https://t.me/{BOT_USERNAME}?start=post_{post_id}"
        states.pop(user.id, None)
        await query.message.reply_text(
            "✅ Пост готов! 🐍\n\n"
            f"🔗 Ссылка для получения:\n<code>{post_link}</code>",
            parse_mode="HTML",
            reply_markup=panel_keyboard(),
        )
        return

    if data == "password_no":
        if not is_admin(user.id):
            return
        states[user.id] = {"password": "", "step": "material"}
        await query.message.edit_text(
            "📦 Без пароля.\n\nТеперь отправь материал (фото, видео, файл или текст) для поста:"
        )
        return

    if data == "password_yes":
        if not is_admin(user.id):
            return
        states[user.id] = {"step": "set_password"}
        await query.message.edit_text(
            "🔐 Введи кодовое слово (пароль) текстом для этого материала:"
        )
        return

    if data.startswith("check_post:"):
        post_id = data.split(":")[1]
        missing = [] if await premium_active(user.id) else await missing_subscriptions(context.bot, user.id)

        if missing:
            await query.message.reply_text("😥 Вы не были подписаны на нужные каналы\n\nПрошу подписаться на каналы",reply_markup=subscription_keyboard(post_id))
            return

        await query.message.delete()
        await request_post(context.bot, query.message.chat_id, user.id, post_id)
        return

    if data == "check_subscriptions":
        missing = [] if await premium_active(user.id) else await missing_subscriptions(context.bot, user.id)

        if missing:
            await send_subscription_required(context.bot, query.message.chat_id)
        else:
            await query.message.reply_text(
                "✅Подписан\nНапиши /start для главного меню"
            )
        return

    if data == "channel_add":
        if not is_admin(user.id):
            return
        states[user.id] = {"step": "add_channel"}
        await query.message.edit_text(
            "➕ Добавление обязательного канала\n\n"
            "Перешли сюда любое сообщение из нужного канала "
            "или отправь его ID (например: <code>-100123456789</code>).\n\n"
            "Для отмены отправь: <code>отмена</code>",
            parse_mode="HTML"
        )
        return

    if data == "channel_list":
        if not is_admin(user.id):
            return
        await query.message.edit_text(
            "📋 Список обязательных каналов:",
            reply_markup=channel_list_keyboard()
        )
        return

    if data == "channel_back":
        if not is_admin(user.id):
            return
        await query.message.edit_text(
            "📡 Управление обязательными подписками",
            reply_markup=channel_management_keyboard()
        )
        return

    if data == "channel_main":
        if not is_admin(user.id):
            return
        await query.answer("🔒 Главный канал нельзя удалить из обязательных.", show_alert=True)
        return

    if data.startswith("channel_remove:"):
        if not is_admin(user.id):
            return
        channel_id = data.split(":")[1]
        if channel_id in channels:
            del channels[channel_id]
            save_channels()
        await query.message.edit_text(
            "🗑 Канал удален из обязательных подписок.",
            reply_markup=channel_list_keyboard()
        )
        return


# ==================================================
# ЗАПУСК БОТА
# ==================================================

async def startup(application):
    application.create_task(expiry_worker(application))


def main():
    load_data()

    application = Application.builder().token(TOKEN).post_init(startup).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    log.info("Бот запущен и готов к работе!")
    application.run_polling()


if __name__ == "__main__":
    main()