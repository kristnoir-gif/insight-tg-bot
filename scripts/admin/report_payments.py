#!/usr/bin/env python3
"""
Отчёт по платежам и использованию анализов.
Показывает всех пользователей, которые платили, сколько анализов куплено и использовано.
"""
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "users.db"


def generate_payments_report():
    """Генерирует отчёт по платежам."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Получаем всех пользователей с платежами
    cursor.execute("""
        SELECT u.user_id, u.username, u.paid_balance, u.request_count,
               COUNT(p.id) as payment_count, SUM(p.stars) as total_stars,
               MAX(p.created_at) as last_payment
        FROM users u
        LEFT JOIN payments p ON u.user_id = p.user_id
        WHERE p.id IS NOT NULL
        GROUP BY u.user_id
        ORDER BY MAX(p.created_at) DESC
    """)
    
    rows = cursor.fetchall()
    
    print("\n" + "="*100)
    print("💳 ОТЧЁТ ПО ПЛАТЕЖАМ И ИСПОЛЬЗОВАНИЮ АНАЛИЗОВ")
    print("="*100 + "\n")
    
    if not rows:
        print("❌ Нет платежей в базе данных\n")
        conn.close()
        return
    
    # Заголовок таблицы
    print(f"{'ID':<12} {'Username':<20} {'Куплено':<10} {'Использ.':<10} {'Осталось':<10} {'Платежей':<10} {'Последний':<20}")
    print("-"*100)
    
    total_bought = 0
    total_used = 0
    
    for user_id, username, balance, requests, payment_count, total_stars, last_payment in rows:
        # Подсчитываем сколько анализов куплено
        cursor.execute("""
            SELECT SUM(
                CASE 
                    WHEN notes = 'pack_3' THEN 3
                    WHEN notes = 'pack_10' THEN 10
                    WHEN notes = 'pack_50' THEN 50
                    ELSE 0
                END
            ) as total
            FROM payments
            WHERE user_id = ?
        """, (user_id,))
        
        result = cursor.fetchone()
        analyses_bought = result[0] or 0
        
        balance = balance or 0
        analyses_used = analyses_bought - balance
        
        # Форматируем дату
        last_payment_str = ""
        if last_payment:
            try:
                last_payment_dt = datetime.fromisoformat(last_payment)
                last_payment_str = last_payment_dt.strftime("%Y-%m-%d %H:%M")
            except:
                last_payment_str = last_payment[:16]
        
        print(f"{user_id:<12} @{username or 'нет':<19} {analyses_bought:<10} {analyses_used:<10} {balance:<10} {payment_count:<10} {last_payment_str:<20}")
        
        total_bought += analyses_bought
        total_used += analyses_used
    
    print("-"*100)
    remaining = total_bought - total_used
    print(f"{'ВСЕГО:':<12} {'':<20} {total_bought:<10} {total_used:<10} {remaining:<10}")
    
    print(f"\n📊 СТАТИСТИКА:")
    print(f"   💰 Всего куплено анализов: {total_bought}")
    print(f"   📊 Всего использовано: {total_used}")
    print(f"   ⏳ Осталось в системе: {remaining}")
    print(f"   👥 Всего платящих пользователей: {len(rows)}")
    
    if total_bought > 0:
        usage_percent = (total_used / total_bought) * 100
        print(f"   📈 Процент использования: {usage_percent:.1f}%")
    
    print()
    conn.close()


def show_user_details(user_id: int):
    """Показывает детали платежей конкретного пользователя."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Получаем информацию о пользователе
    cursor.execute("""
        SELECT user_id, username, paid_balance, request_count, first_seen
        FROM users
        WHERE user_id = ?
    """, (user_id,))
    
    user = cursor.fetchone()
    
    if not user:
        print(f"❌ Пользователь {user_id} не найден")
        conn.close()
        return
    
    uid, username, balance, requests, first_seen = user
    
    print(f"\n👤 Пользователь @{username or 'нет'} (ID: {user_id})")
    print(f"   Текущий баланс: {balance or 0} анализов")
    print(f"   Всего запросов: {requests}")
    print(f"   В системе с: {first_seen}\n")
    
    # Получаем платежи
    cursor.execute("""
        SELECT id, stars, amount, payment_method, notes, created_at
        FROM payments
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,))
    
    payments = cursor.fetchall()
    
    if not payments:
        print("   ❌ Нет платежей\n")
        conn.close()
        return
    
    print("   💳 Платежи:")
    total_analyses = 0
    
    for pid, stars, amount, method, notes, created_at in payments:
        analyses = 0
        if notes == "pack_3":
            analyses = 3
        elif notes == "pack_10":
            analyses = 10
        elif notes == "pack_50":
            analyses = 50
        
        total_analyses += analyses
        print(f"      • {notes}: {analyses} анализов ({stars} ⭐) - {created_at}")
    
    analyses_used = total_analyses - (balance or 0)
    print(f"\n   📊 Итого:")
    print(f"      Куплено: {total_analyses} анализов")
    print(f"      Использовано: {analyses_used}")
    print(f"      Осталось: {balance or 0}\n")
    
    conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        # Показать детали конкретного пользователя
        user_id = int(sys.argv[1])
        show_user_details(user_id)
    else:
        # Показать общий отчёт
        generate_payments_report()
