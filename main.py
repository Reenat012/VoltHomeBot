import os
import logging
import random
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.redis import RedisStorage2  # Более производительное хранилище
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from dotenv import load_dotenv
import aiofiles  # Асинхронная работа с файлами

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()


# Кэширование конфигурационных данных
class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    SPECIALIST_CHAT_ID = os.getenv("SPECIALIST_CHAT_ID")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    @classmethod
    def validate(cls):
        if not all([cls.BOT_TOKEN, cls.SPECIALIST_CHAT_ID]):
            logger.critical("❌ Отсутствуют обязательные переменные окружения!")
            exit(1)


Config.validate()

# Инициализация бота с кэшированием
bot = Bot(token=Config.BOT_TOKEN, parse_mode="HTML")
storage = RedisStorage2.from_url(Config.REDIS_URL)  # Используем Redis для состояний
dp = Dispatcher(bot, storage=storage)

# Константы
REQUEST_COUNTER_FILE = 'request_counter.txt'


# Предварительно созданные клавиатуры
class Keyboards:
    @staticmethod
    def create_reply(buttons):
        return types.ReplyKeyboardMarkup(
            [[types.KeyboardButton(btn) for btn in row] for row in buttons],
            resize_keyboard=True,
            one_time_keyboard=True
        )

    MAIN = create_reply.__func__([["📚 Учебный вопрос", "🏗️ Рабочий вопрос"]])
    CANCEL = create_reply.__func__([["Отмена запроса"]])
    NEW_REQUEST = create_reply.__func__([["📝 Новый запрос!"]])
    URGENCY = create_reply.__func__([
        ["Срочно (24ч)", "3-5 дней"],
        ["Стандартно (7 дней)", "Отмена запроса"]
    ])
    OBJECT_TYPE = create_reply.__func__([
        ["Жилой дом", "Квартира"],
        ["Коммерческое помещение", "Другое"],
        ["Отмена запроса"]
    ])

    CONFIRM = types.InlineKeyboardMarkup().row(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
    )


# Состояния FSM с мемоизацией
class Form(StatesGroup):
    request_type = State()
    answers = State()
    confirm = State()


# Оптимизированные текстовые шаблоны
class Templates:
    WELCOME = [
        "Снова к нам? Отлично! Новый запрос - новые решения!",
        "Рады видеть вас снова! Чем поможем сегодня?",
        "Профессиональная помощь - путь к правильному решению!"
    ]

    @staticmethod
    def price_report(request_type: str, data: dict) -> str:
        params = PRICES[request_type]
        answers = data['answers']

        if request_type == 'study':
            pages = int(answers[1])
            urgency = answers[2]
            base_total = params['base'] * pages
            total = base_total * params['urgency'][urgency]
            return (
                f"📚 *Стоимость учебного вопроса:*\n"
                f"- Страниц: {pages} × {params['base']}₽ = {base_total}₽\n"
                f"- Срочность ({urgency}): ×{params['urgency'][urgency]}\n"
                f"➔ *Итого: {int(total)}₽*\n"
                "_Цена окончательно согласовывается с исполнителем_"
            )
        else:
            object_type = answers[1]
            urgency = answers[2]
            total = params['base'] * params['object_type'][object_type] * params['urgency'][urgency]
            return (
                f"🏗️ *Стоимость рабочего вопроса:*\n"
                f"- Базовая ставка: {params['base']}₽\n"
                f"- Тип объекта ({object_type}): ×{params['object_type'][object_type]}\n"
                f"- Срочность ({urgency}): ×{params['urgency'][urgency]}\n"
                f"➔ *Итого: {int(total)}₽*\n"
                "_Окончательная сумма может быть скорректирована_"
            )


# Оптимизированная структура данных для цен
PRICES = {
    'study': {
        'base': 800,
        'urgency': {
            "Срочно (24ч)": 1.8,
            "3-5 дней": 1.3,
            "Стандартно (7 дней)": 1.0
        }
    },
    'work': {
        'base': 1500,
        'object_type': {
            "Жилой дом": 1.0,
            "Квартира": 0.9,
            "Коммерческое помещение": 1.2,
            "Другое": 1.1
        },
        'urgency': {
            "Срочно (24ч)": 2.0,
            "3-5 дней": 1.5,
            "Стандартно (7 дней)": 1.0
        }
    }
}


# Асинхронный счетчик запросов
async def get_next_request_number() -> int:
    try:
        async with aiofiles.open(REQUEST_COUNTER_FILE, 'r+') as f:
            content = await f.read()
            counter = int(content.strip()) if content else 0
            counter += 1
            await f.seek(0)
            await f.write(str(counter))
            return counter
    except Exception as e:
        logger.error(f"Ошибка счетчика: {e}")
        return random.randint(1000, 9999)


