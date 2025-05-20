import os
import logging
import random
from aiogram import Bot, Dispatcher, types, executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from dotenv import load_dotenv
import aiofiles

# Расширенное логирование с уровнем DEBUG
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s - %(funcName)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot_debug.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()


# Конфигурация бота
class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    SPECIALIST_CHAT_ID = os.getenv("SPECIALIST_CHAT_ID")

    @classmethod
    def validate(cls):
        missing = []
        if not cls.BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not cls.SPECIALIST_CHAT_ID:
            missing.append("SPECIALIST_CHAT_ID")

        if missing:
            logger.critical(f"❌ Отсутствуют обязательные переменные окружения: {', '.join(missing)}")
            exit(1)
        logger.info("✅ Все переменные окружения загружены успешно")


Config.validate()

# Инициализация бота
bot = Bot(token=Config.BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Константы
REQUEST_COUNTER_FILE = 'request_counter.txt'


# Клавиатуры
class Keyboards:
    @staticmethod
    def create_reply(buttons):
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        for row in buttons:
            kb.row(*[types.KeyboardButton(btn) for btn in row])
        return kb

    MAIN = create_reply([
        ["📚 Учебный вопрос", "🏗️ Рабочий вопрос"]
    ])
    CANCEL = create_reply([["Отмена запроса"]])
    NEW_REQUEST = create_reply([["📝 Новый запрос!"]])
    URGENCY = create_reply([
        ["Срочно (24ч)", "3-5 дней"],
        ["Стандартно (7 дней)", "Отмена запроса"]
    ])
    OBJECT_TYPE = create_reply([
        ["Жилой дом", "Квартира"],
        ["Коммерческое помещение", "Другое"],
        ["Отмена запроса"]
    ])
    CONFIRM = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
    )


# Состояния FSM
class Form(StatesGroup):
    request_type = State()
    answers = State()
    confirm = State()


# Шаблоны ответов
class Templates:
    WELCOME = [
        "Снова к нам? Отлично! Новый запрос - новые решения!",
        "Рады видеть вас снова! Чем поможем сегодня?",
        "Профессиональная помощь - путь к правильному решению!"
    ]

    @staticmethod
    def price_report(request_type: str, data: dict) -> str:
        logger.debug(f"Формирование отчета о цене для {request_type} с данными: {data}")
        try:
            params = PRICES[request_type]
            answers = data['answers']

            if request_type == 'study':
                pages = int(answers[1])
                urgency = answers[2]
                base_total = params['base'] * pages
                total = base_total * params['urgency'][urgency]
                return (
                    f"📚 <b>Стоимость учебного вопроса:</b>\n"
                    f"- Страниц: {pages} × {params['base']}₽ = {base_total}₽\n"
                    f"- Срочность ({urgency}): ×{params['urgency'][urgency]}\n"
                    f"➔ <b>Итого: {int(total)}₽</b>\n"
                    "<i>Цена окончательно согласовывается с исполнителем</i>"
                )
            else:
                object_type = answers[1]
                urgency = answers[2]
                total = params['base'] * params['object_type'][object_type] * params['urgency'][urgency]
                return (
                    f"🏗️ <b>Стоимость рабочего вопроса:</b>\n"
                    f"- Базовая ставка: {params['base']}₽\n"
                    f"- Тип объекта ({object_type}): ×{params['object_type'][object_type]}\n"
                    f"- Срочность ({urgency}): ×{params['urgency'][urgency]}\n"
                    f"➔ <b>Итого: {int(total)}₽</b>\n"
                    "<i>Окончательная сумма может быть скорректирована</i>"
                )
        except Exception as e:
            logger.error(f"Ошибка формирования отчета о цене: {e}", exc_info=True)
            return "❌ Не удалось рассчитать стоимость. Пожалуйста, повторите попытку."


# Структура цен
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


# Счетчик запросов
async def get_next_request_number() -> int:
    try:
        logger.debug(f"Получение нового номера запроса из файла {REQUEST_COUNTER_FILE}")

        # Создаем файл если не существует
        if not os.path.exists(REQUEST_COUNTER_FILE):
            async with aiofiles.open(REQUEST_COUNTER_FILE, 'w') as f:
                await f.write('0')
            logger.info("Создан новый файл счетчика запросов")

        async with aiofiles.open(REQUEST_COUNTER_FILE, 'r+') as f:
            content = await f.read()
            counter = int(content.strip()) if content else 0
            logger.debug(f"Текущий номер запроса: {counter}")

            counter += 1
            await f.seek(0)
            await f.truncate()
            await f.write(str(counter))
            return counter

    except Exception as e:
        logger.error(f"Ошибка работы с файлом счетчика: {e}", exc_info=True)
        return random.randint(1000, 9999)


# Обработчики команд
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    logger.info(f"Пользователь {message.from_user.id} запустил бота")
    await Form.request_type.set()
    await message.answer(
        "👨💻 Добро пожаловать в сервис технических консультаций!\nВыберите тип запроса:",
        reply_markup=Keyboards.MAIN
    )


@dp.message_handler(Text("📝 Новый запрос!"))
async def new_request(message: types.Message):
    logger.debug(f"Пользователь {message.from_user.id} выбрал новый запрос")
    await Form.request_type.set()
    await message.answer(random.choice(Templates.WELCOME), reply_markup=Keyboards.MAIN)


