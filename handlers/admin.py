"""
Обработчики админских команд: /admin, /broadcast, /stats, /floodstatus, каналы, callback_admin_*.
"""
import os
import logging
import sqlite3
import tempfile
from datetime import datetime

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from client_pool import get_client_pool
from db import (
    get_stats,
    is_admin,
    get_all_user_ids,
    get_paid_user_ids,
    check_user_access,
    get_floodwait_stats,
    get_pending_analyses_for_user,
    remove_pending_analysis,
    get_top_paid_users,
    get_payment_stats,
    get_users_with_pending_and_balance,
    get_buy_funnel,
    get_all_channels_for_admin,
    DB_PATH,
)
from handlers.common import (
    get_bot_instance,
    PRICES_A,
    PRICES_B,
    PRICES_C,
)

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("admin"))
async def cmd_admin(message: types.Message) -> None:
    """Обработчик команды /admin — статистика для администратора."""
    user = message.from_user

    if not is_admin(user.id):
        logger.warning(f"Попытка доступа к /admin от пользователя {user.id}")
        await message.answer("⛔ Доступ запрещён.")
        return

    stats = get_stats()
    payment_stats = get_payment_stats()
    total_stars = payment_stats.get('total_stars', 0)
    logger.info(f"📊 Admin stats: total_requests={stats['total_requests']}, active={stats['active_users']}, users={stats['total_users']}")

    # Статистика по FloodWait за последние 24 часа
    fw_stats = get_floodwait_stats(days=1)

    # Inline-клавиатура с командами
    admin_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=" Статус пула", callback_data="admin_floodstatus"),
                InlineKeyboardButton(text="🧹 Очистить кэш", callback_data="admin_clear_cache")
            ]
        ]
    )

    await message.answer(
        f"📈 *Статистика бота*\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"📊 Всего анализов: {stats['total_requests']}\n"
        f"⭐ Заработано звёзд: {total_stars}\n\n"
        f"🚧 FloodWait за последние 24ч:\n"
        f"• Событий: {fw_stats['total']}\n"
        f"• Пользователей: {fw_stats['users']}\n\n"
        f"🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}",
        parse_mode="Markdown",
        reply_markup=admin_keyboard,
    )


@router.message(Command("clear_floodwait"))
async def cmd_clear_floodwait(message: types.Message) -> None:
    """Админ-команда: сброс cooldown всех аккаунтов."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    pool = get_client_pool()
    pool.clear_cooldowns()
    await message.answer("✅ Cooldown всех аккаунтов сброшен.")


@router.message(Command("floodstatus"))
async def cmd_floodstatus(message: types.Message) -> None:
    """Админ-команда: показать статус пула клиентов."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    pool = get_client_pool()
    await message.answer(pool.status_text(), parse_mode="Markdown")


@router.message(Command("update_description"))
async def cmd_update_description(message: types.Message) -> None:
    """Админ-команда: обновить описание бота прямо сейчас."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    try:
        from utils import format_number, get_bot_stats
        stats = get_bot_stats()
        total_users = stats["total_users"]
        total_channels = stats["total_channels"]
        total_analyses = stats["total_analyses"]

        short_desc = (
            f"📊 Анализ Telegram-каналов\n"
            f"👥 {format_number(total_users)} пользователей\n"
            f"📈 {format_number(total_channels)} каналов | {format_number(total_analyses)} анализов"
        )

        # Обновляем описание
        bot_instance = get_bot_instance()
        await bot_instance.set_my_short_description(short_description=short_desc)

        await message.answer(
            f"✅ *Описание бота обновлено!*\n\n"
            f"👥 {total_users} пользователей\n"
            f"📊 {total_channels} каналов\n"
            f"📈 {total_analyses} анализов",
            parse_mode="Markdown"
        )
        logger.info(f"✅ Описание обновлено вручную админом {user.id}")
    except Exception as e:
        logger.error(f"Ошибка при обновлении описания: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("clear_cache"))
async def cmd_clear_cache(message: types.Message) -> None:
    """Админ-команда: очистить кэш результатов."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    pool = get_client_pool()
    cache_stats = pool.status()["cache"]
    pool.clear_cache()
    await message.answer(f"✅ Кэш очищен. Было {cache_stats['valid']} записей.")


