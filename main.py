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
service_type_kb = types.ReplyKeyboardMarkup(
    [
        [types.KeyboardButton("📚 Учебная консультация")],
        [types.KeyboardButton("🏗️ Рабочая консультация")]
    ],
    resize_keyboard=True
)

cancel_request_kb = types.ReplyKeyboardMarkup(
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

# Клавиатура для срочности работ
urgency_kb = types.ReplyKeyboardMarkup(
    [
        [types.KeyboardButton("Срочно 24 часа")],
        [types.KeyboardButton("В течении 3-5 дней")],
        [types.KeyboardButton("Стандартно 7 дней")],
        [types.KeyboardButton("Отмена заявки")]
    ],
    resize_keyboard=True
)

confirm_kb = types.InlineKeyboardMarkup().row(
    types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
    types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
)

# Вопросы (убрали "Срок сдачи" из учебных вопросов)
TECH_QUESTIONS = [
    "Укажите площадь объекта (м²):",
    "Количество помещений:",
    "Особые требования к консультации:"
]

STUDY_QUESTIONS = [
    "Укажите тему учебного вопроса:",
    "Требуемый объем консультации (страниц):",
    "Дополнительные пожелания:"
]

class Form(StatesGroup):
    service_type = State()
    answers = State()
    building_type = State()
    custom_building = State()
    urgency = State()
    confirm = State()

# Коэффициенты срочности
URGENCY_COEFFICIENTS = {
    "Срочно 24 часа": 1.5,
    "В течении 3-5 дней": 1.2,
    "Стандартно 7 дней": 1.0
}

# Логика расчета стоимости консультаций
TECH_BASE_PRICES = {
    1: (5000, 10000),   # До 50 м²
    2: (10000, 15000),  # 50-100 м²
    3: (15000, 25000),  # 100-200 м²
    4: (25000, None)    # Свыше 200 м²
}

STUDY_BASE_PRICES = {
    1: (3000, 5000),    # До 20 страниц
    2: (5000, 8000),    # 20-40 страниц
    3: (8000, None)     # Свыше 40 страниц
}

# Функции работы с файлом счетчика
def init_request_counter():
    try:
        if not os.path.exists(REQUEST_COUNTER_FILE):
            with open(REQUEST_COUNTER_FILE, 'w') as f:
                f.write('0')
            logging.info("Счетчик заявок инициализирован")
    except Exception as e:
        logging.error(f"Ошибка создания счетчика: {e}")

def get_next_request_number():
    try:
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

# Расчет стоимости консультации
def calculate_tech_consultation(data):
    try:
        area = float(data['answers'][0])
        building = data['answers'][2] if len(data['answers']) > 2 else "Не указано"

        complexity = {
            "Жилое": 1.0,
            "Коммерческое": 1.3,
            "Промышленное": 1.5
        }.get(building.split()[0], 1.2)

        if area <= 50:
            price_range = TECH_BASE_PRICES[1]
        elif area <= 100:
            price_range = TECH_BASE_PRICES[2]
        elif area <= 200:
            price_range = TECH_BASE_PRICES[3]
        else:
            price_range = TECH_BASE_PRICES[4]

        base_price = (price_range[0] + (price_range[1] or price_range[0]*1.5)) // 2
        total = int(base_price * complexity)

        # Применяем коэффициент срочности
        urgency_coeff = URGENCY_COEFFICIENTS.get(data.get('urgency', "Стандартно 7 дней"), 1.0)
        total_with_urgency = int(total * urgency_coeff)

        report = [
            "🔧 *Предварительный расчет стоимости консультации:*",
            f"- Площадь объекта: {area} м²",
            f"- Тип объекта: {building}",
            f"- Срочность выполнения: {data.get('urgency', 'Стандартно 7 дней')} (x{urgency_coeff})",
            f"- Ориентировочная стоимость: {total_with_urgency:,} руб.",
            "\n_Окончательная стоимость может быть уточнена после обсуждения деталей_"
        ]
        return '\n'.join(report).replace(',', ' ')
    except Exception as e:
        logging.error(f"Ошибка расчета: {e}")
        return "❌ Не удалось рассчитать стоимость. Мы свяжемся с вами для уточнения деталей."

def calculate_study_consultation(data):
    try:
        pages = int(data['answers'][1])
        if pages <= 20:
            price = STUDY_BASE_PRICES[1][0]
        elif pages <= 40:
            price = (STUDY_BASE_PRICES[2][0] + STUDY_BASE_PRICES[2][1]) // 2
        else:
            price = STUDY_BASE_PRICES[3][0] * 1.2

        # Применяем коэффициент срочности
        urgency_coeff = URGENCY_COEFFICIENTS.get(data.get('urgency', "Стандартно 7 дней"), 1.0)
        total_price = int(price * urgency_coeff)

        report = [
            "📚 *Стоимость учебной консультации:*",
            f"- Тема: {data['answers'][0]}",
            f"- Объем: {pages} стр.",
            f"- Срочность выполнения: {data.get('urgency', 'Стандартно 7 дней')} (x{urgency_coeff})",
            f"- Ориентировочная стоимость: {total_price:,} руб.",
            "\n_Окончательная стоимость может быть уточнена после обсуждения деталей_"
        ]
        return '\n'.join(report).replace(',', ' ')
    except Exception as e:
        logging.error(f"Ошибка расчета: {e}")
        return "❌ Не удалось рассчитать стоимость. Мы свяжемся с вами для уточнения деталей."

# Обработчики
@dp.message_handler(lambda message: message.text == "Отмена заявки", state='*')
async def cancel_request(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ Заявка отменена", reply_markup=new_request_kb)

@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    await Form.service_type.set()
    await message.answer(
        "🔌 Добро пожаловать в сервис технических консультаций!\n"
        "Выберите тип консультации:",
        reply_markup=service_type_kb
    )

@dp.message_handler(lambda m: m.text == "📝 Новая заявка!")
async def new_request(message: types.Message):
    await Form.service_type.set()
    await message.answer(random.choice(WELCOME_PHRASES), reply_markup=service_type_kb)

@dp.message_handler(state=Form.service_type)
async def process_type(message: types.Message, state: FSMContext):
    if message.text not in ["📚 Учебная консультация", "🏗️ Техническая консультация"]:
        await message.answer("Пожалуйста, используйте кнопки для выбора.")
        return

    async with state.proxy() as data:
        data['service_type'] = "study" if "Учебная" in message.text else "tech"
        data['questions'] = STUDY_QUESTIONS if data['service_type'] == "study" else TECH_QUESTIONS
        data['current_question'] = 0
        data['answers'] = []

    await Form.answers.set()
    await message.answer(data['questions'][0], reply_markup=cancel_request_kb)

@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        current = data['current_question']
        answer = message.text

        if data['service_type'] == "tech":
            if current == 0 and not answer.replace('.', '').isdigit():
                await message.answer("🔢 Введите число для площади!", reply_markup=cancel_request_kb)
                return
            if current == 1 and not answer.isdigit():
                await message.answer("🔢 Введите целое число помещений!", reply_markup=cancel_request_kb)
                return

        if data['service_type'] == "study" and current == 1 and not answer.isdigit():
            await message.answer("🔢 Введите число страниц!", reply_markup=cancel_request_kb)
            return

        data['answers'].append(answer)

        if data['service_type'] == "tech" and current == 1:
            await Form.building_type.set()
            await message.answer("🏢 Выберите тип объекта:", reply_markup=building_type_kb)
            return

        if current < len(data['questions']) - 1:
            data['current_question'] += 1
            await message.answer(data['questions'][data['current_question']], reply_markup=cancel_request_kb)
        else:
            # Переходим к выбору срочности
            await Form.urgency.set()
            await message.answer("⏱️ Выберите срочность выполнения консультации:", reply_markup=urgency_kb)

@dp.message_handler(state=Form.building_type)
async def process_building(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        if message.text == "Другое":
            await Form.custom_building.set()
            await message.answer("📝 Введите свой вариант типа объекта:", reply_markup=cancel_request_kb)
        else:
            data['answers'].append(message.text)
            await Form.answers.set()
            data['current_question'] += 1
            await message.answer(data['questions'][data['current_question']], reply_markup=cancel_request_kb)

@dp.message_handler(state=Form.custom_building)
async def process_custom_building(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['answers'].append(f"Другое ({message.text})")
        await Form.answers.set()
        data['current_question'] += 1
        await message.answer(data['questions'][data['current_question']], reply_markup=cancel_request_kb)

@dp.message_handler(state=Form.urgency)
async def process_urgency(message: types.Message, state: FSMContext):
    # Проверяем, что выбран правильный вариант срочности
    if message.text not in URGENCY_COEFFICIENTS:
        await message.answer("Пожалуйста, выберите вариант срочности из предложенных кнопок.")
        return

    async with state.proxy() as data:
        # Сохраняем выбранную срочность
        data['urgency'] = message.text

        # Рассчитываем стоимость с учетом срочности
        if data['service_type'] == "tech":
            data['price_report'] = calculate_tech_consultation(data)
        else:
            data['price_report'] = calculate_study_consultation(data)

        # Переходим к подтверждению заявки
        await Form.confirm.set()
        await message.answer(data['price_report'], parse_mode="Markdown")
        await message.answer("Подтвердить заявку на консультацию?", reply_markup=confirm_kb)

@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state=Form.confirm)
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == 'confirm_yes':
        async with state.proxy() as data:
            try:
                req_num = get_next_request_number()
                username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"

                report = f"📋 *Новая заявка на консультацию! Номер заявки №{req_num}*\n"
                report += f"Тип: {'Учебная консультация' if data['service_type'] == 'study' else 'Техническая консультация'}\n"
                report += f"🆔 {callback.from_user.id} | 📧 {username}\n"
                report += f"⏱️ Срочность выполнения: {data.get('urgency', 'Не указана')}\n\n"

                if data['service_type'] == "tech":
                    report += (
                        f"🏢 Тип объекта: {data['answers'][2]}\n"
                        f"📏 Площадь: {data['answers'][0]} м²\n"
                        f"🚪 Помещений: {data['answers'][1]}\n"
                        f"💼 Требования: {data['answers'][3]}\n\n"
                    )
                else:
                    report += (
                        f"📖 Тема: {data['answers'][0]}\n"
                        f"📄 Объем: {data['answers'][1]} стр.\n"
                        f"💡 Пожелания: {data['answers'][2]}\n\n"
                    )

                report += f"💬 *Детали расчета стоимости:*\n{data['price_report']}"

                # Проверка существования DESIGNER_CHAT_ID
                designer_chat_id = os.getenv("DESIGNER_CHAT_ID")
                if not designer_chat_id:
                    raise ValueError("Не задан DESIGNER_CHAT_ID в переменных окружения")

                await bot.send_message(
                    chat_id=designer_chat_id,
                    text=report,
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup().add(
                        types.InlineKeyboardButton(
                            "💬 Написать клиенту",
                            url=f"tg://user?id={callback.from_user.id}"
                        )
                    )
                )

                await callback.message.answer(
                    f"✅ Ваша заявка на консультацию принята! Номер заявки №{req_num}\n"
                    "Наш специалист свяжется с вами в ближайшее время.\n"
                    "Помните, консультация не заменяет проектирование!",
                    reply_markup=new_request_kb
                )

            except Exception as e:
                logging.error(f"Ошибка отправки заявки: {str(e)}", exc_info=True)
                await callback.message.answer(
                    "⚠️ Произошла ошибка при отправке заявки. Пожалуйста, попробуйте еще раз.",
                    reply_markup=new_request_kb
                )
    else:
        await callback.message.answer(
            "❌ Заявка отменена.",
            reply_markup=new_request_kb
        )
    await state.finish()

# Вебхук
async def on_startup(dp):
    init_request_counter()
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Бот запущен")

async def on_shutdown(dp):
    await bot.delete_webhook()
    await dp.storage.close()
    logging.info("Бот остановлен")

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