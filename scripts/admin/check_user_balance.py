#!/usr/bin/env python3
"""
Скрипт для проверки баланса пользователя и восстановления платежей.
Использование: python3 check_user_balance.py USER_ID
"""
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "users.db"


def check_user_balance(user_id: int):
    """Проверяет баланс и историю платежей пользователя."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"\n🔍 Проверка пользователя {user_id}\n")
    print("=" * 60)
    
    # 1. Информация о пользователе
    cursor.execute("""
        SELECT user_id, username, paid_balance, request_count, 
               daily_requests_count, last_request_date, 
               premium_until, first_seen
        FROM users
        WHERE user_id = ?
    """, (user_id,))
    
    user = cursor.fetchone()
    
    if not user:
        print(f"❌ Пользователь {user_id} не найден в базе данных!")
        print("\nВозможные причины:")
        print("1. Пользователь никогда не взаимодействовал с ботом")
        print("2. Неверный ID пользователя")
        conn.close()
        return
    
    uid, username, paid_balance, total_req, daily_req, last_date, premium, first_seen = user
    
    print(f"\n👤 ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ:")
    print(f"   ID: {uid}")
    print(f"   Username: @{username or 'нет'}")
    print(f"   💰 Баланс: {paid_balance or 0} анализов")
    print(f"   📊 Всего запросов: {total_req}")
    print(f"   📅 Последний запрос: {last_date or 'никогда'}")
    print(f"   ⭐ Premium: {'Да' if premium and datetime.fromisoformat(premium) > datetime.now() else 'Нет'}")
    print(f"   📆 В системе с: {first_seen}")
    
    # 2. История платежей
    cursor.execute("""
        SELECT id, stars, amount, payment_method, status, notes, created_at
        FROM payments
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,))
    
    payments = cursor.fetchall()
    
    print(f"\n💳 ИСТОРИЯ ПЛАТЕЖЕЙ ({len(payments)} записей):")
    
    if not payments:
        print("   ⚠️  Нет записей о платежах!")
        print("\n   Возможные причины:")
        print("   1. Платёж прошёл, но не был залогирован (баг)")
        print("   2. Пользователь ещё не платил")
        print("   3. База данных была очищена")
    else:
        total_stars = 0
        total_analyses = 0
        
        for payment_id, stars, amount, method, status, notes, created_at in payments:
            print(f"\n   📝 Платёж #{payment_id}:")
            print(f"      ⭐ Звёзд: {stars}")
            print(f"      💵 Сумма: {amount}")
            print(f"      📦 Пакет: {notes}")
            print(f"      ✅ Статус: {status}")
            print(f"      📅 Дата: {created_at}")
            
            total_stars += stars or 0
            
            # Подсчитываем анализы
            if notes == "pack_3":
                total_analyses += 3
            elif notes == "pack_10":
                total_analyses += 10
            elif notes == "pack_50":
                total_analyses += 50
        
        print(f"\n   📊 ИТОГО:")
        print(f"      ⭐ Всего звёзд: {total_stars}")
        print(f"      📈 Должно быть анализов: {total_analyses}")
        print(f"      💰 Текущий баланс: {paid_balance or 0}")
        
        # Проверяем несоответствие
        analyses_used = total_analyses - (paid_balance or 0)
        print(f"      📊 Использовано: {analyses_used}")
        
        if total_analyses != (paid_balance or 0):
            print(f"\n      ⚠️  НЕСООТВЕТСТВИЕ ОБНАРУЖЕНО!")
            if paid_balance == 0 and total_analyses > 0:
                print(f"      🔧 Баланс пустой, но были платежи на {total_analyses} анализов!")
                print(f"\n      💡 РЕКОМЕНДАЦИЯ: Восстановить баланс")
    
    # 3. История использования (pending analyses)
    cursor.execute("""
        SELECT id, channel_username, status, created_at
        FROM pending_analyses
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 10
    """, (user_id,))
    
    pending = cursor.fetchall()
    
    if pending:
        print(f"\n⏳ НЕЗАВЕРШЕННЫЕ АНАЛИЗЫ ({len(pending)} записей):")
        for pid, channel, status, created in pending:
            print(f"   • @{channel} - {status} ({created})")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print()


def restore_user_balance(user_id: int, analyses_count: int):
    """Восстанавливает баланс пользователя."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Проверяем существует ли пользователь
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        print(f"❌ Пользователь {user_id} не найден!")
        conn.close()
        return
    
    # Обновляем баланс
    cursor.execute("""
        UPDATE users
        SET paid_balance = paid_balance + ?
        WHERE user_id = ?
    """, (analyses_count, user_id))
    
    conn.commit()
    conn.close()
    
    print(f"✅ Баланс пользователя {user_id} увеличен на {analyses_count} анализов")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ Использование: python3 check_user_balance.py USER_ID")
        print("Пример: python3 check_user_balance.py 123456789")
        print("\nДополнительно:")
        print("  Восстановить баланс: python3 check_user_balance.py USER_ID restore ЧИСЛО")
        print("  Пример: python3 check_user_balance.py 123456789 restore 10")
        sys.exit(1)
    
    user_id = int(sys.argv[1])
    
    if len(sys.argv) >= 4 and sys.argv[2] == "restore":
        analyses_count = int(sys.argv[3])
        print(f"\n🔧 Восстановление баланса для пользователя {user_id}...")
        restore_user_balance(user_id, analyses_count)
    
    check_user_balance(user_id)
