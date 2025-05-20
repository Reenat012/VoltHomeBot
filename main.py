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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()


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
            logger.critical(f"Отсутствуют переменные: {', '.join(missing)}")
            exit(1)


Config.validate()

# Инициализация бота
bot = Bot(token=Config.BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Константы
REQUEST_COUNTER_FILE = 'request_counter.txt'


class Keyboards:
    @staticmethod
    def create_reply(buttons, resize=True, one_time=False):
        return types.ReplyKeyboardMarkup(
            resize_keyboard=resize,
            one_time_keyboard=one_time
        ).add(*[types.KeyboardButton(btn) for row in buttons for btn in row])

    MAIN = create_reply([["📚 Учебный вопрос", "🏗️ Рабочий вопрос"]])
    CANCEL = create_reply([["Отмена запроса"]])
    NEW_REQUEST = create_reply([["📝 Новый запрос!"]])
    URGENCY = create_reply([
        ["Срочно (24ч)", "3-5 дней"],
        ["Стандартно (7 дней)", "Отмена запроса"]
    ], one_time=True)
    OBJECT_TYPE = create_reply([
        ["Жилой дом", "Квартира"],
        ["Коммерческое помещение", "Другое"],
        ["Отмена запроса"]
    ], one_time=True)

    @staticmethod
    def confirm():
        return types.InlineKeyboardMarkup().row(
            types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
            types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
        )


class Form(StatesGroup):
    request_type = State()
    answers = State()
    confirm = State()


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


async def get_next_request_number():
    try:
        async with aiofiles.open(REQUEST_COUNTER_FILE, 'r+') as f:
            counter = int(await f.read() or 0) + 1
            await f.seek(0)
            await f.write(str(counter))
            return counter
    except:
        return random.randint(1000, 9999)


@dp.message_handler(commands=['start', 'help'], state='*')
async def cmd_start(message: types.Message):
    await Form.request_type.set()
    await message.answer(
        "👨💻 Добро пожаловать в сервис технических консультаций!\nВыберите тип запроса:",
        reply_markup=Keyboards.MAIN
    )


@dp.message_handler(Text("📝 Новый запрос!"), state='*')
async def new_request(message: types.Message):
    await Form.request_type.set()
    await message.answer("Создаем новый запрос!", reply_markup=Keyboards.MAIN)


@dp.message_handler(Text(equals="Отмена запроса"), state='*')
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Действие отменено", reply_markup=Keyboards.NEW_REQUEST)


@dp.message_handler(Text(equals=["📚 Учебный вопрос", "🏗️ Рабочий вопрос"]), state=Form.request_type)
async def process_type(message: types.Message, state: FSMContext):
    request_type = 'study' if "Учебный" in message.text else 'work'
    questions = [
        "📝 Укажите тему:" if request_type == 'study' else "💼 Опишите проблему:",
        "📄 Количество страниц:" if request_type == 'study' else "🏭 Тип объекта:",
        "⏳ Срочность выполнения:",
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
    answers = data['answers'] + [message.text]

    # Валидация
    if current == 1 and request_type == 'study':
        if not message.text.isdigit():
            await message.answer("Введите число страниц!")
            return

    if current == 1 and request_type == 'work':
        if message.text not in PRICES['work']['object_type']:
            await message.answer("Выберите тип из списка!", reply_markup=Keyboards.OBJECT_TYPE)
            return

    if current == 2:
        if message.text not in PRICES[request_type]['urgency']:
            await message.answer("Выберите срочность из списка!", reply_markup=Keyboards.URGENCY)
            return

    # Обновление состояния
    new_data = {
        'current_question': current + 1,
        'answers': answers
    }
    await state.update_data(new_data)

    if current + 1 < len(data['questions']):
        await message.answer(data['questions'][current + 1])
    else:
        # Формирование отчета
        report = await generate_report(message.from_user, await state.get_data())
        await Form.confirm.set()
        await message.answer(report, reply_markup=Keyboards.confirm())


async def generate_report(user: types.User, data: dict):
    request_type = data['request_type']
    answers = data['answers']

    if request_type == 'study':
        pages = int(answers[1])
        urgency = answers[2]
        total = PRICES['study']['base'] * pages * PRICES['study']['urgency'][urgency]
    else:
        obj_type = answers[1]
        urgency = answers[2]
        total = PRICES['work']['base'] * PRICES['work']['object_type'][obj_type] * PRICES['work']['urgency'][urgency]

    return (
        f"📋 Предварительный расчет:\n"
        f"Тип: {'Учебный' if request_type == 'study' else 'Рабочий'}\n"
        f"Стоимость: {int(total)}₽\n"
        "Подтверждаете заявку?"
    )


@dp.callback_query_handler(Text(startswith="confirm_"), state=Form.confirm)
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "confirm_yes":
        req_num = await get_next_request_number()
        data = await state.get_data()
        report = await generate_report(callback.from_user, data)

        await bot.send_message(
            Config.SPECIALIST_CHAT_ID,
            f"Новая заявка #{req_num}\n{report}",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(
                    "Связаться",
                    url=f"tg://user?id={callback.from_user.id}"
                )
            )
        )
        await callback.message.answer("✅ Заявка принята!", reply_markup=Keyboards.NEW_REQUEST)
    else:
        await callback.message.answer("❌ Заявка отменена", reply_markup=Keyboards.NEW_REQUEST)

    await state.finish()


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)