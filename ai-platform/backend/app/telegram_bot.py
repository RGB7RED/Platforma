"""
Telegram Bot для интеграции с Mini App и управления задачами.
"""

import logging
import os
from typing import Dict, Any
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from .main import create_task, get_task_status

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация бота
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://your-domain.com/app")

# Хранилище пользовательских сессий (в продакшене заменить на Redis/БД)
user_sessions: Dict[int, Dict] = {}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🚀 Создать задачу", callback_data="create_task")],
        [InlineKeyboardButton("📋 Мои задачи", callback_data="my_tasks")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("🖥️ Открыть Web App", web_app={"url": WEB_APP_URL})]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = f"""
👋 Привет, {user.first_name}!

Я — бот для AI Collaboration Platform.
С моей помощью вы можете:

🤖 **Создавать задачи** для ИИ-агентов
🔧 **Получать готовые решения** в виде кода
📊 **Отслеживать прогресс** выполнения задач
📦 **Скачивать результаты** в виде проектов

Для начала работы нажмите "Создать задачу" или откройте Web App для более удобного управления.
"""
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    # Сохраняем сессию пользователя
    user_sessions[user.id] = {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_seen": datetime.now().isoformat()
    }


async def create_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик создания задачи через бота"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📝 Опишите задачу для ИИ-агентов:\n\n"
        "Примеры:\n"
        "• Создай REST API для управления задачами\n"
        "• Напиши скрипт для анализа данных CSV\n"
        "• Создай веб-сайт на React с аутентификацией\n\n"
        "Отправьте описание одним сообщением:"
    )
    
    # Устанавливаем состояние ожидания описания задачи
    context.user_data["waiting_for_task"] = True


async def handle_task_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик получения описания задачи"""
    if not context.user_data.get("waiting_for_task"):
        return
    
    task_description = update.message.text
    user_id = update.effective_user.id
    
    # Создаем задачу через API
    try:
        response = await create_task(task_description, str(user_id))
        task_id = response.get("task_id")
        
        if task_id:
            # Сохраняем информацию о задаче
            if "user_tasks" not in context.user_data:
                context.user_data["user_tasks"] = []
            context.user_data["user_tasks"].append(task_id)
            
            # Показываем клавиатуру для управления задачей
            keyboard = [
                [
                    InlineKeyboardButton("📊 Статус", callback_data=f"status_{task_id}"),
                    InlineKeyboardButton("📁 Файлы", callback_data=f"files_{task_id}")
                ],
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{task_id}"),
                    InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{task_id}")
                ],
                [
                    InlineKeyboardButton("🖥️ Открыть в Web App", 
                                       web_app={"url": f"{WEB_APP_URL}?task={task_id}"})
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ Задача создана!\n\n"
                f"ID: `{task_id}`\n"
                f"Статус: 🟡 Обрабатывается\n"
                f"Прогресс: 0%\n\n"
                f"ИИ-агенты начали работу над вашей задачей. "
                f"Вы можете отслеживать прогресс с помощью кнопок ниже.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Ошибка при создании задачи. Попробуйте позже.")
    
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    
    # Сбрасываем состояние ожидания
    context.user_data["waiting_for_task"] = False


async def task_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик запроса статуса задачи"""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем ID задачи из callback_data
    callback_data = query.data
    if callback_data.startswith("status_"):
        task_id = callback_data[7:]  # Убираем "status_"
    elif callback_data.startswith("refresh_"):
        task_id = callback_data[8:]  # Убираем "refresh_"
    else:
        return
    
    # Получаем статус задачи
    try:
        status_data = await get_task_status(task_id)
        
        # Формируем сообщение со статусом
        status_emoji = {
            "created": "🟡",
            "processing": "🟠",
            "research": "🔍",
            "design": "📐",
            "implementation": "💻",
            "review": "🔍",
            "completed": "✅",
            "error": "❌"
        }.get(status_data.get("status", ""), "⚪")
        
        progress = status_data.get("progress", 0.0) * 100
        files_count = status_data.get("files_count", 0)
        
        status_text = f"""
{status_emoji} **Статус задачи** `{task_id}`

**Состояние:** {status_data.get('status', 'unknown')}
**Прогресс:** {progress:.1f}%
**Файлов создано:** {files_count}

**Текущий этап:** {status_data.get('current_stage', 'N/A')}
**Время создания:** {datetime.fromtimestamp(status_data.get('created_at', 0)).strftime('%H:%M:%S') if status_data.get('created_at') else 'N/A'}
"""
        
        # Клавиатура для управления
        keyboard = [
            [
                InlineKeyboardButton("🔄 Обновить", callback_data=f"refresh_{task_id}"),
                InlineKeyboardButton("📁 Файлы", callback_data=f"files_{task_id}")
            ],
            [
                InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_{task_id}"),
                InlineKeyboardButton("🖥️ Web App", web_app={"url": f"{WEB_APP_URL}?task={task_id}"})
            ]
        ]
        
        if status_data.get("status") == "completed":
            keyboard.append([
                InlineKeyboardButton("📦 Скачать проект", callback_data=f"download_{task_id}")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            status_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Error getting task status: {e}")
        await query.edit_message_text(f"❌ Ошибка при получении статуса: {str(e)}")


async def task_files_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик запроса списка файлов задачи"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    task_id = callback_data[6:]  # Убираем "files_"
    
    # Здесь должен быть вызов API для получения файлов
    # Пока используем заглушку
    await query.edit_message_text(
        f"📁 Файлы задачи `{task_id}`\n\n"
        f"Для просмотра файлов откройте Web App:\n"
        f"{WEB_APP_URL}?task={task_id}",
        parse_mode="Markdown"
    )


async def my_tasks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать задачи пользователя"""
    query = update.callback_query
    await query.answer()
    
    user_tasks = context.user_data.get("user_tasks", [])
    
    if not user_tasks:
        await query.edit_message_text(
            "📭 У вас пока нет задач.\n\n"
            "Создайте первую задачу, нажав кнопку 'Создать задачу'."
        )
        return
    
    # Формируем список задач
    tasks_text = "📋 **Ваши задачи:**\n\n"
    
    for i, task_id in enumerate(user_tasks[-10:], 1):  # Последние 10 задач
        try:
            status_data = await get_task_status(task_id)
            status_emoji = "🟢" if status_data.get("status") == "completed" else "🟡"
            tasks_text += f"{i}. {status_emoji} `{task_id[:8]}...` - {status_data.get('status', 'unknown')}\n"
        except Exception:
            tasks_text += f"{i}. ⚪ `{task_id[:8]}...` - неизвестно\n"
    
    tasks_text += "\nНажмите на ID задачи для просмотра деталей."
    
    # Создаем клавиатуру с задачами
    keyboard = []
    for task_id in user_tasks[-5:]:  # Последние 5 задач для быстрого доступа
        keyboard.append([
            InlineKeyboardButton(f"📝 {task_id[:8]}...", callback_data=f"status_{task_id}")
        ])
    
    keyboard.append([
        InlineKeyboardButton("🔄 Обновить", callback_data="my_tasks"),
        InlineKeyboardButton("🚀 Новая задача", callback_data="create_task")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        tasks_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки бота"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("🔔 Уведомления", callback_data="notifications"),
            InlineKeyboardButton("🎨 Тема", callback_data="theme")
        ],
        [
            InlineKeyboardButton("🔐 Безопасность", callback_data="security"),
            InlineKeyboardButton("ℹ️ О боте", callback_data="about")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "⚙️ **Настройки**\n\n"
        "Здесь вы можете настроить работу бота:\n\n"
        "• 🔔 Уведомления о прогрессе задач\n"
        "• 🎨 Внешний вид интерфейса\n"
        "• 🔐 Настройки безопасности\n"
        "• ℹ️ Информация о боте",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def about_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о боте"""
    query = update.callback_query
    await query.answer()
    
    about_text = """
🤖 **AI Collaboration Platform Bot**

**Версия:** 1.0.0 MVP
**Разработчик:** AI Platform Team
**Дата сборки:** 2024-01-15

**Описание:**
Бот для управления AI Collaboration Platform — системой для автоматической разработки программного обеспечения с помощью ИИ-агентов.

**Возможности:**
• Создание задач для ИИ-агентов
• Автоматическая генерация кода
• Просмотр результатов в Web App
• Скачивание готовых проектов

**Технологии:**
• Python 3.11+
• FastAPI
• Telegram Bot API
• WebSocket для real-time обновлений

**Ссылки:**
[GitHub репозиторий](https://github.com/your-repo)
[Документация](https://docs.your-domain.com)
"""
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="settings")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        about_text,
        reply_markup=reply_markup,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


async def back_to_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🚀 Создать задачу", callback_data="create_task")],
        [InlineKeyboardButton("📋 Мои задачи", callback_data="my_tasks")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("🖥️ Открыть Web App", web_app={"url": WEB_APP_URL})]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Главное меню\n\nПривет, {user.first_name}!",
        reply_markup=reply_markup
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Уведомляем пользователя об ошибке
    if update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже."
        )


