"""
VoltHomeBot — главный файл.
Webhook для Timeweb + авто-фолбэк в long polling.
Услуги:
1) Чертёж схемы (подтипы), 2) Консультация по расчёту нагрузок (подтипы),
3) Полная консультация, 4) Другое.
"""

import os
import logging
import random
import asyncio
from typing import List, Tuple, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from dotenv import load_dotenv

# -------------------- ENV --------------------
load_dotenv()

def _bool_env(name: str, default: bool = False) -> bool:
    val = (os.getenv(name) or "").strip().lower()
    if val in ("1", "true", "yes", "y", "on"):
        return True
    if val in ("0", "false", "no", "n", "off"):
        return False
    return default

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения.")

try:
    DESIGNER_CHAT_ID = int((os.getenv("DESIGNER_CHAT_ID") or "0").strip())
except ValueError:
    raise RuntimeError("DESIGNER_CHAT_ID должен быть целым числом.")
if not DESIGNER_CHAT_ID:
    raise RuntimeError("DESIGNER_CHAT_ID не задан в переменных окружения.")

# Webhook / Server
WEBHOOK_HOST = (os.getenv("WEBHOOK_HOST") or "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8000"))
USE_POLLING = _bool_env("USE_POLLING", default=False)
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else None

# -------------------- BOT / DP --------------------
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.MARKDOWN)  # оставим Markdown для простоты
dp = Dispatcher(bot, storage=MemoryStorage())

# -------------------- MISC --------------------
REQUEST_COUNTER_FILE = "request_counter.txt"
WELCOME_PHRASES = [
    "Снова к нам? Отлично! Давайте новую заявку!",
    "Рады видеть вас снова! Готовы начать?",
    "Новая заявка — новые возможности! Поехали!",
]

# -------------------- KEYBOARDS --------------------
# Главное меню услуг
services_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton("1⃣ Чертёж схемы")],
        [types.KeyboardButton("2⃣ Консультация по расчёту нагрузок")],
        [types.KeyboardButton("3⃣ Полная консультация")],
        [types.KeyboardButton("4⃣ Другое")],
    ],
    resize_keyboard=True,
)

# Подменю «Чертёж схемы»
draft_sub_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton("Однолинейная схема")],
        [types.KeyboardButton("Монтажная схема")],
        [types.KeyboardButton("Другое (чертёж)")],
        [types.KeyboardButton("Отмена заявки")],
    ],
    resize_keyboard=True,
)

# Подменю «Расчёт нагрузок»
loads_sub_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton("Подбор автоматов/УЗО")],
        [types.KeyboardButton("Аудит существующего проекта")],
        [types.KeyboardButton("Распределение по фазам")],
        [types.KeyboardButton("Другое (нагрузки)")],
        [types.KeyboardButton("Отмена заявки")],
    ],
    resize_keyboard=True,
)

cancel_request_kb = types.ReplyKeyboardMarkup(
    keyboard=[[types.KeyboardButton("Отмена заявки")]],
    resize_keyboard=True,
)

attachments_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton("Готово")],
        [types.KeyboardButton("Отмена заявки")],
    ],
    resize_keyboard=True,
)

new_request_kb = types.ReplyKeyboardMarkup(
    keyboard=[[types.KeyboardButton("📝 Новая заявка!")]],
    resize_keyboard=True,
)

object_type_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton("Жилое"), types.KeyboardButton("Коммерческое")],
        [types.KeyboardButton("Промышленное"), types.KeyboardButton("Другое")],
        [types.KeyboardButton("Отмена заявки")],
    ],
    resize_keyboard=True,
)

urgency_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton("Срочно 24 часа")],
        [types.KeyboardButton("В течении 3-5 дней")],
        [types.KeyboardButton("Стандартно 7 дней")],
        [types.KeyboardButton("Отмена заявки")],
    ],
    resize_keyboard=True,
)

# Инлайн «да/нет»
def yn_kb(yes_cb: str, no_cb: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Да", callback_data=yes_cb),
           types.InlineKeyboardButton("Нет", callback_data=no_cb))
    return kb

