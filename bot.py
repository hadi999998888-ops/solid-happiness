import json
import logging
import os
import secrets
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.error import TelegramError, RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ============================================================
# EXTRA CHEAT 🐍 — CONFIGURATION
# ============================================================
# Put your NEW BotFather token here. Do not share it with anyone.
TOKEN = "8757046363:AAH_sxbGCELk5divmluJVWCIrWuiTygmGzo"
ADMIN_ID = 7608889836
MAIN_CHANNEL_ID = -1003957801744
MAIN_CHANNEL_URL = "https://t.me/ExtraCheatStanddof2"
BOT_USERNAME = "ExtraCheatbot"  # username without @
# Set the linked discussion group's numeric ID to enable auto replies.
# Leave 0 to disable this feature.
DISCUSSION_CHAT_ID = 0
START_IMAGE = "Start.jpg"
POSTS_FILE = "posts.json"
CHANNELS_FILE = "channels.json"
USERS_FILE = "users.json"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("extra_cheat")

posts = {}
channels = {}
users = set()
states = {}


def load_json(filename, default):
    path = Path(filename)
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data
    except (OSError, json.JSONDecodeError):
        log.exception("Could not read %s", filename)
        return default


def save_json(filename, data):
    path = Path(filename)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def load_data():
    global posts, channels, users
    posts = load_json(POSTS_FILE, {})
    channels = load_json(CHANNELS_FILE, {})
    users = set(load_json(USERS_FILE, []))
    # Keep the primary channel required at all times.
    channels[str(MAIN_CHANNEL_ID)] = {
        "id": MAIN_CHANNEL_ID,
        "title": "EXTRA CHEAT",
        "url": MAIN_CHANNEL_URL,
        "main": True,
    }
    save_json(CHANNELS_FILE, channels)


def save_posts():
    save_json(POSTS_FILE, posts)


def save_channels():
    save_json(CHANNELS_FILE, channels)


def save_users():
    save_json(USERS_FILE, sorted(users))


# ============================================================
# KEYBOARDS
# ============================================================
def admin_keyboard():
    return ReplyKeyboardMarkup([["⚙️ Админ-панель"]], resize_keyboard=True)


def panel_keyboard():
    return ReplyKeyboardMarkup(
        [["🐍 Создать пост"], ["📡 Подписки", "📨 Рассылка"], ["🚪 Выйти"]],
        resize_keyboard=True,
    )


def subscription_keyboard(post_id=None):
    rows = []
    for channel in channels.values():
        url = channel.get("url")
        if url:
            rows.append([InlineKeyboardButton(
                f"📢 {channel.get('title', 'Канал')}", url=url
            )])
    callback = f"check_post:{post_id}" if post_id else "check_subscriptions"
    rows.append([InlineKeyboardButton("✅ Я подписался — проверить", callback_data=callback)])
    return InlineKeyboardMarkup(rows)


def password_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Нет", callback_data="password_no"),
        InlineKeyboardButton("🔐 Да", callback_data="password_yes"),
    ]])


def generate_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🐍 Сгенерировать ссылку", callback_data="generate")
    ]])


def channel_management_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить канал", callback_data="channel_add")],
        [InlineKeyboardButton("📋 Список каналов", callback_data="channel_list")],
    ])