@router.message(Command("clear_floodwait_db"))
async def cmd_clear_floodwait_db(message: types.Message) -> None:
    """Админ-команда: удалить все записи floodwait_events из БД."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    try:
        from db import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM floodwait_events")
            total = cursor.fetchone()[0]
            cursor.execute("DELETE FROM floodwait_events")
            conn.commit()
        await message.answer(f"✅ Удалено {total} записей floodwait_events из БД.")
    except sqlite3.Error as e:
        logger.error(f"Не удалось очистить floodwait_events: {e}")
        await message.answer("❌ Ошибка при очистке БД. Смотрите логи сервиса.")


@router.message(Command("send_pending"))
async def cmd_send_pending(message: types.Message, bot: Bot) -> None:
    """Админ-команда: отправить уведомление платящим пользователям о переповторных анализах."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    paid_users = get_paid_user_ids()

    if not paid_users:
        await message.answer("❌ Нет платящих пользователей.")
        return

    msg = await message.answer(f"📤 Отправляю уведомления {len(paid_users)} платящим пользователям...")

    success_count = 0
    for user_id in paid_users:
        try:
            status = check_user_access(user_id)
            if status.paid_balance > 0 or status.is_premium:
                pending = get_pending_analyses_for_user(user_id)
                if pending:
                    text = f"✅ У вас есть {len(pending)} незавершённых анализов:\n\n"
                    for p in pending[:5]:
                        text += f"• {p['channel_username']}\n"
                    if len(pending) > 5:
                        text += f"\n+ ещё {len(pending) - 5} анализов"
                    text += "\n\nНапишите название канала для переанализа!"

                    await bot.send_message(user_id, text)
                    success_count += 1
                else:
                    await bot.send_message(
                        user_id,
                        "✅ Бот восстановил работу! Ваши запросы готовы к обработке."
                    )
                    success_count += 1
        except TelegramAPIError as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            continue

    await msg.edit_text(f"✅ Отправлено уведомлений: {success_count}/{len(paid_users)}")