async def broadcast_progress(task_id: str, progress_data: Dict[str, Any]):
    """Отправка уведомления о прогрессе пользователям через бота"""
    # Эта функция будет вызываться из основного приложения
    # для отправки уведомлений о прогрессе через бота
    
    # Здесь должна быть логика поиска чатов, которые подписались на уведомления
    # по данной задаче. Пока это заглушка.
    pass


def setup_bot_handlers(application: Application):
    """Настройка обработчиков бота"""
    # Команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    
    # Callback-запросы
    application.add_handler(CallbackQueryHandler(create_task_command, pattern="^create_task$"))
    application.add_handler(CallbackQueryHandler(my_tasks_callback, pattern="^my_tasks$"))
    application.add_handler(CallbackQueryHandler(settings_callback, pattern="^settings$"))
    application.add_handler(CallbackQueryHandler(about_callback, pattern="^about$"))
    application.add_handler(CallbackQueryHandler(back_to_main_callback, pattern="^back_to_main$"))
    
    # Обработчики статусов задач
    application.add_handler(CallbackQueryHandler(task_status_callback, pattern="^status_"))
    application.add_handler(CallbackQueryHandler(task_status_callback, pattern="^refresh_"))
    application.add_handler(CallbackQueryHandler(task_files_callback, pattern="^files_"))
    
    # Обработчик текстовых сообщений (для описания задач)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_task_description
    ))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)


async def run_bot():
    """Запуск Telegram бота"""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не установлен. Бот не будет запущен.")
        return
    
    # Создаем приложение бота
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Настраиваем обработчики
    setup_bot_handlers(application)
    
    # Запускаем бота
    logger.info("Запуск Telegram бота...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_bot())