# -------------------- FSM --------------------
class Form(StatesGroup):
    service_category = State()   # draft | loads | full | other
    sub_category = State()       # уточнение для draft/loads
    object_type = State()
    area = State()
    rooms = State()
    groups_count = State()
    has_list_of_groups = State()
    need_inrush = State()
    need_mount_scheme = State()
    free_text = State()
    attachments = State()
    urgency = State()
    confirm = State()

# -------------------- PRICING --------------------
URGENCY_COEFFICIENTS = {
    "Срочно 24 часа": 1.5,
    "В течении 3-5 дней": 1.2,
    "Стандартно 7 дней": 1.0,
}

# Базовые прайсы — набросок, подстрой по факту
DRAFT_BASE = {
    "draft_oneline": 7000,
    "draft_mount": 9000,
    "draft_other": 8000,
}
LOADS_BASE = {
    "loads_pick": 6000,
    "loads_audit": 8000,
    "loads_phases": 7000,
    "loads_other": 6500,
}
FULL_BASE = 15000  # базовый за «полную консультацию»

# -------------------- COUNTER --------------------
def init_request_counter() -> None:
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

# -------------------- CALCULATORS --------------------
def _urgency_coeff(state_data: dict) -> float:
    return URGENCY_COEFFICIENTS.get(state_data.get("urgency", "Стандартно 7 дней"), 1.0)

def calc_price_draft(state_data: dict) -> str:
    sub = state_data.get("sub_category", "draft_other")
    base = DRAFT_BASE.get(sub, DRAFT_BASE["draft_other"])
    # Лёгкая модификация по площади
    area = float(state_data.get("area") or 0)
    k_area = 1.0
    if area > 80: k_area = 1.15
    if area > 150: k_area = 1.3
    # Надбавка при отсутствии перечня групп
    if not state_data.get("has_list_of_groups", False):
        base += 1500
    total = int(base * k_area * _urgency_coeff(state_data))
    lines = [
        "📐 *Предварительный расчёт (чертёж):*",
        f"- Подтип: {sub.replace('_', ' ')}",
        f"- Площадь: {int(area)} м²",
        f"- Перечень групп: {'есть' if state_data.get('has_list_of_groups') else 'нет'}",
        f"- Срочность: {state_data.get('urgency')} (x{_urgency_coeff(state_data)})",
        f"- Ориентировочная стоимость: {total:,} руб.",
        "\n_Итог зависит от состава задания и материалов._",
    ]
    return "\n".join(lines).replace(",", " ")

def calc_price_loads(state_data: dict) -> str:
    sub = state_data.get("sub_category", "loads_other")
    base = LOADS_BASE.get(sub, LOADS_BASE["loads_other"])
    area = float(state_data.get("area") or 0)
    groups = int(state_data.get("groups_count") or 0)
    # простые коэффициенты
    k_area = 1.0 + min(area, 300) / 1000.0       # до +0.3
    k_groups = 1.0 + min(groups, 40) / 200.0     # до +0.2
    if state_data.get("need_inrush"):
        base += 1000
    total = int(base * k_area * k_groups * _urgency_coeff(state_data))
    lines = [
        "🔌 *Предварительный расчёт (нагрузки):*",
        f"- Подтип: {sub.replace('_', ' ')}",
        f"- Площадь: {int(area)} м², групп: {groups}",
        f"- Пусковые токи: {'учитывать' if state_data.get('need_inrush') else 'нет'}",
        f"- Срочность: {state_data.get('urgency')} (x{_urgency_coeff(state_data)})",
        f"- Ориентировочная стоимость: {total:,} руб.",
        "\n_Окончательная стоимость уточняется после анализа входных данных._",
    ]
    return "\n".join(lines).replace(",", " ")

