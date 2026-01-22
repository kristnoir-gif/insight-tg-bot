# Настройка Прокси для Telegram Бота

## Проблема
Когда все 3 аккаунта находятся на одном IP-адресе, Telegram блокирует весь IP целиком, вызывая одновременный FloodWait на всех аккаунтах.

## Решение
Использовать SOCKS5 прокси для маршрутизации каждого клиента через разные IP-адреса.

## Как это работает
```
Основной клиент → Прокси 1 (IP A) → Telegram
Backup клиент   → Прокси 2 (IP B) → Telegram  
Третий клиент   → Прокси 3 (IP C) → Telegram
```

## Установка Прокси

### Вариант 1: Бесплатные Прокси (не рекомендуется)
1. Найти бесплатные SOCKS5 прокси (например, на https://www.proxy-list.download/)
2. Указать в `.env`:
```
PROXY_MAIN=socks5://proxy1.example.com:1080
PROXY_BACKUP=socks5://proxy2.example.com:1080
PROXY_THIRD=socks5://proxy3.example.com:1080
```

### Вариант 2: Платные Прокси (РЕКОМЕНДУЕТСЯ)

#### SmartProxy (~$2-5/месяц за 3 IP)
1. Зарегистрироваться на https://smartproxy.com
2. Создать 3 rotating proxy с разными exit IP
3. В `.env` указать:
```
PROXY_MAIN=socks5://user123:pass456@gate.smartproxy.com:7000
PROXY_BACKUP=socks5://user123:pass456@gate.smartproxy.com:7001
PROXY_THIRD=socks5://user123:pass456@gate.smartproxy.com:7002
```

#### IPRoyal (~$3-8/месяц)
1. Зарегистрироваться на https://iproyal.com
2. Купить proxy пакет
3. Указать в `.env`:
```
PROXY_MAIN=socks5://username:password@gw.iproyal.com:12321
PROXY_BACKUP=socks5://username:password@gw.iproyal.com:12321
PROXY_THIRD=socks5://username:password@gw.iproyal.com:12321
```

#### Bright Data (Luminati)
1. Зарегистрироваться на https://brightdata.com
2. Создать proxy port для каждого аккаунта
3. Указать в `.env`:
```
PROXY_MAIN=http://username-country-us:password@proxy.provider.com:port1
PROXY_BACKUP=http://username-country-us:password@proxy.provider.com:port2
PROXY_THIRD=http://username-country-us:password@proxy.provider.com:port3
```

## Форматы Прокси

Telethon поддерживает следующие форматы:

### SOCKS5
```
socks5://host:port
socks5://user:pass@host:port
```

### HTTP/HTTPS
```
http://host:port
http://user:pass@host:port
https://host:port
https://user:pass@host:port
```

### MTProto Proxy
```
mtproto://host:port/secret
```

## Проверка Подключения

### 1. Посмотреть логи
```bash
tail -f bot.log | grep -i proxy
```

Должны появиться сообщения типа:
```
INFO: Основной клиент: используется прокси socks5://proxy1.example.com:1080
INFO: Backup клиент: используется прокси socks5://proxy2.example.com:1080
INFO: Третий клиент: используется прокси socks5://proxy3.example.com:1080
```

### 2. Проверить IP адреса в коде
Добавить в `handlers.py` функцию для проверки:
```python
async def cmd_check_ip(message):
    """Проверяет текущий IP каждого клиента"""
    try:
        me = await get_current_client().get_me()
        ip_info = await get_current_client().invoke(GetConfig())
        await message.answer(f"Информация клиента:\n{me}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
```

### 3. Мониторить в Telegram
Отправить сообщение в тестовый канал с каждого аккаунта и проверить IP в логах Telegram (Web версия).

## Отключение Прокси

Чтобы отключить прокси, просто оставить переменные пустыми в `.env`:
```
PROXY_MAIN=
PROXY_BACKUP=
PROXY_THIRD=
```

## Рекомендации

1. **Выберите платный сервис** - бесплатные прокси часто неработоспособны
2. **Разные страны** - если возможно, выберите разные географические регионы
3. **Ротация IP** - если сервис поддерживает, используйте ротацию каждые 10-60 минут
4. **Мониторинг** - регулярно проверяйте что прокси работают
5. **Резервный план** - имейте запасной аккаунт без прокси на случай сбоя

## Если FloodWait продолжается

1. Увеличьте `RATE_LIMIT_SECONDS` в [config.py](config.py) до 300-600 секунд
2. Добавьте еще 1-2 аккаунта с прокси
3. Включите `PENDING_ANALYSES_ENABLED` для сохранения незаконченных анализов
4. Используйте `/send_pending` команду для обработки очереди когда FloodWait пройдет

## Трубелшутинг

### Ошибка: "Не удалось запустить backup клиент"
- Проверьте что сессия существует
- Проверьте что прокси доступен
- Посмотрите полный лог ошибки

### Ошибка: "Connection refused"
- Прокси сервер не запущен или недоступен
- Проверьте URL прокси
- Проверьте подключение к интернету

### Ошибка: "Authentication failed"
- Неправильное имя пользователя/пароль для прокси
- Проверьте учетные данные в `.env`

### Все еще получаю FloodWait
- Telegram может заблокировать диапазон IP прокси-сервиса
- Попробуйте другого провайдера прокси
- Увеличьте задержки между запросами

## Стоимость

- **SmartProxy**: от $2.99/месяц (вращающиеся IP)
- **IPRoyal**: от $3/месяц (выделенные IP)
- **Bright Data**: от $10/месяц (премиум сервис)
- **Бесплатные**: $0 но очень ненадежные

**Рекомендация**: SmartProxy обеспечивает лучше соотношение цена/качество для этого случая.