# Оптимизированные обработчики
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    await Form.request_type.set()
    await message.answer(
        "👨💻 Добро пожаловать в сервис технических консультаций!\nВыберите тип запроса:",
        reply_markup=Keyboards.MAIN
    )


@dp.message_handler(Text("📝 Новый запрос!"))
async def new_request(message: types.Message):
    await Form.request_type.set()
    await message.answer(random.choice(Templates.WELCOME), reply_markup=Keyboards.MAIN)


@dp.message_handler(Text(equals=["📚 Учебный вопрос", "🏗️ Рабочий вопрос"]), state=Form.request_type)
async def process_type(message: types.Message, state: FSMContext):
    request_type = 'study' if "Учебный" in message.text else 'work'
    questions = [
        "📝 Укажите тему учебного вопроса:" if request_type == 'study'
        else "💼 Опишите ваш рабочий вопрос/проблему:",
        "📄 Требуемый объем материала (страниц):" if request_type == 'study'
        else "🏭 Выберите тип объекта:",
        "⏳ Укажите срочность выполнения:",
        "💡 Дополнительные пожелания:"
    ]

    await state.update_data(
        request_type=request_type,
        questions=questions,
        current_question=0,
        answers=[]
    )
    await Form.answers.set()
    await message.answer(questions[0], reply_markup=Keyboards.CANCEL)


@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current = data['current_question']
    request_type = data['request_type']
    answer = message.text

    # Быстрая валидация через словарь
    validation_map = {
        'study': {
            1: (lambda a: not a.isdigit(), "🔢 Введите число страниц!", Keyboards.CANCEL),
            2: (lambda a: a not in PRICES['study']['urgency'], "Выберите срочность:", Keyboards.URGENCY)
        },
        'work': {
            1: (lambda a: a not in PRICES['work']['object_type'], "Выберите тип объекта:", Keyboards.OBJECT_TYPE),
            2: (lambda a: a not in PRICES['work']['urgency'], "Выберите срочность:", Keyboards.URGENCY)
        }
    }

    if current in validation_map.get(request_type, {}):
        check, error, kb = validation_map[request_type][current]
        if check(answer):
            await message.answer(error, reply_markup=kb)
            return

    data['answers'].append(answer)
    data['current_question'] += 1

    if data['current_question'] < len(data['questions']):
        next_question = data['questions'][data['current_question']]
        keyboard = Keyboards.CANCEL
        if data['current_question'] == 1 and request_type == 'work':
            keyboard = Keyboards.OBJECT_TYPE
        elif data['current_question'] == 2:
            keyboard = Keyboards.URGENCY

        await state.update_data(**data)
        await message.answer(next_question, reply_markup=keyboard)
    else:
        await state.update_data(price_report=Templates.price_report(request_type, data))
        await Form.confirm.set()
        await message.answer(data['price_report'], parse_mode="Markdown")
        await message.answer("Подтвердить запрос?", reply_markup=Keyboards.CONFIRM)


@dp.callback_query_handler(Text(startswith="confirm_"), state=Form.confirm)
async def handle_confirmation(callback: types.CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        if callback.data == "confirm_yes":
            report = await generate_report(callback.from_user, data)
            await bot.send_message(
                chat_id=Config.SPECIALIST_CHAT_ID,
                text=report,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton(
                        "💬 Связаться",
                        url=f"tg://user?id={callback.from_user.id}"
                    )
                )
            )
            await callback.message.answer(
                f"✅ Запрос №{await get_next_request_number()} принят!\n"
                "⚠️ Консультация не заменяет официальное проектирование.",
                reply_markup=Keyboards.NEW_REQUEST
            )
        else:
            await callback.message.answer("❌ Запрос отменен", reply_markup=Keyboards.NEW_REQUEST)
    except Exception as e:
        logger.error(f"Ошибка подтверждения: {e}")
        await callback.message.answer("⚠ Ошибка обработки запроса")
    finally:
        await state.finish()


async def generate_report(user: types.User, data: dict) -> str:
    try:
        cost = data['price_report'].split('Итого: ')[1].split('₽')[0].strip()
    except Exception as e:
        logger.error(f"Ошибка извлечения стоимости: {e}")
        cost = "не определена"

    return (
            f"📋 Запрос №{await get_next_request_number()}\n"
            f"Тип: {'Учебный' if data['request_type'] == 'study' else 'Рабочий'}\n"
            f"Пользователь: @{user.username if user.username else 'N/A'}\n"
            f"ID: {user.id}\n\n" +
            "\n".join(f"{q}: {a}" for q, a in zip(data['questions'], data['answers'])) +
            f"\n\nРасчетная стоимость: {cost}₽"
    )


async def on_startup(dp):
    await bot.delete_webhook()
    logger.info("Бот успешно запущен")


async def on_shutdown(dp):
    await dp.storage.close()
    await bot.session.close()
    logger.info("Бот остановлен")


if __name__ == '__main__':
    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        timeout=30,
        relax=0.1
    )