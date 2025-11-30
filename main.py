import asyncio
import os
import subprocess
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
import aiosqlite

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  # если хочешь только ты могла тестить

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "users.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS videos (
            user_id INTEGER, day INTEGER, file_id TEXT, UNIQUE(user_id, day))""")
        await db.commit()

# ------------------- обычный старт -------------------
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "Привет! Это тестовый бот для 30-дневного челленджа.\n"
        "Напиши /test — чтобы сразу проверить монтаж на любом количестве видео."
    )

# ------------------- тестовый режим -------------------
user_test_mode = {}  # user_id → True/False

@dp.message(Command("test"))
async def test_mode(message: types.Message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        await message.answer("Тестовый режим только для админа 😊")
        return
    user_test_mode[message.from_user.id] = True
    await message.answer(
        "Тестовый режим включён!\n"
        "Присылай подряд любое количество видео (хоть 3, хоть 30).\n"
        "Как закончишь — напиши /finish и я сразу соберу ролик (по 1 секунде + текст «День N»)."
    )

@dp.message(lambda m: user_test_mode.get(m.from_user.id, False))
async def save_video(message: types.Message):
    user_id = message.from_user.id
    if not message.video:
        await message.answer("Пришли именно видео 😊")
        return

    # определяем следующий день
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT MAX(day) FROM videos WHERE user_id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            day = (row[0] or 0) + 1
        await db.execute("INSERT INTO videos VALUES (?, ?, ?)",
                        (user_id, day, message.video.file_id))
        await db.commit()

    await message.answer(f"Видео за День {day} сохранено ✓\nПрисылай следующее или /finish")

# ------------------- монтаж -------------------
@dp.message(Command("finish"))
async def finish(message: types.Message):
    user_id = message.from_user.id
    if not user_test_mode.get(user_id):
        await message.answer("Сначала включи тестовый режим командой /test")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT day, file_id FROM videos WHERE user_id=? ORDER BY day", (user_id,)) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("Нет видео для монтажа")
        return

    await message.answer("Собираю ролик… обычно 5–15 секунд")

    # скачиваем все видео и делаем список для ffmpeg
    txt_files = []
    video_parts = []
    for i, (day, file_id) in enumerate(rows, 1):
        file = await bot.get_file(file_id)
        video_path = f"/tmp/{user_id}_{day}.mp4"
        await bot.download_file(file.file_path, video_path)

        # обрезаем до 1 сек и добавляем текст
        part = f"/tmp/part_{user_id}_{day}.mp4"
        txt = f"/tmp/text_{user_id}_{day}.png"
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-t", "1", "-c", "copy", part
        ], check=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=100x50", 
            "-vf", f"drawtext=text='День {day}':fontcolor=white:fontsize=40:x=w-tw-20:y=h-th-20",
            "-frames:v", "1", txt
        ], check=True)
        video_parts.append(part)
        txt_files.append(txt)

    # список для concat
    list_file = f"/tmp/list_{user_id}.txt"
    with open(list_file, "w") as f:
        for vp in video_parts:
            f.write(f"file '{vp}'\n")

    output = f"/tmp/result_{user_id}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
        "-vf", f"overlay=main_w-overlay_w-10:main_h-overlay_h-10",
        "-c:v", "libx264", "-crf", "23", output
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    await bot.send_video(message.chat.id, FSInputFile(output))
    await message.answer("Готово! Это был тестовый монтаж 😊")

    # очистка
    for f in [output, list_file] + video_parts + txt_files:
        try: os.remove(f)
        except: pass

    # можно очистить базу или оставить — как хочешь

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
