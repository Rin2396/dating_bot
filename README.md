
# Dating Bot

**Телеграм-бот для знакомств** с регистрацией анкет, просмотром профилей, лайками, мэтчингом и уведомлениями о взаимной симпатии.

## Технологии

- **Python 3.11+**
- **Aiogram** — для работы с Telegram API
- **FastAPI** — для фонового API-сервиса
- **PostgreSQL** — база данных для хранения анкет
- **Redis** — хранение состояний FSM
- **RabbitMQ** — очередь анкет для показа пользователям
- **MinIO** — хранение фотографий
- **Docker Compose** — оркестрация сервисов
- **Poetry** — управление зависимостями и виртуальным окружением

## Основные возможности

- Регистрация пользователей пошагово через FSM (Finite State Machine)
- Загрузка и хранение фотографий профиля в MinIO
- Просмотр анкет через команду `/browse`
- Лайки/дизлайки
- Система мэтчинга: уведомление при взаимных симпатиях
- Асинхронная обработка событий и очередей

## Структура проекта

```bash
dating_bot/
│
├── src/
│   ├── bot/         # Telegram-бот (Aiogram)
│   ├── api/         # FastAPI-приложение
│   ├── core/        # Настройки, конфиги
│   ├── db/          # Работа с базой данных (PostgreSQL)
│   ├── services/    # RabbitMQ, MinIO и вспомогательные сервисы
│   ├── models/      # Pydantic-схемы
│   └── utils/       # Утилиты
│
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```

## Как запустить проект

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/your_username/dating_bot.git
cd dating_bot
```

### 2. Настройте окружение

Убедитесь, что установлен **Poetry**:

```bash
pip install poetry
```

Установите зависимости:

```bash
poetry install
```

### 3. Настройте переменные окружения

Создайте `.env` файлы для бота и API-сервиса.

Пример `.env`:

```
BOT_TOKEN=ваш_токен_бота
POSTGRES_DB=dating_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=db
POSTGRES_PORT=5432
REDIS_HOST=redis
RABBITMQ_HOST=rabbitmq
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=dating-photos
```

### 4. Запустите проект через Docker Compose

```bash
docker-compose up --build
```

Это поднимет:
- PostgreSQL
- Redis
- RabbitMQ
- MinIO
- Бота на Aiogram
- API на FastAPI

### 5. Начните пользоваться ботом!

Перейдите в Telegram, найдите вашего бота и начните регистрацию.

## Полезные команды для разработки

- Запуск миграций базы данных (если используются Alembic):

```bash
alembic upgrade head
```

- Пересборка контейнеров:

```bash
docker-compose up --build --force-recreate
```

- Проверка очереди RabbitMQ:  
Перейдите в браузере на `http://localhost:15672` (логин/пароль: `guest`/`guest`).

- Просмотр файлов в MinIO:  
Перейдите на `http://localhost:9000` (логин/пароль: `minioadmin`/`minioadmin`).