def channel_list_keyboard():
    rows = []
    for key, channel in channels.items():
        title = channel.get("title", key)
        if channel.get("main"):
            rows.append([InlineKeyboardButton(f"🔒 {title} (главный)", callback_data="channel_main")])
        else:
            rows.append([InlineKeyboardButton(f"🗑 Удалить: {title}", callback_data=f"channel_remove:{key}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="channel_back")])
    return InlineKeyboardMarkup(rows)


def post_channel_keyboard():
    rows = []
    for channel in channels.values():
        if channel.get("url"):
            rows.append([InlineKeyboardButton(
                f"🐍 {channel.get('title', 'Наш канал')}", url=channel["url"]
            )])
    return InlineKeyboardMarkup(rows) if rows else None


# ============================================================
# REQUIRED SUBSCRIPTIONS
# ============================================================
async def check_channel(bot, user_id, channel_id):
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if member.status in ("creator", "administrator", "member"):
            return True
        if member.status == "restricted":
            return bool(getattr(member, "is_member", False))
        return False
    except TelegramError:
        log.exception("Could not check channel membership: %s", channel_id)
        return False


async def missing_subscriptions(bot, user_id):
    missing = []
    for channel in channels.values():
        if not await check_channel(bot, user_id, channel["id"]):
            missing.append(channel)
    return missing


async def send_subscription_required(bot, chat_id, post_id=None):
    await bot.send_message(
        chat_id=chat_id,
        text=("❗ Чтобы получить материал, подпишись на все обязательные каналы.\n\n"
              "После подписки нажми кнопку проверки ниже."),
        reply_markup=subscription_keyboard(post_id),
    )


# ============================================================
# POST DELIVERY
# ============================================================
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
    material_type = post.get("type", "other")
    source_chat_id = post["source_chat_id"]
    source_message_id = post["source_message_id"]
    description = post.get("description", "")
    keyboard = post_channel_keyboard()

    if material_type == "text":
        text = post.get("original_text", "")
        if description:
            text = f"{text}\n\n{description}" if text else description
        await bot.send_message(chat_id=chat_id, text=text or "🐍 EXTRA CHEAT", reply_markup=keyboard)
        return

    if material_type in ("sticker", "video_note", "other"):
        await bot.copy_message(chat_id=chat_id, from_chat_id=source_chat_id, message_id=source_message_id)
        if description:
            await bot.send_message(chat_id=chat_id, text=description, reply_markup=keyboard)
        elif keyboard:
            await bot.send_message(chat_id=chat_id, text="🐍 EXTRA CHEAT", reply_markup=keyboard)
        return

    original_caption = post.get("original_caption", "")
    caption = f"{original_caption}\n\n{description}" if original_caption and description else (original_caption or description)
    # Telegram media captions have a length limit. If the combined caption is too long,
    # send the original media first and put the description in a separate message.
    if len(caption) > 1024:
        await bot.copy_message(chat_id=chat_id, from_chat_id=source_chat_id, message_id=source_message_id)
        if description:
            await bot.send_message(chat_id=chat_id, text=description, reply_markup=keyboard)
        elif keyboard:
            await bot.send_message(chat_id=chat_id, text="🐍 EXTRA CHEAT", reply_markup=keyboard)
        return
    await bot.copy_message(
        chat_id=chat_id,
        from_chat_id=source_chat_id,
        message_id=source_message_id,
        caption=caption or None,
        reply_markup=keyboard,
    )


async def deliver_post(bot, chat_id, post_id):
    post = posts.get(post_id)
    if not post:
        await bot.send_message(chat_id=chat_id, text="❌ Материал не найден или ссылка устарела.")
        return
    try:
        await send_material(bot, chat_id, post)
    except TelegramError:
        log.exception("Could not deliver post %s", post_id)
        await bot.send_message(chat_id=chat_id, text="❌ Не удалось отправить материал. Попробуй позже.")


async def request_post(bot, chat_id, user_id, post_id):
    post = posts.get(post_id)
    if not post:
        await bot.send_message(chat_id=chat_id, text="❌ Материал не найден или ссылка устарела.")
        return
    if await missing_subscriptions(bot, user_id):
        await send_subscription_required(bot, chat_id, post_id)
        return
    password = post.get("password", "")
    if password:
        states[user_id] = {"step": "get_password", "post_id": post_id}
        await bot.send_message(chat_id=chat_id, text="🔐 Защищённый материал EXTRA CHEAT\n\nВведи код-пароль, чтобы получить материал.")
        return
    states.pop(user_id, None)
    await deliver_post(bot, chat_id, post_id)


# ============================================================
# /START
# ============================================================
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
            log.exception("Could not save users list")

    if user.id == ADMIN_ID and not context.args:
        states.pop(user.id, None)
        await message.reply_text("🐍 EXTRA CHEAT\n\nДобро пожаловать в админ-панель.", reply_markup=admin_keyboard())
        return

    if not context.args:
        text = (
            "🐍 EXTRA CHEAT\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📦 Чтобы получить материал по ссылке, подпишись на обязательные каналы.\n"
            "👇 Выбери канал, подпишись и нажми проверку."
        )
        keyboard = subscription_keyboard()
        if os.path.isfile(START_IMAGE):
            try:
                with open(START_IMAGE, "rb") as photo:
                    await message.reply_photo(photo=photo, caption=text, reply_markup=keyboard)
                return
            except (OSError, TelegramError):
                log.exception("Could not send Start.jpg")
        await message.reply_text(text, reply_markup=keyboard)
        return

    argument = context.args[0]
    if not argument.startswith("post_"):
        await message.reply_text("❌ Неверная ссылка.")
        return
    await request_post(context.bot, message.chat_id, user.id, argument[5:])


# ============================================================
# CHANNEL MANAGEMENT
# ============================================================
async def add_channel_from_id(bot, raw_id):
    try:
        chat = await bot.get_chat(int(raw_id.strip()))
    except (ValueError, TelegramError):
        return False, "❌ Не удалось найти канал. Проверь ID и права бота."
    if chat.type != "channel":
        return False, "❌ Это не канал. Отправь ID канала."
    try:
        bot_user = await bot.get_me()
        member = await bot.get_chat_member(chat.id, bot_user.id)
        if member.status not in ("administrator", "creator"):
            return False, "❌ Сначала добавь бота администратором канала."
    except TelegramError:
        return False, "❌ Бот не видит канал. Добавь его администратором и проверь ID."

    key = str(chat.id)
    if key in channels:
        return False, "ℹ️ Этот канал уже добавлен."
    url = f"https://t.me/{chat.username}" if chat.username else ""
    if not url:
        try:
            url = (await bot.create_chat_invite_link(chat.id)).invite_link
        except TelegramError:
            return False, "❌ Не удалось создать ссылку-приглашение. Проверь права бота."
    channels[key] = {"id": chat.id, "title": chat.title or str(chat.id), "url": url, "main": False}
    save_channels()
    return True, f"✅ Канал добавлен: {chat.title}\nТеперь подписка на него обязательна."


async def add_channel_from_forward(bot, message):
    origin = getattr(message, "forward_origin", None)
    if not origin or getattr(origin, "type", None) != "channel":
        return False, "❌ Перешли сообщение именно из канала или отправь ID канала."
    return await add_channel_from_id(bot, str(origin.chat.id))


# ============================================================
# ADMIN MESSAGES / WIZARDS
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    state = states.get(user.id, {})

    # A user entering the password for a post.
    if state.get("step") == "get_password":
        if not message.text:
            await message.reply_text("🔐 Отправь код обычным текстом.")
            return
        post = posts.get(state.get("post_id"))
        if not post:
            states.pop(user.id, None)
            await message.reply_text("❌ Материал больше не найден.")
            return
        if secrets.compare_digest(message.text.strip(), str(post.get("password", ""))):
            post_id = state["post_id"]
            states.pop(user.id, None)
            if await missing_subscriptions(context.bot, user.id):
                await send_subscription_required(context.bot, message.chat_id, post_id)
                return
            await message.reply_text("✅ Код верный! Отправляю материал 🐍")
            await deliver_post(context.bot, message.chat_id, post_id)
        else:
            await message.reply_text("❌ Неверный код. Попробуй ещё раз.")
        return

    if user.id != ADMIN_ID:
        return

    text = message.text or ""

    if text == "⚙️ Админ-панель":
        states.pop(user.id, None)
        await message.reply_text("🐍 EXTRA CHEAT — админ-панель", reply_markup=panel_keyboard())
        return
    if text == "🚪 Выйти":
        states.pop(user.id, None)
        await message.reply_text("Ты вышел из админ-панели.", reply_markup=admin_keyboard())
        return
    if text == "📡 Подписки":
        states.pop(user.id, None)
        await message.reply_text("📡 Управление обязательными подписками. Главный канал удалить нельзя.", reply_markup=channel_management_keyboard())
        return
    if text == "📨 Рассылка":
        states[user.id] = {"step": "broadcast"}
        await message.reply_text("📨 Отправь сообщение, фото, видео или файл для рассылки всем пользователям. Для отмены напиши «отмена».")
        return
    if text == "🐍 Создать пост":
        states[user.id] = {"step": "choose_password"}
        await message.reply_text("🐍 Придумать код-пароль для получения материала?", reply_markup=password_keyboard())
        return

    state = states.get(user.id, {})
    step = state.get("step")

    if step == "broadcast":
        if text.strip().lower() == "отмена":
            states.pop(user.id, None)
            await message.reply_text("❌ Рассылка отменена.", reply_markup=panel_keyboard())
            return
        states.pop(user.id, None)
        sent = failed = 0
        await message.reply_text("⏳ Начинаю рассылку...")
        for user_id in list(users):
            try:
                await context.bot.copy_message(chat_id=user_id, from_chat_id=message.chat_id, message_id=message.message_id)
                sent += 1
            except RetryAfter as exc:
                try:
                    import asyncio
                    await asyncio.sleep(float(exc.retry_after) + 1)
                    await context.bot.copy_message(chat_id=user_id, from_chat_id=message.chat_id, message_id=message.message_id)
                    sent += 1
                except Exception:
                    failed += 1
            except TelegramError:
                failed += 1
        await message.reply_text(f"✅ Рассылка завершена!\n\n📨 Доставлено: {sent}\n⚠️ Не доставлено: {failed}", reply_markup=panel_keyboard())
        return

    if step == "add_channel":
        if text.strip().lower() == "отмена":
            states.pop(user.id, None)
            await message.reply_text("Добавление отменено.", reply_markup=panel_keyboard())
            return
        if getattr(message, "forward_origin", None):
            ok, result = await add_channel_from_forward(context.bot, message)
        elif message.text:
            ok, result = await add_channel_from_id(context.bot, message.text)
        else:
            await message.reply_text("Отправь ID канала или перешли публикацию из него.")
            return
        if ok:
            states.pop(user.id, None)
        await message.reply_text(result, reply_markup=channel_management_keyboard())
        return

    if step == "set_password":
        if not message.text:
            await message.reply_text("❌ Пароль нужно отправить текстом.")
            return
        password = message.text.strip()
        if not password or len(password) > 100:
            await message.reply_text("❌ Пароль должен содержать от 1 до 100 символов.")
            return
        state["password"] = password
        state["step"] = "material"
        await message.reply_text("🔐 Пароль сохранён.\n\n📦 Теперь отправь материал: фото, видео, файл, GIF, аудио, голосовое, стикер или текст.")
        return

    if step == "material":
        material_type = get_material_type(message)
        if material_type == "other":
            await message.reply_text("❌ Этот формат не поддерживается. Отправь текст, фото, видео, документ, GIF, аудио, голосовое или стикер.")
            return
        state["type"] = material_type
        state["source_chat_id"] = message.chat_id
        state["source_message_id"] = message.message_id
        state["original_text"] = message.text or ""
        state["original_caption"] = message.caption or ""
        state["step"] = "description"
        await message.reply_text("📝 Отправь описание к материалу текстом. Если описание не нужно, напиши «нет».")
        return

    if step == "description":
        if not message.text:
            await message.reply_text("📝 Описание отправь текстом или напиши «нет».")
            return
        description = message.text.strip()
        state["description"] = "" if description.lower() == "нет" else description
        state["step"] = "ready"
        await message.reply_text("✅ Материал и описание готовы. Нажми кнопку для создания ссылки.", reply_markup=generate_keyboard())
        return


# ============================================================
# CALLBACK BUTTONS
# ============================================================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    data = query.data or ""
    await query.answer()
    message = query.message

    if data in ("password_no", "password_yes", "generate", "channel_add", "channel_list", "channel_back", "channel_main") or data.startswith("channel_remove:"):
        if user.id != ADMIN_ID:
            return

    if data == "password_no":
        states[user.id] = {"step": "material", "password": ""}
        await message.reply_text("📦 Без пароля. Теперь отправь материал: фото, видео, файл, GIF, аудио, стикер или текст.")
        return
    if data == "password_yes":
        states[user.id] = {"step": "set_password"}
        await message.reply_text("🔐 Введи код-пароль текстом (до 100 символов).")
        return
    if data == "generate":
        state = states.get(user.id, {})
        if state.get("step") != "ready":
            await message.reply_text("❌ Сначала отправь материал и описание.")
            return
        post_id = secrets.token_urlsafe(8).replace("-", "").replace("_", "")
        posts[post_id] = {
            "type": state["type"],
            "source_chat_id": state["source_chat_id"],
            "source_message_id": state["source_message_id"],
            "original_text": state.get("original_text", ""),
            "original_caption": state.get("original_caption", ""),
            "description": state.get("description", ""),
            "password": state.get("password", ""),
        }
        try:
            save_posts()
        except OSError:
            posts.pop(post_id, None)
            log.exception("Could not save post")
            await message.reply_text("❌ Не удалось сохранить материал. Проверь доступ к файлам.")
            return
        link = f"https://t.me/{BOT_USERNAME}?start=post_{post_id}"
        states.pop(user.id, None)
        extra = "🔐 Получателю понадобится пароль." if posts[post_id]["password"] else "📦 Материал выдаётся после проверки подписок."
        await message.reply_text(f"✅ Ссылка создана!\n\n🔗 {link}\n\n{extra}", reply_markup=panel_keyboard())
        return

    if data == "check_subscriptions":
        missing = await missing_subscriptions(context.bot, user.id)
        if missing:
            await message.reply_text("❌ Подпишись на все обязательные каналы и нажми проверку ещё раз.", reply_markup=subscription_keyboard())
        else:
            await message.reply_text("✅ Подписки подтверждены. Теперь открой ссылку на материал.")
        return
    if data.startswith("check_post:"):
        post_id = data.split(":", 1)[1]
        if await missing_subscriptions(context.bot, user.id):
            await message.reply_text("❌ Подпишись на все обязательные каналы и проверь ещё раз.", reply_markup=subscription_keyboard(post_id))
            return
        await request_post(context.bot, message.chat_id, user.id, post_id)
        return

    if data == "channel_add":
        states[user.id] = {"step": "add_channel"}
        await message.reply_text("➕ Отправь ID канала (например -1001234567890) или перешли публикацию из него. Для отмены напиши «отмена».")
        return
    if data == "channel_list":
        await message.reply_text("📋 Список обязательных каналов:", reply_markup=channel_list_keyboard())
        return
    if data == "channel_back":
        await message.reply_text("📡 Управление подписками", reply_markup=channel_management_keyboard())
        return
    if data == "channel_main":
        await query.answer("🔒 Главный канал нельзя удалить.", show_alert=True)
        return
    if data.startswith("channel_remove:"):
        key = data.split(":", 1)[1]
        channel = channels.get(key)
        if not channel:
            await message.reply_text("Этот канал уже удалён.", reply_markup=channel_list_keyboard())
            return
        if channel.get("main"):
            await message.reply_text("Главный канал удалить нельзя.", reply_markup=channel_list_keyboard())
            return
        channels.pop(key, None)
        save_channels()
        await message.reply_text(f"🗑 Канал «{channel.get('title', key)}» удалён.", reply_markup=channel_list_keyboard())
        return


# ============================================================
# OPTIONAL AUTO-REPLY IN LINKED DISCUSSION GROUP
# ============================================================
async def discussion_auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not DISCUSSION_CHAT_ID or message.chat_id != DISCUSSION_CHAT_ID:
        return
    if not getattr(message, "is_automatic_forward", False):
        return
    try:
        await message.reply_text(
            "🐍 EXTRA CHEAT\n📢 Подпишись на наш канал, чтобы не пропускать публикации.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Наш канал", url=MAIN_CHANNEL_URL)
            ]]),
        )
    except TelegramError:
        log.exception("Could not reply in linked discussion group")


async def post_init(application: Application):
    me = await application.bot.get_me()
    log.info("Started as @%s", me.username)


def main():
    if not TOKEN or TOKEN == "PASTE_NEW_BOTFATHER_TOKEN_HERE":
        raise RuntimeError("Set a valid new BotFather token in TOKEN before starting the bot.")
    load_data()
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    # Group 0 handles discussion auto replies; group 1 handles admin/user messages.
    application.add_handler(MessageHandler(filters.ALL, discussion_auto_reply), group=0)
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message), group=1)
    log.info("Starting EXTRA CHEAT bot")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
