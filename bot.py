#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот для подбора цветов краски.
Поддерживает RAL Classic, NCS 2050, HTML, Tikkurila, Dulux, Sherwin-Williams.
Поиск осуществляется по всем каталогам одновременно.
"""

import asyncio
import logging
import re
import io
import os
import json
import aiofiles
import numpy as np
import colour
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, WebAppInfo
from aiogram.exceptions import TelegramBadRequest
from colorthief import ColorThief
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

import config
from database import (
    init_db, add_user, save_order, get_new_orders, update_order_status
)

# ==================== Импорт цветовых баз ====================
# Убедитесь, что эти файлы существуют в проекте (даже пустые списки)
from ncs2050_full import NCS_COLORS as NCS2050
from html_colors import HTML_COLORS
try:
    from ral_colors import RAL_COLORS
except ImportError:
    RAL_COLORS = []
try:
    from tikkurila_colors import TIKKURILA_COLORS
except ImportError:
    TIKKURILA_COLORS = []
try:
    from dulux import DULUX_COLORS
except ImportError:
    DULUX_COLORS = []
try:
    from sherwin_williams import SHERWIN_WILLIAMS_COLORS
except ImportError:
    SHERWIN_WILLIAMS_COLORS = []

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== URL для Web App ====================
WEBAPP_URL = "https://luckyqwen.github.io/color-picker-webapp/color_picker.html"

# ==================== Папка с готовыми изображениями ====================
IMAGE_FOLDER = "ncs_images"
os.makedirs(IMAGE_FOLDER, exist_ok=True)

# ==================== Функции создания изображений ====================
def create_color_image(rgb, size=(100, 100)):
    img = Image.new('RGB', size, color=rgb)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

def create_color_image_with_text(rgb, text, size=(100, 100)):
    img = Image.new('RGB', size, color=rgb)
    draw = ImageDraw.Draw(img)
    brightness = rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114
    text_color = (255, 255, 255) if brightness < 128 else (0, 0, 0)
    try:
        font = ImageFont.load_default()
    except:
        font = None
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    position = ((size[0] - text_width) // 2, (size[1] - text_height) // 2)
    draw.text(position, text, fill=text_color, font=font)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

# ==================== Вспомогательные функции для работы с Lab ====================
def rgb_to_lab(rgb):
    rgb_norm = np.array(rgb) / 255.0
    xyz = colour.sRGB_to_XYZ(rgb_norm)
    lab = colour.XYZ_to_Lab(xyz)
    return lab

# Кэши для всех каталогов
ncs_lab_cache = {}
ral_lab_cache = {}
html_lab_cache = {}
tikkurila_lab_cache = {}
dulux_lab_cache = {}
sherwin_williams_lab_cache = {}

def get_lab_for_ncs(color):
    rgb = color['rgb']
    key = tuple(rgb)
    if key not in ncs_lab_cache:
        ncs_lab_cache[key] = rgb_to_lab(rgb)
    return ncs_lab_cache[key]

def get_lab_for_ral(color):
    rgb = color['rgb']
    key = tuple(rgb)
    if key not in ral_lab_cache:
        ral_lab_cache[key] = rgb_to_lab(rgb)
    return ral_lab_cache[key]

def get_lab_for_html(color):
    rgb = color['rgb']
    key = tuple(rgb)
    if key not in html_lab_cache:
        html_lab_cache[key] = rgb_to_lab(rgb)
    return html_lab_cache[key]

def get_lab_for_tikkurila(color):
    rgb = color['rgb']
    key = tuple(rgb)
    if key not in tikkurila_lab_cache:
        tikkurila_lab_cache[key] = rgb_to_lab(rgb)
    return tikkurila_lab_cache[key]

def get_lab_for_dulux(color):
    rgb = color['rgb']
    key = tuple(rgb)
    if key not in dulux_lab_cache:
        dulux_lab_cache[key] = rgb_to_lab(rgb)
    return dulux_lab_cache[key]

def get_lab_for_sherwin_williams(color):
    rgb = color['rgb']
    key = tuple(rgb)
    if key not in sherwin_williams_lab_cache:
        sherwin_williams_lab_cache[key] = rgb_to_lab(rgb)
    return sherwin_williams_lab_cache[key]

def get_top_n_all_lab(target_rgb, n=10):
    target_lab = rgb_to_lab(target_rgb)
    candidates = []
    for c in NCS2050:
        dist = colour.delta_E(get_lab_for_ncs(c), target_lab)
        candidates.append((c, dist, 'ncs'))
    for c in RAL_COLORS:
        dist = colour.delta_E(get_lab_for_ral(c), target_lab)
        candidates.append((c, dist, 'ral'))
    for c in HTML_COLORS:
        dist = colour.delta_E(get_lab_for_html(c), target_lab)
        candidates.append((c, dist, 'html'))
    for c in TIKKURILA_COLORS:
        dist = colour.delta_E(get_lab_for_tikkurila(c), target_lab)
        candidates.append((c, dist, 'tikkurila'))
    for c in DULUX_COLORS:
        dist = colour.delta_E(get_lab_for_dulux(c), target_lab)
        candidates.append((c, dist, 'dulux'))
    for c in SHERWIN_WILLIAMS_COLORS:
        dist = colour.delta_E(get_lab_for_sherwin_williams(c), target_lab)
        candidates.append((c, dist, 'sherwin_williams'))
    candidates.sort(key=lambda x: x[1])
    return candidates[:n]

def get_top_n_all_lab_from_lab(target_lab, n=10):
    candidates = []
    for c in NCS2050:
        dist = colour.delta_E(get_lab_for_ncs(c), target_lab)
        candidates.append((c, dist, 'ncs'))
    for c in RAL_COLORS:
        dist = colour.delta_E(get_lab_for_ral(c), target_lab)
        candidates.append((c, dist, 'ral'))
    for c in HTML_COLORS:
        dist = colour.delta_E(get_lab_for_html(c), target_lab)
        candidates.append((c, dist, 'html'))
    for c in TIKKURILA_COLORS:
        dist = colour.delta_E(get_lab_for_tikkurila(c), target_lab)
        candidates.append((c, dist, 'tikkurila'))
    for c in DULUX_COLORS:
        dist = colour.delta_E(get_lab_for_dulux(c), target_lab)
        candidates.append((c, dist, 'dulux'))
    for c in SHERWIN_WILLIAMS_COLORS:
        dist = colour.delta_E(get_lab_for_sherwin_williams(c), target_lab)
        candidates.append((c, dist, 'sherwin_williams'))
    candidates.sort(key=lambda x: x[1])
    return candidates[:n]

def color_distance_lab(rgb1, rgb2):
    lab1 = rgb_to_lab(rgb1)
    lab2 = rgb_to_lab(rgb2)
    return colour.delta_E(lab1, lab2)

# ==================== Обратные индексы для поиска по коду ====================
ncs_code_to_rgb = {}
for color in NCS2050:
    code = color['code'].upper()
    rgb = color['rgb']
    ncs_code_to_rgb[code] = rgb
    if code.startswith("NCS "):
        without_prefix = code[4:].strip()
        ncs_code_to_rgb[without_prefix] = rgb
        without_space = without_prefix.replace(" ", "")
        ncs_code_to_rgb[without_space] = rgb

ral_code_to_rgb = {}
if isinstance(RAL_COLORS, dict):
    unified_ral = []
    for rgb, codes in RAL_COLORS.items():
        for code in codes:
            unified_ral.append({'code': code, 'rgb': rgb})
    RAL_COLORS = unified_ral
for color in RAL_COLORS:
    code = color['code'].upper()
    rgb = color['rgb']
    ral_code_to_rgb[code] = rgb
    ral_code_to_rgb[f"RAL{code}"] = rgb
    ral_code_to_rgb[f"RAL {code}"] = rgb

html_code_to_rgb = {color['name'].lower(): color['rgb'] for color in HTML_COLORS}

tikkurila_code_to_rgb = {}
for color in TIKKURILA_COLORS:
    code = color['code'].upper()
    rgb = color['rgb']
    tikkurila_code_to_rgb[code] = rgb
    tikkurila_code_to_rgb[f"TIKKURILA{code}"] = rgb
    tikkurila_code_to_rgb[f"TIKKURILA {code}"] = rgb

dulux_code_to_rgb = {}
for color in DULUX_COLORS:
    code = color['code'].upper()
    rgb = color['rgb']
    dulux_code_to_rgb[code] = rgb
    dulux_code_to_rgb[code.replace(' ', '')] = rgb

sherwin_williams_code_to_rgb = {}
for color in SHERWIN_WILLIAMS_COLORS:
    code = color['code'].upper()
    rgb = color['rgb']
    sherwin_williams_code_to_rgb[code] = rgb
    sherwin_williams_code_to_rgb[code.replace(' ', '')] = rgb

# ==================== Состояния ====================
class OrderStates(StatesGroup):
    waiting_photo = State()
    waiting_wood = State()
    waiting_method = State()
    waiting_gloss = State()
    waiting_volume = State()

class CompareStates(StatesGroup):
    waiting_color1 = State()
    waiting_color2 = State()

# ==================== Константы ====================
HTML_NAMES_MAP = {color['name'].lower(): color for color in HTML_COLORS}

def rgb_to_hex(rgb):
    return '#{:02X}{:02X}{:02X}'.format(*rgb)

# ==================== Клавиатуры ====================
def get_main_menu():
    buttons = [
        [InlineKeyboardButton(text="🎨 Подобрать цвет", callback_data="main_pick")],
        [InlineKeyboardButton(text="🔍 Сравнить цвета", callback_data="main_compare")],
        [InlineKeyboardButton(text="📦 Новый заказ", callback_data="main_order")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="main_help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_compare")]
    ])

# ==================== Команда /start ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await add_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )
    await message.answer(
        "👋 Привет! Я универсальный помощник колориста.\n\n"
        "Я умею:\n"
        "• 🎨 Подбирать ближайшие цвета из каталогов RAL, NCS, Dulux, Sherwin-Williams, HTML/HEX, Tikkurila (сразу по всем)\n"
        "• 🔍 Сравнивать два цвета и показывать их разницу\n"
        "• 📦 Принимать заказы на подбор краски (для мебельщиков)\n\n"
        "Выберите действие в меню ниже.",
        reply_markup=get_main_menu()
    )

# ==================== Обработчик кнопки "Назад" ====================
@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text(
            "👋 Выберите действие:",
            reply_markup=get_main_menu()
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer()
        else:
            raise
    await callback.answer()

# ==================== Общий обработчик главного меню ====================
@dp.callback_query(F.data.startswith("main_"))
async def main_menu_handler(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.replace("main_", "")
    if action == "pick":
        await state.clear()
        try:
            await callback.message.edit_text(
                "🎨 Отправьте фото цвета или введите код (RAL/NCS/Tikkurila/Dulux/Sherwin-Williams), RGB, HEX или название цвета.\n"
                "Я найду ближайшие оттенки из всех доступных каталогов.",
                reply_markup=get_main_menu()
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback.answer()
            else:
                raise
    elif action == "compare":
        await state.set_state(CompareStates.waiting_color1)
        try:
            await callback.message.edit_text(
                "🔍 Введите первый цвет в любом формате (код RAL/NCS/Tikkurila/Dulux/Sherwin-Williams, RGB, HEX, название цвета).\n"
                "Или отправьте фото (я возьму доминирующий цвет).\n"
                "Для отмены используйте кнопку ниже.",
                reply_markup=get_cancel_keyboard()
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback.answer()
            else:
                raise
    elif action == "order":
        await state.set_state(OrderStates.waiting_photo)
        try:
            await callback.message.edit_text(
                "📸 Пришлите фото образца (кусок дерева, фасада и т.п.) или нажмите «Пропустить».\n"
                "Для возврата в меню используйте /start.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏭ Пропустить", callback_data="photo_skip")]
                ])
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback.answer()
            else:
                raise
    elif action == "help":
        try:
            await callback.message.edit_text(
                "📸 **Подбор цвета:** Отправьте фото или введите код/название – я покажу 10 ближайших цветов.\n"
                "🔍 **Сравнение:** Введите два цвета (или отправьте фото) – я покажу их разницу.\n"
                "📦 **Новый заказ:** Последовательно укажите фото, породу дерева, способ нанесения, блеск (0-100) и объём.\n\n"
                "По всем вопросам: тел. +375333509356",
                reply_markup=get_main_menu()
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback.answer()
            else:
                raise
    await callback.answer()

# ==================== Вспомогательные функции ====================
def parse_lab_input(text: str):
    text = text.strip().lower()
    if not text.startswith('lab '):
        return None
    parts = text[4:].strip().split()
    if len(parts) != 3:
        return None
    try:
        L = float(parts[0])
        a = float(parts[1])
        b = float(parts[2])
        if 0 <= L <= 100:
            return np.array([L, a, b])
    except ValueError:
        pass
    return None

async def parse_color_input(text: str):
    text_upper = text.strip().upper()
    if text_upper in ncs_code_to_rgb:
        return ncs_code_to_rgb[text_upper]
    if text_upper in ral_code_to_rgb:
        return ral_code_to_rgb[text_upper]
    if text_upper in tikkurila_code_to_rgb:
        return tikkurila_code_to_rgb[text_upper]
    if text_upper in dulux_code_to_rgb:
        return dulux_code_to_rgb[text_upper]
    if text_upper in sherwin_williams_code_to_rgb:
        return sherwin_williams_code_to_rgb[text_upper]
    text_lower = text.lower()
    if text_lower in HTML_NAMES_MAP:
        return HTML_NAMES_MAP[text_lower]['rgb']
    hex_pattern = r'^#?([0-9A-Fa-f]{6})$'
    hex_match = re.match(hex_pattern, text)
    if hex_match:
        hex_code = hex_match.group(1)
        r = int(hex_code[0:2], 16)
        g = int(hex_code[2:4], 16)
        b = int(hex_code[4:6], 16)
        return (r, g, b)
    pattern = r'^(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})$'
    match = re.match(pattern, text)
    if match:
        r, g, b = map(int, match.groups())
        if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
            return (r, g, b)
    return None

def create_color_comparison_image(rgb1, rgb2, dist):
    img = Image.new('RGB', (300, 150), color='white')
    draw = ImageDraw.Draw(img)
    draw.rectangle([(20, 20), (130, 130)], fill=rgb1)
    draw.rectangle([(170, 20), (280, 130)], fill=rgb2)
    text = f"ΔE: {dist:.2f}"
    draw.text((150 - len(text)*3, 140), text, fill='black')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return img_bytes

# ==================== Функция для отправки результатов подбора ====================
async def send_color_results(message: types.Message, rgb, source_description):
    top_colors = get_top_n_all_lab(rgb, n=10)
    if not top_colors:
        await message.answer("❌ Не удалось найти подходящие цвета.", reply_markup=get_main_menu())
        return
    await message.answer(f"🎨 {source_description}")
    media_group = []
    for i, (color, dist, cat) in enumerate(top_colors):
        if cat == 'ncs':
            color_name = color.get('code', 'NCS')
        elif cat == 'ral':
            color_name = color.get('code', 'RAL')
        elif cat == 'html':
            color_name = color.get('name', 'HTML')
        elif cat == 'tikkurila':
            color_name = color.get('code', 'Tikkurila')
        elif cat == 'dulux':
            color_name = color.get('code', 'Dulux')
        elif cat == 'sherwin_williams':
            color_name = color.get('code', 'Sherwin-Williams')
        else:
            color_name = str(color.get('code', ''))
        caption = f"{cat.upper()}: {color_name}  |  ΔE = {dist:.1f}"
        img_bytes = await get_color_image(color, cat, delta=dist)
        media_group.append(
            InputMediaPhoto(
                media=types.BufferedInputFile(img_bytes.getvalue(), filename=f"color_{i}.png"),
                caption=caption
            )
        )
    await message.answer_media_group(media=media_group)
    await message.answer("✅ Подбор завершён. Выберите дальнейшее действие.", reply_markup=get_main_menu())

# ==================== Асинхронное получение изображения цвета ====================
async def get_color_image(color, cat, delta=None):
    rgb = color['rgb']
    if delta is not None and delta < 1:
        if cat == 'ncs':
            text = color.get('code', 'NCS')
        elif cat == 'ral':
            text = color.get('code', 'RAL')
        elif cat == 'html':
            text = color.get('name', 'HTML')
        elif cat == 'tikkurila':
            text = color.get('code', 'Tikkurila')
        elif cat == 'dulux':
            text = color.get('code', 'Dulux')
        elif cat == 'sherwin_williams':
            text = color.get('code', 'Sherwin-Williams')
        else:
            text = rgb_to_hex(rgb)
        return create_color_image_with_text(rgb, text)
    possible_names = []
    if cat == 'ncs':
        code = color.get('code', '')
        possible_names.append(f"{code}.png")
        possible_names.append(f"{code.replace(' ', '_')}.png")
        if code.startswith("NCS "):
            short = code[4:].strip()
            possible_names.append(f"{short}.png")
            possible_names.append(f"{short.replace(' ', '_')}.png")
    elif cat == 'ral':
        code = color.get('code', '')
        possible_names.append(f"RAL {code}.png")
        possible_names.append(f"RAL{code}.png")
        possible_names.append(f"{code}.png")
    elif cat == 'html':
        name = color.get('name', '')
        safe_name = name.replace(' ', '_')
        possible_names.append(f"{safe_name}.png")
        possible_names.append(f"{safe_name.lower()}.png")
    elif cat == 'tikkurila':
        code = color.get('code', '')
        possible_names.append(f"{code}.png")
        possible_names.append(f"Tikkurila_{code}.png")
    elif cat == 'dulux':
        code = color.get('code', '')
        possible_names.append(f"{code}.png")
        possible_names.append(f"{code.replace(' ', '_')}.png")
    elif cat == 'sherwin_williams':
        code = color.get('code', '')
        possible_names.append(f"{code}.png")
        possible_names.append(f"{code.replace(' ', '_')}.png")
    else:
        return create_color_image(rgb)
    for name in possible_names:
        file_path = os.path.join(IMAGE_FOLDER, name)
        if os.path.isfile(file_path):
            try:
                async with aiofiles.open(file_path, 'rb') as f:
                    content = await f.read()
                return io.BytesIO(content)
            except Exception as e:
                logger.error(f"Ошибка чтения файла {file_path}: {e}")
                continue
    logger.warning(f"Файл не найден для {cat} {color.get('code', color.get('name', 'unknown'))}, генерирую.")
    return create_color_image(rgb)

# ==================== Обработка сравнения цветов ====================
async def handle_compare_photo(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    photo_bytes = await bot.download_file(file.file_path)
    color_thief = ColorThief(photo_bytes)
    dominant_color = color_thief.get_color(quality=1)
    current_state = await state.get_state()
    if current_state == CompareStates.waiting_color1.state:
        await state.update_data(color1=dominant_color)
        await state.set_state(CompareStates.waiting_color2)
        await message.answer(
            f"✅ Первый цвет (доминирующий) – RGB{dominant_color}\n\n"
            "Теперь введите второй цвет (код RAL/NCS/Tikkurila/Dulux/Sherwin-Williams, RGB, HEX, название) или отправьте фото.",
            reply_markup=get_cancel_keyboard()
        )
    else:
        data = await state.get_data()
        color1 = data['color1']
        dist = color_distance_lab(color1, dominant_color)
        img_bytes = create_color_comparison_image(color1, dominant_color, dist)
        await message.answer_photo(
            types.BufferedInputFile(img_bytes.getvalue(), filename="compare.png"),
            caption=f"🔍 Сравнение цветов:\n"
                    f"Цвет 1: RGB{color1} (HEX {rgb_to_hex(color1)})\n"
                    f"Цвет 2: RGB{dominant_color} (HEX {rgb_to_hex(dominant_color)})\n"
                    f"📏 ΔE (CIE2000): {dist:.2f}"
        )
        await state.clear()
        await message.answer("✅ Сравнение завершено. Возвращаюсь в меню.", reply_markup=get_main_menu())

async def handle_compare_text(message: types.Message, state: FSMContext):
    text = message.text.strip()
    rgb = await parse_color_input(text)
    if not rgb:
        await message.answer(
            "❌ Не удалось распознать цвет. Попробуйте ещё раз или отправьте фото.\n"
            "Для отмены нажмите кнопку ниже.",
            reply_markup=get_cancel_keyboard()
        )
        return
    current_state = await state.get_state()
    if current_state == CompareStates.waiting_color1.state:
        await state.update_data(color1=rgb)
        await state.set_state(CompareStates.waiting_color2)
        text_upper = text.upper()
        text_lower = text.lower()
        if text_upper in ncs_code_to_rgb:
            color_name = text_upper
        elif text_upper in ral_code_to_rgb:
            color_name = text_upper
        elif text_upper in tikkurila_code_to_rgb:
            color_name = text_upper
        elif text_upper in dulux_code_to_rgb:
            color_name = text_upper
        elif text_upper in sherwin_williams_code_to_rgb:
            color_name = text_upper
        elif text_lower in HTML_NAMES_MAP:
            color_name = HTML_NAMES_MAP[text_lower]['name']
        elif re.match(r'^#?[0-9A-F]{6}$', text.upper()):
            color_name = f"HEX {text.upper()}"
        else:
            color_name = f"RGB{rgb}"
        await message.answer(
            f"✅ Первый цвет: {color_name} – RGB{rgb} (HEX {rgb_to_hex(rgb)})\n\n"
            "Теперь введите второй цвет (код RAL/NCS/Tikkurila/Dulux/Sherwin-Williams, RGB, HEX, название) или отправьте фото.",
            reply_markup=get_cancel_keyboard()
        )
    else:
        data = await state.get_data()
        color1 = data['color1']
        dist = color_distance_lab(color1, rgb)
        img_bytes = create_color_comparison_image(color1, rgb, dist)
        await message.answer_photo(
            types.BufferedInputFile(img_bytes.getvalue(), filename="compare.png"),
            caption=f"🔍 Сравнение цветов:\n"
                    f"Цвет 1: RGB{color1} (HEX {rgb_to_hex(color1)})\n"
                    f"Цвет 2: RGB{rgb} (HEX {rgb_to_hex(rgb)})\n"
                    f"📏 ΔE (CIE2000): {dist:.2f}"
        )
        await state.clear()
        await message.answer("✅ Сравнение завершено. Возвращаюсь в меню.", reply_markup=get_main_menu())

@dp.callback_query(F.data == "cancel_compare")
async def cancel_compare(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text("❌ Сравнение отменено.", reply_markup=get_main_menu())
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer()
        else:
            raise
    await callback.answer()

# ==================== Обработчики заказа ====================
@dp.callback_query(F.data == "photo_skip")
async def photo_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(photo_id=None)
    await callback.message.answer("⏭ Фото пропущено. Введите тип древесины (например, сосна, дуб):")
    await state.set_state(OrderStates.waiting_wood)
    await callback.answer()

@dp.message(OrderStates.waiting_photo)
async def order_photo(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    await state.update_data(photo_id=photo.file_id)
    await message.answer("✅ Фото сохранено. Введите тип древесины (например, сосна, дуб):")
    await state.set_state(OrderStates.waiting_wood)

@dp.message(OrderStates.waiting_wood)
async def order_wood(message: types.Message, state: FSMContext):
    await state.update_data(wood=message.text)
    await message.answer("Способ нанесения (кисть, валик, распыление):")
    await state.set_state(OrderStates.waiting_method)

@dp.message(OrderStates.waiting_method)
async def order_method(message: types.Message, state: FSMContext):
    await state.update_data(method=message.text)
    await message.answer("Степень блеска (0-100):")
    await state.set_state(OrderStates.waiting_gloss)

@dp.message(OrderStates.waiting_gloss)
async def order_gloss(message: types.Message, state: FSMContext):
    try:
        gloss = int(message.text)
        if not (0 <= gloss <= 100):
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число от 0 до 100.")
        return
    await state.update_data(gloss=gloss)
    await message.answer("Объём (литры):")
    await state.set_state(OrderStates.waiting_volume)

@dp.message(OrderStates.waiting_volume)
async def order_volume(message: types.Message, state: FSMContext):
    try:
        volume = float(message.text.replace(',', '.'))
        if volume <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число.")
        return
    data = await state.get_data()
    order_id = await save_order(
        user_id=message.from_user.id,
        photo_id=data.get('photo_id'),
        wood=data['wood'],
        method=data['method'],
        gloss=data['gloss'],
        volume=volume
    )
    await message.answer(f"✅ Заказ #{order_id} оформлен! Мы свяжемся с вами.")
    await state.clear()
    await message.answer("Вернуться в меню:", reply_markup=get_main_menu())

# ==================== Обработка фото для подбора цвета (с выбором) ====================
@dp.message(F.photo)
async def handle_photo_pick(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state in (CompareStates.waiting_color1.state, CompareStates.waiting_color2.state):
        await handle_compare_photo(message, state)
        return
    if current_state == OrderStates.waiting_photo.state:
        await order_photo(message, state)
        return
    photo = message.photo[-1]
    file_id = photo.file_id
    file = await bot.get_file(file_id)
    photo_url = f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{file.file_path}"
    await state.update_data(last_photo_id=file_id, last_photo_url=photo_url)
    web_app_url = f"{WEBAPP_URL}?file_id={file_id}&photo_url={photo_url}"
    web_app = WebAppInfo(url=web_app_url)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Выбрать цвет на фото", web_app=web_app)],
        [InlineKeyboardButton(text="🔍 Искать по всему фото (доминирующий)", callback_data="use_dominant")]
    ])
    await message.answer(
        "Выберите действие: точно указать цвет на фото или использовать автоматический доминирующий цвет.",
        reply_markup=keyboard
    )

# ==================== Обработчик кнопки "Использовать доминирующий" ====================
@dp.callback_query(F.data == "use_dominant")
async def use_dominant(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id = data.get('last_photo_id')
    if not file_id:
        await callback.message.answer("❌ Не удалось найти фото. Отправьте его ещё раз.")
        await callback.answer()
        return
    file = await bot.get_file(file_id)
    photo_bytes = await bot.download_file(file.file_path)
    color_thief = ColorThief(photo_bytes)
    dominant_color = color_thief.get_color(quality=1)
    await send_color_results(callback.message, dominant_color, f"🎨 Доминирующий цвет: RGB{dominant_color}")
    await callback.answer()
    await state.update_data(last_photo_id=None)

# ==================== Обработчик данных от Web App ====================
@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message, state: FSMContext):
    try:
        data_str = message.web_app_data.data
        logger.info(f"📦 Получены web_app_data: {data_str}")

        parts = data_str.strip().split()
        if len(parts) != 3:
            raise ValueError("Неверное количество чисел")

        r, g, b = map(int, parts)
        selected_rgb = (r, g, b)

    except Exception as e:
        logger.error(f"❌ Ошибка парсинга web_app_data: {e}")
        await message.answer("❌ Ошибка при получении цвета. Ожидалось три числа через пробел.")
        return

    await send_color_results(message, selected_rgb, f"🎨 Вы выбрали цвет: RGB{selected_rgb}")
    await state.update_data(last_photo_id=None)

# ==================== Обработка текста (включая Lab) ====================
@dp.message(F.text)
async def handle_text_input(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state in (CompareStates.waiting_color1.state, CompareStates.waiting_color2.state):
        await handle_compare_text(message, state)
        return
    if current_state == OrderStates.waiting_wood.state:
        await order_wood(message, state)
        return
    if current_state == OrderStates.waiting_method.state:
        await order_method(message, state)
        return
    if current_state == OrderStates.waiting_gloss.state:
        await order_gloss(message, state)
        return
    if current_state == OrderStates.waiting_volume.state:
        await order_volume(message, state)
        return
    text = message.text.strip()
    target_lab = parse_lab_input(text)
    if target_lab is not None:
        top_colors = get_top_n_all_lab_from_lab(target_lab, n=10)
        if not top_colors:
            await message.answer("❌ Не удалось найти подходящие цвета.", reply_markup=get_main_menu())
            return
        await message.answer(f"🔍 Поиск по Lab: L={target_lab[0]:.2f}, a={target_lab[1]:.2f}, b={target_lab[2]:.2f}")
        media_group = []
        for i, (color, dist, cat) in enumerate(top_colors):
            if cat == 'ncs':
                color_name = color.get('code', 'NCS')
            elif cat == 'ral':
                color_name = color.get('code', 'RAL')
            elif cat == 'html':
                color_name = color.get('name', 'HTML')
            elif cat == 'tikkurila':
                color_name = color.get('code', 'Tikkurila')
            elif cat == 'dulux':
                color_name = color.get('code', 'Dulux')
            elif cat == 'sherwin_williams':
                color_name = color.get('code', 'Sherwin-Williams')
            else:
                color_name = str(color.get('code', ''))
            caption = f"{cat.upper()}: {color_name}  |  ΔE = {dist:.1f}"
            img_bytes = await get_color_image(color, cat, delta=dist)
            media_group.append(
                InputMediaPhoto(
                    media=types.BufferedInputFile(img_bytes.getvalue(), filename=f"color_{i}.png"),
                    caption=caption
                )
            )
        await message.answer_media_group(media=media_group)
        await message.answer("✅ Подбор завершён. Выберите дальнейшее действие.", reply_markup=get_main_menu())
        return
    rgb = await parse_color_input(text)
    if not rgb:
        await message.answer(
            "❌ Не понимаю. Отправь фото, код RAL/NCS/Tikkurila/Dulux/Sherwin-Williams, RGB тремя числами, "
            "HEX-код, название цвета или Lab (например, lab 91.74 -0.30 3.66).",
            reply_markup=get_main_menu()
        )
        return
    text_upper = text.upper()
    text_lower = text.lower()
    if text_upper in ncs_code_to_rgb:
        input_name = text_upper
    elif text_upper in ral_code_to_rgb:
        input_name = text_upper
    elif text_upper in tikkurila_code_to_rgb:
        input_name = text_upper
    elif text_upper in dulux_code_to_rgb:
        input_name = text_upper
    elif text_upper in sherwin_williams_code_to_rgb:
        input_name = text_upper
    elif text_lower in HTML_NAMES_MAP:
        input_name = HTML_NAMES_MAP[text_lower]['name']
    elif re.match(r'^#?[0-9A-Fa-f]{6}$', text):
        hex_clean = text.lstrip('#').upper()
        input_name = f"HEX #{hex_clean}"
    else:
        input_name = f"RGB{rgb}"
    await send_color_results(message, rgb, f"🎨 Введённый цвет: {input_name} (RGB{rgb})")

# ==================== Команда /admin ====================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    orders = await get_new_orders()
    if not orders:
        await message.answer("📭 Новых заказов нет.")
        return
    for order in orders:
        # order - словарь из database.py (PostgreSQL версия)
        order_id = order['id']
        user_id = order['user_id']
        photo_id = order['photo_file_id']
        wood = order['wood_type']
        method = order['application_method']
        gloss = order['gloss']
        volume = order['volume']
        status = order['status']
        created_at = order['created_at']
        wood_display = wood if wood else "не указано"
        method_display = method if method else "не указано"
        gloss_display = f"{gloss} (0-100)" if gloss is not None else "не указано"
        photo_display = "есть фото" if photo_id else "нет фото"
        caption = (
            f"🆕 Заказ #{order_id}\n"
            f"👤 Пользователь ID: {user_id}\n"
            f"📷 Фото: {photo_display}\n"
            f"🌳 Порода: {wood_display}\n"
            f"🛠️ Способ: {method_display}\n"
            f"🎨 Блеск: {gloss_display}\n"
            f"📦 Объём: {volume} кг\n"
            f"📅 Дата: {created_at}"
        )
        if photo_id:
            await message.answer_photo(photo=photo_id, caption=caption)
        else:
            await message.answer(caption)

# ==================== Обработчик прочих сообщений ====================
@dp.message()
async def handle_unknown(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Используйте /start для начала работы.", reply_markup=get_main_menu())

# ==================== Запуск ====================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)