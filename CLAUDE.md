# CLAUDE.md — Telegram Analytics Bot (@insight_tg_bot)

## Обзор
Telegram-бот для анализа публичных каналов: облака слов, тональность, активность, личности, фразы, эмодзи. Монетизация через Telegram Stars.

## Архитектура

### Файлы
- `main.py` — точка входа, фоновые задачи (pending queue, описание бота, cleanup)
- `config.py` — все настройки из .env + константы
- `db.py` — SQLite (users.db): пользователи, платежи, кэш, очередь, статистика
- `analyzer.py` — анализ каналов (Telethon + веб-парсинг)
- `client_pool.py` — пул Telethon-аккаунтов с ротацией и cooldown
- `utils.py` — format_number, format_bot_description, get_bot_stats, cleanup_analysis_files
- `metrics.py` — Prometheus метрики

### Handlers (aiogram Router)
- `handlers/common.py` — rate limiting, клавиатуры, notify_admin(), A/B тест цен
- `handlers/user.py` — /start, /help, /balance, /compare, анализ каналов
- `handlers/payments.py` — /buy, покупка пакетов, Telegram Stars
- `handlers/admin.py` — /admin, /broadcast, /stats, графики, управление

### Режимы анализа
- **Lite** (бесплатные) — только облако слов + топ-15, через веб-парсинг (не тратит Telethon)
- **Full** (платные/premium/admin) — полный анализ 9 графиков, через Telethon

### Приоритетная очередь
При FloodWait анализы попадают в pending_analyses с приоритетами: paid(2) > premium(1) > free(0). Фоновая задача auto_process_pending обрабатывает очередь.

## Сервер

- **IP:** 144.31.221.196
- **Путь:** /opt/bot_tg
- **Сервис:** systemd `tg-bot`
- **SSH:** `ssh root@144.31.221.196`
- **Логи:** `ssh root@144.31.221.196 'journalctl -u tg-bot -f'`

## Деплой

```bash
./deploy.sh          # Полный деплой: проверка синтаксиса + тесты + rsync + restart
```

### Важно про деплой
- `users.db` исключена из rsync — она живёт только на сервере
- `.env`, `*.session` тоже исключены — они индивидуальны для сервера
- При миграции на новый сервер обязательно копировать users.db и *.session отдельно

## Бэкапы

- **Сервер:** cron каждый день в 3:00, хранит 7 копий в /opt/bot_tg/backups/
- **Локально:** `./scripts/pull_backup.sh` — скачивает базу с сервера
- **Автоматически:** launchd каждый день в 10:00 (com.bot-tg.backup)
- **Копии:** backups/users_latest.db — самая свежая локальная копия

## Оффсеты статистики

При миграции сервера 2026-02-12 часть данных была потеряна. В config.py добавлены:
- STATS_OFFSET_USERS = 2837
- STATS_OFFSET_ANALYSES = 2130
- STATS_OFFSET_STARS = 1734

Применяются в get_stats(), get_payment_stats(), get_bot_stats().

## Команды разработки

```bash
# Тесты
python3 -m pytest tests/ -x -q

# Проверка синтаксиса
python3 -m py_compile main.py handlers/__init__.py

# Ручной деплой (без deploy.sh)
rsync -avz --exclude '.env' --exclude '*.session' --exclude 'users.db' --exclude '__pycache__' --exclude '.git' ./ root@144.31.221.196:/opt/bot_tg/
ssh root@144.31.221.196 "systemctl restart tg-bot"

# Статус бота
ssh root@144.31.221.196 "systemctl status tg-bot --no-pager"
```

## Рабочий процесс

- **Реализация, а не планы.** Всегда выполняй реализацию, а не останавливайся на плане. Не заканчивай сессию только планом — если есть время, сразу начинай реализацию.
- **Не застревай в plan mode.** Никогда не входи и не оставайся в plan mode, когда пользователь просит реализовать, выполнить, закоммитить или задеплоить. Если пишешь план вместо кода — остановись и переключись на реализацию.
- **Тесты после каждого изменения.** Всегда запускай `python3 -m pytest tests/ -x -q` после изменений кода и убедись, что все тесты проходят, прежде чем считать задачу завершённой.
- **Проверяй результаты правок данных.** При правке JSON/HTML файлов всегда перечитывай файл после правки и проверяй edge cases (спецсимволы, неразрывные пробелы, кавычки, embedded comments). Не считай, что regex/скрипт сработал без верификации.
- **Долгие процессы — спроси.** Перед запуском долгих процессов (экспорт, скрейпинг, загрузка) спроси о таймфрейме и доступности внешних ресурсов (диски, сеть).

