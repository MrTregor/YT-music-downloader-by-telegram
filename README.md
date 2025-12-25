# YTMusicDownloader Bot

Telegram бот для скачивания аудио с YouTube в формате M4A с обложкой и метаданными.

## Возможности

- Скачивание аудио с YouTube в M4A формате
- Автоматическое добавление метаданных (название, исполнитель)
- Обложка из превью видео (кроп до 1:1)
- Отображение прогресса скачивания
- Поддержка файлов до 2000 МБ (через Local Bot API)
- Ограничение доступа по списку пользователей

## Требования

- Docker
- Docker Compose
- Telegram API credentials (для файлов >50 МБ)

## Настройка

### 1. Получение токенов

1. **BOT_TOKEN**: Создать бота через [@BotFather](https://t.me/BotFather)
2. **TELEGRAM_API_ID** и **TELEGRAM_API_HASH**: Получить на [my.telegram.org](https://my.telegram.org)
3. **ALLOWED_USERS**: Узнать свой ID через [@userinfobot](https://t.me/userinfobot)

### 2. Создание .env файла

```bash
cp .env.example .env
```

Заполнить `.env`:

```env
# Обязательные
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
ALLOWED_USERS=123456789,987654321

# Опциональные
PROXY=http://127.0.0.1:10080
```

| Переменная | Описание | Обязательно |
|------------|----------|-------------|
| `BOT_TOKEN` | Токен бота от @BotFather | Да |
| `TELEGRAM_API_ID` | API ID от my.telegram.org | Да |
| `TELEGRAM_API_HASH` | API Hash от my.telegram.org | Да |
| `ALLOWED_USERS` | ID пользователей через запятую | Да |
| `PROXY` | Прокси для YouTube (если заблокирован) | Нет |

## Сборка и запуск

### Сборка образа

```bash
docker-compose build
```

### Запуск

```bash
docker-compose up -d
```

### Просмотр логов

```bash
# Все сервисы
docker-compose logs -f

# Только бот
docker-compose logs -f bot
```

### Остановка

```bash
docker-compose down
```

### Перезапуск после изменений

```bash
docker-compose up -d --build
```

## Структура проекта

```
YTMusicDownloader/
├── bot.py              # Telegram бот
├── downloader.py       # Модуль скачивания
├── logger.py           # Логирование
├── cli.py              # CLI для тестирования
├── requirements.txt    # Python зависимости
├── Dockerfile          # Образ бота
├── docker-compose.yml  # Конфигурация сервисов
├── .env                # Переменные окружения (создать)
├── .env.example        # Пример переменных
├── downloads/          # Временные файлы (создаётся автоматически)
├── logs/               # Логи бота (создаётся автоматически)
└── data/               # Данные telegram-bot-api (создаётся автоматически)
```

## Использование

1. Отправить боту ссылку на YouTube видео
2. Дождаться скачивания (прогресс отображается в сообщении)
3. Получить аудио файл

Команды:
- `/start` — приветствие
- `/help` — справка

## Деплой на сервер

```bash
# 1. Скопировать файлы на сервер
scp -r *.py requirements.txt Dockerfile docker-compose.yml .env.example user@server:/opt/ytmusic-bot/

# 2. На сервере создать и заполнить .env
cd /opt/ytmusic-bot
cp .env.example .env
nano .env

# 3. Запустить
docker-compose up -d --build
```
