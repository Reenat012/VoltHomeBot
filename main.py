import asyncio
import logging
import os
import signal

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()

bot = Bot(token=os.getenv("BOT_TOKEN"))
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Клавиатуры
cancel_kb = ReplyKeyboardMarkup([[KeyboardButton("Отмена")]], resize_keyboard=True)
confirm_kb = InlineKeyboardMarkup().row(
    InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
    InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
)

# Вопросы
QUESTIONS = [
    "Как вас зовут?",
    "Введите адрес квартиры:",
    "Укажите площадь квартиры (м²):",
    "Количество комнат:",
    "Перечислите мощные электроприборы:",
    "Дополнительные пожелания:"
]


class Form(StatesGroup):
    answers = State()
    confirm = State()


# --- Упрощенное ценообразование ---
BASE_PRICES = {
    1: (10000, 18000),
    2: (18000, 30000),
    3: (30000, 50000),
    4: (50000, None)  # Индивидуальный расчет
}


def calculate_price(data):
    try:
        rooms = int(data['answers'][3])
        area = float(data['answers'][2])

        if rooms >= 4 or area > 100:
            return "Индивидуальный расчет (квартира более 100 м² или 4+ комнат)"

        base_min, base_max = BASE_PRICES.get(rooms, (0, 0))
        base_price = (base_min + base_max) // 2  # Среднее значение

        # Форматирование отчета
        report = [
            "🔧 *Предварительный расчет стоимости:*",
            f"- Базовый проект ({rooms}-комн., {area} м²): {base_price:,} руб.",
            f"💎 *Итого: ~{base_price:,} руб.*",
            "\n_Указанная стоимость является ориентировочной. Точная сумма будет определена после разработки ТЗ._"
        ]

        return '\n'.join(report).replace(',', ' ')

    except Exception as e:
        logger.error(f"Calculation error: {e}")
        return "Не удалось рассчитать стоимость. Инженер свяжется с вами для уточнений."


# --- Обработчики ---
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
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

        # Валидация
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
            # Расчет стоимости
            price_report = calculate_price(data)
            await Form.confirm.set()
            await message.answer(price_report, parse_mode="Markdown")
            await message.answer("Подтверждаете заявку?", reply_markup=confirm_kb)


@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state=Form.confirm)
async def process_confirmation(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == 'confirm_yes':
        async with state.proxy() as data:
            # Отправка проектировщику
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

async def on_shutdown(dp):
    await dp.storage.close()
    await dp.storage.wait_closed()
    await bot.close()

if __name__ == '__main__':
    # Регистрация обработчиков сигналов
    signal.signal(signal.SIGINT, lambda s, f: asyncio.get_event_loop().create_task(on_shutdown(dp)))
    signal.signal(signal.SIGTERM, lambda s, f: asyncio.get_event_loop().create_task(on_shutdown(dp)))

    executor.start_polling(dp, skip_updates=True)