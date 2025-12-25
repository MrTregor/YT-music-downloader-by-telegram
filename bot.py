import os
import threading
import time
from pathlib import Path

import schedule
import telebot
from dotenv import load_dotenv

from downloader import download_audio, get_video_info, embed_metadata
from logger import logger, cleanup_old_logs

load_dotenv()

BOT_TOKEN = os.environ.get('BOT_TOKEN')
ALLOWED_USERS_RAW = os.environ.get('ALLOWED_USERS', '')
API_SERVER = os.environ.get('TELEGRAM_API_SERVER', '')

if not BOT_TOKEN:
    raise ValueError('BOT_TOKEN environment variable is not set')

ALLOWED_USERS: set[int] = set()
if ALLOWED_USERS_RAW:
    ALLOWED_USERS = {int(uid.strip()) for uid in ALLOWED_USERS_RAW.split(',') if uid.strip()}

if API_SERVER:
    telebot.apihelper.API_URL = f"{API_SERVER}/bot{{0}}/{{1}}"
    telebot.apihelper.READ_TIMEOUT = 300  # 5 минут для больших файлов
    MAX_FILE_SIZE_MB = 2000
    logger.info(f'Используется Local Bot API: {API_SERVER}')
else:
    MAX_FILE_SIZE_MB = 50

bot = telebot.TeleBot(BOT_TOKEN)


DOWNLOADS_DIR = Path('downloads')
MAX_FILE_AGE_DAYS = 30


def cleanup_old_downloads() -> None:
    """Удаляет файлы старше MAX_FILE_AGE_DAYS из папки downloads."""
    if not DOWNLOADS_DIR.exists():
        return
    cutoff_time = time.time() - (MAX_FILE_AGE_DAYS * 24 * 60 * 60)
    deleted_count = 0
    for file_path in DOWNLOADS_DIR.iterdir():
        if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
            file_path.unlink()
            deleted_count += 1
    if deleted_count:
        logger.info(f'Удалено старых файлов: {deleted_count}')


def daily_cleanup() -> None:
    """Ежедневная очистка старых файлов и логов."""
    logger.info('Запуск ежедневной очистки')
    cleanup_old_downloads()
    cleanup_old_logs(days=MAX_FILE_AGE_DAYS)


def run_scheduler() -> None:
    """Запускает планировщик в отдельном потоке."""
    schedule.every().day.at('00:00').do(daily_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(60)


def is_allowed(user_id: int) -> bool:
    """Проверяет, разрешён ли пользователь."""
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def is_youtube_url(text: str) -> bool:
    """Проверяет, является ли текст ссылкой на YouTube."""
    return 'youtube.com' in text or 'youtu.be' in text


@bot.message_handler(commands=['start'])
def handle_start(message: telebot.types.Message) -> None:
    """Обработчик команды /start."""
    if not is_allowed(message.from_user.id):
        logger.warning(f'Неразрешённый пользователь {message.from_user.id}')
        return
    logger.info(f'Пользователь {message.from_user.id} запустил бота')
    bot.reply_to(
        message,
        'Привет! Отправь мне ссылку на YouTube видео, и я скачаю аудио.'
    )


@bot.message_handler(commands=['help'])
def handle_help(message: telebot.types.Message) -> None:
    """Обработчик команды /help."""
    if not is_allowed(message.from_user.id):
        return
    bot.reply_to(
        message,
        'Просто отправь ссылку на YouTube видео.\n'
        'Я скачаю аудио в формате M4A с обложкой и отправлю тебе.'
    )


@bot.message_handler(func=lambda m: is_youtube_url(m.text or ''))
def handle_youtube_url(message: telebot.types.Message) -> None:
    """Обработчик YouTube ссылок."""
    user_id = message.from_user.id
    if not is_allowed(user_id):
        logger.warning(f'Неразрешённый пользователь {user_id} пытался скачать')
        return
    url = message.text.strip()
    logger.info(f'Пользователь {user_id} запросил: {url}')

    status_msg = bot.reply_to(message, 'Получаю информацию о видео...')

    try:
        info = get_video_info(url)
        title = info['title']

        def update_progress(percent: int) -> None:
            try:
                bot.edit_message_text(
                    f"Скачиваю: {title}\nПрогресс: {percent}%",
                    chat_id=message.chat.id,
                    message_id=status_msg.message_id
                )
            except Exception:
                pass

        bot.edit_message_text(
            f"Скачиваю: {title}\nПрогресс: 0%",
            chat_id=message.chat.id,
            message_id=status_msg.message_id
        )

        file_path = download_audio(url, progress_callback=update_progress)

        bot.edit_message_text(
            'Добавляю метаданные...',
            chat_id=message.chat.id,
            message_id=status_msg.message_id
        )
        raw_title = info['title']
        uploader = info['uploader']

        # Пытаемся извлечь артиста и название из формата "Artist - Title"
        if ' - ' in raw_title:
            parts = raw_title.split(' - ', 1)
            performer = parts[0].strip()
            title = parts[1].strip()
        else:
            performer = uploader or ''
            title = raw_title

        lyrics = embed_metadata(file_path, performer, title, info['thumbnail'])

        # Сохраняем lyrics в .lrc файл если есть
        lrc_path = None
        if lyrics:
            lrc_path = Path(file_path).with_suffix('.lrc')
            lrc_path.write_text(lyrics, encoding='utf-8')
            logger.info(f'LRC файл сохранён: {lrc_path}')

        file_size_mb = Path(file_path).stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            Path(file_path).unlink(missing_ok=True)
            if lrc_path:
                lrc_path.unlink(missing_ok=True)
            bot.edit_message_text(
                f'Файл слишком большой ({file_size_mb:.1f} МБ).\n'
                f'Лимит: {MAX_FILE_SIZE_MB} МБ.',
                chat_id=message.chat.id,
                message_id=status_msg.message_id
            )
            logger.warning(f'Файл слишком большой: {file_size_mb:.1f} МБ')
            return

        bot.edit_message_text(
            'Отправляю файл...',
            chat_id=message.chat.id,
            message_id=status_msg.message_id
        )

        with open(file_path, 'rb') as audio_file:
            bot.send_audio(
                message.chat.id,
                audio_file,
                title=title,
                performer=performer,
                reply_to_message_id=message.message_id
            )

        # Отправляем .lrc файл если есть
        if lrc_path and lrc_path.exists():
            with open(lrc_path, 'rb') as lrc_file:
                bot.send_document(
                    message.chat.id,
                    lrc_file,
                    caption='Текст песни\nПоложи в: MIUI/Music/lyric/',
                    reply_to_message_id=message.message_id
                )
            lrc_path.unlink(missing_ok=True)

        bot.delete_message(message.chat.id, status_msg.message_id)

        Path(file_path).unlink(missing_ok=True)
        logger.info(f'Успешно отправлено пользователю {user_id}: {info["title"]}')

    except Exception as e:
        logger.error(f'Ошибка для пользователя {user_id}: {e}', exc_info=True)
        bot.edit_message_text(
            f'Ошибка: {e}',
            chat_id=message.chat.id,
            message_id=status_msg.message_id
        )


@bot.message_handler(func=lambda m: True)
def handle_other(message: telebot.types.Message) -> None:
    """Обработчик всех остальных сообщений."""
    if not is_allowed(message.from_user.id):
        return
    bot.reply_to(message, 'Отправь ссылку на YouTube видео.')


def main() -> None:
    """Запуск бота."""
    daily_cleanup()
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info('Бот запущен')
    print('Бот запущен. Нажмите Ctrl+C для остановки.')
    bot.infinity_polling()


if __name__ == '__main__':
    main()