def calc_price_full(state_data: dict) -> str:
    base = FULL_BASE
    area = float(state_data.get("area") or 0)
    rooms = int(state_data.get("rooms") or 0)
    if state_data.get("need_mount_scheme"):
        base += 3000
    # коэффициенты
    k_area = 1.0 + min(area, 300) / 800.0    # до +0.375
    k_rooms = 1.0 + min(rooms, 20) / 100.0   # до +0.2
    total = int(base * k_area * k_rooms * _urgency_coeff(state_data))
    lines = [
        "🧩 *Предварительный расчёт (полная консультация):*",
        f"- Площадь: {int(area)} м², помещений: {rooms}",
        f"- Монтажная схема: {'нужна' if state_data.get('need_mount_scheme') else 'не нужна'}",
        f"- Срочность: {state_data.get('urgency')} (x{_urgency_coeff(state_data)})",
        f"- Ориентировочная стоимость: {total:,} руб.",
        "\n_Итоговая смета формируется после детализации задания._",
    ]
    return "\n".join(lines).replace(",", " ")

# -------------------- HANDLERS --------------------
@dp.message_handler(lambda m: m.text == "Отмена заявки", state="*")
async def cancel_request(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("❌ Заявка отменена", reply_markup=new_request_kb)

@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    await Form.service_category.set()
    await message.answer(
        "🔌 Добро пожаловать в *VoltHome (Бета)*!\n\n"
        "Какая услуга вам требуется?",
        reply_markup=services_kb,
    )

@dp.message_handler(lambda m: m.text == "📝 Новая заявка!")
async def new_request(message: types.Message):
    await Form.service_category.set()
    await message.answer(random.choice(WELCOME_PHRASES), reply_markup=services_kb)

# --- 1) Выбор услуги ---
@dp.message_handler(state=Form.service_category)
async def choose_service(message: types.Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt.startswith("1"):  # Чертёж
        await state.update_data(service_category="draft", attachments=[])
        await Form.sub_category.set()
        await message.answer("Уточните тип чертежа:", reply_markup=draft_sub_kb)
    elif txt.startswith("2"):  # Нагрузки
        await state.update_data(service_category="loads", attachments=[])
        await Form.sub_category.set()
        await message.answer("Какой тип консультации по нагрузкам?", reply_markup=loads_sub_kb)
    elif txt.startswith("3"):  # Полная
        await state.update_data(service_category="full", attachments=[])
        await Form.object_type.set()
        await message.answer("Выберите тип объекта:", reply_markup=object_type_kb)
    elif txt.startswith("4"):  # Другое
        await state.update_data(service_category="other", attachments=[])
        await Form.free_text.set()
        await message.answer("Опишите кратко, что требуется:", reply_markup=cancel_request_kb)
    else:
        await message.answer("Пожалуйста, выберите один из пунктов меню выше.", reply_markup=services_kb)

# --- 2a) Подтип «Чертёж» ---
@dp.message_handler(state=Form.sub_category)
async def choose_subcategory(message: types.Message, state: FSMContext):
    data = await state.get_data()
    svc = data.get("service_category")
    txt = (message.text or "").strip()

    if svc == "draft":
        if txt == "Однолинейная схема":
            await state.update_data(sub_category="draft_oneline")
        elif txt == "Монтажная схема":
            await state.update_data(sub_category="draft_mount")
        elif txt == "Другое (чертёж)":
            await state.update_data(sub_category="draft_other")
        else:
            await message.answer("Выберите один из вариантов подтипа чертежа.", reply_markup=draft_sub_kb)
            return
        await Form.object_type.set()
        await message.answer("Выберите тип объекта:", reply_markup=object_type_kb)
        return

    if svc == "loads":
        if txt == "Подбор автоматов/УЗО":
            await state.update_data(sub_category="loads_pick")
        elif txt == "Аудит существующего проекта":
            await state.update_data(sub_category="loads_audit")
        elif txt == "Распределение по фазам":
            await state.update_data(sub_category="loads_phases")
        elif txt == "Другое (нагрузки)":
            await state.update_data(sub_category="loads_other")
        else:
            await message.answer("Выберите один из вариантов консультации по нагрузкам.", reply_markup=loads_sub_kb)
            return
        await Form.object_type.set()
        await message.answer("Выберите тип объекта:", reply_markup=object_type_kb)
        return

    # если сюда попали — значит ветка «full/other» не должна была заходить в sub_category
    await message.answer("Этот шаг здесь не требуется. Начнём заново?", reply_markup=new_request_kb)
    await state.finish()

# --- 3) Тип объекта ---
@dp.message_handler(state=Form.object_type)
async def ask_object_type(message: types.Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt not in {"Жилое", "Коммерческое", "Промышленное", "Другое"}:
        await message.answer("Пожалуйста, выберите вариант на клавиатуре.", reply_markup=object_type_kb)
        return

    if txt == "Другое":
        await Form.free_text.set()
        await message.answer("Введите свой вариант типа объекта:", reply_markup=cancel_request_kb)
        # пометим, что это «другое (тип объекта)»
        await state.update_data(_awaiting_custom_object=True)
        return

    await state.update_data(object_type=txt)
    await Form.area.set()
    await message.answer("Укажите площадь объекта (м²):", reply_markup=cancel_request_kb)

# --- «Другое»: либо свободное ТЗ, либо кастомный тип объекта ---
@dp.message_handler(state=Form.free_text, content_types=types.ContentType.TEXT)
async def free_text_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    txt = (message.text or "").strip()

    # если ждали «кастомный тип объекта»
    if data.get("_awaiting_custom_object"):
        await state.update_data(object_type=f"Другое ({txt})", _awaiting_custom_object=False)
        await Form.area.set()
        await message.answer("Укажите площадь объекта (м²):", reply_markup=cancel_request_kb)
        return

    # иначе это ветка «service_category=other»
    await state.update_data(free_text=txt)
    await Form.attachments.set()
    await message.answer(
        "Прикрепите фото/план/ТЗ (по одному сообщению). Когда закончите — нажмите «Готово».",
        reply_markup=attachments_kb,
    )

# --- 4) Площадь ---
@dp.message_handler(state=Form.area, content_types=types.ContentType.TEXT)
async def ask_area(message: types.Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        area = float(raw)
        if area <= 0:
            raise ValueError
    except Exception:
        await message.answer("🔢 Введите положительное число (м²).", reply_markup=cancel_request_kb)
        return

    await state.update_data(area=area)
    data = await state.get_data()
    svc = data.get("service_category")

    if svc == "draft":
        # есть ли перечень групп?
        await Form.has_list_of_groups.set()
        await message.answer("Есть ли перечень групп/щит?", reply_markup=yn_kb("groups_yes", "groups_no"))
    elif svc == "loads":
        await Form.groups_count.set()
        await message.answer("Сколько электрических групп планируется (примерно)?", reply_markup=cancel_request_kb)
    elif svc == "full":
        await Form.rooms.set()
        await message.answer("Сколько помещений (примерно)?", reply_markup=cancel_request_kb)
    else:
        # не должно сюда попадать
        await message.answer("Что-то пошло не так. Начнём заново?", reply_markup=new_request_kb)
        await state.finish()

# --- 5a) Перечень групп (draft) ---
@dp.callback_query_handler(lambda c: c.data in ("groups_yes", "groups_no"), state=Form.has_list_of_groups)
async def groups_list_cb(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(has_list_of_groups=(callback.data == "groups_yes"))
    await Form.attachments.set()
    await callback.message.answer(
        "Прикрепите фото/план/ТЗ (по одному сообщению). Когда закончите — нажмите «Готово».",
        reply_markup=attachments_kb,
    )

# --- 5b) Кол-во групп (loads) ---
@dp.message_handler(state=Form.groups_count)
async def groups_count_handler(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("🔢 Введите целое число (0 или больше).", reply_markup=cancel_request_kb)
        return
    await state.update_data(groups_count=int(raw))
    await Form.need_inrush.set()
    await message.answer("Учитывать пусковые токи?", reply_markup=yn_kb("inrush_yes", "inrush_no"))

@dp.callback_query_handler(lambda c: c.data in ("inrush_yes", "inrush_no"), state=Form.need_inrush)
async def inrush_cb(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(need_inrush=(callback.data == "inrush_yes"))
    await Form.attachments.set()
    await callback.message.answer(
        "Прикрепите фото/план/ТЗ (по одному сообщению). Когда закончите — нажмите «Готово».",
        reply_markup=attachments_kb,
    )

# --- 5c) Кол-во помещений (full) ---
@dp.message_handler(state=Form.rooms)
async def rooms_handler(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("🔢 Введите целое число (0 или больше).", reply_markup=cancel_request_kb)
        return
    await state.update_data(rooms=int(raw))
    await Form.need_mount_scheme.set()
    await message.answer("Нужна ли монтажная схема?", reply_markup=yn_kb("needmount_yes", "needmount_no"))

@dp.callback_query_handler(lambda c: c.data in ("needmount_yes", "needmount_no"), state=Form.need_mount_scheme)
async def need_mount_cb(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(need_mount_scheme=(callback.data == "needmount_yes"))
    await Form.attachments.set()
    await callback.message.answer(
        "Прикрепите фото/план/ТЗ (по одному сообщению). Когда закончите — нажмите «Готово».",
        reply_markup=attachments_kb,
    )

# --- 8) Приём вложений ---
@dp.message_handler(lambda m: m.text == "Готово", state=Form.attachments)
async def attachments_done(message: types.Message, state: FSMContext):
    await Form.urgency.set()
    await message.answer("⏱️ Выберите срочность выполнения консультации:", reply_markup=urgency_kb)

@dp.message_handler(content_types=[types.ContentType.PHOTO, types.ContentType.DOCUMENT], state=Form.attachments)
async def collect_attachments(message: types.Message, state: FSMContext):
    data = await state.get_data()
    files: List[Tuple[str, str]] = list(data.get("attachments", []))
    if len(files) >= 10:
        await message.answer("Достаточно вложений. Нажмите «Готово», чтобы продолжить.")
        return
    if message.photo:
        files.append(("photo", message.photo[-1].file_id))
    elif message.document:
        files.append(("document", message.document.file_id))
    await state.update_data(attachments=files)
    await message.answer(f"Добавлено вложений: {len(files)}. Можно отправить ещё или нажать «Готово».")

@dp.message_handler(state=Form.attachments)
async def attachments_other_text(message: types.Message, state: FSMContext):
    await message.answer("Пришлите фото/документ или нажмите «Готово».", reply_markup=attachments_kb)

# --- 9) Срочность ---
@dp.message_handler(state=Form.urgency)
async def choose_urgency(message: types.Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt not in URGENCY_COEFFICIENTS:
        await message.answer("Пожалуйста, выберите вариант срочности на клавиатуре.", reply_markup=urgency_kb)
        return
    await state.update_data(urgency=txt)

    data = await state.get_data()
    svc = data.get("service_category")
    if svc == "draft":
        price_report = calc_price_draft(data)
    elif svc == "loads":
        price_report = calc_price_loads(data)
    elif svc == "full":
        price_report = calc_price_full(data)
    else:  # other
        # простой отчёт без калькуляции
        price_report = (
            "📝 *Предварительная оценка:*\n"
            "- Услуга: Другое (по описанию)\n"
            f"- Срочность: {data.get('urgency')} (x{_urgency_coeff(data)})\n"
            "_Стоимость будет рассчитана после ознакомления с ТЗ._"
        )

    await state.update_data(price_report=price_report)
    await Form.confirm.set()
    confirm_kb = types.InlineKeyboardMarkup().row(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_yes"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="confirm_no"),
    )
    await message.answer(price_report)
    await message.answer("Подтвердить заявку?", reply_markup=confirm_kb)

# --- 10) Подтверждение и отправка ---
@dp.callback_query_handler(lambda c: c.data in ("confirm_yes", "confirm_no"), state=Form.confirm)
async def confirm_cb(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "confirm_no":
        await state.finish()
        await callback.message.answer("❌ Заявка отменена.", reply_markup=new_request_kb)
        return

    req_num = get_next_request_number()
    data = await state.get_data()
    username = f"@{callback.from_user.username}" if callback.from_user.username else "N/A"

    # заголовок
    lines = [
        f"📋 *Новая заявка! №{req_num}*",
        f"👤 {callback.from_user.full_name}",
        f"🆔 {callback.from_user.id} | 📧 {username}",
        f"Услуга: {data.get('service_category')} | Подтип: {data.get('sub_category', '—')}",
        f"Тип объекта: {data.get('object_type', '—')}",
        f"Площадь: {int(float(data.get('area', 0) or 0))} м²",
    ]

    # ветвенные поля
    if data.get("service_category") == "loads":
        lines += [
            f"Групп: {data.get('groups_count', '—')}",
            f"Пусковые токи: {'да' if data.get('need_inrush') else 'нет'}",
        ]
    if data.get("service_category") == "full":
        lines += [
            f"Помещений: {data.get('rooms', '—')}",
            f"Монтажная схема: {'нужна' if data.get('need_mount_scheme') else 'не нужна'}",
        ]
    if data.get("service_category") == "draft":
        lines += [f"Перечень групп: {'есть' if data.get('has_list_of_groups') else 'нет'}"]
    if data.get("service_category") == "other" and data.get("free_text"):
        lines += [f"Описание: {data.get('free_text')}"]

    lines += [
        f"Срочность: {data.get('urgency', '—')}",
        "",
        "💬 *Детали расчёта:*",
        data.get("price_report", "—"),
    ]
    text = "\n".join(lines)

    # отправка дизайнеру
    try:
        await bot.send_message(
            chat_id=DESIGNER_CHAT_ID,
            text=text,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("💬 Написать клиенту", url=f"tg://user?id={callback.from_user.id}")
            ),
        )
        for kind, fid in data.get("attachments", []):
            if kind == "photo":
                await bot.send_photo(DESIGNER_CHAT_ID, fid, caption=f"Заявка №{req_num}: фото")
            else:
                await bot.send_document(DESIGNER_CHAT_ID, fid, caption=f"Заявка №{req_num}: документ")
    except Exception as e:
        logging.exception("Ошибка отправки заявки специалисту: %s", e)

    await state.finish()
    await callback.message.answer(
        f"✅ Ваша заявка принята! Номер №{req_num}\n"
        "Наш специалист свяжется с вами в ближайшее время.\n"
        "Помните, консультация не заменяет проектирования!",
        reply_markup=new_request_kb,
    )

# -------------------- START/SHUTDOWN --------------------
async def try_set_webhook() -> bool:
    if not WEBHOOK_URL:
        logging.error("WEBHOOK_HOST не задан — пропускаю установку вебхука.")
        return False
    from aiogram.utils.exceptions import TelegramAPIError
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(WEBHOOK_URL)
        info = await bot.get_webhook_info()
        logging.info("Webhook установлен: %s (pending=%s)", info.url, info.pending_update_count)
        return True
    except TelegramAPIError as e:
        logging.error("Не удалось поставить вебхук: %s", e)
        return False

def start_as_webhook():
    from aiogram.utils.executor import start_webhook
    logging.info("Запускаю aiohttp-сервер webhook на %s:%s", WEBAPP_HOST, WEBAPP_PORT)
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=lambda _: init_request_counter(),
        on_shutdown=None,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
    )

def start_as_polling():
    from aiogram.utils.executor import start_polling
    logging.info("Запускаю long polling (skip_updates=True)")
    init_request_counter()
    start_polling(dp, skip_updates=True)

# -------------------- ENTRY --------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    # логгер aiogram чуть приглушим
    logging.getLogger("aiogram").setLevel(logging.INFO)

    # маленькая проверка токена
    me = asyncio.get_event_loop().run_until_complete(bot.get_me())
    logging.info("Bot: %s", me.username)

    if USE_POLLING:
        start_as_polling()
    else:
        ok = asyncio.get_event_loop().run_until_complete(try_set_webhook())
        if ok:
            start_as_webhook()
        else:
            logging.info("Фолбэк в long polling из-за проблем с вебхуком.")
            start_as_polling()