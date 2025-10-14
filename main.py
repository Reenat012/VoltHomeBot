"""
Главный файл Telegram-бота с интеграцией Webhook для Timeweb
MVP (Бета): флажок "нужен чертёж", приём вложений, расчёт и отправка заявки.
"""

import os
import logging
import random

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.executor import start_webhook
from dotenv import load_dotenv

# ---------- ENV ----------
load_dotenv()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан (env).")

try:
    DESIGNER_CHAT_ID = int((os.getenv("DESIGNER_CHAT_ID") or "0").strip())
except ValueError:
    raise RuntimeError("DESIGNER_CHAT_ID должен быть целым числом.")

if not DESIGNER_CHAT_ID:
    raise RuntimeError("DESIGNER_CHAT_ID не задан (env).")

# ---------- Webhook config ----------
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://reenat012-volthomebot-2d67.twc1.net").rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8000"))

# ---------- Bot / Dispatcher ----------
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.MARKDOWN)  # сохраним Markdown как у тебя
dp = Dispatcher(bot, storage=MemoryStorage())

# ---------- Misc ----------
REQUEST_COUNTER_FILE = "request_counter.txt"
WELCOME_PHRASES = [
    "Снова к нам? Отлично! Давайте новую заявку!",
    "Рады видеть вас снова! Готовы начать?",
    "Новая заявка — новые возможности! Поехали!"
]

# ---------- Keyboards ----------
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

attachments_kb = types.ReplyKeyboardMarkup(
    [[types.KeyboardButton("Готово")], [types.KeyboardButton("Отмена заявки")]],
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
    types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no"),
)

need_drawing_kb = types.InlineKeyboardMarkup().row(
    types.InlineKeyboardButton("📐 Нужен чертёж", callback_data="drawing_yes"),
    types.InlineKeyboardButton("Без чертежа", callback_data="drawing_no"),
)

# ---------- Questions ----------
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

# ---------- States ----------
class Form(StatesGroup):
    service_type = State()
    answers = State()
    building_type = State()
    custom_building = State()
    need_drawing = State()   # Новый шаг
    attachments = State()    # Новый шаг
    urgency = State()
    confirm = State()

# ---------- Pricing ----------
URGENCY_COEFFICIENTS = {
    "Срочно 24 часа": 1.5,
    "В течении 3-5 дней": 1.2,
    "Стандартно 7 дней": 1.0
}

TECH_BASE_PRICES = {
    1: (5000, 10000),
    2: (10000, 15000),
    3: (15000, 25000),
    4: (25000, None),
}

STUDY_BASE_PRICES = {
    1: (3000, 5000),
    2: (5000, 8000),
    3: (8000, None),
}

# ---------- Counter helpers ----------
def init_request_counter():
    try:
        if not os.path.exists(REQUEST_COUNTER_FILE):
            with open(REQUEST_COUNTER_FILE, "w") as f:
                f.write("0")
            logging.info("Счётчик заявок инициализирован.")
    except Exception as e:
        logging.error(f"Ошибка создания счётчика: {e}")

def get_next_request_number() -> int:
    try:
        with open(REQUEST_COUNTER_FILE, "r+") as f:
            try:
                counter = int(f.read().strip() or 0)
            except ValueError:
                counter = 0
                logging.warning("Сброс счётчика заявок.")
            counter += 1
            f.seek(0)
            f.write(str(counter))
            return counter
    except Exception as e:
        logging.error(f"Ошибка счётчика: {e}")
        return random.randint(1000, 9999)

# ---------- Price calculators ----------
def calculate_tech_consultation(data: dict) -> str:
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

        base_price = int((price_range[0] + (price_range[1] or int(price_range[0] * 1.5))) / 2)
        total = int(base_price * complexity)

        urgency_coeff = URGENCY_COEFFICIENTS.get(data.get('urgency', "Стандартно 7 дней"), 1.0)
        total_with_urgency = int(total * urgency_coeff)

        report = [
            "🔧 *Предварительный расчёт стоимости консультации:*",
            f"- Площадь объекта: {area} м²",
            f"- Тип объекта: {building}",
            f"- Срочность выполнения: {data.get('urgency', 'Стандартно 7 дней')} (x{urgency_coeff})",
            f"- Ориентировочная стоимость: {total_with_urgency:,} руб.",
            "\n_Окончательная стоимость может быть уточнена после обсуждения деталей_",
        ]
        return "\n".join(report).replace(",", " ")
    except Exception as e:
        logging.exception("Ошибка расчёта (tech): %s", e)
        return "❌ Не удалось рассчитать стоимость. Мы свяжемся с вами для уточнения деталей."

