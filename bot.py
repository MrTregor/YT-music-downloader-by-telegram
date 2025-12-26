import base64
import json
import os
import threading
import time
from pathlib import Path

import schedule
import telebot
from dotenv import load_dotenv

from downloader import download_audio, get_video_info, get_playlist_info, embed_metadata
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

WEBAPP_URL = os.environ.get('WEBAPP_URL', '')

# Хранилище данных плейлистов по user_id
playlist_cache: dict[int, dict] = {}

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


def is_playlist_url(text: str) -> bool:
    """Проверяет, является ли текст ссылкой на плейлист YouTube."""
    return is_youtube_url(text) and 'list=' in text


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
        'Я скачаю аудио в формате M4A с обложкой и отправлю тебе.\n\n'
        'Для плейлистов: отправь ссылку и выбери треки в мини-приложении.'
    )


def format_duration(seconds: int) -> str:
    """Форматирует длительность в минуты:секунды."""
    if not seconds:
        return '--:--'
    minutes = seconds // 60
    secs = seconds % 60
    return f'{minutes}:{secs:02d}'


def build_track_data(entry: dict) -> dict:
    """Формирует данные трека для Mini App."""
    return {
        'id': entry['id'],
        'title': entry['title'],
        'duration': format_duration(entry['duration']),
        'thumb': f'https://i.ytimg.com/vi/{entry["id"]}/default.jpg',  # 120x90
    }


def calc_max_tracks_for_url(entries: list, base_url: str, max_url_len: int = 2000) -> int:
    """Вычисляет сколько треков влезает в URL (бинарный поиск)."""
    def url_len(count: int) -> int:
        tracks_data = [build_track_data(e) for e in entries[:count]]
        data_json = json.dumps({'tracks': tracks_data}, ensure_ascii=False)
        data_b64 = base64.urlsafe_b64encode(data_json.encode()).decode()
        return len(f'{base_url}?data={data_b64}')

    left, right = 1, len(entries)
    result = 0

    while left <= right:
        mid = (left + right) // 2
        if url_len(mid) <= max_url_len:
            result = mid
            left = mid + 1
        else:
            right = mid - 1

    return result


def build_playlist_keyboard(entries: list, start_idx: int, page_size: int, total: int) -> tuple:
    """Создаёт клавиатуру для выбора диапазона треков."""
    end_idx = min(start_idx + page_size, len(entries))
    page_entries = entries[start_idx:end_idx]

    # Формируем данные для Mini App
    tracks_data = [build_track_data(e) for e in page_entries]
    data_json = json.dumps({'tracks': tracks_data}, ensure_ascii=False)
    data_b64 = base64.urlsafe_b64encode(data_json.encode()).decode()
    webapp_full_url = f'{WEBAPP_URL}?data={data_b64}'

    keyboard = telebot.types.InlineKeyboardMarkup()

    # Кнопка выбора треков
    keyboard.add(telebot.types.InlineKeyboardButton(
        text=f'Выбрать треки {start_idx + 1}-{end_idx}',
        web_app=telebot.types.WebAppInfo(url=webapp_full_url)
    ))

    # Кнопки навигации
    nav_buttons = []
    if start_idx > 0:
        nav_buttons.append(telebot.types.InlineKeyboardButton(
            text='◀ Назад',
            callback_data=f'pl:{start_idx - page_size}:{page_size}'
        ))
    if end_idx < len(entries):
        nav_buttons.append(telebot.types.InlineKeyboardButton(
            text='Вперёд ▶',
            callback_data=f'pl:{end_idx}:{page_size}'
        ))
    if nav_buttons:
        keyboard.add(*nav_buttons)

    return keyboard, start_idx + 1, end_idx


@bot.message_handler(func=lambda m: is_playlist_url(m.text or ''))
def handle_playlist_url(message: telebot.types.Message) -> None:
    """Обработчик ссылок на плейлисты YouTube."""
    user_id = message.from_user.id
    if not is_allowed(user_id):
        logger.warning(f'Неразрешённый пользователь {user_id} пытался скачать плейлист')
        return

    if not WEBAPP_URL:
        bot.reply_to(message, 'Mini App не настроен. Обратитесь к администратору.')
        return

    url = message.text.strip()
    logger.info(f'Пользователь {user_id} запросил плейлист: {url}')

    status_msg = bot.reply_to(message, 'Получаю список треков...')

    try:
        playlist_info = get_playlist_info(url)
        entries = playlist_info['entries']

        if not entries:
            bot.edit_message_text(
                'Плейлист пуст или недоступен.',
                chat_id=message.chat.id,
                message_id=status_msg.message_id
            )
            return

        # Вычисляем сколько треков влезает в URL
        page_size = calc_max_tracks_for_url(entries, WEBAPP_URL)
        if page_size == 0:
            bot.edit_message_text(
                'Ошибка: не удалось сформировать URL.',
                chat_id=message.chat.id,
                message_id=status_msg.message_id
            )
            return

        # Сохраняем данные плейлиста для пользователя
        playlist_cache[user_id] = {
            'entries': {e['id']: e for e in entries},
            'entries_list': entries,  # сохраняем как список для пагинации
            'title': playlist_info['title'],
            'total': playlist_info['count'],
            'page_size': page_size,
            'url': url,
        }

        keyboard, start, end = build_playlist_keyboard(entries, 0, page_size, playlist_info['count'])

        info_text = f'Плейлист: {playlist_info["title"]}\n'
        info_text += f'Треков: {len(entries)}'
        if playlist_info['count'] > len(entries):
            info_text += f' (загружено из {playlist_info["count"]})'
        info_text += f'\n\nПоказаны треки {start}-{end}:'

        bot.edit_message_text(
            info_text,
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f'Ошибка плейлиста для пользователя {user_id}: {e}', exc_info=True)
        bot.edit_message_text(
            f'Ошибка: {e}',
            chat_id=message.chat.id,
            message_id=status_msg.message_id
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith('pl:'))
def handle_playlist_navigation(call: telebot.types.CallbackQuery) -> None:
    """Обработчик навигации по плейлисту."""
    user_id = call.from_user.id
    if not is_allowed(user_id):
        return

    cached = playlist_cache.get(user_id)
    if not cached:
        bot.answer_callback_query(call.id, 'Данные устарели. Отправь ссылку ещё раз.')
        return

    try:
        _, start_str, page_size_str = call.data.split(':')
        start_idx = max(0, int(start_str))
        page_size = int(page_size_str)

        entries = cached['entries_list']
        keyboard, start, end = build_playlist_keyboard(entries, start_idx, page_size, cached['total'])

        info_text = f'Плейлист: {cached["title"]}\n'
        info_text += f'Треков: {len(entries)}'
        if cached['total'] > len(entries):
            info_text += f' (загружено из {cached["total"]})'
        info_text += f'\n\nПоказаны треки {start}-{end}:'

        bot.edit_message_text(
            info_text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=keyboard
        )
        bot.answer_callback_query(call.id)

    except Exception as e:
        logger.error(f'Ошибка навигации плейлиста: {e}')
        bot.answer_callback_query(call.id, 'Ошибка навигации')


