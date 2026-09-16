# Moscow Shelters — production MVP

Каталог приютов и животных Москвы и Московской области.

Telegram пока **не подключён** — проект подготовлен для последующего добавления канала и автопубликации.

## Стек
- FastAPI
- PostgreSQL / Neon
- HTML/CSS/JS
- Render

## Запуск
```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Переменные окружения
Скопируйте `.env.example` в `.env` и задайте `DATABASE_URL`.

## Production
Для Render используется `render.yaml`. Render поддерживает деплой FastAPI из GitHub с build-командой `pip install -r requirements.txt` и запуском через Uvicorn.

## Источники
Импорт выполняется только из разрешённых публичных источников. Не выполняются обход CAPTCHA, авторизации, robots.txt, антибот-защиты или ограничений скорости.

## Telegram
Будет подключён отдельным этапом после создания канала.
