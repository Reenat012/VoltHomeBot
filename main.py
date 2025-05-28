import os
import logging
import random
import asyncio
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.redis import RedisStorage2
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.executor import start_webhook
from dotenv import load_dotenv

load_dotenv()

# Конфигурация хранилища
DATA_PATH = os.getenv("DATA_PATH", "/tmp")
REQUEST_COUNTER_FILE = f'{DATA_PATH}/request_counter.txt'

# Конфигурация вебхука
WEBHOOK_HOST = 'https://reenat012-volthomebot-2d67.twc1.net'
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
WEBAPP_HOST = '0.0.0.0'
WEBAPP_PORT = 8000

# Инициализация бота с таймаутами
bot = Bot(
    token=os.getenv("BOT_TOKEN"),
    timeout=15,
    parse_mode="Markdown"
)

# Использование Redis вместо MemoryStorage
storage = RedisStorage2(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=os.getenv("REDIS_PORT", 6379),
    db=os.getenv("REDIS_DB", 0),
    password=os.getenv("REDIS_PASSWORD")
)
dp = Dispatcher(bot, storage=storage)


# Проверка соединения с Redis
async def check_redis_connection():
    try:
        await storage.redis.ping()
        logging.info("✅ Redis connection successful")
    except Exception as e:
        logging.error(f"❌ Redis connection error: {e}")


# Конфигурация
WELCOME_PHRASES = [
    "Снова к нам? Отлично! Давайте новую заявку!",
    "Рады видеть вас снова! Готовы начать?",
    "Новая заявка - новые возможности! Поехали!"
]

# Глобальная блокировка для атомарных операций
counter_lock = asyncio.Lock()


# Асинхронные клавиатуры
def get_project_type_kb():
    return types.ReplyKeyboardMarkup(
        [
            [types.KeyboardButton("📚 Учебный вопрос")],
            [types.KeyboardButton("🏗️ Рабочий вопрос")]
        ],
        resize_keyboard=True
    )


def get_cancel_request_kb():
    return types.ReplyKeyboardMarkup(
        [[types.KeyboardButton("Отмена заявки")]],
        resize_keyboard=True
    )


def get_new_request_kb():
    return types.ReplyKeyboardMarkup(
        [[types.KeyboardButton("📝 Новая заявка!")]],
        resize_keyboard=True
    )


def get_building_type_kb():
    return types.ReplyKeyboardMarkup(
        [
            [types.KeyboardButton("Жилое"), types.KeyboardButton("Коммерческое")],
            [types.KeyboardButton("Промышленное"), types.KeyboardButton("Другое")],
            [types.KeyboardButton("Отмена заявки")]
        ],
        resize_keyboard=True
    )


def get_confirm_kb():
    return types.InlineKeyboardMarkup().row(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
    )


# Вопросы
WORK_QUESTIONS = [
    "Укажите площадь объекта (м²):",
    "Количество помещений:",
    "Дополнительные пожелания:"
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
    4: (70000, None)  # Свыше 200 м²
}

STUDY_BASE_PRICES = {
    1: (5000, 10000),  # До 20 страниц
    2: (10000, 15000),  # 20-40 страниц
    3: (15000, None)  # Свыше 40 страниц
}


# Асинхронные функции работы с файлом счетчика
async def init_request_counter():
    try:
        async with counter_lock:
            # Создаем директорию, если не существует
            os.makedirs(DATA_PATH, exist_ok=True)

            if not os.path.exists(REQUEST_COUNTER_FILE):
                with open(REQUEST_COUNTER_FILE, 'w') as f:
                    f.write('0')
                logging.info("Счетчик заявок инициализирован")
    except Exception as e:
        logging.error(f"Ошибка создания счетчика: {e}")
        return False
    return True


async def get_next_request_number():
    async with counter_lock:
        try:
            # Инициализируем счетчик при первом запуске
            if not os.path.exists(REQUEST_COUNTER_FILE):
                await init_request_counter()

            with open(REQUEST_COUNTER_FILE, 'r+') as f:
                content = f.read().strip()
                counter = int(content) if content.isdigit() else 0
                counter += 1
                f.seek(0)
                f.write(str(counter))
                f.truncate()
                return counter
        except Exception as e:
            logging.error(f"Ошибка счетчика: {e}")
            return random.randint(1000, 9999)


# Асинхронный расчет стоимости
async def calculate_work_price(data):
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

        base_price = (price_range[0] + (price_range[1] or price_range[0] * 1.5)) // 2
        total = int(base_price * complexity)

        report = [
            "🔧 *Предварительный расчет:*",
            f"- Площадь: {area} м² | Тип: {building}",
            f"- Стоимость: {total:,} руб.",
            "\n_Точная сумма после анализа требований_"
        ]
        return '\n'.join(report).replace(',', ' ')
    except Exception as e:
        logging.error(f"Ошибка расчета: {e}")
        return "❌ Не удалось рассчитать стоимость. Специалист свяжется с вами."


async def calculate_study_price(data):
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
            "\n_Цена может измениться после уточнения требований_"
        ]
        return '\n'.join(report).replace(',', ' ')
    except Exception as e:
        logging.error(f"Ошибка расчета: {e}")
        return "❌ Не удалось рассчитать. Менеджер свяжется с вами."