@bot.message_handler(content_types=['web_app_data'])
def handle_web_app_data(message: telebot.types.Message) -> None:
    """Обработчик данных из Mini App."""
    user_id = message.from_user.id
    if not is_allowed(user_id):
        return

    try:
        data = json.loads(message.web_app_data.data)
        selected_ids = data.get('selected', [])

        if not selected_ids:
            bot.reply_to(message, 'Не выбрано ни одного трека.')
            return

        cached = playlist_cache.get(user_id)
        if not cached:
            bot.reply_to(message, 'Данные плейлиста устарели. Отправь ссылку ещё раз.')
            return

        entries = cached['entries']
        tracks_to_download = [entries[vid] for vid in selected_ids if vid in entries]

        if not tracks_to_download:
            bot.reply_to(message, 'Выбранные треки не найдены.')
            return

        logger.info(f'Пользователь {user_id} выбрал {len(tracks_to_download)} треков')

        status_msg = bot.reply_to(
            message,
            f'Скачиваю {len(tracks_to_download)} треков...'
        )

        for i, track in enumerate(tracks_to_download, 1):
            video_url = f'https://www.youtube.com/watch?v={track["id"]}'
            track_title = track['title']

            try:
                bot.edit_message_text(
                    f'[{i}/{len(tracks_to_download)}] Скачиваю: {track_title}',
                    chat_id=message.chat.id,
                    message_id=status_msg.message_id
                )

                # Получаем полную информацию о видео
                info = get_video_info(video_url)

                def update_progress(percent: int) -> None:
                    try:
                        bot.edit_message_text(
                            f'[{i}/{len(tracks_to_download)}] {track_title}\nПрогресс: {percent}%',
                            chat_id=message.chat.id,
                            message_id=status_msg.message_id
                        )
                    except Exception:
                        pass

                file_path = download_audio(video_url, progress_callback=update_progress)

                # Метаданные
                raw_title = info['title']
                uploader = info['uploader']
                if ' - ' in raw_title:
                    parts = raw_title.split(' - ', 1)
                    performer = parts[0].strip()
                    title = parts[1].strip()
                else:
                    performer = uploader or ''
                    title = raw_title

                embed_metadata(file_path, performer, title, info['thumbnail'])

                file_size_mb = Path(file_path).stat().st_size / (1024 * 1024)
                if file_size_mb > MAX_FILE_SIZE_MB:
                    Path(file_path).unlink(missing_ok=True)
                    bot.send_message(
                        message.chat.id,
                        f'Трек "{track_title}" слишком большой ({file_size_mb:.1f} МБ), пропускаю.'
                    )
                    continue

                with open(file_path, 'rb') as audio_file:
                    bot.send_audio(
                        message.chat.id,
                        audio_file,
                        title=title,
                        performer=performer
                    )

                Path(file_path).unlink(missing_ok=True)
                logger.info(f'Отправлен трек {i}/{len(tracks_to_download)}: {track_title}')

            except Exception as e:
                logger.error(f'Ошибка скачивания трека {track_title}: {e}')
                bot.send_message(
                    message.chat.id,
                    f'Ошибка при скачивании "{track_title}": {e}'
                )

        bot.edit_message_text(
            f'Готово! Скачано треков: {len(tracks_to_download)}',
            chat_id=message.chat.id,
            message_id=status_msg.message_id
        )

        # Очищаем кэш
        playlist_cache.pop(user_id, None)

    except json.JSONDecodeError:
        bot.reply_to(message, 'Ошибка: неверный формат данных.')
    except Exception as e:
        logger.error(f'Ошибка обработки web_app_data: {e}', exc_info=True)
        bot.reply_to(message, f'Ошибка: {e}')


@bot.message_handler(func=lambda m: is_youtube_url(m.text or '') and not is_playlist_url(m.text or ''))
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
