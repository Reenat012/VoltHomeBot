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
            total = params['base'] * params['object_type'].get(object_type, 1.0) * params['urgency'].get(urgency, 1.0)

            return '\n'.join(TEXTS['price_templates']['work']).format(
                base=params['base'],
                object_type=object_type,
                object_coeff=params['object_type'].get(object_type, 1.0),
                urgency=urgency,
                urgency_coeff=params['urgency'].get(urgency, 1.0),
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
        validation_errors = {
            'study': {
                1: (lambda: not answer.isdigit(), "🔢 Введите число страниц!", KEYBOARDS['cancel']),
                2: (lambda: answer not in PRICES['study']['urgency'], "Выберите срочность из предложенных:",
                    KEYBOARDS['urgency'])
            },
            'work': {
                1: (lambda: answer not in PRICES['work']['object_type'], "Выберите тип объекта из предложенных:",
                    KEYBOARDS['object_type']),
                2: (lambda: answer not in PRICES['work']['urgency'], "Выберите срочность из предложенных:",
                    KEYBOARDS['urgency'])
            }
        }

        if current in validation_errors[request_type]:
            condition, error_text, keyboard = validation_errors[request_type][current]
            if condition():
                await message.answer(error_text, reply_markup=keyboard)
                return

        data['answers'].append(answer)

        if current < len(questions) - 1:
            data['current_question'] += 1
            next_question = questions[data['current_question']]

            # Определение клавиатуры для следующего вопроса
            keyboard_mapping = {
                1: {'work': KEYBOARDS['object_type']},
                2: {True: KEYBOARDS['urgency']}
            }
            keyboard = keyboard_mapping.get(data['current_question'], {}).get(
                request_type if data['current_question'] == 1 else True,
                KEYBOARDS['cancel']
            )

            await message.answer(next_question, reply_markup=keyboard)
        else:
            data['price_report'] = await generate_price_report(request_type, data)
            await Form.confirm.set()
            await message.answer(data['price_report'], parse_mode="Markdown")
            await message.answer("Подтвердить запрос?", reply_markup=confirm_kb)


@dp.callback_query_handler(lambda c: c.data in ['confirm_yes', 'confirm_no'], state=Form.confirm)
async def handle_confirmation(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()  # Важно: подтверждаем callback сразу

        if not SPECIALIST_CHAT_ID:
            logging.error("SPECIALIST_CHAT_ID не настроен")
            await callback.message.answer("⚠ Ошибка конфигурации сервера")
            return

        async with state.proxy() as data:
            if callback.data == 'confirm_yes':
                req_num = get_next_request_number()
                username = callback.from_user.username or "N/A"

                try:
                    cost = data['price_report'].split('Итого: ')[1].split('₽')[0].strip()
                except Exception as e:
                    logging.error(f"Ошибка извлечения стоимости: {str(e)}")
                    cost = "не определена"

                report = (
                        f"📋 Запрос №{req_num}\n"
                        f"Тип: {'Учебный' if data['request_type'] == 'study' else 'Рабочий'}\n"
                        f"Пользователь: @{username}\n"
                        f"ID: {callback.from_user.id}\n\n"
                        + "\n".join(f"{q}: {a}" for q, a in zip(data['questions'], data['answers']))
                        + f"\n\nРасчетная стоимость: {cost}₽"
                )

                await bot.send_message(
                    chat_id=SPECIALIST_CHAT_ID,
                    text=report,
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup().add(
                        types.InlineKeyboardButton(
                            "💬 Связаться",
                            url=f"tg://user?id={callback.from_user.id}"
                        )
                    )
                )

                await callback.message.edit_reply_markup(None)  # Удаляем инлайн-кнопки
                await callback.message.answer(
                    f"✅ Запрос №{req_num} принят! Ожидайте ответа специалиста.\n"
                    "⚠️ Помните: консультация не заменяет официальное проектирование.",
                    reply_markup=KEYBOARDS['new_request']
                )
            else:
                await callback.message.edit_reply_markup(None)
                await callback.message.answer(
                    "❌ Запрос отменен",
                    reply_markup=KEYBOARDS['new_request']
                )
    except Exception as e:
        logging.error(f"Ошибка обработки подтверждения: {str(e)}")
        await callback.message.answer("⚠ Произошла ошибка, попробуйте позже")
    finally:
        await state.finish()


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