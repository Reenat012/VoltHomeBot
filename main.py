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
from typing import Dict, Any, Union, Optional
import re

# Инициализация переменных окружения
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация вебхука
WEBHOOK_HOST = 'https://reenat012-volthomebot-2d67.twc1.net'
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
WEBAPP_HOST = '0.0.0.0'
WEBAPP_PORT = 8000

# Проверка обязательных переменных окружения
REQUIRED_ENV_VARS = ["BOT_TOKEN", "DESIGNER_CHAT_ID"]
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    logger.error(f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}")
    raise EnvironmentError("Необходимы все переменные окружения для запуска бота")

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
    [[types.KeyboardButton("📚 Учебный проект")],
     [types.KeyboardButton("🏗️ Рабочий проект")]],
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
    [[types.KeyboardButton("Жилое"), types.KeyboardButton("Коммерческое")],
     [types.KeyboardButton("Промышленное"), types.KeyboardButton("Другое")],
     [types.KeyboardButton("Отмена заявки")]],
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


# Базовые цены
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


def init_request_counter():
    """Инициализация счетчика заявок"""
    try:
        if not os.path.exists(REQUEST_COUNTER_FILE):
            with open(REQUEST_COUNTER_FILE, 'w') as f:
                f.write('0')
            logger.info("Счетчик заявок успешно инициализирован")
    except Exception as e:
        logger.error(f"Ошибка создания счетчика: {e}", exc_info=True)


def get_next_request_number() -> int:
    """Получение следующего номера заявки"""
    try:
        if not os.path.exists(REQUEST_COUNTER_FILE):
            init_request_counter()

        with open(REQUEST_COUNTER_FILE, 'r+') as f:
            try:
                counter = int(f.read().strip() or 0)
            except ValueError:
                counter = 0
                logger.warning("Сброс счетчика заявок из-за некорректного значения")

            counter += 1
            f.seek(0)
            f.write(str(counter))
            return counter

    except Exception as e:
        logger.error(f"Ошибка работы со счетчиком: {e}", exc_info=True)
        return random.randint(1000, 9999)


def validate_area(area: str) -> bool:
    """Проверка корректности введенной площади"""
    try:
        value = float(area)
        return value > 0
    except ValueError:
        return False


def validate_room_count(count: str) -> bool:
    """Проверка корректности количества помещений"""
    try:
        value = int(count)
        return value > 0
    except ValueError:
        return False


def validate_page_count(count: str) -> bool:
    """Проверка корректности количества страниц"""
    try:
        value = int(count)
        return value > 0
    except ValueError:
        return False


def calculate_work_price(data: Dict[str, Any]) -> str:
    """Расчет стоимости рабочего проекта"""
    try:
        if len(data['answers']) < 3:
            raise ValueError("Недостаточно данных для расчета стоимости рабочего проекта")

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

        # Исправленный расчет для случая, когда цена не задана
        if price_range[1] is None:
            base_price = price_range[0] * 1.5
        else:
            base_price = (price_range[0] + price_range[1]) // 2

        total = int(base_price * complexity)

        report = [
            "🔧 *Предварительный расчет:*",
            f"- Площадь: {area} м² | Тип: {building}",
            f"- Стоимость: {total:,} руб.",
            "_Точная сумма после анализа требований_"
        ]
        return '\n'.join(report).replace(',', ' ')

    except ValueError as ve:
        logger.error(f"Ошибка валидации данных: {ve}", exc_info=True)
        return "❌ Не удалось рассчитать стоимость. Проверьте введенные данные."
    except Exception as e:
        logger.error(f"Неожиданная ошибка расчета: {e}", exc_info=True)
        return "❌ Не удалось рассчитать стоимость. Специалист свяжется с вами."


def calculate_study_price(data: Dict[str, Any]) -> str:
    """Расчет стоимости учебного проекта"""
    try:
        if len(data['answers']) < 2:
            raise ValueError("Недостаточно данных для расчета стоимости учебного проекта")

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

    except ValueError as ve:
        logger.error(f"Ошибка валидации данных: {ve}", exc_info=True)
        return "❌ Не удалось рассчитать стоимость. Проверьте введенные данные."
    except Exception as e:
        logger.error(f"Неожиданная ошибка расчета: {e}", exc_info=True)
        return "❌ Не удалось рассчитать. Менеджер свяжется с вами."


@dp.message_handler(lambda message: message.text == "Отмена заявки", state='*')
async def cancel_request(message: types.Message, state: FSMContext):
    """Обработчик отмены заявки"""
    current_state = await state.get_state()
    if current_state is None:
        return

    await state.finish()
    await message.answer("❌ Заявка отменена", reply_markup=new_request_kb)

    await Form.project_type.set()
    await message.answer("Выберите тип проекта:", reply_markup=project_type_kb)


@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    """Стартовое сообщение"""
    await Form.project_type.set()
    await message.answer(
        "🔌 Добро пожаловать в сервис проектирования!\n"
        "Выберите тип проекта:",
        reply_markup=project_type_kb
    )


@dp.message_handler(lambda m: m.text == "📝 Новая заявка!")
async def new_request(message: types.Message):
    """Начало новой заявки"""
    await Form.project_type.set()
    await message.answer(
        random.choice(WELCOME_PHRASES),
        reply_markup=project_type_kb
    )


@dp.message_handler(state=Form.project_type)
async def process_type(message: types.Message, state: FSMContext):
    """Обработка выбора типа проекта"""
    if message.text not in ["📚 Учебный проект", "🏗️ Рабочий проект"]:
        await message.answer("Пожалуйста, используйте кнопки для выбора.")
        return

    async with state.proxy() as data:
        data['project_type'] = "study" if "Учебный" in message.text else "work"
        data['questions'] = STUDY_QUESTIONS if data['project_type'] == "study" else WORK_QUESTIONS
        data['current_question'] = 0
        data['answers'] = []

    await Form.answers.set()
    await message.answer(data['questions'][0], reply_markup=cancel_request_kb)


