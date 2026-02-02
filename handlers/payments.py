"""
Обработчики платежей: /buy, pre_checkout, successful_payment, callback_buy_*.
"""
import logging

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message

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
    get_ab_group,
    get_prices,
    SUPPORT_PRICE,
)

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("buy"))
async def cmd_buy(message: types.Message) -> None:
    """Обработчик команды /buy — покупка анализов."""
    if not await _check_access(message):
        return

    user = message.from_user
    register_user(user.id, user.username)
    log_buy_click(user.id, f"open_menu_{get_ab_group(user.id)}")

    status = check_user_access(user.id)

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
        f"*Что входит в полный анализ:*\n"
        f"• Облако слов + топ-15\n"
        f"• Анализ тональности\n"
        f"• Мат-облако\n"
        f"• Активность по дням/часам\n"
        f"• Упоминаемые личности\n"
        f"• Популярные фразы\n"
        f"• Топ-20 эмодзи\n\n"
        f"Выберите пакет:",
        parse_mode="Markdown",
        reply_markup=_get_buy_keyboard(user.id),
    )


@router.message(F.text == "💎 Купить анализы")
async def handle_buy_button(message: types.Message) -> None:
    """Обработчик кнопки покупки в основном меню."""
    await cmd_buy(message)


@router.callback_query(F.data == "buy_pack_1")
async def callback_buy_pack_1(callback: types.CallbackQuery) -> None:
    """Обработчик покупки 1 полного анализа."""
    user = callback.from_user
    group = get_ab_group(user.id)
    prices = get_prices(user.id)
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить 1 полный анализ [group={group}]")
    log_buy_click(user.id, f"pack_1_{group}")
    await callback.answer()

    await callback.message.answer_invoice(
        title="1 полный анализ",
        description="Попробуйте полный анализ канала: тональность, активность, личности, фразы",
        payload="pack_1",
        currency="XTR",
        prices=[LabeledPrice(label="1 полный анализ", amount=prices['pack_1'])],
    )


@router.callback_query(F.data == "buy_pack_3")
async def callback_buy_pack_3(callback: types.CallbackQuery) -> None:
    """Обработчик покупки пакета 3 полных анализов."""
    user = callback.from_user
    group = get_ab_group(user.id)
    prices = get_prices(user.id)
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить 3 полных анализа [group={group}]")
    log_buy_click(user.id, f"pack_3_{group}")
    await callback.answer()

    await callback.message.answer_invoice(
        title="3 полных анализа",
        description="Полный анализ 3 каналов: тональность, активность, личности, фразы, эмодзи",
        payload="pack_3",
        currency="XTR",
        prices=[LabeledPrice(label="3 полных анализа", amount=prices['pack_3'])],
    )


@router.callback_query(F.data == "buy_pack_10")
async def callback_buy_pack_10(callback: types.CallbackQuery) -> None:
    """Обработчик покупки пакета 10 полных анализов."""
    user = callback.from_user
    group = get_ab_group(user.id)
    prices = get_prices(user.id)
    logger.info(f"Пользователь {user.id} (@{user.username}) нажал купить 10 полных анализов [group={group}]")
    log_buy_click(user.id, f"pack_10_{group}")
    await callback.answer()

    await callback.message.answer_invoice(
        title="10 полных анализов",
        description="Полный анализ 10 каналов",
        payload="pack_10",
        currency="XTR",
        prices=[LabeledPrice(label="10 полных анализов", amount=prices['pack_10'])],
    )


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

    expected = None
    if payload in ("pack_1", "pack_3", "pack_10"):
        expected = get_prices(user_id)[payload]
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

    # Гарантируем что пользователь есть в БД перед добавлением баланса
    register_user(user.id, user.username)

    group = get_ab_group(user.id)
    logger.info(f"Успешный платёж от {user.id}: {payload}, {payment.total_amount} Stars [group={group}]")

    if payload == "pack_1":
        process_pack_payment(user.id, 1, payment.total_amount, "telegram_stars", f"pack_1_{group}")
        record_payment("pack_1", payment.total_amount)
        log_buy_click(user.id, f"paid_{payload}_{group}")
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "💎 На ваш баланс добавлен *1 полный анализ*.\n\n"
            "Отправьте юзернейм канала для полного анализа!",
            parse_mode="Markdown",
        )
    elif payload == "pack_3":
        result = process_pack_payment(user.id, 3, payment.total_amount, "telegram_stars", f"pack_3_{group}")
        logger.info(f"💰 Платеж pack_3: user={user.id}, result={result}")
        record_payment("pack_3", payment.total_amount)
        log_buy_click(user.id, f"paid_{payload}_{group}")
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
    elif payload == "pack_10":
        process_pack_payment(user.id, 10, payment.total_amount, "telegram_stars", f"pack_10_{group}")
        record_payment("pack_10", payment.total_amount)
        log_buy_click(user.id, f"paid_{payload}_{group}")
        await message.answer(
            "✅ *Спасибо за покупку!*\n\n"
            "💎 На ваш баланс добавлено *10 полных анализов*.\n\n"
            "Отправьте юзернейм канала для полного анализа!",
            parse_mode="Markdown",
        )
    elif payload == "support":
        log_payment(user.id, stars=payment.total_amount, payment_method="telegram_stars", notes="support")
        record_payment("support", payment.total_amount)
        await message.answer(
            "💎 *Огромное спасибо за поддержку проекта!*\n\n"
            "Ваш вклад помогает развивать бот и делать его лучше.\n"
            "Мы очень ценим вашу поддержку! 🙏",
            parse_mode="Markdown",
        )
    elif payload == "donate":
        log_payment(user.id, stars=payment.total_amount, payment_method="telegram_stars", notes="donate")
        record_payment("donate", payment.total_amount)
        await message.answer(
            "❤️ *Спасибо за поддержку!*\n\n"
            "Ваш донат очень ценен для развития бота!",
            parse_mode="Markdown",
        )
