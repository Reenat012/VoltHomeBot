"""
Главный файл Telegram-бота с интеграцией Webhook для Timeweb
"""
# Импорт необходимых библиотек
import os
import logging
import random
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

# ================== КОНФИГУРАЦИЯ ==================
REQUEST_COUNTER_FILE = 'request_counter.txt'

# Дежурные приветственные фразы (кроме первой, которая останется без изменений)
WELCOME_PHRASES = [
    "Снова к нам? Отлично! Давайте создадим новую заявку!",
    "Рады видеть вас снова! Готовы оформить новую заявку?",
    "Отлично, что вы вернулись! Приступим к новой заявке?",
    "Новая заявка - новые возможности! Поехали!",
    "Готовы создать еще один проект? Давайте начнем!"
]

# Клавиатура после завершения заявки
new_request_kb = types.ReplyKeyboardMarkup(
    [[types.KeyboardButton("📝 Новая заявка!")]],
    resize_keyboard=True
)

# Остальные клавиатуры
project_type_kb = types.ReplyKeyboardMarkup(
    [
        [types.KeyboardButton("📚 Учебный проект")],
        [types.KeyboardButton("🏗️ Рабочий проект")]
    ],
    resize_keyboard=True
)

cancel_kb = types.ReplyKeyboardMarkup(
    [[types.KeyboardButton("Отмена")]],
    resize_keyboard=True
)

confirm_kb = types.InlineKeyboardMarkup().row(
    types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
    types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
)

# Вопросы для проектов
WORK_QUESTIONS = [
    "Укажите площадь объекта (м²):",
    "Количество помещений:",
    "Перечислите мощные электроприборы (с указанием мощности):",
    "Тип здания (жилое, коммерческое, промышленное):",
    "Дополнительные технические требования:"
]

STUDY_QUESTIONS = [
    "Укажите тему учебного проекта:",
    "Требуемый объем работы (страниц):",
    "Срок сдачи проекта:",
    "Методические требования (если есть):",
    "Дополнительные пожелания:"
]

# Базовые цены для расчета
WORK_BASE_PRICES = {
    1: (15000, 25000),  # До 50 м²
    2: (25000, 40000),  # 50-100 м²
    3: (40000, 70000),  # 100-200 м²
    4: (70000, None)     # Свыше 200 м²
}

STUDY_BASE_PRICES = {
    1: (5000, 10000),    # До 20 страниц
    2: (10000, 15000),   # 20-40 страниц
    3: (15000, None)     # Свыше 40 страниц
}

class Form(StatesGroup):
    project_type = State()
    answers = State()
    confirm = State()

# Функции для работы с счетчиком заявок
def init_request_counter():
    if not os.path.exists(REQUEST_COUNTER_FILE):
        try:
            with open(REQUEST_COUNTER_FILE, 'w') as f:
                f.write('0')
            logging.info("Файл счетчика заявок создан")
        except Exception as e:
            logging.error(f"Ошибка при создании файла счетчика: {e}")
            raise

def get_next_request_number():
    try:
        if not os.path.exists(REQUEST_COUNTER_FILE):
            init_request_counter()
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
        import random
        return random.randint(1000, 9999)

# Инициализация счетчика
try:
    init_request_counter()
except Exception as e:
    logging.error(f"Не удалось инициализировать счетчик заявок: {e}")

# Функции расчета цены
def calculate_work_price(data):
    try:
        area = float(data['answers'][0])
        if area <= 50:
            price_range = WORK_BASE_PRICES[1]
        elif area <= 100:
            price_range = WORK_BASE_PRICES[2]
        elif area <= 200:
            price_range = WORK_BASE_PRICES[3]
        else:
            price_range = WORK_BASE_PRICES[4]
        base_price = (price_range[0] + (price_range[1] or price_range[0]*1.5)) // 2
        report = (
            "🔧 *Предварительный расчет стоимости рабочего проекта:*\n"
            f"- Площадь объекта: {area} м²\n"
            f"- Ориентировочная стоимость: {base_price:,} руб.\n"
            "\n_Точная стоимость будет определена после анализа технических требований._"
        )
        return report.replace(',', ' ')
    except Exception as e:
        logging.error(f"Ошибка расчета цены: {e}")
        return "Не удалось рассчитать стоимость. Инженер свяжется с вами для уточнений."

def calculate_study_price(data):
    try:
        pages = int(data['answers'][1]) if data['answers'][1].isdigit() else 0
        if pages <= 20:
            price_range = STUDY_BASE_PRICES[1]
        elif pages <= 40:
            price_range = STUDY_BASE_PRICES[2]
        else:
            price_range = STUDY_BASE_PRICES[3]
        base_price = (price_range[0] + (price_range[1] or price_range[0]*1.3)) // 2
        report = (
            "📚 *Предварительный расчет стоимости учебного проекта:*\n"
            f"- Тема: {data['answers'][0]}\n"
            f"- Объем: {pages} страниц\n"
            f"- Ориентировочная стоимость: {base_price:,} руб.\n"
            "\n_Окончательная цена может быть скорректирована после уточнения требований._"
        )
        return report.replace(',', ' ')
    except Exception as e:
        logging.error(f"Ошибка расчета цены: {e}")
        return "Не удалось рассчитать стоимость. Менеджер свяжется с вами для уточнений."