# Обработчики
@dp.message_handler(lambda message: message.text == "Отмена заявки", state='*')
async def cancel_request(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ Заявка отменена", reply_markup=get_new_request_kb())


@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    await Form.project_type.set()
    await message.answer(
        "🔌 Добро пожаловать в сервис проектирования!\nВыберите тип проекта:",
        reply_markup=get_project_type_kb()
    )


@dp.message_handler(lambda m: m.text == "📝 Новая заявка!")
async def new_request(message: types.Message):
    await Form.project_type.set()
    await message.answer(random.choice(WELCOME_PHRASES), reply_markup=get_project_type_kb())


@dp.message_handler(state=Form.project_type)
async def process_type(message: types.Message, state: FSMContext):
    valid_options = ["📚 Учебный вопрос", "🏗️ Рабочий вопрос"]
    if message.text not in valid_options:
        await message.answer("Пожалуйста, используйте кнопки для выбора.")
        return

    async with state.proxy() as data:
        data['project_type'] = "study" if "Учебный" in message.text else "work"
        data['questions'] = STUDY_QUESTIONS if data['project_type'] == "study" else WORK_QUESTIONS
        data['current_question'] = 0
        data['answers'] = []

    await Form.answers.set()
    await message.answer(data['questions'][0], reply_markup=get_cancel_request_kb())


@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        current = data['current_question']
        answer = message.text

        # Валидация ввода
        if data['project_type'] == "work":
            if current == 0 and not answer.replace('.', '', 1).isdigit():
                await message.answer("🔢 Введите число для площади!", reply_markup=get_cancel_request_kb())
                return
            if current == 1 and not answer.isdigit():
                await message.answer("🔢 Введите целое число помещений!", reply_markup=get_cancel_request_kb())
                return

        if data['project_type'] == "study" and current == 1 and not answer.isdigit():
            await message.answer("🔢 Введите число страниц!", reply_markup=get_cancel_request_kb())
            return

        data['answers'].append(answer)

        # Переход к следующему вопросу или выбору типа здания
        if data['project_type'] == "work" and current == 1:
            await Form.building_type.set()
            await message.answer("🏢 Выберите тип здания:", reply_markup=get_building_type_kb())
            return

        if current < len(data['questions']) - 1:
            data['current_question'] += 1
            await message.answer(data['questions'][data['current_question']], reply_markup=get_cancel_request_kb())
        else:
            # Расчет стоимости
            if data['project_type'] == "work":
                data['price_report'] = await calculate_work_price(data)
            else:
                data['price_report'] = await calculate_study_price(data)

            await Form.confirm.set()
            await message.answer(data['price_report'])
            await message.answer("Подтвердить заявку?", reply_markup=get_confirm_kb())


@dp.message_handler(state=Form.building_type)
async def process_building(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        if message.text == "Другое":
            await Form.custom_building.set()
            await message.answer("📝 Введите свой вариант типа здания:", reply_markup=get_cancel_request_kb())
        else:
            data['answers'].append(message.text)
            await Form.answers.set()
            data['current_question'] += 1
            await message.answer(data['questions'][data['current_question']], reply_markup=get_cancel_request_kb())


@dp.message_handler(state=Form.custom_building)
async def process_custom_building(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['answers'].append(f"Другое ({message.text})")
        await Form.answers.set()
        data['current_question'] += 1
        await message.answer(data['questions'][data['current_question']], reply_markup=get_cancel_request_kb())


@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state=Form.confirm)
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == 'confirm_yes':
        async with state.proxy() as data:
            try:
                req_num = await get_next_request_number()
                username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"

                report = f"📋 *Новая заявка! Номер заявки №{req_num}*\nТип: {'Учебный' if data['project_type'] == 'study' else 'Рабочий'}\n"
                report += f"🆔 {callback.from_user.id} | 📧 {username}\n\n"

                if data['project_type'] == "work":
                    report += (
                        f"🏢 Тип здания: {data['answers'][2]}\n"
                        f"📏 Площадь: {data['answers'][0]} м²\n"
                        f"🚪 Помещений: {data['answers'][1]}\n"
                        f"💼 Требования: {data['answers'][3]}\n\n"
                        f"{data['price_report']}"
                    )
                else:
                    report += (
                        f"📖 Тема: {data['answers'][0]}\n"
                        f"📄 Объем: {data['answers'][1]} стр.\n"
                        f"⏳ Срок: {data['answers'][2]}\n"
                        f"💡 Пожелания: {data['answers'][3]}\n\n"
                        f"{data['price_report']}"
                    )

                # Проверка существования DESIGNER_CHAT_ID
                designer_chat_id = os.getenv("DESIGNER_CHAT_ID")
                if not designer_chat_id:
                    raise ValueError("Не задан DESIGNER_CHAT_ID в переменных окружения")

                await bot.send_message(
                    chat_id=designer_chat_id,
                    text=report,
                    reply_markup=types.InlineKeyboardMarkup().add(
                        types.InlineKeyboardButton(
                            "💬 Написать",
                            url=f"tg://user?id={callback.from_user.id}"
                        )
                    ),
                    timeout=5
                )

                await callback.message.answer(
                    f"✅ Ваша заявка принята! Номер заявки №{req_num}. \nОжидайте связи специалиста.",
                    reply_markup=get_new_request_kb()
                )

            except Exception as e:
                logging.error(f"Ошибка отправки заявки: {str(e)}", exc_info=True)
                await callback.message.answer(
                    "⚠️ Произошла ошибка при отправке заявки. Пожалуйста, попробуйте еще раз.",
                    reply_markup=get_new_request_kb()
                )
    else:
        await callback.message.answer(
            "❌ Заявка отменена.",
            reply_markup=get_new_request_kb()
        )
    await state.finish()


# Вебхук
async def on_startup(dp):
    await check_redis_connection()
    await init_request_counter()
    await bot.set_webhook(WEBHOOK_URL, max_connections=40)
    logging.info("Бот запущен")


async def on_shutdown(dp):
    await bot.delete_webhook()
    await dp.storage.close()
    await dp.storage.wait_closed()
    logging.info("Бот остановлен")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        skip_updates=True
    )