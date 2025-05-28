import os
import logging
from aiogram import Bot, Dispatcher, types, executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils.executor import start_webhook
from dotenv import load_dotenv

load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("DESIGNER_CHAT_ID")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
WEBAPP_HOST = '0.0.0.0'
WEBAPP_PORT = 8000

# Инициализация бота
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot, storage=MemoryStorage())

# Счетчик заявок
request_counter = 0


# Клавиатуры
def main_keyboard():
    return types.ReplyKeyboardMarkup([
        [types.KeyboardButton("📝 Создать заявку")]
    ], resize_keyboard=True)


def type_keyboard():
    return types.ReplyKeyboardMarkup([
        [types.KeyboardButton("📚 Учебный проект")],
        [types.KeyboardButton("🏗️ Рабочий проект")],
        [types.KeyboardButton("🚫 Отменить")]
    ], resize_keyboard=True)


def cancel_keyboard():
    return types.ReplyKeyboardMarkup([
        [types.KeyboardButton("🚫 Отменить")]
    ], resize_keyboard=True)


# Состояния
class OrderStates(StatesGroup):
    CHOOSING_TYPE = State()
    WORK_DETAILS = State()
    STUDY_DETAILS = State()


# Обработчики
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    await message.answer(
        "🔌 Добро пожаловать в сервис проектирования!\n"
        "Нажмите кнопку ниже, чтобы создать новую заявку",
        reply_markup=main_keyboard()
    )


@dp.message_handler(text="📝 Создать заявку")
async def create_order(message: types.Message):
    await OrderStates.CHOOSING_TYPE.set()
    await message.answer("Выберите тип проекта:", reply_markup=type_keyboard())


@dp.message_handler(text="🚫 Отменить", state='*')
async def cancel_order(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Действие отменено", reply_markup=main_keyboard())


@dp.message_handler(state=OrderStates.CHOOSING_TYPE)
async def process_type(message: types.Message, state: FSMContext):
    if message.text == "📚 Учебный проект":
        await OrderStates.STUDY_DETAILS.set()
        await message.answer("📝 Введите тему учебного проекта:", reply_markup=cancel_keyboard())
    elif message.text == "🏗️ Рабочий проект":
        await OrderStates.WORK_DETAILS.set()
        await message.answer("📏 Введите площадь объекта (м²):", reply_markup=cancel_keyboard())
    else:
        await message.answer("Пожалуйста, выберите тип проекта")


@dp.message_handler(state=OrderStates.WORK_DETAILS)
async def process_work_order(message: types.Message, state: FSMContext):
    global request_counter
    try:
        # Простая обработка заявки
        area = float(message.text)
        request_counter += 1

        # Формируем сообщение пользователю
        user_msg = (
            f"✅ Ваша заявка #{request_counter} принята!\n"
            f"Тип: Рабочий проект\n"
            f"Площадь: {area} м²\n\n"
            "Специалист свяжется с вами в течение 15 минут."
        )

        # Формируем сообщение администратору
        admin_msg = (
            f"🏗️ Новая заявка #{request_counter}\n"
            f"Пользователь: @{message.from_user.username or message.from_user.id}\n"
            f"Тип: Рабочий проект\n"
            f"Площадь: {area} м²\n"
            f"Ссылка: tg://user?id={message.from_user.id}"
        )

        # Отправляем сообщения
        await message.answer(user_msg, reply_markup=main_keyboard())
        if ADMIN_CHAT_ID:
            await bot.send_message(ADMIN_CHAT_ID, admin_msg)

    except ValueError:
        await message.answer("❗ Пожалуйста, введите число для площади")
        return

    await state.finish()


@dp.message_handler(state=OrderStates.STUDY_DETAILS)
async def process_study_order(message: types.Message, state: FSMContext):
    global request_counter
    topic = message.text
    request_counter += 1

    # Формируем сообщение пользователю
    user_msg = (
        f"✅ Ваша заявка #{request_counter} принята!\n"
        f"Тип: Учебный проект\n"
        f"Тема: {topic}\n\n"
        "Менеджер свяжется с вами в течение 15 минут."
    )

    # Формируем сообщение администратору
    admin_msg = (
        f"📚 Новая заявка #{request_counter}\n"
        f"Пользователь: @{message.from_user.username or message.from_user.id}\n"
        f"Тип: Учебный проект\n"
        f"Тема: {topic}\n"
        f"Ссылка: tg://user?id={message.from_user.id}"
    )

    # Отправляем сообщения
    await message.answer(user_msg, reply_markup=main_keyboard())
    if ADMIN_CHAT_ID:
        await bot.send_message(ADMIN_CHAT_ID, admin_msg)

    await state.finish()


# Вебхуки
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Бот запущен. Вебхук: {WEBHOOK_URL}")


async def on_shutdown(dp):
    await bot.delete_webhook()
    logging.info("Бот остановлен")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        skip_updates=True
    )