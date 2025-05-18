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

# Конфигурация
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST', 'https://reenat012-volthomebot-2d67.twc1.net')
WEBHOOK_PATH = os.getenv('WEBHOOK_PATH', '/webhook')
WEBAPP_HOST = os.getenv('WEBAPP_HOST', '0.0.0.0')
WEBAPP_PORT = int(os.getenv('WEBAPP_PORT', 8000))
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# Инициализация бота
bot = Bot(token=os.getenv("BOT_TOKEN"))
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Константы
REQUEST_COUNTER_FILE = 'request_counter.txt'
SPECIALIST_CHAT_ID = os.getenv("SPECIALIST_CHAT_ID")


class Form(StatesGroup):
    request_type = State()
    answers = State()
    confirm = State()


# Текстовые ресурсы
TEXTS = {
    'welcome': [
        "Снова к нам? Отлично! Новый запрос - новые решения!",
        "Рады видеть вас снова! Чем поможем сегодня?",
        "Профессиональная помощь - путь к правильному решению!"
    ],
    'errors': {
        'counter': "Ошибка счетчика: {}",
        'calculation': "Ошибка расчета: {}",
        'send': "Ошибка отправки: {}"
    },
    'price_templates': {
        'study': [
            "📚 *Стоимость учебного вопроса:*",
            "- Страниц: {pages} × {base}₽ = {base_total}₽",
            "- Срочность ({urgency}): ×{urgency_coeff}",
            "➔ *Итого: {total}₽*",
            "\n_Цена окончательно согласовывается с исполнителем_"
        ],
        'work': [
            "🏗️ *Стоимость рабочего вопроса:*",
            "- Базовая ставка: {base}₽",
            "- Тип объекта ({object_type}): ×{object_coeff}",
            "- Срочность ({urgency}): ×{urgency_coeff}",
            "➔ *Итого: {total}₽*",
            "\n_Окончательная сумма может быть скорректирована_"
        ]
    }
}


# Клавиатуры
def create_keyboard(buttons, row_width=2):
    return types.ReplyKeyboardMarkup(
        [[types.KeyboardButton(btn) for btn in row] for row in buttons],
        resize_keyboard=True
    )


KEYBOARDS = {
    'request_type': create_keyboard([["📚 Учебный вопрос", "🏗️ Рабочий вопрос"]]),
    'cancel': create_keyboard([["Отмена запроса"]]),
    'new_request': create_keyboard([["📝 Новый запрос!"]]),
    'urgency': create_keyboard([
        ["Срочно (24ч)", "3-5 дней"],
        ["Стандартно (7 дней)", "Отмена запроса"]
    ]),
    'object_type': create_keyboard([
        ["Жилой дом", "Квартира"],
        ["Коммерческое помещение", "Другое"],
        ["Отмена запроса"]
    ])
}

# Inline клавиатура подтверждения
confirm_kb = types.InlineKeyboardMarkup().row(
    types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
    types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no")
)

# Вопросы
QUESTIONS = {
    'study': [
        "📝 Укажите тему учебного вопроса:",
        "📄 Требуемый объем материала (страниц):",
        "⏳ Укажите срочность выполнения:",
        "💡 Дополнительные пожелания:"
    ],
    'work': [
        "💼 Опишите ваш рабочий вопрос/проблему:",
        "🏭 Выберите тип объекта:",
        "🚨 Укажите срочность решения:",
        "📌 Дополнительные комментарии:"
    ]
}

# Ценообразование
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


def init_request_counter():
    try:
        if not os.path.exists(REQUEST_COUNTER_FILE):
            with open(REQUEST_COUNTER_FILE, 'w') as f:
                f.write('0')
            logging.info("Счетчик запросов инициализирован")
    except Exception as e:
        logging.error(TEXTS['errors']['counter'].format(e))


def get_next_request_number():
    try:
        with open(REQUEST_COUNTER_FILE, 'r+') as f:
            counter = int(f.read().strip() or 0)
            counter += 1
            f.seek(0)
            f.write(str(counter))
            return counter
    except Exception as e:
        logging.error(TEXTS['errors']['counter'].format(e))
        return random.randint(1000, 9999)


async def generate_price_report(request_type, data):
    try:
        params = PRICES[request_type]
        answers = data['answers']

        if request_type == 'study':
            pages = int(answers[1])
            urgency = answers[2]
            base_total = params['base'] * pages
            total = base_total * params['urgency'].get(urgency, 1.0)

            return '\n'.join(TEXTS['price_templates']['study']).format(
                pages=pages,
                base=params['base'],
                base_total=base_total,
                urgency=urgency,
                urgency_coeff=params['urgency'].get(urgency, 1.0),
                total=int(total)
            )
        else:
            object_type = answers[1]
            urgency = answers[2]
            object_coeff = params['object_type'].get(object_type, 1.0)
            urgency_coeff = params['urgency'].get(urgency, 1.0)
            total = params['base'] * object_coeff * urgency_coeff

            return '\n'.join(TEXTS['price_templates']['work']).format(
                base=params['base'],
                object_type=object_type,
                object_coeff=object_coeff,
                urgency=urgency,
                urgency_coeff=urgency_coeff,
                total=int(total)
            )
    except Exception as e:
        logging.error(TEXTS['errors']['calculation'].format(e))
        return "❌ Не удалось рассчитать стоимость. Специалист свяжется с вами."