## Правила

- Всегда запускать тесты перед деплоем
- Не коммитить .env, *.session, users.db, deploy.sh (всё в .gitignore)
- При изменении db.py — проверить миграции (ALTER TABLE в init_db)
- Коммиты на русском языке (см. git log)
- Ветка разработки: 2026-01-17-2mri, основная: main
- setuptools на сервере должен быть <81 (для pymorphy2 pkg_resources)

## A/B тест цен

Две группы по user_id % 2:
- Группа A (чётные): 20/40/100 Stars
- Группа B (нечётные): 50/100/250 Stars

## Иерархия импортов

```
config → db → analyzer → client_pool → handlers → main
              utils ↗      nlp_module ↗
                           visualization ↗
```

Циклические импорты избегаются через отложенный импорт внутри функций (например `from db import ...` внутри notify_admin).

## Порядок роутеров (ВАЖНО)

В `handlers/__init__.py` роутеры подключаются в определённом порядке:
```python
main_router.include_router(payments_router)  # 1. Платежи (callback pack_*)
main_router.include_router(admin_router)     # 2. Админ (/admin, /broadcast)
main_router.include_router(user_router)      # 3. Пользовательский (catch-all)
```
**user_router последний**, потому что содержит catch-all обработчик текстовых сообщений. Если поставить его раньше — платежи и админка перестанут работать.

## AnalysisResult (analyzer.py)

Dataclass с 12 полями путей к файлам:
```
wordcloud_path, top_words_chart_path, sentiment_chart_path,
hourly_chart_path, weekday_chart_path, heatmap_path,
monthly_chart_path, emoji_chart_path, personality_chart_path,
top_phrases_chart_path, compare_chart_path, engagement_chart_path
```
Метод `get_all_paths()` возвращает список всех не-None путей (для cleanup).

## ClientPool (client_pool.py)

- `_get_best_account()`: выбирает аккаунт с наименьшим cooldown_until
- `asyncio.Semaphore` на каждый аккаунт для ограничения параллелизма
- При FloodWait: cooldown_until = now + wait_seconds, запись в floodwait_events
- `get_pool_status()`: текущее состояние всех аккаунтов для /admin

## NLP модуль (nlp_module/)

- `processor.py` — основной: pymorphy3 лемматизация + natasha NER
- Первый импорт ~2 секунды (загрузка моделей) — не импортировать на верхнем уровне handlers
- nltk stopwords + кастомные стоп-слова в config.py
- Используется в analyzer.py для обработки текстов постов

## Визуализация (visualization/)

- `charts.py` — 12 типов графиков (matplotlib + wordcloud)
- `__init__.py` — generate_all_charts() через asyncio.gather()
- Все графики генерируются в executor (run_in_executor) чтобы не блокировать event loop
- Шрифт DejaVu Sans для поддержки кириллицы (fonts-dejavu-core на сервере)

### Добавление нового графика:
1. Создать функцию в `charts.py`: `def create_X_chart(data, path) -> str`
2. Добавить поле в `AnalysisResult` dataclass
3. Добавить вызов в `generate_all_charts()` в `__init__.py`
4. Добавить отправку в обработчике результата в `handlers/user.py`

## Кэш анализов (cache/)

Структура: `cache/{channel_key}/meta.json` + PNG файлы.
- channel_key = username канала без @ в нижнем регистре
- meta.json хранит результаты анализа + timestamp
- TTL кэша настраивается в config.py (CACHE_TTL_HOURS)
- Фоновая задача в main.py чистит устаревший кэш

## Тестирование

```bash
python3 -m pytest tests/ -x -q    # Запуск всех тестов
python3 -m pytest tests/test_payments.py -x -q  # Один файл
```

### Паттерн тестов
- `conftest.py` содержит фикстуру `temp_db` — создаёт временную SQLite базу с init_db()
- Все тесты БД используют `with patch("db.DB_PATH", temp_db):`
- Если тест вызывает функцию из другого модуля (utils.py), нужен patch и для того модуля: `patch("utils.DB_PATH", temp_db)`

## База данных (users.db)

Таблицы: users, channel_cache, channel_stats, floodwait_events, pending_analyses, payments, buy_clicks.
WAL mode для высокой пропускной способности.

## Частые проблемы

- **setuptools >= 81**: ломает pymorphy2 (нет pkg_resources). На сервере pin `setuptools<81`
- **FloodWait каскад**: если все аккаунты в cooldown — анализы уходят в pending_analyses
- **Шрифты**: без fonts-dejavu-core графики падают с ошибкой шрифта
- **Кэш ключ**: всегда нормализовать username канала через `.lower().lstrip("@")`
