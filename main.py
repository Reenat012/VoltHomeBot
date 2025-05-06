"""
Главный файл Telegram-бота с интеграцией Webhook для Timeweb
"""
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

# Конфигурация
REQUEST_COUNTER_FILE = 'request_counter.txt'
WELCOME_PHRASES = [
    "Снова к нам? Отлично! Давайте новую заявку!",
    "Рады видеть вас снова! Готовы начать?",
    "Новая заявка - новые возможности! Поехали!"
]

# Клавиатуры
project_type_kb = types.ReplyKeyboardMarkup(
    [
        [types.KeyboardButton("📚 Учебный проект")],
        [types.KeyboardButton("🏗️ Рабочий проект")]
    ],
    resize_keyboard=True
)

universal_cancel_kb = types.ReplyKeyboardMarkup(
    [[types.KeyboardButton("Отмена заявки")]],
    resize_keyboard=True
)

new_request_kb = types.ReplyKeyboardMarkup(
    [[types.KeyboardButton("📝 Новая заявка!")]],
    resize_keyboard=True
)

building_type_kb = types.ReplyKeyboardMarkup(
    [
        [types.KeyboardButton("Жилое"), types.KeyboardButton("Коммерческое")],
        [types.KeyboardButton("Промышленное"), types.KeyboardButton("Другое")],
        [types.KeyboardButton("Отмена заявки")]
    ],
    resize_keyboard=True
)

confirm_kb = types.InlineKeyboardMarkup().row(
    types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
    types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
)

# Вопросы
WORK_QUESTIONS = [
    "Укажите площадь объекта (м²):",
    "Количество помещений:",
    "Особые требования к проекту:"
]
STUDY_QUESTIONS = [
    "Укажите тему учебного проекта:",
    "Требуемый объем работы (страниц):",
    "Срок сдачи проекта:",
    "Дополнительные пожелания:"
]

class Form(StatesGroup):
    project_type = State()
    answers = State()
    building_type = State()
    custom_building = State()
    confirm = State()

# Логика расчета цен
WORK_BASE_PRICES = {
    1: (15000, 25000),  # До 50 м²
    2: (25000, 40000),  # 50-100 м²
    3: (40000, 70000),  # 100-200 м²
    4: (70000, None)    # Свыше 200 м²
}
STUDY_BASE_PRICES = {
    1: (5000, 10000),   # До 20 страниц
    2: (10000, 15000),  # 20-40 страниц
    3: (15000, None)    # Свыше 40 страниц
}

# Функции работы с файлом счетчика
def init_request_counter():
    if not os.path.exists(REQUEST_COUNTER_FILE):
        try:
            with open(REQUEST_COUNTER_FILE, 'w') as f:
                f.write('0')
            logging.info("Счетчик заявок инициализирован")
        except Exception as e:
            logging.error(f"Ошибка создания счетчика: {e}")

def get_next_request_number():
    try:
        if not os.path.exists(REQUEST_COUNTER_FILE):
            init_request_counter()
        with open(REQUEST_COUNTER_FILE, 'r+') as f:
            try:
                counter = int(f.read().strip() or 0)
            except ValueError:
                counter = 0
                logging.warning("Сброс счетчика заявок")
            counter += 1
            f.seek(0)
            f.write(str(counter))
            return counter
    except Exception as e:
        logging.error(f"Ошибка счетчика: {e}")
        return random.randint(1000, 9999)

# Расчет стоимости
def calculate_work_price(data):
    try:
        area = float(data['answers'][0])
        building = data['answers'][2]
        complexity = {
            "Жилое": 1.0,
            "Коммерческое": 1.3,
            "Промышленное": 1.5
        }.get(building.split()[0], 1.2)
        if area <= 50:
            price_range = WORK_BASE_PRICES[1]
        elif area <= 100:
            price_range = WORK_BASE_PRICES[2]
        elif area <= 200:
            price_range = WORK_BASE_PRICES[3]
        else:
            price_range = WORK_BASE_PRICES[4]
        base_price = (price_range[0] + (price_range[1] or price_range[0]*1.5)) // 2
        total = int(base_price * complexity)
        report = [
            "🔧 *Предварительный расчет:*",
            f"- Площадь: {area} м² | Тип: {building}",
            f"- Стоимость: {total:,} руб.",
            "_Точная сумма после анализа требований_"
        ]
        return '\n'.join(report).replace(',', ' ')
    except Exception as e:
        logging.error(f"Ошибка расчета: {e}")
        return "❌ Не удалось рассчитать стоимость. Специалист свяжется с вами."

def calculate_study_price(data):
    try:
        pages = int(data['answers'][1])
        if pages <= 20:
            price = STUDY_BASE_PRICES[1][0]
        elif pages <= 40:
            price = (STUDY_BASE_PRICES[2][0] + STUDY_BASE_PRICES[2][1]) // 2
        else:
            price = STUDY_BASE_PRICES[3][0] * 1.2
        report = [
            "📚 *Стоимость учебного проекта:*",
            f"- Тема: {data['answers'][0]}",
            f"- Объем: {pages} стр. → {price:,} руб.",
            "_Цена может измениться после уточнения требований_"
        ]
        return '\n'.join(report).replace(',', ' ')
    except Exception as e:
        logging.error(f"Ошибка расчета: {e}")
        return "❌ Не удалось рассчитать. Менеджер свяжется с вами."

