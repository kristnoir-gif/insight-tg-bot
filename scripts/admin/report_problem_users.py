#!/usr/bin/env python3
"""
Отчёт о пользователях которые заплатили но не получили анализы.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "users.db"

def get_problem_users():
    """Получает список пользователей с проблемами."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("=" * 80)
    print("ОТЧЁТ: ПОЛЬЗОВАТЕЛИ КОТОРЫЕ ЗАПЛАТИЛИ НО НЕ ПОЛУЧИЛИ АНАЛИЗЫ")
    print("=" * 80)
    
    # 1. Те у кого есть pending анализы
    print("\n1️⃣ PENDING АНАЛИЗЫ (не завершены из-за FloodWait):\n")
    cursor.execute("""
        SELECT 
          u.user_id,
          COALESCE(u.username, 'NO_USER') as username,
          COUNT(DISTINCT p.id) as платежей,
          SUM(p.stars) as потратили_звёзд,
          u.paid_balance as осталось_на_балансе,
          COUNT(pa.id) as незаконченные_анализы
        FROM users u
        INNER JOIN payments p ON u.user_id = p.user_id
        LEFT JOIN pending_analyses pa ON u.user_id = pa.user_id AND pa.status = 'pending'
        WHERE pa.id IS NOT NULL
        GROUP BY u.user_id
        ORDER BY COUNT(pa.id) DESC
    """)
    
    rows = cursor.fetchall()
    if not rows:
        print("   ✅ Нет пользователей с pending анализами")
    else:
        for row in rows:
            print(f"   user_id {row[0]:12} | @{row[1]:20} | "
                  f"платежей: {row[2]} | звёзд: {row[3]:3} | "
                  f"осталось: {row[4]:2} | pending: {row[5]}")
    
    # 2. Те у кого на балансе остались деньги
    print("\n2️⃣ НА БАЛАНСЕ ОСТАЛИСЬ ЗВЁЗДЫ (не потрачены):\n")
    cursor.execute("""
        SELECT 
          u.user_id,
          COALESCE(u.username, 'NO_USER') as username,
          COUNT(DISTINCT p.id) as платежей,
          SUM(p.stars) as всего_потратил,
          u.paid_balance as осталось_на_балансе,
          (SUM(p.stars) - u.paid_balance) as уже_потратил
        FROM users u
        INNER JOIN payments p ON u.user_id = p.user_id
        WHERE u.paid_balance > 0
        GROUP BY u.user_id
        ORDER BY u.paid_balance DESC
    """)
    
    rows = cursor.fetchall()
    if not rows:
        print("   ✅ Все звёзды потрачены")
    else:
        for row in rows:
            print(f"   user_id {row[0]:12} | @{row[1]:20} | "
                  f"платежей: {row[2]} | всего: {row[3]:3} | "
                  f"осталось: {row[4]:2} | потрачено: {row[5]}")
    
    # 3. Статистика
    print("\n3️⃣ ОБЩАЯ СТАТИСТИКА:\n")
    cursor.execute("""
        SELECT 
          (SELECT COUNT(DISTINCT user_id) FROM payments) as платящих_юзеров,
          (SELECT COUNT(DISTINCT user_id) FROM pending_analyses WHERE status = 'pending') as с_pending,
          (SELECT COUNT(DISTINCT user_id) FROM users WHERE paid_balance > 0) as с_балансом
    """)
    
    stats = cursor.fetchone()
    print(f"   Платящих пользователей: {stats[0]}")
    print(f"   С pending анализами: {stats[1]}")
    print(f"   С осталось на балансе: {stats[2]}")
    
    print("\n" + "=" * 80)
    conn.close()

if __name__ == "__main__":
    get_problem_users()
