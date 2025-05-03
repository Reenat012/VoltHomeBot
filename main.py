"""
Главный файл Telegram-бота с интеграцией Webhook для Timeweb
"""

# Импорт необходимых библиотек
import os
import logging
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.executor import start_webhook
from dotenv import load_dotenv


load_dotenv()

# Конфигурация вебхука
WEBHOOK_HOST = 'https://83.217.220.42' #Замените на ваш домен
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

WEBAPP_HOST = '0.0.0.0'
WEBAPP_PORT = 8000  # Порт должен совпадать с настройками Nginx

# Инициализация бота
bot = Bot(token=os.getenv("BOT_TOKEN"))
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ================== КОНФИГУРАЦИЯ БОТА ==================
cancel_kb = types.ReplyKeyboardMarkup(
    [[types.KeyboardButton("Отмена")]],
    resize_keyboard=True
)

confirm_kb = types.InlineKeyboardMarkup().row(
    types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
    types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
)

QUESTIONS = [
    "Как вас зовут?",
    "Введите адрес квартиры:",
    "Укажите площадь квартиры (м²):",
    "Количество комнат:",
    "Перечислите мощные электроприборы:",
    "Дополнительные пожелания:"
]

class Form(StatesGroup):
    """Класс для управления состояниями диалога"""
    answers = State()
    confirm = State()

# Логика расчета цены
BASE_PRICES = {
    1: (10000, 18000),
    2: (18000, 30000),
    3: (30000, 50000),
    4: (50000, None)
}

def calculate_price(data):
    try:
        rooms = int(data['answers'][3])
        area = float(data['answers'][2])

        if rooms >= 4 or area > 100:
            return "Индивидуальный расчет (квартира более 100 м² или 4+ комнат)"

        base_min, base_max = BASE_PRICES.get(rooms, (0, 0))
        base_price = (base_min + base_max) // 2

        report = [
            "🔧 *Предварительный расчет стоимости:*",
            f"- Базовый проект ({rooms}-комн., {area} м²): {base_price:,} руб.",
            f"💎 *Итого: ~{base_price:,} руб.*",
            "\n_Указанная стоимость является ориентировочной. Точная сумма будет определена после разработки ТЗ._"
        ]

        return '\n'.join(report).replace(',', ' ')
    except Exception as e:
        return "Не удалось рассчитать стоимость. Инженер свяжется с вами для уточнений."

# ================== ОБРАБОТЧИКИ СОБЫТИЙ ==================
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await Form.answers.set()
    await message.answer("🔌 Заполните заявку на проектирование:", reply_markup=cancel_kb)
    await message.answer(QUESTIONS[0])

    async with dp.current_state().proxy() as data:
        data['current_question'] = 0
        data['answers'] = []

@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        current_question = data['current_question']
        answer = message.text

        if current_question == 2 and not answer.replace('.', '').isdigit():
            await message.answer("⚠️ Введите число (например: 45.5)!")
            return
        elif current_question == 3 and not answer.isdigit():
            await message.answer("⚠️ Введите целое число!")
            return

        data['answers'].append(answer)

        if current_question < len(QUESTIONS) - 1:
            data['current_question'] += 1
            await message.answer(QUESTIONS[data['current_question']])
        else:
            price_report = calculate_price(data)
            await Form.confirm.set()
            await message.answer(price_report, parse_mode="Markdown")
            await message.answer("Подтверждаете заявку?", reply_markup=confirm_kb)

@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state=Form.confirm)
async def process_confirmation(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == 'confirm_yes':
        async with state.proxy() as data:
            report = "📋 *Новая заявка*\n\n"
            report += f"👤 {data['answers'][0]} (ID: {callback.from_user.id})\n"
            report += f"📍 Адрес: {data['answers'][1]}\n\n"

            for q, a in zip(QUESTIONS[2:], data['answers'][2:]):
                report += f"*{q}*\n{a}\n\n"

            await bot.send_message(
                chat_id=os.getenv("DESIGNER_CHAT_ID"),
                text=report,
                parse_mode="Markdown"
            )
            await callback.message.answer("✅ Заявка отправлена! Спасибо!")
    else:
        await callback.message.answer("❌ Заявка отменена.")
    await state.finish()

async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Бот запущен через вебхук")

async def on_shutdown(dp):
    logging.warning('Завершение работы...')
    await bot.delete_webhook()
    await dp.storage.close()
    await dp.storage.wait_closed()
    logging.warning('Все соединения закрыты')

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT
    )