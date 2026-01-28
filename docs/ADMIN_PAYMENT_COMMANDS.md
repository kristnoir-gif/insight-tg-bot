#!/usr/bin/env python3
"""
Команда для бота: /payment_report — показывает отчёт по платежам в Telegram
"""

# Добавить в handlers.py следующие команды:

PAYMENT_REPORT_COMMAND = """
@router.message(Command("payment_report"))
async def cmd_payment_report(message: types.Message) -> None:
    \"\"\"Отчёт по платежам (только для админа).\"\"\"
    user = message.from_user
    
    if not is_admin(user.id):
        await message.answer("❌ Только админ может использовать эту команду")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Пользователи с балансом
    cursor.execute(\"\"\"
        SELECT user_id, username, paid_balance, request_count, last_request_date
        FROM users
        WHERE paid_balance > 0
        ORDER BY paid_balance DESC
    \"\"\")
    
    users = cursor.fetchall()
    conn.close()
    
    if not users:
        await message.answer("📭 Нет пользователей с балансом")
        return
    
    text = "💰 *ОТЧЁТ ПО ПЛАТЕЖАМ*\\n\\n"
    text += f"👥 Пользователей с балансом: {len(users)}\\n"
    
    total = 0
    for uid, username, balance, requests, last_request in users[:15]:  # Top 15
        username_str = f"@{username}" if username else "нет username"
        text += f"\\n• {uid} ({username_str}): {balance} анализов (использовано: {requests})"
        total += balance
    
    text += f"\\n\\n💰 Общий баланс: {total} анализов"
    
    if len(users) > 15:
        text += f"\\n...и ещё {len(users) - 15} пользователей"
    
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("fix_payment"))
async def cmd_fix_payment(message: types.Message) -> None:
    \"\"\"Исправить баланс пользователя: /fix_payment USER_ID AMOUNT\"\"\"
    user = message.from_user
    
    if not is_admin(user.id):
        await message.answer("❌ Только админ может использовать эту команду")
        return
    
    args = message.text.split()
    
    if len(args) < 3:
        await message.answer(
            "❌ Использование: /fix_payment USER_ID AMOUNT\\n"
            "Пример: /fix_payment 123456789 10",
            parse_mode="Markdown"
        )
        return
    
    target_user_id = int(args[1])
    amount = int(args[2])
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Проверяем пользователя
    cursor.execute("SELECT username, paid_balance FROM users WHERE user_id = ?", (target_user_id,))
    result = cursor.fetchone()
    
    if not result:
        cursor.close()
        conn.close()
        await message.answer(f"❌ Пользователь {target_user_id} не найден")
        return
    
    username, current_balance = result
    
    # Обновляем баланс
    cursor.execute(
        "UPDATE users SET paid_balance = paid_balance + ? WHERE user_id = ?",
        (amount, target_user_id)
    )
    
    new_balance = current_balance + amount
    
    conn.commit()
    conn.close()
    
    text = (
        f"✅ *Баланс исправлен*\\n\\n"
        f"👤 Пользователь: {target_user_id} (@{username})\\n"
        f"💰 Было: {current_balance}\\n"
        f"➕ Добавлено: {amount}\\n"
        f"✅ Стало: {new_balance}"
    )
    
    await message.answer(text, parse_mode="Markdown")
    
    # Уведомляем пользователя
    try:
        await _bot_instance.send_message(
            target_user_id,
            f"✅ *Ваш баланс пополнен!*\\n\\n"
            f"➕ Добавлено: {amount} анализов\\n"
            f"Новый баланс: {new_balance} анализов",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить пользователя {target_user_id}: {e}")
"""

print("📝 Добавьте эти команды в handlers.py:")
print(PAYMENT_REPORT_COMMAND)