@dp.message_handler(lambda message: message.text == "Отмена запроса", state='*')
async def cancel_request(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ Запрос отменен", reply_markup=KEYBOARDS['new_request'])


@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    await Form.request_type.set()
    await message.answer(
        "👨💻 Добро пожаловать в сервис технических консультаций!\nВыберите тип запроса:",
        reply_markup=KEYBOARDS['request_type']
    )


@dp.message_handler(lambda m: m.text == "📝 Новый запрос!")
async def new_request(message: types.Message):
    await Form.request_type.set()
    await message.answer(random.choice(TEXTS['welcome']), reply_markup=KEYBOARDS['request_type'])


@dp.message_handler(state=Form.request_type)
async def process_type(message: types.Message, state: FSMContext):
    if message.text not in ["📚 Учебный вопрос", "🏗️ Рабочий вопрос"]:
        await message.answer("Пожалуйста, используйте кнопки для выбора.")
        return

    async with state.proxy() as data:
        request_type = 'study' if "Учебный" in message.text else 'work'
        data.update({
            'request_type': request_type,
            'questions': QUESTIONS[request_type],
            'current_question': 0,
            'answers': []
        })

    await Form.answers.set()
    await message.answer(data['questions'][0], reply_markup=KEYBOARDS['cancel'])


@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        current = data['current_question']
        answer = message.text
        request_type = data['request_type']
        questions = data['questions']

        # Валидация ввода
        if current == 1 and request_type == 'study' and not answer.isdigit():
            await message.answer("🔢 Введите число страниц!", reply_markup=KEYBOARDS['cancel'])
            return

        if current == 2 and answer not in ["Срочно (24ч)", "3-5 дней", "Стандартно (7 дней)"]:
            await message.answer("Выберите срочность из предложенных:", reply_markup=KEYBOARDS['urgency'])
            return

        if current == 1 and request_type == 'work' and answer not in PRICES['work']['object_type']:
            await message.answer("Выберите тип объекта из предложенных:", reply_markup=KEYBOARDS['object_type'])
            return

        data['answers'].append(answer)

        if current < len(questions) - 1:
            data['current_question'] += 1
            next_question = questions[data['current_question']]

            if data['current_question'] == 2:
                await message.answer(next_question, reply_markup=KEYBOARDS['urgency'])
            elif data['current_question'] == 1 and request_type == 'work':
                await message.answer(next_question, reply_markup=KEYBOARDS['object_type'])
            else:
                await message.answer(next_question, reply_markup=KEYBOARDS['cancel'])
        else:
            data['price_report'] = await generate_price_report(request_type, data)
            await Form.confirm.set()
            await message.answer(data['price_report'], parse_mode="Markdown")
            await message.answer("Подтвердить запрос?", reply_markup=confirm_kb)


@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state=Form.confirm)
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    try:
        if not SPECIALIST_CHAT_ID:
            logging.error("Не задан SPECIALIST_CHAT_ID в переменных окружения")
            await callback.answer("Ошибка конфигурации бота")
            return

        async with state.proxy() as data:
            if callback.data == 'confirm_yes':
                try:
                    req_num = get_next_request_number()
                    username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"

                    # Формируем отчет безопасным способом
                    try:
                        cost_part = data['price_report'].split('Итого: ')[1].split('₽')[0].strip()
                    except Exception as e:
                        logging.error(f"Ошибка парсинга стоимости: {str(e)}")
                        cost_part = "не определена"

                    report = (
                            f"📋 Новый запрос №{req_num}\n"
                            f"Тип: {'Учебный' if data['request_type'] == 'study' else 'Рабочий'}\n"
                            f"Клиент: {username}\nID: {callback.from_user.id}\n\n"
                            + '\n'.join(f"{q}: {a}" for q, a in zip(data['questions'], data['answers']))
                            + f"\n\nРасчетная стоимость: {cost_part}₽"
                    )

                    await bot.send_message(
                        chat_id=SPECIALIST_CHAT_ID,
                        text=report,
                        parse_mode="Markdown",
                        reply_markup=types.InlineKeyboardMarkup().add(
                            types.InlineKeyboardButton(
                                "💬 Связаться с клиентом",
                                url=f"tg://user?id={callback.from_user.id}"
                            )
                        )
                    )

                    disclaimer = (
                        "\n\n⚠️ *Важно:* Консультация не заменяет официальное проектирование. "
                        "Для реализации работ требуется привлечение лицензированных организаций."
                    )

                    await callback.message.edit_reply_markup()  # Удаляем инлайн-клавиатуру
                    await callback.message.answer(
                        f"✅ Ваш запрос №{req_num} принят! Ожидайте связи специалиста.{disclaimer}",
                        reply_markup=KEYBOARDS['new_request'],
                        parse_mode="Markdown"
                    )

                except Exception as e:
                    logging.error(TEXTS['errors']['send'].format(e))
                    await callback.message.answer(
                        "⚠️ Ошибка при отправке. Попробуйте снова.",
                        reply_markup=KEYBOARDS['new_request']
                    )
            else:
                await callback.message.edit_reply_markup()  # Удаляем инлайн-клавиатуру
                await callback.message.answer(
                    "❌ Запрос отменен.",
                    reply_markup=KEYBOARDS['new_request']
                )
    finally:
        await state.finish()  # Гарантированное завершение состояния
    await callback.answer()  # Подтверждаем обработку callback

async def on_startup(dp):
    init_request_counter()
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Бот запущен")


async def on_shutdown(dp):
    await bot.delete_webhook()
    await dp.storage.close()
    logging.info("Бот остановлен")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT
    )