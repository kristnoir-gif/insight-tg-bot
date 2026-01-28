#!/usr/bin/env python3
"""
Отчёт о пользователях с платёжными балансами.
Так как таблица payments пока пуста, берём данные из колонки paid_balance.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "users.db"


def generate_balance_report():
    """Генерирует отчёт о пользователях с балансами."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Получаем всех пользователей с ненулевым балансом
    cursor.execute("""
        SELECT user_id, username, paid_balance, request_count, first_seen, last_request_date
        FROM users
        WHERE paid_balance > 0
        ORDER BY paid_balance DESC, first_seen ASC
    """)
    
    rows = cursor.fetchall()
    
    print("\n" + "="*110)
    print("💰 ОТЧЁТ О ПОЛЬЗОВАТЕЛЯХ С ПЛАТЕЖНЫМИ БАЛАНСАМИ")
    print("="*110 + "\n")
    
    if not rows:
        print("❌ Нет пользователей с балансом!\n")
        print("ℹ️  Примечание:")
        print("   • Таблица payments на сервере пока пуста")
        print("   • Балансы хранятся в колонке paid_balance таблицы users")
        print("   • Это может означать, что платежи не логируются в таблицу payments\n")
        conn.close()
        return
    
    # Заголовок таблицы
    print(f"{'ID':<12} {'Username':<20} {'Баланс':<10} {'Запросов':<10} {'Последний':<15} {'В системе':<19}")
    print("-"*110)
    
    total_balance = 0
    users_with_balance = 0
    
    for user_id, username, balance, requests, first_seen, last_request_date in rows:
        username_str = f"@{username}" if username else "@нет"
        last_request = last_request_date if last_request_date else "никогда"
        
        print(f"{user_id:<12} {username_str:<20} {balance:<10} {requests:<10} {last_request:<15} {first_seen[:19]:<19}")
        
        total_balance += balance
        users_with_balance += 1
    
    print("-"*110)
    print(f"{'ВСЕГО:':<12} {'':<20} {total_balance:<10}")
    
    print(f"\n📊 СТАТИСТИКА:")
    print(f"   👥 Пользователей с балансом: {users_with_balance}")
    print(f"   💰 Общий баланс в системе: {total_balance} анализов")
    print(f"   📈 Средний баланс на пользователя: {total_balance / users_with_balance:.1f} анализов")
    
    # Получаем общую статистику
    cursor.execute("SELECT COUNT(*), SUM(paid_balance) FROM users")
    total_users, total_all_balance = cursor.fetchone()
    
    print(f"\n📋 ОБЩАЯ СТАТИСТИКА:")
    print(f"   👥 Всего пользователей: {total_users}")
    print(f"   💰 Общий баланс всех пользователей: {total_all_balance or 0} анализов")
    print(f"   📊 Процент пользователей с балансом: {(users_with_balance / total_users * 100) if total_users > 0 else 0:.1f}%")
    
    print()
    conn.close()


def show_user_details(user_id: int):
    """Показывает детали пользователя."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT user_id, username, paid_balance, request_count, 
               first_seen, last_request_date, daily_requests_count,
               premium_until
        FROM users
        WHERE user_id = ?
    """, (user_id,))
    
    user = cursor.fetchone()
    
    if not user:
        print(f"❌ Пользователь {user_id} не найден\n")
        conn.close()
        return
    
    uid, username, balance, requests, first_seen, last_request_date, daily_count, premium_until = user
    
    print(f"\n" + "="*60)
    print(f"👤 ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ")
    print("="*60)
    print(f"\n   ID: {uid}")
    print(f"   Username: @{username or 'нет'}")
    print(f"   💰 Текущий баланс: {balance or 0} анализов")
    print(f"   📊 Всего запросов: {requests}")
    print(f"   📅 Сегодня запросов: {daily_count or 0}")
    print(f"   🕐 Последний запрос: {last_request_date or 'никогда'}")
    print(f"   🎯 Premium: {'Да' if premium_until else 'Нет'}")
    print(f"   📆 В системе с: {first_seen}")
    print()
    
    conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        user_id = int(sys.argv[1])
        show_user_details(user_id)
    else:
        generate_balance_report()
