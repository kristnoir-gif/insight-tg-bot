import ssl
import asyncio
import re
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np
from collections import Counter
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InputMediaPhoto
from telethon import TelegramClient
from wordcloud import WordCloud
import pymorphy2
import nltk
from nltk.corpus import stopwords
from nltk.util import ngrams
from datetime import datetime
from datetime import timezone, timedelta
MOSCOW_TZ = timezone(timedelta(hours=3))

# --- SSL обход ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# --- КОНФИГУРАЦИЯ ---
API_ID = 34404218
API_HASH = '26f2cb869a2293037cc21c796750e616'
BOT_TOKEN = '8570008034:AAHvvU92yovbz6_u7cgBiPl3tdunz3UObw4'

morph = pymorphy2.MorphAnalyzer()
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

russian_stopwords = set(stopwords.words('russian'))
EXTRA_STOP = {'это', 'который', 'свой', 'ваш', 'наш', 'весь', 'такой', 'очень', 'мочь', 'год', 'человек', 'тип', 'кароче', 'вообще', 'просто', 'почему', 'день', 'всё', 'хотеть', 'стать'}
russian_stopwords.update(EXTRA_STOP)

positive_words = set(['радость', 'счастье', 'любовь', 'мечта', 'блаженство', 'восторг', 'удовольствие', 'мир', 'душевность', 'эйфория', 'волшебный', 'влюблённый'])
aggressive_words = set(['злость', 'гнев', 'ненависть', 'страх', 'грусть', 'тревога', 'вредный', 'подлый', 'грубый', 'злой', 'агрессия'])

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_client = TelegramClient('kristina_user', API_ID, API_HASH)

# --- ФУНКЦИИ ОБРАБОТКИ ---

def get_clean_words(text, mode='normal'):
    text = re.sub(r'http\S+', '', text)
    words = re.findall(r'[а-яА-ЯёЁ]+', text)
    clean_words = []

    obscene_roots = ['хуй', 'пизд', 'еба', 'ебл', 'бля', 'хул', 'сук', 'ганд', 'дроч']

    for original_word in words:
        lower_word = original_word.lower()
        parsed = morph.parse(lower_word)[0]
        normal = parsed.normal_form
        if normal == 'деньга':
            normal = 'деньги'

        if mode == 'normal':
            if len(normal) > 2 and normal not in russian_stopwords:
                if parsed.tag.POS in ['NOUN', 'ADJF']:
                    clean_words.append(normal)

        elif mode == 'mats':
            if any(root in normal for root in obscene_roots):
                clean_words.append(normal)

        elif mode == 'person':
            # Улучшенный фильтр: только слова с большой буквы + тег Name + длина >2 + чёрный список
            black_list = {
                'это', 'тот', 'такой', 'весь', 'сам', 'какой', 'мой', 'твой', 'наш', 'ваш',
                'бог', 'дух', 'ангел', 'дьявол', 'чёрт', 'жизнь', 'смерть', 'любовь', 'россия', 'пошл', 'ебунася',
                'мир', 'страна', 'город', 'дом', 'работа', 'день', 'ночь', 'время', 'год', 'дело', 'рука', 'нога'
            }
            if original_word[0].isupper() and len(normal) > 2 and 'Name' in parsed.tag and normal not in black_list:
                clean_words.append(original_word)  # Сохраняем оригинальный регистр

    return clean_words