@router.message(Command("paid_users"))
async def cmd_paid_users(message: types.Message) -> None:
    """Админ-команда: показать платящих пользователей и тех кто не получил результаты."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    # Статистика платежей
    stats = get_payment_stats()

    # Топ платящих
    top_users = get_top_paid_users(10)

    # Пользователи с проблемами (оплатили но не получили)
    problematic = get_users_with_pending_and_balance()

    # Воронка покупок
    funnel = get_buy_funnel()

    text = (
        f"💰 *Статистика платежей:*\n\n"
        f"👥 Платящих пользователей: {stats.get('unique_users', 0)}\n"
        f"💳 Всего платежей: {stats.get('total_payments', 0)}\n"
        f"⭐ Всего звёзд: {stats.get('total_stars', 0)}\n"
    )

    if funnel:
        text += f"\n📊 *Воронка A/B/C теста:*\n"
        text += f"_A = 10⭐, B = 20⭐, C = 50⭐_\n\n"
        for group in ['a', 'b', 'c']:
            prices = {"a": PRICES_A, "b": PRICES_B, "c": PRICES_C}[group]
            menu = funnel.get(f'open_menu_{group}', {'clicks': 0, 'users': 0})
            text += f"*Группа {group.upper()}* ({prices['pack_1']}/{prices['pack_3']}/{prices['pack_10']}⭐):\n"
            text += f"  Открыли меню: {menu['clicks']} ({menu['users']} чел.)\n"
            for pack in ['pack_1', 'pack_3', 'pack_10']:
                key = f'{pack}_{group}'
                if key in funnel:
                    f = funnel[key]
                    text += f"  Выбрали {pack}: {f['clicks']} ({f['users']} чел.)\n"
                paid_key = f'paid_{pack}_{group}'
                if paid_key in funnel:
                    pf = funnel[paid_key]
                    text += f"  ✅ Оплатили {pack}: {pf['clicks']} ({pf['users']} чел.)\n"
            text += "\n"

    if top_users:
        text += f"\n🏆 *Топ-5 платящих:*\n"
        for i, u in enumerate(top_users[:5], 1):
            text += f"{i}. @{u['username']} — {u['total_stars']}⭐ ({u['payment_count']} платежей)\n"

    if problematic:
        text += f"\n⚠️ *ВНИМАНИЕ! Не получили результаты ({len(problematic)}):*\n"
        for u in problematic[:10]:
            text += f"• @{u['username']} — {u['pending_count']} незавершённых анализов (баланс: {u.get('paid_balance', '?')})\n"

    await message.answer(text, parse_mode="Markdown")


@router.message(Command("payments"))
async def cmd_payments(message: types.Message) -> None:
    """Админ-команда: показать отчёт по платежам."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    from db import get_db_connection
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Платящие пользователи
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

        text = "💳 *ОТЧЁТ ПО ПЛАТЕЖАМ*\n\n"

        if not rows:
            text += "❌ Нет данных о платежах\n"
        else:
            total_users = 0
            total_stars = 0

            for uid, username, balance, payment_count, total in rows:
                uname = f"@{username}" if username else "нет username"
                balance = balance or 0
                total = total or 0

                text += f"• {uname}: баланс={balance}, ⭐={total}\n"

                total_users += 1
                total_stars += total

            text += f"\n*Итого:*\n"
            text += f"👥 Платящих: {total_users}\n"
            text += f"⭐ Звёзд: {total_stars}\n"

        # Проверяем таблицу payments
        cursor.execute("SELECT COUNT(*) FROM payments")
        payments_count = cursor.fetchone()[0]

        text += f"\n📋 Таблица payments: {payments_count} записей"

        if payments_count == 0:
            text += "\n⚠️ ВНИМАНИЕ: Платежи не логируются!"

    await message.answer(text, parse_mode="Markdown")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, bot: Bot) -> None:
    """Обработчик команды /broadcast — рассылка всем пользователям."""
    user = message.from_user

    if not is_admin(user.id):
        logger.warning(f"Попытка рассылки от пользователя {user.id}")
        await message.answer("⛔ Доступ запрещён.")
        return

    text = message.text.replace("/broadcast", "", 1).strip()

    if not text:
        await message.answer(
            "📢 *Рассылка сообщений*\n\n"
            "Использование: `/broadcast Текст сообщения`\n\n"
            "Пример: `/broadcast Привет! У нас новые функции!`",
            parse_mode="Markdown",
        )
        return

    user_ids = get_all_user_ids()
    total = len(user_ids)

    if total == 0:
        await message.answer("❌ Нет пользователей для рассылки.")
        return

    status_msg = await message.answer(f"📤 Начинаю рассылку {total} пользователям...")

    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except TelegramAPIError:
            failed += 1

    await status_msg.edit_text(
        f"✅ *Рассылка завершена*\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"👥 Всего: {total}",
        parse_mode="Markdown",
    )

    logger.info(f"Рассылка завершена: {sent} отправлено, {failed} ошибок")