# ================== ОБРАБОТЧИКИ СОБЫТИЙ ==================
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    await Form.project_type.set()
    await message.answer(
        "🔌 Добро пожаловать в сервис проектирования!\n"
        "Выберите тип проекта:",
        reply_markup=project_type_kb
    )

# Новый обработчик для кнопки "Новая заявка!"
@dp.message_handler(lambda message: message.text == "📝 Новая заявка!")
async def new_request_handler(message: types.Message):
    # Для первой заявки - стандартное приветствие
    if random.random() < 0.5 or not hasattr(message, 'request_count'):
        await cmd_start(message)
    else:
        # Для последующих - случайная приветственная фраза
        welcome_phrase = random.choice(WELCOME_PHRASES)
        await Form.project_type.set()
        await message.answer(welcome_phrase, reply_markup=project_type_kb)

@dp.message_handler(state=Form.project_type)
async def process_project_type(message: types.Message, state: FSMContext):
    if message.text not in ["📚 Учебный проект", "🏗️ Рабочий проект"]:
        await message.answer("Пожалуйста, выберите тип проекта из предложенных вариантов.")
        return

    async with state.proxy() as data:
        data['project_type'] = "study" if message.text == "📚 Учебный проект" else "work"
        data['questions'] = STUDY_QUESTIONS if data['project_type'] == "study" else WORK_QUESTIONS
        data['current_question'] = 0
        data['answers'] = []

    await Form.next()
    await message.answer(data['questions'][0], reply_markup=cancel_kb)

@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        current_question = data['current_question']
        answer = message.text

        if data['project_type'] == "work":
            if current_question == 0 and not answer.replace('.', '').isdigit():
                await message.answer("⚠️ Пожалуйста, введите число для площади объекта!")
                return
            elif current_question == 1 and not answer.isdigit():
                await message.answer("⚠️ Пожалуйста, введите целое число для количества помещений!")
                return

        elif data['project_type'] == "study":
            if current_question == 1 and not answer.isdigit():
                await message.answer("⚠️ Пожалуйста, введите целое число для объема работы!")
                return

        data['answers'].append(answer)

        if current_question < len(data['questions']) - 1:
            data['current_question'] += 1
            await message.answer(data['questions'][data['current_question']], reply_markup=cancel_kb)
        else:
            if data['project_type'] == "work":
                data['price_report'] = calculate_work_price(data)
            else:
                data['price_report'] = calculate_study_price(data)

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
                project_type = "Учебный проект" if data['project_type'] == "study" else "Рабочий проект"
                report = (
                    f"📋 *Новая заявка! Номер заявки №{request_number}* ({project_type})\n"
                    f"🆔 ID: `{callback.from_user.id}`\n"
                    f"📧 Username: {username}\n"
                )
                if data['project_type'] == "work":
                    report += (
                        f"📏 *Площадь объекта:* {data['answers'][0]} м²\n"
                        f"🚪 *Помещений:* {data['answers'][1]}\n"
                        f"🔌 *Электроприборы:* {data['answers'][2]}\n"
                        f"🏢 *Тип здания:* {data['answers'][3]}\n"
                        f"📝 *Технические требования:* {data['answers'][4]}\n"
                        f"💵 *Расчет стоимости:\n{data['price_report']}"
                    )
                else:
                    report += (
                        f"📖 *Тема проекта:* {data['answers'][0]}\n"
                        f"📄 *Объем работы:* {data['answers'][1]} стр.\n"
                        f"⏳ *Срок сдачи:* {data['answers'][2]}\n"
                        f"📚 *Методические требования:* {data['answers'][3]}\n"
                        f"💡 *Пожелания:* {data['answers'][4]}\n"
                        f"💵 *Расчет стоимости:\n{data['price_report']}"
                    )
                await bot.send_message(
                    chat_id=os.getenv("DESIGNER_CHAT_ID"),
                    text=report,
                    parse_mode="Markdown",
                    reply_markup=contact_button
                )
                await callback.message.answer(
                    f"✅ Ваша заявка отправлена на обработку! Номер заявка №{request_number}. Спасибо за доверие!",
                    reply_markup=new_request_kb
                )
            except Exception as e:
                logging.error(f"Ошибка при обработке заявки: {e}")
                await callback.message.answer(
                    "⚠️ Произошла ошибка при обработке заявки. Пожалуйста, попробуйте позже.",
                    reply_markup=new_request_kb
                )
    else:
        await callback.message.answer(
            "❌ Заявка отменена.",
            reply_markup=new_request_kb
        )
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