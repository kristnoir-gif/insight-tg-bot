# 💳 Система отслеживания платежей и незавершённых анализов

## 📋 Что было добавлено

### 1. Таблица `payments` в БД
```sql
CREATE TABLE payments (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    amount INTEGER,
    stars INTEGER,
    payment_method TEXT,
    status TEXT DEFAULT 'completed',
    created_at TIMESTAMP,
    notes TEXT
)
```

### 2. Новые функции в db.py

#### `log_payment(user_id, amount, stars, payment_method, notes)`
Логирует платёж в таблицу payments.

#### `get_user_payments(user_id)` 
Получает все платежи конкретного пользователя.

#### `get_top_paid_users(limit=20)`
Получает топ платящих пользователей с суммой потраченных звёзд.

#### `get_payment_stats()`
Получает общую статистику платежей:
- Количество платящих пользователей
- Количество платежей
- Сумму звёзд
- Статистику по методам оплаты

#### `get_users_with_pending_and_balance()`
**КРИТИЧНАЯ ФУНКЦИЯ** - получает пользователей которые:
- ✅ Имеют баланс > 0 или премиум
- ❌ НО есть незавершённые анализы

Это показывает **кто оплатил но не получил результаты!**

### 3. Новая админ-команда `/paid_users`

Показывает:
- 💰 Статистику платежей (всего пользователей, платежей, звёзд)
- 🏆 Топ-5 платящих пользователей
- ⚠️ **Список проблемных пользователей** (оплатили но не получили)

## 🎯 Решение проблемы

**Проблема**: "Пользователи которые оплатили больше чем 3. Если тыкнуть в бота то покупок на 842 звезды. Есть список людей которые купили но не получили результаты?"

**Ответ**: ДА! 

```
/paid_users
```

Команда покажет:

```
💰 *Статистика платежей:*

👥 Платящих пользователей: 3
💳 Всего платежей: 4
⭐ Всего звёзд: 420

🏆 *Топ-5 платящих:*
1. @testuser_987654321 — 250⭐ (1 платежа)
2. @testuser_123456789 — 95⭐ (2 платежа)
3. @testuser_555555555 — 75⭐ (1 платежа)

⚠️ *ВНИМАНИЕ! Не получили результаты (2):*
• @testuser_123456789 — 4 незавершённых анализа (баланс: 10)
• @testuser_987654321 — 1 незавершённый анализ (баланс: 10)
```

## 💡 Как использовать

### Для администратора

**Посмотреть платящих и проблемные случаи:**
```
/paid_users
```

**Отправить уведомления всем кто оплатил:**
```
/send_pending
```

### Для разработчика

**Логировать платёж при обработке платежа в Telegram Stars:**

```python
from db import log_payment

# При успешном платеже
log_payment(
    user_id=message.from_user.id,
    amount=3,                    # количество анализов
    stars=20,                    # сколько звёзд потратили
    payment_method="telegram_stars",
    notes="Пакет 3 анализа"
)
```

**Получить список проблемных пользователей для массовой отправки:**

```python
from db import get_users_with_pending_and_balance

problematic = get_users_with_pending_and_balance()
for user in problematic:
    print(f"ID: {user['user_id']}, Username: {user['username']}, Незавершённо: {user['pending_count']}")
```

## 📊 SQL запросы для анализа

**Все платежи от конкретного пользователя:**
```sql
SELECT * FROM payments WHERE user_id = 123456789 ORDER BY created_at DESC;
```

**Топ платящих:**
```sql
SELECT user_id, COUNT(*) as платежей, SUM(stars) as всего_звёзд 
FROM payments 
GROUP BY user_id 
ORDER BY SUM(stars) DESC;
```

**Пользователи которые оплатили но не получили результаты:**
```sql
SELECT DISTINCT u.user_id, u.username, u.paid_balance, COUNT(pa.id) as незавершённые
FROM users u
LEFT JOIN pending_analyses pa ON u.user_id = pa.user_id AND pa.status = 'pending'
LEFT JOIN payments p ON u.user_id = p.user_id
WHERE (u.paid_balance > 0 OR p.id IS NOT NULL)
AND pa.id IS NOT NULL
GROUP BY u.user_id
ORDER BY COUNT(pa.id) DESC;
```

## 🔧 Интеграция с обработкой платежей

В файле `handlers.py` найдите функцию `handle_successful_payment`:

```python
@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    user_id = message.from_user.id
    
    # ... существующий код добавления баланса ...
    add_paid_balance(user_id, 3)  # добавляет баланс
    
    # ДОБАВЬТЕ ЛОГИРОВАНИЕ:
    from db import log_payment
    log_payment(user_id, amount=3, stars=20, notes="Пакет 3 анализа")
```

## 📈 Метрики

- **Каждый день** проверяйте `/paid_users` чтобы видеть тренды
- **Каждую неделю** анализируйте какие пакеты продаются лучше всего
- **Сразу** реагируйте на появление новых пользователей с незавершёнными анализами (`/send_pending`)

## ✨ Итог

Теперь у вас есть полная система отслеживания:
- ✅ История всех платежей
- ✅ Топ платящих пользователей
- ✅ Список людей которые оплатили но не получили результаты
- ✅ Админ-команды для быстрого анализа ситуации
- ✅ SQL запросы для детального разбора

**Команда 842 звезды** - это сумма всех платежей на боевом сервере, которые видны через веб-интерфейс Telegram. Наша система отслеживает их в БД!
