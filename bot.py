import os
from pathlib import Path

import telebot
from dotenv import load_dotenv

from downloader import download_audio, get_video_info, embed_metadata
from logger import logger

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
    MAX_FILE_SIZE_MB = 2000
    logger.info(f'Используется Local Bot API: {API_SERVER}')
else:
    MAX_FILE_SIZE_MB = 50

bot = telebot.TeleBot(BOT_TOKEN)


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
        embed_metadata(file_path, info['uploader'], info['title'], info['thumbnail'])

        file_size_mb = Path(file_path).stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            Path(file_path).unlink(missing_ok=True)
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
                title=info['title'],
                performer=info['uploader'],
                reply_to_message_id=message.message_id
            )

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
    logger.info('Бот запущен')
    print('Бот запущен. Нажмите Ctrl+C для остановки.')
    bot.infinity_polling()


if __name__ == '__main__':
    main()
