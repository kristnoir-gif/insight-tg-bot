#!/usr/bin/env python3
"""Восстановление сессии 211766470_telethon из auth_key"""
import sqlite3
import os

SESSION_FILE = "211766470_telethon.session"
AUTH_KEY_HEX = "5915d4015ab224469a4dd558dc0208d669d31f96c90dac95f6abd521b322500cff450f0367e2d71740f27dfae7ff2e007e61cf66eebeb8d0c1b40c08bad31a95bcc4636fec118151f29a961a680c5b1f5245120cbd2fd444e2aebc35562aa129360b9f33b10e01687b1ac9f684abb765dd1c27ee52e95c998e97e1af81121f268754b4d9ce873c9202251d6dee97c8e71b4ae8bf39af716d3fa90de0d04c4367d4dd39ab5e51fb527e1391f9cebeb98895a716b170934b847d9100fe81ce65b510bf2d432a904651b3f31667dba4fc3387792bda343d12ffe4e276864f085c3b609efcf348e819996ef40a912110b1decb17d6a076d3e570ead91f4ac9805481"
DC_ID = 1

print(f"\n{'='*70}")
print(f"🔧 ВОССТАНОВЛЕНИЕ СЕССИИ: {SESSION_FILE}")
print(f"{'='*70}\n")

if not os.path.exists(SESSION_FILE):
    print(f"❌ Файл {SESSION_FILE} не найден!")
    exit(1)

# Конвертируем hex в bytes
auth_key_bytes = bytes.fromhex(AUTH_KEY_HEX)
print(f"📊 Auth Key:")
print(f"   • Длина: {len(auth_key_bytes)} байт")
print(f"   • DC ID: {DC_ID}")

# Обновляем базу данных
try:
    conn = sqlite3.connect(SESSION_FILE)
    cursor = conn.cursor()
    
    # Проверяем текущее состояние
    cursor.execute("SELECT dc_id, server_address, port FROM sessions WHERE dc_id = ?", (DC_ID,))
    row = cursor.fetchone()
    
    if row:
        print(f"\n📝 Текущая запись:")
        print(f"   • DC ID: {row[0]}")
        print(f"   • Сервер: {row[1]}:{row[2]}")
        
        # Обновляем auth_key
        cursor.execute("""
            UPDATE sessions 
            SET auth_key = ?
            WHERE dc_id = ?
        """, (auth_key_bytes, DC_ID))
        print(f"\n✅ Auth key обновлен!")
    else:
        # Вставляем новую запись с правильным сервером для DC 1
        server_address = "149.154.175.54"  # DC 1
        port = 443
        
        cursor.execute("""
            INSERT INTO sessions (dc_id, server_address, port, auth_key)
            VALUES (?, ?, ?, ?)
        """, (DC_ID, server_address, port, auth_key_bytes))
        print(f"\n✅ Создана новая запись:")
        print(f"   • DC ID: {DC_ID}")
        print(f"   • Сервер: {server_address}:{port}")
    
    conn.commit()
    conn.close()
    
    print(f"\n{'='*70}")
    print(f"✅ СЕССИЯ УСПЕШНО ВОССТАНОВЛЕНА!")
    print(f"{'='*70}\n")
    
except Exception as e:
    print(f"\n❌ ОШИБКА: {e}\n")
    exit(1)