async def generate_sentiment_cloud(username, words, title, sentiment='positive'):
    if not words:
        return None
    colormap = 'YlGn' if sentiment == 'positive' else 'OrRd'  # Более тёмные оттенки для видимости
    wc = WordCloud(width=1000, height=600, background_color='white', colormap=colormap, max_words=100,
                   min_font_size=10, prefer_horizontal=True)\
        .generate(" ".join(words))

    path = f"{sentiment}_{username}.png"
    fig = plt.figure(figsize=(12, 7), facecolor='white')
    ax = fig.add_axes([0.0, 0.08, 1.0, 0.82])
    ax.imshow(wc.to_image(), interpolation='bilinear')
    ax.axis("off")

    clean_title = re.sub(r'[^\w\s-]', '', title).strip()
    header = "Облако позитивных слов" if sentiment == 'positive' else "Облако агрессивных слов"
    fig.text(0.5, 0.95, f"{header} канала: {clean_title}", fontsize=24, fontweight='bold', ha='center', va='center', color='#1a1a1a')
    fig.text(0.5, 0.03, "@insight_tg_bot", fontsize=14, ha='center', va='center', color='#FFC0CB', alpha=0.9, fontweight='bold')

    plt.savefig(path, dpi=150, facecolor='white')
    plt.close()
    return path

async def generate_mats_cloud(username, mat_words, title):
    if not mat_words:
        return None
    wc = WordCloud(width=1000, height=600, background_color='white', colormap='Reds', max_words=100)\
        .generate(" ".join(mat_words))

    path = f"mats_{username}.png"
    fig = plt.figure(figsize=(12, 7), facecolor='white')
    ax = fig.add_axes([0.0, 0.08, 1.0, 0.82])
    ax.imshow(wc.to_image(), interpolation='bilinear')
    ax.axis("off")

    clean_title = re.sub(r'[^\w\s-]', '', title).strip()
    fig.text(0.5, 0.95, f"Облако мата канала: {clean_title}", fontsize=24, fontweight='bold', ha='center', va='center', color='#1a1a1a')
    fig.text(0.5, 0.03, "@insight_tg_bot", fontsize=14, ha='center', va='center', color='#FFC0CB', alpha=0.9, fontweight='bold')

    plt.savefig(path, dpi=150, facecolor='white')
    plt.close()
    return path

def generate_weekday_avg_chart(username, avg_lens, title):
    days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    values = [avg_lens.get(i, 0) for i in range(7)]

    path = f"weekday_{username}.png"
    fig, ax = plt.subplots(figsize=(12, 7), facecolor='#f8f9fa')
    ax.set_facecolor('#f8f9fa')
    colors = cm.viridis(np.linspace(0.2, 0.8, 7))
    bars = ax.bar(days, values, color=colors, edgecolor='white', linewidth=1)

    clean_title = re.sub(r'[^\w\s-]', '', title).strip()
    fig.text(0.5, 0.94, f"Ср. длина поста по дням недели: {clean_title}", fontsize=22, fontweight='bold', ha='center', va='center', color='#2d3436')
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, height + max(values)*0.01, f'{round(height,1)}', ha='center', fontsize=13, fontweight='bold', color='#2d3436')
    fig.text(0.5, 0.03, "@insight_tg_bot", fontsize=14, ha='center', va='center', color='#FFC0CB', alpha=0.9)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout(rect=[0.01, 0.07, 0.99, 0.90])
    plt.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path