@router.message(Command("stats"))
async def cmd_stats(message: types.Message) -> None:
    """Админ-команда: графики статистики по базе данных."""
    user = message.from_user
    if not is_admin(user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    await message.answer("📊 Генерирую графики...")

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    from db import get_db_connection
    with get_db_connection() as conn:
        cursor = conn.cursor()

        chart_paths = []

        try:
            # === 1. Новые пользователи по дням (последние 30 дней) ===
            cursor.execute("""
                SELECT DATE(first_seen) as day, COUNT(*) as cnt
                FROM users
                WHERE first_seen >= datetime('now', '-30 days')
                GROUP BY day ORDER BY day
            """)
            user_rows = cursor.fetchall()

            if user_rows:
                days = [datetime.strptime(r[0], "%Y-%m-%d") for r in user_rows]
                counts = [r[1] for r in user_rows]

                cursor.execute("SELECT COUNT(*) FROM users WHERE first_seen < datetime('now', '-30 days')")
                base_users = cursor.fetchone()[0]
                cumulative = []
                total = base_users
                for c in counts:
                    total += c
                    cumulative.append(total)

                fig, ax1 = plt.subplots(figsize=(12, 5))
                ax1.bar(days, counts, color='#6c5ce7', alpha=0.7, label='Новых за день')
                ax1.set_ylabel('Новых за день', color='#6c5ce7')
                ax1.tick_params(axis='y', labelcolor='#6c5ce7')

                ax2 = ax1.twinx()
                ax2.plot(days, cumulative, color='#d63031', linewidth=2, label='Всего')
                ax2.set_ylabel('Всего пользователей', color='#d63031')
                ax2.tick_params(axis='y', labelcolor='#d63031')

                ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
                ax1.xaxis.set_major_locator(mdates.DayLocator(interval=3))
                fig.autofmt_xdate()
                plt.title('Пользователи (30 дней)', fontweight='bold', pad=15)
                fig.tight_layout()

                p = tempfile.mktemp(suffix='_users.png')
                fig.savefig(p, dpi=150, facecolor='white')
                plt.close(fig)
                chart_paths.append(p)

            # === 2. Анализы по дням ===
            cursor.execute("""
                SELECT DATE(last_analyzed) as day, SUM(analysis_count) as cnt
                FROM channel_stats
                WHERE last_analyzed >= datetime('now', '-30 days')
                GROUP BY day ORDER BY day
            """)
            analysis_rows = cursor.fetchall()

            if analysis_rows:
                days_a = [datetime.strptime(r[0], "%Y-%m-%d") for r in analysis_rows]
                counts_a = [r[1] for r in analysis_rows]

                fig, ax = plt.subplots(figsize=(12, 5))
                ax.bar(days_a, counts_a, color='#00b894', alpha=0.8)
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
                fig.autofmt_xdate()
                ax.set_ylabel('Анализов')
                plt.title('Анализы по дням (30 дней)', fontweight='bold', pad=15)
                fig.tight_layout()

                p = tempfile.mktemp(suffix='_analyses.png')
                fig.savefig(p, dpi=150, facecolor='white')
                plt.close(fig)
                chart_paths.append(p)

            # === 3. Выручка (звёзды) по дням ===
            cursor.execute("""
                SELECT DATE(created_at) as day, SUM(stars) as total_stars, COUNT(*) as tx_count
                FROM payments
                WHERE created_at >= datetime('now', '-30 days')
                AND status = 'completed'
                GROUP BY day ORDER BY day
            """)
            revenue_rows = cursor.fetchall()

            if revenue_rows:
                days_r = [datetime.strptime(r[0], "%Y-%m-%d") for r in revenue_rows]
                stars_r = [r[1] for r in revenue_rows]

                cum_stars = []
                s = 0
                for st in stars_r:
                    s += st
                    cum_stars.append(s)

                fig, ax1 = plt.subplots(figsize=(12, 5))
                ax1.bar(days_r, stars_r, color='#fdcb6e', alpha=0.8, label='⭐ за день')
                ax1.set_ylabel('Звёзд за день', color='#e17055')
                ax1.tick_params(axis='y', labelcolor='#e17055')

                ax2 = ax1.twinx()
                ax2.plot(days_r, cum_stars, color='#e17055', linewidth=2, marker='o', markersize=4)
                ax2.set_ylabel('Накопительно ⭐', color='#e17055')

                ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
                ax1.xaxis.set_major_locator(mdates.DayLocator(interval=3))
                fig.autofmt_xdate()

                cursor.execute("SELECT SUM(stars) FROM payments WHERE status = 'completed'")
                total_all_stars = cursor.fetchone()[0] or 0
                plt.title(f'Выручка (30 дней) — всего за всё время: {total_all_stars}⭐', fontweight='bold', pad=15)
                fig.tight_layout()

                p = tempfile.mktemp(suffix='_revenue.png')
                fig.savefig(p, dpi=150, facecolor='white')
                plt.close(fig)
                chart_paths.append(p)

            # === 4. A/B/C тест воронки ===
            funnel = get_buy_funnel()
            if funnel:
                groups = {'a': {}, 'b': {}, 'c': {}}
                for action, data in funnel.items():
                    for g in ('a', 'b', 'c'):
                        if action.endswith(f'_{g}'):
                            groups[g][action.replace(f'_{g}', '')] = data

                stages = ['open_menu', 'pack_1', 'pack_3', 'pack_10', 'paid_total']
                labels = ['Открыли меню', '1 анализ', '3 анализа', '10 анализов', 'Оплатили']

                for g in ('a', 'b', 'c'):
                    paid_total_clicks = sum(groups[g].get(f'paid_pack_{p}', {}).get('clicks', 0) for p in ('1', '3', '10'))
                    paid_total_users = sum(groups[g].get(f'paid_pack_{p}', {}).get('users', 0) for p in ('1', '3', '10'))
                    groups[g]['paid_total'] = {'clicks': paid_total_clicks, 'users': paid_total_users}

                a_clicks = [groups['a'].get(s, {}).get('clicks', 0) for s in stages]
                b_clicks = [groups['b'].get(s, {}).get('clicks', 0) for s in stages]
                c_clicks = [groups['c'].get(s, {}).get('clicks', 0) for s in stages]

                # Платежи по группам
                cursor.execute("""
                    SELECT notes, COUNT(*), SUM(stars)
                    FROM payments
                    WHERE status = 'completed' AND notes IS NOT NULL
                    GROUP BY notes
                """)
                pay_rows = cursor.fetchall()
                a_paid = sum(r[1] for r in pay_rows if r[0] and '_a' in r[0])
                b_paid = sum(r[1] for r in pay_rows if r[0] and '_b' in r[0])
                c_paid = sum(r[1] for r in pay_rows if r[0] and '_c' in r[0])
                a_stars = sum(r[2] for r in pay_rows if r[0] and '_a' in r[0])
                b_stars = sum(r[2] for r in pay_rows if r[0] and '_b' in r[0])
                c_stars = sum(r[2] for r in pay_rows if r[0] and '_c' in r[0])

                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

                x = range(len(labels))
                w = 0.25
                ax1.bar([i - w for i in x], a_clicks, w, color='#74b9ff', label='A (10⭐)')
                ax1.bar(list(x), b_clicks, w, color='#fdcb6e', label='B (20⭐)')
                ax1.bar([i + w for i in x], c_clicks, w, color='#ff7675', label='C (50⭐)')
                ax1.set_xticks(x)
                ax1.set_xticklabels(labels, rotation=15)
                ax1.set_ylabel('Клики')
                ax1.legend()
                ax1.set_title('Воронка покупок (клики)')

                bar_labels = ['Покупок', 'Звёзд ⭐']
                a_vals = [a_paid, a_stars]
                b_vals = [b_paid, b_stars]
                c_vals = [c_paid, c_stars]
                x2 = range(len(bar_labels))
                ax2.bar([i - w for i in x2], a_vals, w, color='#74b9ff', label=f'A ({a_paid} покупок, {a_stars}⭐)')
                ax2.bar(list(x2), b_vals, w, color='#fdcb6e', label=f'B ({b_paid} покупок, {b_stars}⭐)')
                ax2.bar([i + w for i in x2], c_vals, w, color='#ff7675', label=f'C ({c_paid} покупок, {c_stars}⭐)')
                ax2.set_xticks(x2)
                ax2.set_xticklabels(bar_labels)
                ax2.legend()
                ax2.set_title('A/B/C тест: результат')

                fig.suptitle('A/B/C тест цен', fontweight='bold', fontsize=14)
                fig.tight_layout()

                p = tempfile.mktemp(suffix='_ab_test.png')
                fig.savefig(p, dpi=150, facecolor='white')
                plt.close(fig)
                chart_paths.append(p)

            if not chart_paths:
                await message.answer("📊 Недостаточно данных для построения графиков.")
                return

            # Отправляем медиагруппу
            media = []
            for i, path in enumerate(chart_paths):
                caption = "📊 Статистика бота" if i == 0 else None
                media.append(InputMediaPhoto(media=FSInputFile(path), caption=caption))

            await message.answer_media_group(media=media)

            # Удаляем временные файлы
            for path in chart_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass

        except Exception as e:
            logger.exception(f"Ошибка генерации графиков: {e}")
            await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("broadcast_paid"))