@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    """Обработка ответов пользователя"""
    async with state.proxy() as data:
        current = data['current_question']
        answer = message.text.strip()

        # Валидация ввода
        if data['project_type'] == "work":
            if current == 0 and not validate_area(answer):
                await message.answer("🔢 Введите корректное число для площади!", reply_markup=cancel_request_kb)
                return
            if current == 1 and not validate_room_count(answer):
                await message.answer("🔢 Введите целое положительное число помещений!", reply_markup=cancel_request_kb)
                return
        elif data['project_type'] == "study" and current == 1 and not validate_page_count(answer):
            await message.answer("🔢 Введите целое положительное число страниц!", reply_markup=cancel_request_kb)
            return

        data['answers'].append(answer)

        if data['project_type'] == "work" and current == 1:
            await Form.building_type.set()
            await message.answer("🏢 Выберите тип здания:", reply_markup=building_type_kb)
            return

        if current < len(data['questions']) - 1:
            data['current_question'] += 1
            await message.answer(data['questions'][data['current_question']], reply_markup=cancel_request_kb)
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
    """Обработка выбора типа здания"""
    async with state.proxy() as data:
        if message.text == "Другое":
            await Form.custom_building.set()
            await message.answer("📝 Введите свой вариант типа здания:", reply_markup=cancel_request_kb)
        else:
            data['answers'].append(message.text)
            await Form.answers.set()
            data['current_question'] += 1

            if data['current_question'] < len(data['questions']):
                await message.answer(data['questions'][data['current_question']], reply_markup=cancel_request_kb)
            else:
                if data['project_type'] == "work":
                    data['price_report'] = calculate_work_price(data)
                else:
                    data['price_report'] = calculate_study_price(data)

                await Form.confirm.set()
                await message.answer(data['price_report'], parse_mode="Markdown")
                await message.answer("Подтвердить заявку?", reply_markup=confirm_kb)


@dp.message_handler(state=Form.custom_building)
async def process_custom_building(message: types.Message, state: FSMContext):
    """Обработка пользовательского типа здания"""
    async with state.proxy() as data:
        data['answers'].append(f"Другое ({message.text})")
        await Form.answers.set()
        data['current_question'] += 1

        if data['current_question'] < len(data['questions']):
            await message.answer(data['questions'][data['current_question']], reply_markup=cancel_request_kb)
        else:
            if data['project_type'] == "work":
                data['price_report'] = calculate_work_price(data)
            else:
                data['price_report'] = calculate_study_price(data)

            await Form.confirm.set()
            await message.answer(data['price_report'], parse_mode="Markdown")
            await message.answer("Подтвердить заявку?", reply_markup=confirm_kb)


@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state=Form.confirm)
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение заявки"""
    if callback.data == 'confirm_yes':
        async with state.proxy() as data:
            try:
                designer_chat_id = os.getenv("DESIGNER_CHAT_ID")
                if not designer_chat_id:
                    raise ValueError("DESIGNER_CHAT_ID не задан в переменных окружения")

                req_num = get_next_request_number()
                username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"

                report = (
                    f"📋 *Новая заявка! Номер заявки №{req_num}\n"
                    f"Тип: {'Учебный' if data['project_type'] == 'study' else 'Рабочий'}\n"
                    f"🆔 {callback.from_user.id} | 📧 {username}\n"
                )

                if data['project_type'] == "work":
                    if len(data['answers']) < 4:
                        raise ValueError(f"Недостаточно данных в заявке: {data['answers']}")

                    report += (
                        f"🏢 Тип здания: {data['answers'][2]}\n"
                        f"📏 Площадь: {data['answers'][0]} м²\n"
                        f"🚪 Помещений: {data['answers'][1]}\n"
                        f"💼 Требования: {data['answers'][3]}\n"
                        f"{data['price_report']}"
                    )
                else:
                    if len(data['answers']) < 4:
                        raise ValueError(f"Недостаточно данных в заявке: {data['answers']}")

                    report += (
                        f"📖 Тема: {data['answers'][0]}\n"
                        f"📄 Объем: {data['answers'][1]} стр.\n"
                        f"⏳ Срок: {data['answers'][2]}\n"
                        f"💡 Пожелания: {data['answers'][3]}\n"
                        f"{data['price_report']}"
                    )

                # Отправка сообщения проектировщику
                await bot.send_message(
                    designer_chat_id,
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
                    f"✅ Ваша заявка принята! Номер заявка №{req_num}. \n"
                    "Ожидайте связи специалиста.",
                    reply_markup=new_request_kb
                )

            except ValueError as ve:
                logger.error(f"Ошибка валидации данных: {ve}", exc_info=True)
                await callback.message.answer(
                    "⚠️ Ошибка в данных заявки. Пожалуйста, проверьте введенные данные.",
                    reply_markup=new_request_kb
                )
            except Exception as e:
                logger.error(f"Ошибка отправки заявки: {str(e)}", exc_info=True)
                await callback.message.answer(
                    "⚠️ Произошла ошибка при отправке заявки. Пожалуйста, попробуйте еще раз.",
                    reply_markup=new_request_kb
                )
    else:
        await cancel_request(callback.message, state)

    await state.finish()


async def on_startup(dp):
    """Действия при запуске бота"""
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("Бот запущен")
    init_request_counter()


async def on_shutdown(dp):
    """Действия при остановке бота"""
    await bot.delete_webhook()
    await dp.storage.close()
    logger.info("Бот остановлен")


if __name__ == '__main__':
    init_request_counter()
    logger.info("Запуск бота")
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT
    )