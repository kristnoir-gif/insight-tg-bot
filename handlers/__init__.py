"""
Пакет обработчиков Telegram-бота.
"""
from aiogram import Router

from handlers.common import set_bot_instance
from handlers import user, payments, admin

# Главный роутер, включающий все подроутеры
router = Router()

# Порядок важен: payments.router (с F.successful_payment) должен быть перед user.router (с F.text)
router.include_router(payments.router)
router.include_router(admin.router)
router.include_router(user.router)

__all__ = ["router", "set_bot_instance"]