async def cmd_broadcast_paid(message: types.Message, bot: Bot) -> None:
    """Обработчик команды /broadcast_paid — рассылка пользователям с балансом."""
    user = message.from_user

    if not is_admin(user.id):
        logger.warning(f"Попытка рассылки от пользователя {user.id}")
        await message.answer("⛔ Доступ запрещён.")
        return

    text = message.text.replace("/broadcast_paid", "", 1).strip()

    if not text:
        await message.answer(
            "📢 *Рассылка платным пользователям*\n\n"
            "Использование: `/broadcast_paid Текст сообщения`\n\n"
            "Отправляет сообщение только тем, у кого paid\\_balance > 0",
            parse_mode="Markdown",
        )
        return

    user_ids = get_paid_user_ids()
    total = len(user_ids)

    if total == 0:
        await message.answer("❌ Нет пользователей с балансом для рассылки.")
        return

    status_msg = await message.answer(f"📤 Начинаю рассылку {total} платным пользователям...")

    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            await bot.send_message(uid, text, parse_mode="Markdown")
            sent += 1
        except TelegramAPIError:
            failed += 1

    await status_msg.edit_text(
        f"✅ *Рассылка платным завершена*\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"👥 Всего платных: {total}",
        parse_mode="Markdown",
    )

    logger.info(f"Рассылка платным завершена: {sent} отправлено, {failed} ошибок")


