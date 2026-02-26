"""
Обработчики платежей: /buy, pre_checkout, successful_payment, callback_buy_*.
"""
import logging
import os

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message, InputMediaPhoto, FSInputFile

from metrics import record_payment
from db import (
    register_user,
    check_user_access,
    process_pack_payment,
    log_payment,
    log_buy_click,
)
from handlers.common import (
    _check_access,
    _get_buy_keyboard,
    get_prices,
    get_ab_group,
    SUPPORT_PRICE,
    notify_admin_payment,
)

logger = logging.getLogger(__name__)

router = Router()

EXAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "example")
EXAMPLE_CHANNEL = "новый положняк"
EXAMPLE_ORDER = [
    "cloud.png", "graph.png", "mats.png", "positive.png",
    "aggressive.png", "weekday.png", "hour.png",
    "names.png", "phrases.png", "register.png", "dichotomy.png",
]


async def _send_example(message: types.Message) -> None:
    """Отправляет пример полного анализа."""
    media = []
    for i, filename in enumerate(EXAMPLE_ORDER):
        path = os.path.join(EXAMPLE_DIR, filename)
        if not os.path.exists(path):
            continue
        if i == 0:
            media.append(InputMediaPhoto(
                media=FSInputFile(path),
                caption=(
                    f"📋 <b>Пример полного анализа</b>\n"
                    f"Канал: {EXAMPLE_CHANNEL}\n\n"
                    f"Вот что вы получите при покупке:"
                ),
                parse_mode="HTML",
            ))
        else:
            media.append(InputMediaPhoto(media=FSInputFile(path)))
    if media:
        await message.answer_media_group(media=media)


@router.message(Command("buy"))
async def cmd_buy(message: types.Message) -> None:
    """Обработчик команды /buy — покупка анализов."""
    if not await _check_access(message):
        return

    user = message.from_user
    register_user(user.id, user.username)
    group = get_ab_group(user.id)
    log_buy_click(user.id, f"open_menu_{group}")

    status = check_user_access(user.id)

    # Отправляем пример анализа
    await _send_example(message)

    # Формируем информацию о текущем статусе
    status_text = ""
    if status.is_premium:
        if status.premium_until:
            status_text = f"👑 У вас Premium до {status.premium_until.strftime('%d.%m.%Y')}\n\n"
        else:
            status_text = "👑 У вас безлимитный доступ\n\n"
    elif status.paid_balance > 0:
        status_text = f"💎 Ваш баланс: {status.paid_balance} полных анализов\n\n"
    else:
        status_text = ""

    await message.answer(
        f"💎 *Полный анализ канала*\n\n"
        f"{status_text}"
        f"Выберите пакет:",
        parse_mode="Markdown",
        reply_markup=_get_buy_keyboard(user.id),
    )


@router.message(F.text == "💎 Купить анализы")
async def handle_buy_button(message: types.Message) -> None:
    """Обработчик кнопки покупки в основном меню."""
    await cmd_buy(message)


_PACK_INFO = {
    "pack_1": {"title": "1 полный анализ", "description": "Попробуйте полный анализ канала: тональность, активность, личности, фразы"},
    "pack_3": {"title": "3 полных анализа", "description": "Полный анализ 3 каналов: тональность, активность, личности, фразы, эмодзи"},
    "pack_10": {"title": "10 полных анализов", "description": "Полный анализ 10 каналов"},
}


async def _handle_pack_purchase(callback: types.CallbackQuery, pack: str) -> None:
    """Общий обработчик покупки пакета анализов."""
    user = callback.from_user
    group = get_ab_group(user.id)
    info = _PACK_INFO[pack]
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить {info['title']} (группа {group})")
    log_buy_click(user.id, f"{pack}_{group}")
    await callback.answer()

    prices = get_prices(user.id)
    await callback.message.answer_invoice(
        title=info["title"],
        description=info["description"],
        payload=pack,
        currency="XTR",
        prices=[LabeledPrice(label=info["title"], amount=prices[pack])],
    )


@router.callback_query(F.data == "buy_pack_1")
async def callback_buy_pack_1(callback: types.CallbackQuery) -> None:
    await _handle_pack_purchase(callback, "pack_1")


@router.callback_query(F.data == "buy_pack_3")
async def callback_buy_pack_3(callback: types.CallbackQuery) -> None:
    await _handle_pack_purchase(callback, "pack_3")


@router.callback_query(F.data == "buy_pack_10")
async def callback_buy_pack_10(callback: types.CallbackQuery) -> None:
    await _handle_pack_purchase(callback, "pack_10")


