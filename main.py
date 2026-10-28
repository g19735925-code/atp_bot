import os
import sqlite3
import logging
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

# ================= НАСТРОЙКИ =================
# ПОДСТАВЬТЕ СВОЙ ТОКЕН НИЖЕ (ОБЯЗАТЕЛЬНО В КАВЫЧКАХ)
API_TOKEN = '9150952667:AAHrVOTtvqm7NWRHHuGfYi2HfsSWh_hnQl0'
# ССЫЛКУ ПОКА НЕ ТРОГАЙ, МЫ ОБНОВИМ ЕЕ В КОНЦЕ
MINI_APP_LINK = 'https://atp-bot.onrender.com' 
DB_NAME = "atp_journal.db"

PORT = int(os.environ.get("PORT", 8080))
HOST = "0.0.0.0"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
routes = web.RouteTableDef()

# ================= 1. БАЗА ДАННЫХ =================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'Активен',
            skips INTEGER DEFAULT 0,
            avg_grade REAL DEFAULT 0.0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            date TEXT,
            status TEXT,
            delay TEXT
        )
    ''')
    cursor.execute("SELECT COUNT(*) FROM students")
    if cursor.fetchone() == 0:
        cursor.executemany("INSERT INTO students (name, skips, avg_grade) VALUES (?, ?, ?)", [
            ("Иванов Александр (Тест)", 4, 4.6),
            ("Петров Дмитрий (Тест)", 12, 3.9),
            ("Сидорова Мария (Тест)", 0, 4.9)
        ])
    conn.commit()
    conn.close()

# ================= 2. КОД ТЕЛЕГРАМ-БОТА =================
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO students (tg_id, name) VALUES (?, ?)", 
                       (message.from_user.id, message.from_user.full_name))
        conn.commit()
    finally:
        conn.close()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Журнал АТП 📊", web_app=WebAppInfo(url=MINI_APP_LINK))]
    ])
    
    await message.reply(
        f"Привет, {message.from_user.first_name}! Я бот-помощник старосты **АТП**.\n"
        f"Ты добавлен в базу. Нажми кнопку ниже, чтобы открыть журнал.",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def send_attendance_poll():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT tg_id FROM students WHERE status = 'Активен' AND tg_id IS NOT NULL")
    students = cursor.fetchall()
    conn.close()
    
    for student in students:
        try:
            await bot.send_poll(
                chat_id=student[0],
                question="Пара началась! Отметь свой статус в АТП:",
                options=["На паре ✅", "Опаздываю ⏳", "Отсутствую ❌"],
                is_anonymous=False
            )
        except Exception as e:
            logging.error(f"Ошибка отправки опроса: {e}")

@dp.poll_answer()
async def handle_poll_answer(poll_answer: types.PollAnswer):
    tg_id = poll_answer.user.id
    option = poll_answer.option_ids[0]
    
    statuses = {0: "На паре", 1: "Опаздывает", 2: "Н"}
    status = statuses.get(option, "Н")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM students WHERE tg_id = ?", (tg_id,))
    student = cursor.fetchone()
    
    if student:
        student_id = student[0]
        date_today = datetime.now().strftime("%Y-%m-%d")
        
        if status == "Н":
            cursor.execute("UPDATE students SET skips = skips + 2 WHERE id = ?", (student_id,))
        
        cursor.execute("INSERT INTO attendance (student_id, date, status, delay) VALUES (?, ?, ?, ?)",
                       (student_id, date_today, status, "0"))
        conn.commit()
        
        if status == "Опаздывает":
            await bot.send_message(tg_id, "На сколько минут ты опаздываешь? Ответь цифрой.")
    conn.close()

# ================= 3. ВЕБ-СЕРВЕР И ИНТЕРФЕЙС MINI APP =================
@routes.get('/')
async def index(request):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Обработка действий старосты (если нажали на кнопку в интерфейсе)
    params = request.rel_url.query
    if 'action' in params and 'id' in params:
        student_id = params['id']
        action = params['action']
        if action == 'sick':
            cursor.execute("UPDATE students SET status = 'Больничный' WHERE id = ?", (student_id,))
        elif action == 'active':
            cursor.execute("UPDATE students SET status = 'Активен' WHERE id = ?", (student_id,))
        elif action == 'grade5':
            cursor.execute("UPDATE students SET avg_grade = ROUND((avg_grade + 5)/2, 1) WHERE id = ?", (student_id,))
        elif action == 'skip':
            cursor.execute("UPDATE students SET skips = skips + 2 WHERE id = ?", (student_id,))
        conn.commit()

    cursor.execute("SELECT id, name, skips, avg_grade, status FROM students")
    students = cursor.fetchall()
    conn.close()

    students_html = ""
    for s in students:
        s_id, name, skips, grade, status = s
        badge_class = "badge-active" if status == "Активен" else "badge-sick"
        
        # Кнопки действий для старосты
        students_html += f'''
        <div class="student-card">
            <div class="flex-row">
                <strong>{name}</strong>
                <span class="badge {badge_class}">{status}</span>
            </div>
            <p style="margin: 5px 0; font-size: 14px; opacity: 0.8;">Пропуски: {skips} ч. | Ср. балл: {grade}</p>
            <div class="actions" style="margin-top: 10px; display: flex; gap: 5px;">
                <a href="/?action=grade5&id={s_id}" class="mini-btn btn-success">+5</a>
                <a href="/?action=skip&id={s_id}" class="mini-btn btn-danger">+2ч пропуск</a>
                { f'<a href="/?action=sick&id={s_id}" class="mini-btn btn-warn">Заболел</a>' if status == "Активен" else f'<a href="/?action=active&id={s_id}" class="mini-btn btn-success">Выздоровел</a>' }
            </div>
        </div>
        '''

    html_content = f'''
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>АТП Журнал</title>
        <script src="https://telegram.org"></script>
        <style>
            body {{ font-family: system-ui, sans-serif; background-color: var(--tg-theme-bg-color, #ffffff); color: var(--tg-theme-text-color, #000000); padding: 15px; margin: 0; }}
            .header {{ text-align: center; margin-bottom: 20px; }}
            .student-card {{ background: var(--tg-theme-secondary-bg-color, #f0f0f0); border-radius: 12px; padding: 12px; margin-bottom: 10px; }}
            .flex-row {{ display: flex; justify-content: space-between; align-items: center; }}
            .badge {{ padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: bold; }}
            .badge-active {{ background: #2ecc71; color: white; }}
            .badge-sick {{ background: #e67e22; color: white; }}
            .mini-btn {{ padding: 6px 10px; border-radius: 6px; font-size: 12px; text-decoration: none; font-weight: bold; color: white; text-align: center; }}
            .btn-success {{ background: #2ecc71; }}
            .btn-danger {{ background: #e74c3c; }}
            .btn-warn {{ background: #f39c12; }}
            .btn-main {{ width: 100%; background: var(--tg-theme-button-color, #3498db); color: var(--tg-theme-button-text-color, #ffffff); border: none; padding: 12px; border-radius: 8px; font-weight: bold; margin-top: 15px; cursor: pointer; }}
        </style>
    </head>
    <body>
        <div class="header"><h2>Журнал старосты "АТП"</h2></div>
        <div id="group-list">{students_html}</div>
        <button class="btn-main" onclick="window.Telegram.WebApp.close()">Закрыть</button>
        <script>window.Telegram.WebApp.expand();</script>
    </body>
    </html>
    '''
    return web.Response(text=html_content, content_type='text/html')

# ================= 4. ЗАПУСК ВСЕГО ОДНОВРЕМЕННО =================
async def start_bot_and_server():
    init_db()
    # Опрос Пн-Сб в 08:30 по серверному времени
    scheduler.add_job(send_attendance_poll, 'cron', day_of_week='mon-sat', hour=8, minute=30)
    scheduler.start()

    asyncio.create_task(dp.start_polling(bot))

    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()

    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_bot_and_server())
