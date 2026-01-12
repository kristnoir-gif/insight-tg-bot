# Telegram Channel Analytics Bot

Бот для анализа текстового контента публичных Telegram-каналов с генерацией визуальных отчётов.

## Возможности

- **Облако смыслов** — визуализация ключевых слов канала
- **Топ-15 слов** — график частотности слов
- **Облако мата** — анализ ненормативной лексики
- **Позитивные/негативные слова** — облака по настроению
- **Статистика по дням недели** — средняя длина постов
- **Статистика по часам** — время публикаций
- **Топ имён** — упомянутые люди и личности
- **Топ фраз** — частые триграммы (3-словные фразы)
- **Топ эмодзи** — частые эмодзи в постах

## Структура проекта

```
bot_tg/
├── config.py              # Конфигурация из .env
├── nlp/
│   ├── __init__.py
│   ├── constants.py       # Стоп-слова, словари настроений
│   └── processor.py       # Обработка текста, лемматизация
├── visualization/
│   ├── __init__.py
│   ├── wordclouds.py      # Генерация облаков слов
│   └── charts.py          # Генерация графиков
├── analyzer.py            # Логика анализа каналов
├── handlers.py            # Обработчики команд бота
├── main.py                # Точка входа
├── .env                   # Секреты (не в git)
├── .env.example           # Шаблон для .env
└── README.md
```

## Технологический стек

| Компонент | Библиотека |
|-----------|------------|
| Telegram Bot API | aiogram 3.x |
| Telegram Client | telethon |
| NLP (русский) | pymorphy2, nltk |
| Визуализация | matplotlib, wordcloud |
| Эмодзи | emoji |
| Конфигурация | python-dotenv |

## Установка

### 1. Клонирование
```bash
git clone <repo-url>
cd bot_tg
```

### 2. Зависимости
```bash
pip install aiogram telethon pymorphy2 nltk matplotlib wordcloud numpy emoji python-dotenv
```

### 3. Настройка окружения
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

### 4. Первый запуск
```bash
python3 main.py
```

При первом запуске Telethon запросит авторизацию (номер телефона и код из Telegram).

## Использование

1. Найдите бота в Telegram: `@insight_tg_bot`
2. Отправьте `/start`
3. Отправьте юзернейм канала (например: `polozhnyak`)
4. Получите визуальный отчёт

## Тестирование

### Проверка импортов
```bash
python3 -c "
from config import API_ID, BOT_TOKEN
from nlp.processor import get_clean_words, extract_emojis
from visualization.wordclouds import generate_main_cloud
from visualization.charts import generate_top_words_chart
from analyzer import analyze_channel
from handlers import router
print('Все импорты OK')
"
```

### Тест NLP
```bash
python3 -c "
from nlp.processor import get_clean_words, extract_emojis

text = 'Привет! Это тестовое сообщение о Python. Москва красивый город!'
words = get_clean_words(text, 'normal')
print(f'Слова: {words}')

emojis = extract_emojis('Привет! 🔥💪😊')
print(f'Эмодзи: {emojis}')
"
```

### Тест визуализации
```bash
python3 -c "
from collections import Counter
from visualization.wordclouds import generate_main_cloud
from visualization.charts import generate_top_words_chart
import os

words = ['тест', 'код', 'python', 'тест', 'код', 'данные']
cloud = generate_main_cloud('test', words, 'Тест')
print(f'Облако: {cloud}')

graph = generate_top_words_chart('test', Counter(words), 'Тест', top_n=3)
print(f'График: {graph}')

# Очистка
for f in ['cloud_test.png', 'graph_test.png']:
    if os.path.exists(f): os.remove(f)
print('Тестовые файлы удалены')
"
```

### Запуск бота (фоновый режим)
```bash
nohup python3 main.py > /tmp/bot_log.txt 2>&1 &
echo $! > /tmp/bot_pid.txt
```

### Мониторинг
```bash
# Логи в реальном времени
tail -f /tmp/bot_log.txt

# Статус процесса
ps -p $(cat /tmp/bot_pid.txt) -o pid,stat,etime

# Остановка
kill $(cat /tmp/bot_pid.txt)
```

## API

### NLP Processor

```python
from nlp.processor import get_clean_words, extract_emojis

# Режимы обработки:
# 'normal' - существительные и прилагательные
# 'mats' - ненормативная лексика
# 'person' - имена собственные

words = get_clean_words(text, mode='normal')
emojis = extract_emojis(text)
```

### Analyzer

```python
from analyzer import analyze_channel, AnalysisResult

result: AnalysisResult = await analyze_channel(client, 'channel_name', limit=500)

# Результат содержит:
# - result.title - название канала
# - result.stats.unique_count - уникальные слова
# - result.stats.avg_len - средняя длина поста
# - result.stats.scream_index - индекс "крика"
# - result.cloud_path, result.graph_path, ... - пути к изображениям
# - result.top_emojis - топ эмодзи
```

### Visualization

```python
from visualization.wordclouds import generate_main_cloud, generate_sentiment_cloud
from visualization.charts import generate_top_words_chart, generate_hour_chart

# Все функции возвращают путь к PNG файлу или None
path = generate_main_cloud(username, words, title)
path = generate_sentiment_cloud(username, words, title, sentiment='positive')
path = generate_top_words_chart(username, counter, title, top_n=15)
```

## Конфигурация

Все настройки в `config.py`:

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `API_ID` | Telegram API ID | из .env |
| `API_HASH` | Telegram API Hash | из .env |
| `BOT_TOKEN` | Токен бота | из .env |
| `SESSION_NAME` | Имя файла сессии | user_session |
| `MOSCOW_TZ` | Временная зона | UTC+3 |
| `DPI` | Качество изображений | 150 |
| `MAX_WORDS_CLOUD` | Макс. слов в облаке | 200 |
| `DEFAULT_MESSAGE_LIMIT` | Лимит сообщений | 500 |

## Логирование

Бот использует стандартный Python logging:

```
2026-01-12 21:26:19 | INFO | __main__ | Бот успешно запущен
2026-01-12 21:26:19 | INFO | analyzer | Начат анализ канала: polozhnyak
2026-01-12 21:26:19 | INFO | visualization.wordclouds | Создано облако слов: cloud_polozhnyak.png
```

## Известные проблемы

### database is locked
Если файл сессии заблокирован:
```bash
pkill -9 -f python
rm -f *.session-journal
python3 main.py
```

### Conflict: terminated by other getUpdates
Другой экземпляр бота уже запущен. Остановите его и подождите 30 секунд:
```bash
pkill -f "python3 main.py"
sleep 30
python3 main.py
```

## Лицензия

MIT
