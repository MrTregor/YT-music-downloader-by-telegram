import os
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional
import urllib.request
import yt_dlp
from dotenv import load_dotenv
from mutagen.mp4 import MP4, MP4Cover
from PIL import Image

from logger import logger

load_dotenv()

PROXY = os.environ.get('PROXY', 'http://127.0.0.1:180')


def get_video_info(url: str) -> dict:
    """Получает метаданные видео с YouTube.

    Args:
        url: URL YouTube видео

    Returns:
        Словарь с метаданными: title, duration, thumbnail, uploader
    """
    logger.info(f'Получение информации о видео: {url}')
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'proxy': PROXY,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    video_id = info.get('id')
    thumbnail_url = f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg'

    result = {
        'title': info.get('title'),
        'duration': info.get('duration'),
        'thumbnail': thumbnail_url,
        'uploader': info.get('uploader'),
    }
    logger.debug(f'Информация получена: {result}')
    return result


def embed_metadata(file_path: str, artist: str, title: str, thumbnail_url: str) -> None:
    """Встраивает метаданные в M4A файл.

    Args:
        file_path: Путь к M4A файлу
        artist: Имя исполнителя
        title: Название трека
        thumbnail_url: URL обложки
    """
    logger.info(f'Встраивание метаданных в файл: {file_path}')
    logger.debug(f'Метаданные: artist={artist}, title={title}')

    audio = MP4(file_path)

    audio['\xa9nam'] = [title]
    audio['\xa9ART'] = [artist]

    logger.debug(f'Загрузка обложки: {thumbnail_url}')
    proxy_handler = urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY})
    opener = urllib.request.build_opener(proxy_handler)
    with opener.open(thumbnail_url) as response:
        cover_data = response.read()

    img = Image.open(BytesIO(cover_data))
    width, height = img.size
    if width != height:
        size = min(width, height)
        left = (width - size) // 2
        top = (height - size) // 2
        img = img.crop((left, top, left + size, top + size))
        logger.debug(f'Обложка обрезана до {size}x{size}')

    output = BytesIO()
    img.save(output, format='JPEG', quality=95)
    cover_data = output.getvalue()

    audio['covr'] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]

    audio.save()
    logger.info('Метаданные успешно встроены')


def download_audio(
    url: str,
    output_dir: str = 'downloads',
    progress_callback: Optional[Callable[[int], None]] = None
) -> str:
    """Скачивает аудио из YouTube видео в формате M4A.

    Args:
        url: URL YouTube видео
        output_dir: Папка для сохранения (по умолчанию 'downloads')
        progress_callback: Функция для отчёта о прогрессе (принимает процент 0-100)

    Returns:
        Путь к скачанному файлу
    """
    logger.info(f'Начало скачивания: {url}')
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    downloaded_file: Optional[str] = None
    last_percent: int = -1

    def progress_hook(d):
        nonlocal downloaded_file, last_percent
        if d['status'] == 'downloading' and progress_callback:
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            if total > 0:
                percent = int(downloaded * 100 / total)
                if percent >= last_percent + 10:
                    last_percent = percent
                    progress_callback(percent)
        elif d['status'] == 'finished':
            downloaded_file = d['filename']
            logger.info(f'Скачивание завершено: {downloaded_file}')

    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': str(output_path / '%(title)s.%(ext)s'),
        'quiet': False,
        'no_warnings': False,
        'proxy': PROXY,
        'progress_hooks': [progress_hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return downloaded_file or str(output_path)