def generate_names_chart(username, top_names, title):
    if len(top_names) < 2:
        return None

    # Фильтруем: минимум 2 упоминания или топ-15 самых частых
    filtered = [item for item in top_names if item[1] >= 2] or top_names[:15]
    filtered = sorted(filtered, key=lambda x: x[1], reverse=True)[:15]

    if not filtered:
        return None

    labels = [x[0] for x in filtered][::-1]
    counts = [x[1] for x in filtered][::-1]

    path = f"names_{username}.png"
    fig, ax = plt.subplots(figsize=(14, 8), facecolor='#f8f9fa')
    ax.set_facecolor('#f8f9fa')

    colors = cm.tab20c(np.linspace(0.1, 0.9, len(labels)))
    bars = ax.barh(labels, counts, color=colors, height=0.65, edgecolor='gray', linewidth=0.8)

    clean_title = re.sub(r'[^\w\s-]', '', title).strip()
    fig.text(0.5, 0.96, f"Топ упомянутых людей и личностей\n{clean_title}", fontsize=22, fontweight='bold', ha='center', color='#1f2937')

    for bar in bars:
        width = bar.get_width()
        ax.text(width + 0.1, bar.get_y() + bar.get_height()/2,
                f' {int(width)} ', va='center', fontsize=12, fontweight='bold',
                color='#111827', bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1.8))

    ax.set_xlim(0, max(counts) * 1.3 if counts else 10)
    ax.tick_params(axis='both', labelsize=11)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    fig.text(0.5, 0.02, "@insight_tg_bot", fontsize=13, ha='center', color='#9f1239', alpha=0.85, fontweight='bold')

    plt.tight_layout(rect=[0.02, 0.06, 0.98, 0.92])
    plt.savefig(path, dpi=160, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return path

def generate_hour_freq_chart(username, hour_counts, title):
    hours = list(range(24))
    values = [hour_counts.get(h, 0) for h in hours]
    max_val = max(values) if values else 1

    path = f"hour_{username}.png"
    fig, ax = plt.subplots(figsize=(14, 7.5), facecolor='#f8f9fa')
    ax.set_facecolor('#f8f9fa')

    # Цвета: ночь — серый, утро/вечер — оранжевый, день — синий
    colors = []
    for h in hours:
        if 0 <= h < 6 or 21 <= h <= 23:
            colors.append('#4b5563')
        elif 6 <= h < 9 or 18 <= h < 21:
            colors.append('#f59e0b')
        else:
            colors.append('#3b82f6')

    bars = ax.bar(hours, values, color=colors, width=0.82, edgecolor='white', linewidth=0.4)

    clean_title = re.sub(r'[^\w\s-]', '', title).strip()
    fig.text(0.5, 0.96, f"Время публикаций постов • {clean_title}", fontsize=22, fontweight='bold', ha='center', color='#111827')

    for bar in bars:
        height = bar.get_height()
        if height > 0:
            ax.text(bar.get_x() + bar.get_width()/2, height + max_val * 0.03,
                    f'{int(height)}', ha='center', va='bottom', fontsize=10, fontweight='bold', color='#111827')

    ax.set_xticks(hours)
    ax.set_xticklabels([f"{h:02d}:00" for h in hours], fontsize=9, rotation=45, ha='right')
    ax.set_yticks(np.arange(0, max_val + max_val * 0.15, max(5, int(max_val / 5))))

    ax.set_xlabel("Час суток (московское время)", fontsize=12, labelpad=10)
    ax.set_ylabel("Количество постов", fontsize=12, labelpad=10)

    ax.grid(axis='y', linestyle='--', alpha=0.3, color='gray')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    fig.text(0.5, 0.02, "@insight_tg_bot", fontsize=13, ha='center', color='#6b7280', alpha=0.9)

    plt.tight_layout(rect=[0.04, 0.12, 0.96, 0.92])
    plt.savefig(path, dpi=160, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return path

def generate_phrases_chart(username, top_phrases, title):
    if not top_phrases:
        return None
    labels = [' '.join(x[0]).upper() for x in top_phrases][::-1]
    counts = [x[1] for x in top_phrases][::-1]

    path = f"phrases_{username}.png"
    fig, ax = plt.subplots(figsize=(12, 7), facecolor='#f8f9fa')
    ax.set_facecolor('#f8f9fa')
    colors = cm.viridis(np.linspace(0.2, 0.8, len(labels)))
    bars = ax.barh(labels, counts, color=colors, edgecolor='white', linewidth=1)

    clean_title = re.sub(r'[^\w\s-]', '', title).strip()
    fig.text(0.5, 0.94, f"Топ-10 часто используемых фраз: {clean_title}", fontsize=22, fontweight='bold', ha='center', va='center', color='#2d3436')
    for bar in bars:
        width = bar.get_width()
        ax.text(width + max(counts)*0.01, bar.get_y() + bar.get_height()/2, f'{int(width)}', va='center', fontsize=13, fontweight='bold', color='#2d3436')
    fig.text(0.5, 0.03, "@insight_tg_bot", fontsize=14, ha='center', va='center', color='#FFC0CB', alpha=0.9)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout(rect=[0.01, 0.07, 0.99, 0.90])
    plt.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path



async def analyze_channel(username, limit=500):
    try:
        if not user_client.is_connected():
            await user_client.connect()

        entity = await user_client.get_entity(username)
        title = entity.title
        messages = [m async for m in user_client.iter_messages(entity, limit=limit) if m.text]
        posts = [(m.date, m.text) for m in messages]

        if not posts:
            return None, None, None, None, None, None, None, None, None, title

        all_words = []
        mat_words = []
        pos_words = []
        agg_words = []
        names = []

        upper_ratios = []
        excl_counts = []

        for date, text in posts:
            all_words.extend(get_clean_words(text, 'normal'))
            mat_words.extend(get_clean_words(text, 'mats'))
            names.extend(get_clean_words(text, 'person'))

            clean = get_clean_words(text, 'normal')
            pos_words.extend(w for w in clean if w in positive_words)
            agg_words.extend(w for w in clean if w in aggressive_words)

            # Индекс крика
            if text:
                alpha_count = sum(1 for c in text if c.isalpha())
                if alpha_count > 0:
                    upper_ratios.append(sum(c.isupper() for c in text) / alpha_count)
                word_count = len(text.split())
                if word_count > 0:
                    excl_counts.append(text.count('!') / word_count)

        if not all_words:
            return None, None, None, None, None, None, None, None, None, title

        # Облако смыслов
        wc = WordCloud(width=1000, height=600, background_color='white', colormap='magma', max_words=200)\
            .generate(" ".join(all_words))
        cloud_path = f"cloud_{username}.png"
        fig = plt.figure(figsize=(12, 7), facecolor='white')
        ax = fig.add_axes([0.0, 0.08, 1.0, 0.82])
        ax.imshow(wc.to_image(), interpolation='bilinear')
        ax.axis("off")
        clean_title = re.sub(r'[^\w\s-]', '', title).strip()
        fig.text(0.5, 0.95, f"Облако смыслов канала: {clean_title}", fontsize=24, fontweight='bold', ha='center', va='center', color='#1a1a1a')
        fig.text(0.5, 0.03, "@insight_tg_bot", fontsize=14, ha='center', va='center', color='#FFC0CB', alpha=0.9, fontweight='bold')
        plt.savefig(cloud_path, dpi=150, facecolor='white')
        plt.close()

        # Топ-15 слов
        top_15 = Counter(all_words).most_common(15)
        w_labels = [x[0].upper() for x in top_15][::-1]
        counts = [x[1] for x in top_15][::-1]
        graph_path = f"graph_{username}.png"
        fig, ax = plt.subplots(figsize=(12, 7), facecolor='#f8f9fa')
        ax.set_facecolor('#f8f9fa')
        colors = cm.plasma(np.linspace(0.2, 0.8, len(w_labels)))
        bars = ax.barh(w_labels, counts, color=colors, edgecolor='white', linewidth=1)
        fig.text(0.5, 0.94, f"Топ-15 ключевых слов канала {clean_title}", fontsize=22, fontweight='bold', ha='center', va='center', color='#2d3436')
        for bar in bars:
            width = bar.get_width()
            ax.text(width + (max(counts or [1]) * 0.01), bar.get_y() + bar.get_height()/2,
                    f'{int(width)}', va='center', fontsize=13, fontweight='bold', color='#2d3436')
        fig.text(0.5, 0.03, "@insight_tg_bot", fontsize=14, ha='center', va='center', color='#FFC0CB', alpha=0.9, fontweight='bold')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        plt.tight_layout(rect=[0.01, 0.07, 0.99, 0.90])
        plt.savefig(graph_path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)

        mats_path = await generate_mats_cloud(username, mat_words, title)
        pos_path = await generate_sentiment_cloud(username, pos_words, title, 'positive')
        agg_path = await generate_sentiment_cloud(username, agg_words, title, 'aggressive')

        # По дням недели
        weekday_lens = {i: [] for i in range(7)}
        for date, text in posts:
            weekday_lens[date.weekday()].append(len(text.split()))
        avg_lens = {wd: np.mean(lens) if lens else 0 for wd, lens in weekday_lens.items()}
        weekday_path = generate_weekday_avg_chart(username, avg_lens, title)

        # По часам
        hour_counts = Counter((date.astimezone(MOSCOW_TZ)).hour for date, _ in posts)
        hour_path = generate_hour_freq_chart(username, hour_counts, title)

        # Имена
        top_names = Counter(names).most_common(30)  # Больше кандидатов для фильтра
        names_path = generate_names_chart(username, top_names, title)

        # Фразы
        all_tokens = []
        for _, text in posts:
            all_tokens.extend(re.findall(r'\b\w+\b', text.lower()))
        trigrams = ngrams(all_tokens, 3)
        top_trigrams = Counter(trigrams).most_common(10)
        phrases_path = generate_phrases_chart(username, top_trigrams, title)

        # Статистика
        avg_upper = np.mean(upper_ratios) if upper_ratios else 0
        avg_excl = np.mean(excl_counts) if excl_counts else 0
        scream_index = round(avg_upper * 100 + avg_excl * 10, 1)

        stats = {
            "unique_count": len(set(all_words)),
            "avg_len": round(np.mean([len(p[1].split()) for p in posts]), 1),
            "scream_index": scream_index
        }

        return cloud_path, graph_path, mats_path, pos_path, agg_path, weekday_path, hour_path, names_path, phrases_path, stats, title

    except Exception as e:
        print(f"Ошибка в анализе: {e}")
        return None, None, None, None, None, None, None, None, None, None, str(e)

# --- 5. ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("📊 Пришли мне юзернейм канала (например: `polozhnyak`), и я выверну его смыслы наизнанку!")

@dp.message(F.text)
async def handle_msg(message: types.Message):
    if message.text.startswith('/'): return
    username = message.text.replace('@', '').split('/')[-1].strip()
    status = await message.answer("🛸 Извлекаю смыслы... Подождите")
    
    res = await analyze_channel(username)
    if res and res[0]:
        cloud_p, graph_p, mats_p, pos_p, agg_p, weekday_p, hour_p, names_p, phrases_p, stats, title = res
        caption = (
            f"📊 Канал: {title}\n\n"
            f"📚 Количество уникальных слов: {stats['unique_count']}\n"
            f"📏 Ср. длина поста: {stats['avg_len']} слов\n"
            f"🗣️ Индекс крика: {stats['scream_index']}"
        )
        media = [InputMediaPhoto(media=FSInputFile(cloud_p), caption=caption), InputMediaPhoto(media=FSInputFile(graph_p))]
        if mats_p: media.append(InputMediaPhoto(media=FSInputFile(mats_p)))
        if pos_p: media.append(InputMediaPhoto(media=FSInputFile(pos_p)))
        if agg_p: media.append(InputMediaPhoto(media=FSInputFile(agg_p)))
        if weekday_p: media.append(InputMediaPhoto(media=FSInputFile(weekday_p)))
        if hour_p: media.append(InputMediaPhoto(media=FSInputFile(hour_p)))
        if names_p: media.append(InputMediaPhoto(media=FSInputFile(names_p)))
        if phrases_p: media.append(InputMediaPhoto(media=FSInputFile(phrases_p)))
        
        await message.answer_media_group(media=media)
        paths = [cloud_p, graph_p, mats_p, pos_p, agg_p, weekday_p, hour_p, names_p, phrases_p]
        for p in paths:
            if p and os.path.exists(p): os.remove(p)
    else:
        await message.answer(f"❌ Ошибка или канал пуст.")
    await status.delete()

# --- 6. ЗАПУСК ---
async def main():
    await user_client.start() 
    await dp.start_polling(bot, skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())