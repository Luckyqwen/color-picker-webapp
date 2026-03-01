#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания недостающих файлов цветовых баз (пустых заглушек).
Запустите этот скрипт перед деплоем на Railway.
"""

import os

# Список файлов и соответствующих переменных
FILES = {
    'ncs2050_full.py': 'NCS_COLORS = []',
    'html_colors.py': 'HTML_COLORS = []',
    'ral_colors.py': 'RAL_COLORS = []',
    'tikkurila_colors.py': 'TIKKURILA_COLORS = []',
    'dulux.py': 'DULUX_COLORS = []',
    'sherwin_williams.py': 'SHERWIN_WILLIAMS_COLORS = []',
}

# Проверка и создание файлов
for filename, content in FILES.items():
    if not os.path.exists(filename):
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content + '\n')
        print(f"✅ Создан файл: {filename}")
    else:
        # Проверим, не пустой ли он и не содержит ли ошибок
        with open(filename, 'r', encoding='utf-8') as f:
            existing = f.read().strip()
        if existing != content:
            print(f"⚠️  Файл {filename} уже существует, но его содержимое отличается.")
            answer = input("Перезаписать его корректной заглушкой? (y/N): ").strip().lower()
            if answer == 'y':
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(content + '\n')
                print(f"✅ Файл {filename} перезаписан.")
            else:
                print(f"➡️  Файл {filename} оставлен без изменений.")
        else:
            print(f"✅ Файл {filename} уже корректен.")

print("\n🔍 Проверка requirements.txt...")
req_file = 'requirements.txt'
required_packages = [
    'aiogram>=3.18.0',
    'asyncpg',
    'colour-science',
    'numpy',
    'Pillow',
    'colorthief',
    'aiofiles',
    'python-dotenv'
]

if not os.path.exists(req_file):
    with open(req_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(required_packages) + '\n')
    print(f"✅ Создан файл {req_file}")
else:
    with open(req_file, 'r', encoding='utf-8') as f:
        content = f.read()
    # Проверим наличие aiogram (хотя бы приблизительно)
    if 'aiogram' not in content:
        print("⚠️  В requirements.txt отсутствует aiogram. Добавьте его вручную.")
    else:
        print("✅ requirements.txt в порядке (по крайней мере aiogram присутствует).")

print("\n🎉 Готово! Теперь можно коммитить и деплоить.")