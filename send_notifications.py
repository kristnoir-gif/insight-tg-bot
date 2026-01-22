"""
Скрипт для отправки уведомлений платящим пользователям о незавершённых анализах.
Используется для восстановления после сбоев FloodWait.
"""
import asyncio
import logging
from aiogram import Bot
from config import BOT_TOKEN
from db import get_paid_user_ids, check_user_access, get_pending_analyses_for_user

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


async def send_notifications():
    """Отправляет уведомления всем платящим пользователям."""
    bot = Bot(token=BOT_TOKEN)
    
    # Получаем всех платящих пользователей
    paid_users = get_paid_user_ids()
    
    if not paid_users:
        logger.warning("❌ Нет платящих пользователей")
        await bot.session.close()
        return
    
    logger.info(f"📤 Начинаю отправку для {len(paid_users)} пользователей...")
    
    success_count = 0
    failed_count = 0
    
    for user_id in paid_users:
        try:
            status = check_user_access(user_id)
            
            # Пропускаем если нет баланса и не премиум
            if status.paid_balance <= 0 and not status.is_premium:
                continue
            
            # Проверяем незавершённые анализы
            pending = get_pending_analyses_for_user(user_id)
            
            if pending:
                # Есть незавершённые анализы
                text = (
                    "📊 *Привет!*\n\n"
                    "Бот был восстановлен и готов продолжить работу!\n\n"
                    f"✅ У вас есть {len(pending)} незавершённых анализов:\n\n"
                )
                
                for i, p in enumerate(pending[:10], 1):  # Максимум 10
                    text += f"{i}. `{p['channel_username']}`\n"
                
                if len(pending) > 10:
                    text += f"\n...и ещё {len(pending) - 10} анализов\n"
                
                text += (
                    "\n💡 *Что делать:*\n"
                    "Напишите название канала и я выполню анализ:\n\n"
                    "`/analyze @channel_name`\n\n"
                    "или просто: `@channel_name`"
                )
                
                await bot.send_message(user_id, text, parse_mode="Markdown")
                logger.info(f"✅ {user_id}: отправлено ({len(pending)} анализов)")
                success_count += 1
            
            else:
                # Нет незавершённых, просто уведомляем
                text = (
                    "✅ *Бот восстановил работу!*\n\n"
                    "Все системы готовы к работе. Можете начинать анализы каналов.\n\n"
                    "Отправьте название канала: `@channel_name` или `/analyze @channel_name`"
                )
                
                await bot.send_message(user_id, text, parse_mode="Markdown")
                logger.info(f"✅ {user_id}: отправлено (статус)")
                success_count += 1
        
        except Exception as e:
            logger.error(f"❌ {user_id}: ошибка - {e}")
            failed_count += 1
        
        # Небольшая задержка между отправками чтобы не спамить API
        await asyncio.sleep(0.5)
    
    await bot.session.close()
    
    # Итоговый результат
    logger.info("")
    logger.info("="*50)
    logger.info(f"✅ Успешно отправлено: {success_count}")
    logger.info(f"❌ Ошибок: {failed_count}")
    logger.info("="*50)


if __name__ == "__main__":
    asyncio.run(send_notifications())
