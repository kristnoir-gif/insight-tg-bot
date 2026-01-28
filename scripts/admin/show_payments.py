#!/usr/bin/env python3
"""Получить отчёт по платежам из базы."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "users.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Получаем платящих пользователей
cursor.execute("""
    SELECT 
        u.user_id,
        u.username,
        u.paid_balance,
        COUNT(p.id) as payment_count,
        SUM(p.stars) as total_stars
    FROM users u
    LEFT JOIN payments p ON u.user_id = p.user_id
    WHERE u.paid_balance > 0 OR p.id IS NOT NULL
    GROUP BY u.user_id
    ORDER BY COALESCE(SUM(p.stars), 0) DESC
""")

rows = cursor.fetchall()

print("\n" + "="*90)
print("💳 ОТЧЁТ ПО ПЛАТЕЖАМ ИЗ БАЗЫ ДАННЫХ")
print("="*90 + "\n")

if not rows:
    print("❌ Нет данных о платежах\n")
else:
    print(f"{'ID':<12} {'Username':<25} {'Баланс':<10} {'Платежей':<10} {'Всего ⭐':<10}")
    print("-"*90)
    
    total_users = 0
    total_payments = 0
    total_stars = 0
    
    for uid, username, balance, payment_count, total in rows:
        username_str = f"@{username}" if username else "нет"
        balance = balance or 0
        payment_count = payment_count or 0
        total = total or 0
        
        print(f"{uid:<12} {username_str:<25} {balance:<10} {payment_count:<10} {total:<10}")
        
        total_users += 1
        total_payments += payment_count
        total_stars += total
    
    print("-"*90)
    
    print(f"\n📊 ИТОГО:")
    print(f"   👥 Платящих пользователей: {total_users}")
    print(f"   💳 Всего платежей: {total_payments}")
    print(f"   ⭐ Всего звёзд: {total_stars}")
    
    if total_users > 0:
        print(f"   📈 Средний платёж на пользователя: {total_stars / total_users:.1f} ⭐")

# Проверяем таблицу payments
cursor.execute("SELECT COUNT(*) FROM payments")
payments_count = cursor.fetchone()[0]

print(f"\n📋 ТАБЛИЦА PAYMENTS:")
print(f"   Записей в payments: {payments_count}")

if payments_count > 0:
    cursor.execute("SELECT user_id, stars, notes, created_at FROM payments ORDER BY created_at DESC LIMIT 5")
    print("   Последние 5 платежей:")
    for user_id, stars, notes, created_at in cursor.fetchall():
        print(f"      • User {user_id}: {notes} ({stars} ⭐) - {created_at}")
else:
    print("   ⚠️ Таблица payments пуста - платежи не логируются!")

conn.close()
print()
