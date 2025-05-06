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
WEBHOOK_HOST = 'https://reenat012-volthomebot-2d67.twc1.net'
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

WEBAPP_HOST = '0.0.0.0'
WEBAPP_PORT = 8000

# Инициализация бота
bot = Bot(token=os.getenv("BOT_TOKEN"))
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ================== УЛУЧШЕННАЯ ФУНКЦИЯ ДЛЯ НУМЕРАЦИИ ЗАЯВОК ==================
REQUEST_COUNTER_FILE = 'request_counter.txt'

def init_request_counter():
    """Инициализирует файл счетчика, если он не существует"""
    if not os.path.exists(REQUEST_COUNTER_FILE):
        try:
            with open(REQUEST_COUNTER_FILE, 'w') as f:
                f.write('0')
            logging.info("Файл счетчика заявок создан")
        except Exception as e:
            logging.error(f"Ошибка при создании файла счетчика: {e}")
            raise

def get_next_request_number():
    """Возвращает следующий номер заявки с обработкой ошибок"""
    try:
        # Если файл не существует, создаем его
        if not os.path.exists(REQUEST_COUNTER_FILE):
            init_request_counter()

        # Читаем и обновляем счетчик
        with open(REQUEST_COUNTER_FILE, 'r+') as f:
            try:
                counter = int(f.read().strip() or 0)
            except ValueError:
                counter = 0
                logging.warning("Некорректное значение в файле счетчика, сброс на 0")

            counter += 1
            f.seek(0)
            f.write(str(counter))
            f.truncate()
            return counter

    except Exception as e:
        logging.error(f"Ошибка при работе с файлом счетчика: {e}")
        # Возвращаем случайное число как fallback
        import random
        return random.randint(1000, 9999)

# Инициализируем счетчик при старте
try:
    init_request_counter()
except Exception as e:
    logging.error(f"Не удалось инициализировать счетчик заявок: {e}")

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
    answers = State()
    confirm = State()

# Логика расчета цены (без изменений)
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

# ================== ОБНОВЛЕННЫЕ ОБРАБОТЧИКИ ==================
@dp.message_handler(commands=['start', 'help'])
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
            data['price_report'] = calculate_price(data)
            await Form.confirm.set()
            await message.answer(data['price_report'], parse_mode="Markdown")
            await message.answer("Подтверждаете заявку?", reply_markup=confirm_kb)

@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state=Form.confirm)
async def process_confirmation(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == 'confirm_yes':
        async with state.proxy() as data:
            try:
                request_number = get_next_request_number()
                username = f"@{callback.from_user.username}" if callback.from_user.username else "не указан"

                contact_button = types.InlineKeyboardMarkup()
                contact_button.add(types.InlineKeyboardButton(
                    text="💬 Написать пользователю",
                    url=f"tg://user?id={callback.from_user.id}"
                ))

                report = (
                    f"📋 *Заявка №{request_number}*\n\n"
                    f"👤 *Клиент:* {data['answers'][0]}\n"
                    f"🆔 ID: `{callback.from_user.id}`\n"
                    f"📧 Username: {username}\n\n"
                    f"📍 *Адрес:* {data['answers'][1]}\n\n"
                    f"💵 *Рассчитанная стоимость:*\n{data['price_report']}\n\n"
                    f"📏 *Площадь:* {data['answers'][2]} м²\n"
                    f"🚪 *Комнат:* {data['answers'][3]}\n"
                    f"🔌 *Приборы:* {data['answers'][4]}\n"
                    f"📝 *Пожелания:* {data['answers'][5]}"
                )

                await bot.send_message(
                    chat_id=os.getenv("DESIGNER_CHAT_ID"),
                    text=report,
                    parse_mode="Markdown",
                    reply_markup=contact_button
                )
                await callback.message.answer(f"✅ Заявка отправлена! Номер заявки №{request_number}. Спасибо за доверие!")
            except Exception as e:
                logging.error(f"Ошибка при обработке заявки: {e}")
                await callback.message.answer("⚠️ Произошла ошибка при обработке заявки. Пожалуйста, попробуйте позже.")
    else:
        await callback.message.answer("❌ Заявка отменена.")
    await state.finish()

# Остальной код без изменений
async def on_startup(dp):
    try:
        await bot.set_webhook(WEBHOOK_URL)
        logging.info("Webhook установлен")
    except Exception as e:
        logging.error(f"Ошибка вебхука: {e}")
        exit(1)

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