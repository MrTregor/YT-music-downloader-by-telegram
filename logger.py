import logging
import os
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOGS_DIR = Path(__file__).parent / 'logs'


def cleanup_old_logs(days: int = 30) -> None:
    """Удаляет логи старше указанного количества дней."""
    if not LOGS_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=days)

    for log_file in LOGS_DIR.glob('*.log*'):
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff:
                log_file.unlink()
        except OSError:
            pass


def setup_logger(name: str = 'ytdownloader') -> logging.Logger:
    """Настраивает и возвращает логгер с ротацией по дням.

    Args:
        name: Имя логгера

    Returns:
        Настроенный логгер
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    cleanup_old_logs(days=30)

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    log_file = LOGS_DIR / 'app.log'
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8',
    )
    file_handler.suffix = '%Y-%m-%d.log'
    file_handler.setLevel(logging.DEBUG)

    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)

    logger.addHandler(file_handler)

    return logger


logger = setup_logger()
