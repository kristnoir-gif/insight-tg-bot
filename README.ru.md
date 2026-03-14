# Insight TG Bot

**[English version](README.md)**

Telegram-бот для анализа публичных каналов — облака слов, тональность, тепловые карты активности, упоминания личностей, фразы, эмодзи и многое другое.

Попробовать: [@insight_tg_bot](https://t.me/insight_tg_bot)

## Примеры

<p align="center">
  <img src="example/cloud.png" width="400" alt="Облако слов">
  <img src="example/graph.png" width="400" alt="Топ слов">
</p>
<p align="center">
  <img src="example/positive.png" width="400" alt="Позитивные слова">
  <img src="example/mats.png" width="400" alt="Облако мата">
</p>
<p align="center">
  <img src="example/hour.png" width="400" alt="Активность по часам">
  <img src="example/weekday.png" width="400" alt="Статистика по дням">
</p>
<p align="center">
  <img src="example/heatmap.png" width="400" alt="Тепловая карта">
  <img src="example/aggressive.png" width="400" alt="Агрессивные слова">
</p>
<p align="center">
  <img src="example/names.png" width="400" alt="Топ имён">
  <img src="example/phrases.png" width="400" alt="Топ фраз">
</p>
<p align="center">
  <img src="example/register.png" width="400" alt="Анализ регистра">
  <img src="example/dichotomy.png" width="400" alt="Дихотомия">
</p>

## Возможности

- **Облако слов** — визуализация ключевых тем
- **Топ-15 слов** — график частотности
- **Облако мата** — анализ ненормативной лексики с фильтрацией ложных срабатываний
- **Облака тональности** — позитивные и негативные слова
- **Статистика по дням** — средняя длина постов по дням недели
- **Активность по часам** — распределение времени публикаций
- **Тепловая карта** — час × день недели
- **Топ имён** — упомянутые люди (NER через Natasha)
- **Топ фраз** — частые триграммы
- **Топ эмодзи** — самые используемые эмодзи
- **Анализ регистра** — соотношение КАПСА и строчных
- **Дихотомия** — формальное vs неформальное, длинное vs короткое
- **PDF-экспорт** — полный отчёт в PDF

### Два режима

| | Lite (бесплатный) | Full (платный) |
|---|---|---|
| Метод | Веб-скрейпинг | Telethon API |
| Графики | Только облако слов | Все 12 графиков |
| Посты | До 150 | До 500 |
| Скорость | ~10 сек | ~30 сек |

### Монетизация

Оплата через **Telegram Stars** с A/B тестированием цен (2 группы).

## Стек технологий

| Компонент | Библиотека |
|---|---|
| Бот-фреймворк | aiogram 3.x |
| Telegram-клиент | Telethon (пул из 3 аккаунтов) |
| NLP | pymorphy3, Natasha NER, NLTK |
| Визуализация | matplotlib, wordcloud |
| База данных | SQLite (WAL mode) |
| Мониторинг | Prometheus, Sentry |
| PDF | matplotlib PdfPages |

## Архитектура

```
main.py              — точка входа, фоновые задачи
config.py            — настройки из .env
db.py                — SQLite: пользователи, платежи, очередь
analyzer.py          — пайплайн анализа (Telethon + веб-скрейпинг)
client_pool.py       — 3 Telethon-аккаунта, ротация, cooldown, кэш
handlers/
  ├── common.py      — rate limiting, клавиатуры, A/B тест
  ├── user.py        — /start, /help, анализ каналов
  ├── payments.py    — оплата Telegram Stars
  └── admin.py       — /admin, /broadcast, /stats
nlp/
  ├── processor.py   — лемматизация (pymorphy3) + NER (Natasha)
  └── constants.py   — стоп-слова, словари тональности
visualization/
  ├── charts.py      — 12 типов графиков (потокобезопасно, OOP API)
  ├── wordclouds.py  — облака слов
  └── pdf_export.py  — генерация PDF-отчётов
```

## Установка

### 1. Клонирование и зависимости

```bash
git clone https://github.com/kristnoir-gif/insight-tg-bot.git
cd insight-tg-bot
pip install -r requirements.txt
python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab'); nltk.download('stopwords')"
```

### 2. Настройка

```bash
cp .env.example .env
```

Отредактируйте `.env`:

```env
API_ID=your_api_id          # https://my.telegram.org/apps
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token    # от @BotFather
SESSION_NAME=user_session
```

### 3. Создание Telethon-сессии

При первом запуске Telethon запросит номер телефона и код авторизации:

```bash
python3 main.py
```

### 4. Запуск

```bash
python3 main.py
```

Проверка здоровья: `http://localhost:8080/health`

## Тестирование

```bash
pip install pytest
python3 -m pytest tests/ -x -q
```

CI запускается на Python 3.11 и 3.12 через GitHub Actions.

## Деплой

Бот работает как systemd-сервис. Пример unit-файла: `tg-bot.service`.

```bash
# Скопировать на сервер
rsync -avz --exclude-from='.gitignore' . server:/opt/bot_tg/

# Включить сервис
sudo cp tg-bot.service /etc/systemd/system/
sudo systemctl enable --now tg-bot
```

> **Важно:** На сервере нужен пакет `fonts-dejavu-core` для графиков matplotlib.

## Ключевые решения

- **Пул аккаунтов** — 3 Telethon-аккаунта с автоматической ротацией при FloodWait, приоритетная очередь для отложенных анализов
- **Двухуровневый кэш** — in-memory + диск (`cache/`) для минимизации запросов к API
- **Потокобезопасные графики** — только OOP API matplotlib (`fig.savefig()`, никогда `plt.savefig()`) для избежания race conditions
- **Атомарные платежи** — единая транзакция для обновления баланса + записи платежа, уведомление админа при сбое
- **Ленивая загрузка NLP** — модели pymorphy3/Natasha (~2с) загружаются при первом использовании, не при импорте

## Лицензия

MIT