# --- Callback handlers ---

@router.callback_query(F.data == "admin_help")
async def callback_admin_help(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Справка по командам'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await callback.answer()

    help_text = (
        "🔐 *АДМИНСКИЕ КОМАНДЫ*\n\n"
        "📊 *Статистика и мониторинг:*\n"
        "`/admin` — основная статистика\n"
        "`/floodstatus` — статус пула клиентов\n"
        "`/payments` — отчёт по платежам\n"
        "`/paid_users` — детальная статистика\n\n"
        "🛠️ *Управление ботом:*\n"
        "`/clear_floodwait` — сброс cooldown\n"
        "`/clear_cache` — очистка кэша\n"
        "`/clear_floodwait_db` — очистка FloodWait БД\n\n"
        "📢 *Рассылки:*\n"
        "`/broadcast <текст>` — всем\n"
        "`/broadcast_paid <текст>` — платящим\n"
        "`/send_pending` — уведомление о незавершённых\n\n"
        "💡 Используйте кнопки ниже для быстрого доступа"
    )

    await callback.message.answer(help_text, parse_mode="Markdown")


@router.callback_query(F.data == "admin_payments")
async def callback_admin_payments(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Платежи'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await callback.answer()

    temp_message = callback.message
    temp_message.from_user = callback.from_user
    await cmd_payments(temp_message)


@router.callback_query(F.data == "admin_paid_users")
async def callback_admin_paid_users(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Платящие пользователи'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await callback.answer()

    temp_message = callback.message
    temp_message.from_user = callback.from_user
    await cmd_paid_users(temp_message)


@router.callback_query(F.data == "admin_floodstatus")
async def callback_admin_floodstatus(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Статус пула'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await callback.answer()

    pool = get_client_pool()
    await callback.message.answer(pool.status_text(), parse_mode="Markdown")


@router.callback_query(F.data == "admin_clear_cache")
async def callback_admin_clear_cache(callback: types.CallbackQuery) -> None:
    """Обработчик кнопки 'Очистить кэш'."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    pool = get_client_pool()
    cache_stats = pool.status()["cache"]
    pool.clear_cache()

    await callback.answer(f"✅ Кэш очищен ({cache_stats['valid']} записей)", show_alert=True)


# --- Каналы ---

async def show_channels_menu(message_or_query, page: int = 0):
    """Показывает меню выбора каналов с пагинацией."""
    channels = get_all_channels_for_admin()

    if not channels:
        if isinstance(message_or_query, types.Message):
            await message_or_query.answer("📭 Нет каналов в базе данных")
        else:
            await message_or_query.message.answer("📭 Нет каналов в базе данных")
        return

    items_per_page = 8
    total_pages = (len(channels) + items_per_page - 1) // items_per_page

    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1

    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_channels = channels[start_idx:end_idx]

    keyboard = []

    for i in range(0, len(page_channels), 2):
        row = []
        for j in range(2):
            if i + j < len(page_channels):
                ch = page_channels[i + j]
                title = ch['title'][:18] + '..' if len(ch['title']) > 20 else ch['title']
                row.append(InlineKeyboardButton(
                    text=f"📺 {title}",
                    callback_data=f"select_ch:{ch['channel_key']}"
                ))
        keyboard.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"ch_page:{page - 1}"
        ))

    nav_row.append(InlineKeyboardButton(
        text=f"📄 {page + 1}/{total_pages}",
        callback_data="ch_noop"
    ))

    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=f"ch_page:{page + 1}"
        ))

    keyboard.append(nav_row)

    keyboard.append([
        InlineKeyboardButton(text="❌ Закрыть", callback_data="ch_close")
    ])

    text = (
        f"📋 *Выберите канал для анализа*\n\n"
        f"Всего каналов: {len(channels)}\n"
        f"Страница {page + 1} из {total_pages}"
    )

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    if isinstance(message_or_query, types.Message):
        await message_or_query.answer(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        try:
            await message_or_query.message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        except TelegramBadRequest:
            pass


@router.callback_query(F.data.startswith("ch_page:"))
async def callback_channels_page(query: types.CallbackQuery):
    """Пагинация списка каналов."""
    page = int(query.data.split(":")[1])
    await show_channels_menu(query, page)
    await query.answer()


@router.callback_query(F.data.startswith("select_ch:"))
async def callback_select_channel(query: types.CallbackQuery):
    """Выбор канала для анализа."""
    user = query.from_user

    if not is_admin(user.id):
        await query.answer("⛔ Доступ запрещён", show_alert=True)
        return

    channel_key = query.data.split(":", 1)[1]

    try:
        await query.message.delete()
    except Exception:
        pass

    await query.message.answer(
        f"✅ Выбран канал: `{channel_key}`\n\n"
        "🔄 Запускаю анализ...",
        parse_mode="Markdown"
    )

    # Создаем временное сообщение для обработки
    from handlers.user import handle_msg
    temp_message = types.Message(
        message_id=query.message.message_id,
        date=query.message.date,
        chat=query.message.chat,
        from_user=user,
        text=channel_key
    )

    await handle_msg(temp_message)
    await query.answer()


@router.callback_query(F.data == "ch_noop")
async def callback_channels_noop(query: types.CallbackQuery):
    """Пустой callback для кнопки страницы."""
    await query.answer()


@router.callback_query(F.data == "ch_close")
async def callback_channels_close(query: types.CallbackQuery):
    """Закрытие меню каналов."""
    try:
        await query.message.delete()
    except Exception:
        pass
    await query.answer("Меню закрыто")


@router.message(F.text == "📋 Мои каналы")
async def cmd_my_channels_button(message: types.Message):
    """Обработчик кнопки выбора каналов."""
    user = message.from_user

    if not is_admin(user.id):
        return

    await show_channels_menu(message, page=0)


@router.message(F.text.startswith("📊 Админка"))
async def handle_admin_button(message: types.Message) -> None:
    """Обработчик кнопки админки."""
    await cmd_admin(message)
