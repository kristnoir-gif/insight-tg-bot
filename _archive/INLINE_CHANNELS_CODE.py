"""
Упрощенная версия выбора каналов через Inline клавиатуру.
Использовать вместо Web App если не нужен HTTPS.
"""

# Добавьте эти функции в handlers.py после других функций

async def show_channels_menu(message: types.Message, page: int = 0):
    """Показывает меню выбора каналов с пагинацией."""
    from db import get_all_channels_for_admin
    
    channels = get_all_channels_for_admin()
    
    if not channels:
        await message.answer("📭 Нет каналов в базе данных")
        return
    
    # Пагинация
    items_per_page = 8
    total_pages = (len(channels) + items_per_page - 1) // items_per_page
    
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_channels = channels[start_idx:end_idx]
    
    # Создаем клавиатуру
    keyboard = []
    
    # Кнопки каналов (по 2 в ряд)
    for i in range(0, len(page_channels), 2):
        row = []
        for j in range(2):
            if i + j < len(page_channels):
                ch = page_channels[i + j]
                # Ограничиваем название до 20 символов
                title = ch['title'][:18] + '..' if len(ch['title']) > 20 else ch['title']
                row.append(InlineKeyboardButton(
                    text=f"📺 {title}",
                    callback_data=f"select_ch:{ch['channel_key']}"
                ))
        keyboard.append(row)
    
    # Навигация
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
    
    # Кнопка закрыть
    keyboard.append([
        InlineKeyboardButton(text="❌ Закрыть", callback_data="ch_close")
    ])
    
    text = (
        f"📋 *Выберите канал для анализа*\n\n"
        f"Всего каналов: {len(channels)}\n"
        f"Страница {page + 1} из {total_pages}"
    )
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    # Если это первый вызов - отправляем новое сообщение
    # Если callback - редактируем существующее
    if isinstance(message, types.Message):
        await message.answer(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        # Это callback query
        await message.message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)


# Обработчики callback'ов

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
    
    # Закрываем меню
    await query.message.delete()
    
    # Отправляем подтверждение
    await query.message.answer(
        f"✅ Выбран канал: `{channel_key}`\n\n"
        "🔄 Запускаю анализ...",
        parse_mode="Markdown"
    )
    
    # Создаем временное сообщение для обработки
    temp_message = types.Message(
        message_id=query.message.message_id,
        date=query.message.date,
        chat=query.message.chat,
        from_user=user,
        text=channel_key
    )
    
    # Запускаем анализ
    await handle_msg(temp_message)
    await query.answer()


@router.callback_query(F.data == "ch_noop")
async def callback_channels_noop(query: types.CallbackQuery):
    """Пустой callback для кнопки страницы."""
    await query.answer()


@router.callback_query(F.data == "ch_close")
async def callback_channels_close(query: types.CallbackQuery):
    """Закрытие меню каналов."""
    await query.message.delete()
    await query.answer("Меню закрыто")


# Обработчик кнопки "📋 Мои каналы"

@router.message(F.text.contains("Мои каналы"))
async def cmd_my_channels_button(message: types.Message):
    """Обработчик кнопки выбора каналов."""
    user = message.from_user
    
    if not is_admin(user.id):
        return
    
    await show_channels_menu(message, page=0)


# ИЗМЕНЕНИЕ В _get_main_keyboard:
# Замените Web App кнопку на обычную:

    if is_admin(user_id):
        keyboard.append([
            KeyboardButton(text="📋 Мои каналы")
        ])
        keyboard.append([
            KeyboardButton(text="📊 Админка")
        ])