@router.callback_query(F.data == "support")
async def callback_support(callback: types.CallbackQuery) -> None:
    """Обработчик поддержки проекта."""
    user = callback.from_user
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал поддержать проект")
    await callback.answer()

    await callback.message.answer_invoice(
        title="Поддержать проект",
        description="Поддержите развитие бота и помогите сделать его еще лучше!",
        payload="support",
        currency="XTR",
        prices=[LabeledPrice(label="Поддержка проекта", amount=SUPPORT_PRICE)],
    )


@router.callback_query(F.data == "donate")
async def callback_donate(callback: types.CallbackQuery) -> None:
    """Обработчик доната."""
    user = callback.from_user
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал донат")
    await callback.answer()

    await callback.message.answer_invoice(
        title="Поддержать бота",
        description="Спасибо, что пользуетесь ботом!",
        payload="donate",
        currency="XTR",
        prices=[LabeledPrice(label="Донат", amount=1)],
    )


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
    """Обработчик pre-checkout запроса — проверяем сумму перед подтверждением."""
    payload = pre_checkout.invoice_payload
    user_id = pre_checkout.from_user.id
    amount = pre_checkout.total_amount
    prices = get_prices(user_id)

    expected = None
    if payload in ("pack_1", "pack_3", "pack_10"):
        expected = prices[payload]
    elif payload == "support":
        expected = SUPPORT_PRICE
    elif payload == "donate":
        expected = 1

    if expected is not None and amount != expected:
        logger.warning(f"Pre-checkout: сумма {amount} != ожидаемая {expected} для {user_id}, payload={payload}")
        await pre_checkout.answer(ok=False, error_message="Сумма не совпадает с ценой. Попробуйте снова.")
        return

    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    """Обработчик успешного платежа."""
    user = message.from_user
    payment = message.successful_payment
    payload = payment.invoice_payload
    group = get_ab_group(user.id)

    # Гарантируем что пользователь есть в БД перед добавлением баланса
    register_user(user.id, user.username)

    logger.info(f"Успешный платёж от {user.id}: {payload}, {payment.total_amount} Stars (группа {group})")

    if payload == "pack_1":
        process_pack_payment(user.id, 1, payment.total_amount, "telegram_stars", f"pack_1_{group}")
        record_payment("pack_1", payment.total_amount, group)
        log_buy_click(user.id, f"paid_pack_1_{group}")
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "💎 На ваш баланс добавлен *1 полный анализ*.\n\n"
            "Отправьте юзернейм канала для полного анализа!",
            parse_mode="Markdown",
        )
        await notify_admin_payment("1 анализ", payment.total_amount, group)
    elif payload == "pack_3":
        result = process_pack_payment(user.id, 3, payment.total_amount, "telegram_stars", f"pack_3_{group}")
        logger.info(f"💰 Платеж pack_3: user={user.id}, result={result} (группа {group})")
        record_payment("pack_3", payment.total_amount, group)
        log_buy_click(user.id, f"paid_pack_3_{group}")
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "💎 На ваш баланс добавлено *3 полных анализа*.\n\n"
            "Теперь вы получите:\n"
            "• Облако слов + топ-15\n"
            "• Анализ тональности\n"
            "• Мат-облако\n"
            "• Активность по дням/часам\n"
            "• Личности, фразы, эмодзи\n\n"
            "Отправьте юзернейм канала!",
            parse_mode="Markdown",
        )
        await notify_admin_payment("3 анализа", payment.total_amount, group)
    elif payload == "pack_10":
        process_pack_payment(user.id, 10, payment.total_amount, "telegram_stars", f"pack_10_{group}")
        record_payment("pack_10", payment.total_amount, group)
        log_buy_click(user.id, f"paid_pack_10_{group}")
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "💎 На ваш баланс добавлено *10 полных анализов*.\n\n"
            "Отправьте юзернейм канала для полного анализа!",
            parse_mode="Markdown",
        )
        await notify_admin_payment("10 анализов", payment.total_amount, group)
    elif payload == "support":
        log_payment(user.id, stars=payment.total_amount, payment_method="telegram_stars", notes="support")
        record_payment("support", payment.total_amount, group)
        await message.answer(
            "💎 *Огромное спасибо за поддержку проекта!*\n\n"
            "Ваш вклад помогает развивать бот и делать его лучше.\n"
            "Мы очень ценим вашу поддержку! 🙏",
            parse_mode="Markdown",
        )
        await notify_admin_payment("Поддержка", payment.total_amount, group)
    elif payload == "donate":
        log_payment(user.id, stars=payment.total_amount, payment_method="telegram_stars", notes="donate")
        record_payment("donate", payment.total_amount, group)
        await message.answer(
            "❤️ *Спасибо за поддержку!*\n\n"
            "Ваш донат очень ценен для развития бота!",
            parse_mode="Markdown",
        )
        await notify_admin_payment("Донат", payment.total_amount, group)
