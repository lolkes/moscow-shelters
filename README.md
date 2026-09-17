# Приюты Москвы и МО — v9 Production Core

Автономный каталог приютов и животных. Telegram пока не подключён.

## Запуск
```bash
pip install -r requirements.txt
python scripts/seed_shelters.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Автоматизация
- полный цикл каждый час;
- проверка источников раз в 7 дней;
- безопасные публичные RSS/Atom/разрешённые источники;
- без обхода CAPTCHA, авторизации, robots.txt, rate limits и антибот-защиты;
- временная ошибка источника не архивирует животных;
- история изменений;
- дедупликация по URL/fingerprint;
- пагинация каталога;
- дополнительные поля: порода, размер, окрас, стерилизация, вакцинация;
- фотографии хранятся ссылками на первоисточник;
- статистика импорта и здоровье источников;
- SQLite для локальной работы, PostgreSQL через `DATABASE_URL` для production.

## API
- `GET /api/shelters`
- `GET /api/animals?page=1&limit=50`
- `GET /api/animals/{id}`
- `GET /api/animals/{id}/history`
- `GET /api/sources/health`
- `GET /api/import/summary`
- `GET /api/metrics`
- `GET /api/health`


## v12 — автоматические фотографии
Фото автоматически берутся только из первоисточника: RSS/Atom media/enclosure/thumbnail либо og:image/Twitter image оригинальной страницы. Разрешены только изображения того же домена, что и оригинальное объявление. До 10 фото на животное. Ручная загрузка и сторонние фотостоки не используются.


## v12
- Public catalog cards now use photos collected from the original source automatically.
- Animal detail pages have a photo gallery and thumbnails.
- Shelter pages show source photos when available.
- Broken source images fall back to the species icon without breaking the card.
- Fixed frontend handling of the paginated `/api/animals` response.
- No manual photo upload and no stock/generated replacement images.


## v12 — автоматическая дедупликация
- Сильные совпадения между источниками помечаются как `duplicate`, а не публикуются повторно.
- Исходное объявление сохраняется и связывается через `duplicate_of_id`.
- Слабые совпадения не объединяются автоматически, чтобы не скрыть разных животных.
- Добавлена безопасная миграция SQLite для новых полей.
- `/api/duplicates` показывает найденные дубли для контроля.
- Исправлен запуск FastAPI и пересчёт количества животных по приютам.


## v13 — automatic public source discovery

Added safe automatic source discovery for public animal catalogs:
- РосПриют Moscow/MO catalog, dogs and cats catalogs;
- Мосприют catalog;
- source URLs remain attached to every imported record;
- no CAPTCHA/auth/robots/rate-limit bypass;
- image extraction remains limited to original source domains;
- hourly cycle planning is available in `scripts/auto_source_cycle.py`;
- `/api/sources/discover` exposes discovered public sources for monitoring.

Current source examples are based on public catalogs that are currently accessible on the web. citeturn0search3turn0search0turn0search1turn0search2

## FINAL CORE
The project now includes the core pieces needed for an autonomous catalog:
- public source discovery;
- generic safe HTML extraction helpers;
- automatic same-origin photo extraction/validation;
- conservative duplicate detection;
- hourly-cycle runbook;
- source health/metrics endpoints from the existing core;
- history and source URLs preserved;
- no manual photo upload requirement;
- Telegram intentionally remains out of scope until requested.