@dp.message_handler(Text(equals=["📚 Учебный вопрос", "🏗️ Рабочий вопрос"]), state=Form.request_type)
async def process_type(message: types.Message, state: FSMContext):
    logger.debug(f"Пользователь {message.from_user.id} выбрал тип запроса: {message.text}")

    request_type = 'study' if "Учебный" in message.text else 'work'
    questions = [
        "📝 Укажите тему учебного вопроса:" if request_type == 'study'
        else "💼 Опишите ваш рабочий вопрос/проблему:",
        "📄 Требуемый объем материала (страниц):" if request_type == 'study'
        else "🏭 Выберите тип объекта:",
        "⏳ Укажите срочность выполнения:",
        "💡 Дополнительные пожелания:"
    ]

    await state.update_data({
        'request_type': request_type,
        'questions': questions,
        'current_question': 0,
        'answers': []
    })

    logger.debug(f"Инициализированы данные для {request_type}: {questions}")
    await Form.answers.set()
    await message.answer(questions[0], reply_markup=Keyboards.CANCEL)


@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    logger.debug(f"Получен ответ от пользователя {message.from_user.id}")

    data = await state.get_data()
    current = data['current_question']
    request_type = data['request_type']
    answer = message.text

    logger.debug(f"Текущий вопрос: {current}, тип запроса: {request_type}, ответ: {answer}")

    # Валидация данных
    validation_map = {
        'study': {
            1: (lambda a: not (a.isdigit() and int(a) > 0), "🔢 Введите положительное число страниц!", Keyboards.CANCEL),
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
            logger.warning(f"Ошибка валидации на шаге {current}: {error}")
            await message.answer(error, reply_markup=kb)
            return

    # Сохраняем ответ
    answers = data['answers'] + [answer]
    current += 1

    logger.debug(f"Обновленные данные: ответы={answers}, текущий шаг={current}")

    if current < len(data['questions']):
        next_question = data['questions'][current]
        keyboard = Keyboards.CANCEL

        if current == 1 and request_type == 'work':
            keyboard = Keyboards.OBJECT_TYPE
        elif current == 2:
            keyboard = Keyboards.URGENCY

        await state.update_data({
            'current_question': current,
            'answers': answers
        })

        logger.debug(f"Переход к вопросу {current}: {next_question}")
        await message.answer(next_question, reply_markup=keyboard)
    else:
        logger.debug("Все вопросы обработаны, переход к подтверждению")
        price_report = Templates.price_report(request_type, {'answers': answers})
        await state.update_data({
            'price_report': price_report,
            'answers': answers
        })
        await Form.confirm.set()

        await message.answer(price_report, parse_mode="HTML")
        await message.answer("Подтвердить запрос?", reply_markup=Keyboards.CONFIRM)


@dp.callback_query_handler(Text(startswith="confirm_"), state=Form.confirm)
async def handle_confirmation(callback: types.CallbackQuery, state: FSMContext):
    logger.debug(f"Получено подтверждение от пользователя {callback.from_user.id}: {callback.data}")

    try:
        data = await state.get_data()
        request_number = await get_next_request_number()

        if callback.data == "confirm_yes":
            report = await generate_report(callback.from_user, data, request_number)

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
                f"✅ Запрос №{request_number} принят!\n"
                "⚠️ Консультация не заменяет официальное проектирование.",
                reply_markup=Keyboards.NEW_REQUEST
            )
            logger.info(f"Запрос {request_number} успешно обработан")
        else:
            await callback.message.answer("❌ Запрос отменен", reply_markup=Keyboards.NEW_REQUEST)
            logger.info("Запрос отменен пользователем")
    except Exception as e:
        logger.error(f"Ошибка при подтверждении запроса: {e}", exc_info=True)
        await callback.message.answer("⚠ Ошибка обработки запроса")
    finally:
        await state.finish()
        logger.debug("Состояние FSM завершено")


async def generate_report(user: types.User, data: dict, request_number: int) -> str:
    logger.debug(f"Генерация отчета для запроса {request_number}")

    try:
        cost_str = data.get('price_report', '').split('Итого: ')[1].split('₽')[0].strip()
        cost = int(cost_str)
    except Exception as e:
        logger.error(f"Ошибка извлечения стоимости: {e}", exc_info=True)
        cost = "не определена"

    return (
            f"📋 Запрос №{request_number}\n"
            f"Тип: {'Учебный' if data['request_type'] == 'study' else 'Рабочий'}\n"
            f"Пользователь: @{user.username or 'N/A'}\n"
            f"ID: {user.id}\n" +
            "\n".join(f"{q}: {a}" for q, a in zip(data['questions'], data['answers'])) +
            f"\nРасчетная стоимость: {cost}₽"
    )


async def on_startup(dp):
    logger.info("🚀 Бот успешно запущен")
    await bot.delete_webhook()


async def on_shutdown(dp):
    logger.info("🛑 Бот остановлен")
    await dp.storage.close()
    await bot.session.close()


if __name__ == '__main__':
    logger.info("🔄 Запуск бота...")
    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        timeout=30,
        relax=0.1
    )