# Обработчики
@dp.message_handler(lambda message: message.text == "Отмена заявки", state="*")
async def handle_cancel(message: types.Message, state: FSMContext):
    await state.finish()
    await cmd_start(message)

@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    await Form.project_type.set()
    await message.answer(
        "🔌 Добро пожаловать в сервис проектирования!\nВыберите тип проекта:",
        reply_markup=project_type_kb
    )

@dp.message_handler(lambda m: m.text == "📝 Новая заявка!")
async def new_request(message: types.Message):
    await Form.project_type.set()
    await message.answer(random.choice(WELCOME_PHRASES), reply_markup=project_type_kb)

@dp.message_handler(state=Form.project_type)
async def process_type(message: types.Message, state: FSMContext):
    if message.text not in ["📚 Учебный проект", "🏗️ Рабочий проект"]:
        await message.answer("Пожалуйста, используйте кнопки для выбора.")
        return

    async with state.proxy() as data:
        data['project_type'] = "study" if "Учебный" in message.text else "work"
        data['questions'] = STUDY_QUESTIONS if data['project_type'] == "study" else WORK_QUESTIONS
        data['current_question'] = 0
        data['answers'] = []

    await Form.answers.set()
    await message.answer(data['questions'][0], reply_markup=universal_cancel_kb)

@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        current = data['current_question']
        answer = message.text

        # Валидация для рабочих проектов
        if data['project_type'] == "work":
            if current == 0 and not answer.replace('.', '').isdigit():
                await message.answer("🔢 Введите число для площади!")
                return
            if current == 1 and not answer.isdigit():
                await message.answer("🔢 Введите целое число помещений!")
                return

        # Валидация для учебных проектов
        if data['project_type'] == "study" and current == 1 and not answer.isdigit():
            await message.answer("🔢 Введите число страниц!")
            return

        data['answers'].append(answer)

        # Переход к выбору типа здания для рабочих проектов
        if data['project_type'] == "work" and current == 1:
            await Form.building_type.set()
            await message.answer("🏢 Выберите тип здания:", reply_markup=building_type_kb)
            return

        if current < len(data['questions']) - 1:
            data['current_question'] += 1
            await message.answer(data['questions'][data['current_question']], reply_markup=universal_cancel_kb)
        else:
            if data['project_type'] == "work":
                data['price_report'] = calculate_work_price(data)
            else:
                data['price_report'] = calculate_study_price(data)

            await Form.confirm.set()
            await message.answer(data['price_report'], parse_mode="Markdown")
            await message.answer("Подтвердить заявку?", reply_markup=confirm_kb)

@dp.message_handler(state=Form.building_type)
async def process_building(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        if message.text == "Другое":
            await Form.custom_building.set()
            await message.answer("📝 Введите свой вариант типа здания:", reply_markup=universal_cancel_kb)
        else:
            data['answers'].append(message.text)
            await Form.answers.set()
            data['current_question'] += 1  # Важное исправление!
            await message.answer(data['questions'][data['current_question']], reply_markup=universal_cancel_kb)

@dp.message_handler(state=Form.custom_building)
async def process_custom_building(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['answers'].append(f"Другое ({message.text})")
        await Form.answers.set()
        data['current_question'] += 1  # Важное исправление!
        await message.answer(data['questions'][data['current_question']], reply_markup=universal_cancel_kb)

@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state=Form.confirm)
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == 'confirm_yes':
        async with state.proxy() as data:
            try:
                req_num = get_next_request_number()
                username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"
                report = f"📋 *Заявка №{req_num}\nТип: {'Учебный' if data['project_type'] == 'study' else 'Рабочий'}\n"
                report += f"🆔 {callback.from_user.id} | 📧 {username}\n"

                if data['project_type'] == "work":
                    report += (
                        f"🏢 Тип здания: {data['answers'][2]}\n"
                        f"📏 Площадь: {data['answers'][0]} м²\n"
                        f"🚪 Помещений: {data['answers'][1]}\n"
                        f"💼 Требования: {data['answers'][3]}\n"
                        f"{data['price_report']}"
                    )
                else:
                    report += (
                        f"📖 Тема: {data['answers'][0]}\n"
                        f"📄 Объем: {data['answers'][1]} стр.\n"
                        f"⏳ Срок: {data['answers'][2]}\n"
                        f"💡 Пожелания: {data['answers'][3]}\n"
                        f"{data['price_report']}"
                    )

                # Отправка сообщения проектировщику
                await bot.send_message(
                    os.getenv("DESIGNER_CHAT_ID"),
                    report,
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup().add(
                        types.InlineKeyboardButton(
                            "💬 Написать",
                            url=f"tg://user?id={callback.from_user.id}"
                        )
                    )
                )

                await callback.message.answer(
                    f"✅ Заявка №{req_num} принята!\nОжидайте связи специалиста.",
                    reply_markup=new_request_kb
                )
            except Exception as e:
                logging.error(f"Ошибка отправки заявки: {str(e)}")
                await callback.message.answer(
                    "⚠️ Произошла ошибка при отправке заявки. Пожалуйста, попробуйте еще раз.",
                    reply_markup=new_request_kb
                )
    else:
        await handle_cancel(callback.message, state)

    await state.finish()

# Вебхук
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Бот запущен")

async def on_shutdown(dp):
    await bot.delete_webhook()
    await dp.storage.close()
    logging.info("Бот остановлен")

if __name__ == '__main__':
    init_request_counter()
    logging.basicConfig(level=logging.INFO)
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT
    )