def calculate_study_consultation(data: dict) -> str:
    try:
        pages = int(data['answers'][1])
        if pages <= 20:
            price = STUDY_BASE_PRICES[1][0]
        elif pages <= 40:
            price = int((STUDY_BASE_PRICES[2][0] + STUDY_BASE_PRICES[2][1]) / 2)
        else:
            price = int(STUDY_BASE_PRICES[3][0] * 1.2)

        urgency_coeff = URGENCY_COEFFICIENTS.get(data.get('urgency', "Стандартно 7 дней"), 1.0)
        total_price = int(price * urgency_coeff)

        report = [
            "📚 *Стоимость учебной консультации:*",
            f"- Тема: {data['answers'][0]}",
            f"- Объём: {pages} стр.",
            f"- Срочность выполнения: {data.get('urgency', 'Стандартно 7 дней')} (x{urgency_coeff})",
            f"- Ориентировочная стоимость: {total_price:,} руб.",
            "\n_Окончательная стоимость может быть уточнена после обсуждения деталей_",
        ]
        return "\n".join(report).replace(",", " ")
    except Exception as e:
        logging.exception("Ошибка расчёта (study): %s", e)
        return "❌ Не удалось рассчитать стоимость. Мы свяжемся с вами для уточнения деталей."

# ---------- Handlers ----------
@dp.message_handler(lambda m: m.text == "Отмена заявки", state="*")
async def cancel_request(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ Заявка отменена", reply_markup=new_request_kb)

@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    await Form.service_type.set()
    await message.answer(
        "🔌 Добро пожаловать в сервис консультаций *VoltHome (Бета)*!\n\n"
        "Функция находится в тестировании — интерфейс и скорость отклика могут меняться.\n\n"
        "Выберите тип консультации:",
        reply_markup=service_type_kb
    )

@dp.message_handler(lambda m: m.text == "📝 Новая заявка!")
async def new_request(message: types.Message):
    await Form.service_type.set()
    await message.answer(random.choice(WELCOME_PHRASES), reply_markup=service_type_kb)

@dp.message_handler(state=Form.service_type)
async def process_type(message: types.Message, state: FSMContext):
    if message.text not in ["📚 Учебная консультация", "🏗️ Рабочая консультация"]:
        await message.answer("Пожалуйста, используйте кнопки для выбора.")
        return

    svc = "study" if "Учебная" in message.text else "tech"
    questions = STUDY_QUESTIONS if svc == "study" else TECH_QUESTIONS
    await state.update_data(service_type=svc, questions=questions, current_question=0, answers=[], attachments=[])

    await Form.answers.set()
    await message.answer(questions[0], reply_markup=cancel_request_kb)

@dp.message_handler(state=Form.answers)
async def process_answers(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current = data.get("current_question", 0)
    svc = data.get("service_type", "tech")
    questions = data.get("questions", [])
    answers = data.get("answers", [])

    answer = message.text.strip()

    # Валидации
    if svc == "tech":
        if current == 0 and not answer.replace(".", "", 1).isdigit():
            await message.answer("🔢 Введите число для площади!", reply_markup=cancel_request_kb)
            return
        if current == 1 and not answer.isdigit():
            await message.answer("🔢 Введите целое число помещений!", reply_markup=cancel_request_kb)
            return
    if svc == "study" and current == 1 and not answer.isdigit():
        await message.answer("🔢 Введите число страниц!", reply_markup=cancel_request_kb)
        return

    answers.append(answer)
    await state.update_data(answers=answers)

    # После 2-го ответа показываем "нужен ли чертёж"
    if (svc in ("tech", "study")) and current == 1:
        await Form.need_drawing.set()
        await message.answer(
            "Нужна ли консультация с подготовкой *чертежа схемы щита*?",
            reply_markup=need_drawing_kb
        )
        await state.update_data(current_question=current + 1)  # чтобы далее вернуться к цепочке
        return

    # Ветка "тип объекта" для tech после вопроса о помещениях
    if svc == "tech" and current == 1:
        await Form.building_type.set()
        await message.answer("🏢 Выберите тип объекта:", reply_markup=building_type_kb)
        return

    # Идём по вопросам дальше
    current += 1
    if current < len(questions):
        await state.update_data(current_question=current)
        await message.answer(questions[current], reply_markup=cancel_request_kb)
    else:
        # Закончили блок вопросов → срочность
        await Form.urgency.set()
        await message.answer("⏱️ Выберите срочность выполнения консультации:", reply_markup=urgency_kb)

@dp.callback_query_handler(lambda c: c.data in ("drawing_yes", "drawing_no"), state=Form.need_drawing)
async def choose_drawing(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(need_drawing=(callback.data == "drawing_yes"))

    # Переходим к приёму вложений
    await Form.attachments.set()
    await callback.message.answer(
        "Прикрепите фото/документы (план, ТЗ, скриншоты) — по одному сообщению.\n"
        "Когда закончите, нажмите «Готово».",
        reply_markup=attachments_kb
    )

@dp.message_handler(lambda m: m.text == "Готово", state=Form.attachments)
async def attachments_done(message: types.Message, state: FSMContext):
    # После вложений идём к срочности
    await Form.urgency.set()
    await message.answer("⏱️ Выберите срочность выполнения консультации:", reply_markup=urgency_kb)

@dp.message_handler(content_types=[types.ContentType.PHOTO, types.ContentType.DOCUMENT], state=Form.attachments)
async def collect_attachments(message: types.Message, state: FSMContext):
    data = await state.get_data()
    files = list(data.get("attachments", []))

    if len(files) >= 10:
        await message.answer("Достаточно вложений. Нажмите «Готово», чтобы продолжить.")
        return

    if message.photo:
        fid = message.photo[-1].file_id
        files.append(("photo", fid))
    elif message.document:
        fid = message.document.file_id
        files.append(("document", fid))

    await state.update_data(attachments=files)
    await message.answer(f"Добавлено вложений: {len(files)}. Можно отправить ещё или нажать «Готово».")

@dp.message_handler(state=Form.attachments)
async def attachments_other_text(message: types.Message, state: FSMContext):
    await message.answer("Пришлите фото/документ или нажмите «Готово».", reply_markup=attachments_kb)

@dp.message_handler(state=Form.building_type)
async def process_building(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if message.text == "Другое":
        await Form.custom_building.set()
        await message.answer("📝 Введите свой вариант типа объекта:", reply_markup=cancel_request_kb)
    else:
        answers = data.get("answers", [])
        answers.append(message.text)
        await state.update_data(answers=answers)
        await Form.answers.set()
        cur = data.get("current_question", 0) + 1
        await state.update_data(current_question=cur)
        questions = data.get("questions", [])
        await message.answer(questions[cur], reply_markup=cancel_request_kb)

@dp.message_handler(state=Form.custom_building)
async def process_custom_building(message: types.Message, state: FSMContext):
    data = await state.get_data()
    answers = data.get("answers", [])
    answers.append(f"Другое ({message.text})")
    await state.update_data(answers=answers)
    await Form.answers.set()
    cur = data.get("current_question", 0) + 1
    await state.update_data(current_question=cur)
    questions = data.get("questions", [])
    await message.answer(questions[cur], reply_markup=cancel_request_kb)

@dp.message_handler(state=Form.urgency)
async def process_urgency(message: types.Message, state: FSMContext):
    if message.text not in URGENCY_COEFFICIENTS:
        await message.answer("Пожалуйста, выберите вариант срочности из предложенных кнопок.")
        return

    data = await state.get_data()
    await state.update_data(urgency=message.text)

    # Расчёт
    if data.get("service_type") == "tech":
        price_report = calculate_tech_consultation(await state.get_data())
    else:
        price_report = calculate_study_consultation(await state.get_data())

    await state.update_data(price_report=price_report)
    await Form.confirm.set()
    await message.answer(price_report)
    await message.answer("Подтвердить заявку на консультацию?", reply_markup=confirm_kb)

@dp.callback_query_handler(lambda c: c.data in ["confirm_yes", "confirm_no"], state=Form.confirm)
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "confirm_no":
        await state.finish()
        await callback.message.answer("❌ Заявка отменена.", reply_markup=new_request_kb)
        return

    # confirm_yes
    req_num = get_next_request_number()
    data = await state.get_data()
    username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"

    # Сводка для специалиста
    report_lines = [
        f"📋 *Новая заявка на консультацию! Номер заявки №{req_num}*",
        f"🧪 Канал: VoltHome (Бета)",
        f"👤 Клиент: {callback.from_user.full_name}",
        f"🆔 {callback.from_user.id} | 📧 {username}",
        f"Тип: {'Учебная консультация' if data.get('service_type') == 'study' else 'Рабочая консультация'}",
        f"⏱️ Срочность выполнения: {data.get('urgency', 'Не указана')}",
        ""
    ]

    answers = data.get("answers", [])
    if data.get("service_type") == "tech":
        # ожидаем: 0 — площадь, 1 — помещения, 2/3 — тип/особые требования
        area = answers[0] if len(answers) > 0 else "—"
        rooms = answers[1] if len(answers) > 1 else "—"
        building = answers[2] if len(answers) > 2 else "—"
        requirements = answers[3] if len(answers) > 3 else "—"
        report_lines += [
            f"🏢 Тип объекта: {building}",
            f"📏 Площадь: {area} м²",
            f"🚪 Помещений: {rooms}",
            f"💼 Требования: {requirements}",
            ""
        ]
    else:
        # study: 0 — тема, 1 — объём, 2 — пожелания
        topic = answers[0] if len(answers) > 0 else "—"
        pages = answers[1] if len(answers) > 1 else "—"
        wishes = answers[2] if len(answers) > 2 else "—"
        report_lines += [
            f"📖 Тема: {topic}",
            f"📄 Объём: {pages} стр.",
            f"💡 Пожелания: {wishes}",
            ""
        ]

    # флажок чертежа и вложения
    need_drawing = data.get("need_drawing")
    if need_drawing is not None:
        report_lines.append(f"📐 Чертёж схемы щита: {'нужен' if need_drawing else 'не требуется'}")
    attachments = data.get("attachments", [])
    if attachments:
        report_lines.append(f"📎 Вложения: {len(attachments)} шт.")
    report_lines += ["", "💬 *Детали расчёта стоимости:*", data.get("price_report", "—")]

    report_text = "\n".join(report_lines)

    try:
        # 1) текст
        await bot.send_message(
            chat_id=DESIGNER_CHAT_ID,
            text=report_text,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("💬 Написать клиенту", url=f"tg://user?id={callback.from_user.id}")
            )
        )
        # 2) вложения (если есть)
        for kind, fid in attachments:
            if kind == "photo":
                await bot.send_photo(DESIGNER_CHAT_ID, fid, caption=f"Заявка №{req_num}: фото")
            else:
                await bot.send_document(DESIGNER_CHAT_ID, fid, caption=f"Заявка №{req_num}: документ")
    except Exception as e:
        logging.exception("Ошибка отправки заявки специалисту: %s", e)

    await state.finish()
    await callback.message.answer(
        f"✅ Ваша заявка на консультацию принята! Номер заявки №{req_num}\n"
        "Наш специалист свяжется с вами в ближайшее время.\n"
        "Помните, консультация не заменяет проектирования!",
        reply_markup=new_request_kb
    )

# ---------- Webhook ----------
async def on_startup(dp: Dispatcher):
    init_request_counter()
    await bot.set_webhook(WEBHOOK_URL)
    logging.info("Бот запущен. Webhook: %s", WEBHOOK_URL)

async def on_shutdown(dp: Dispatcher):
    await bot.delete_webhook()
    await dp.storage.close()
    logging.info("Бот остановлен")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from aiogram.utils.executor import start_webhook
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
    )