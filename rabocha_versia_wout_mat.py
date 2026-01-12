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

# --- 1. НАСТРОЙКИ (SSL) ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError: 
    pass
else: 
    ssl._create_default_https_context = _create_unverified_https_context

# --- 2. КОНФИГУРАЦИЯ ---
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

# --- 3. ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_client = TelegramClient('kristina_user', API_ID, API_HASH)

# --- 4. ФУНКЦИИ ОБРАБОТКИ ---

def get_clean_words(text, mode='normal'):
    text = re.sub(r'http\S+', '', text)
    words = re.findall(r'[а-яА-ЯёЁ]+', text.lower())
    clean_words = []
    
    # Корни для поиска матов
    obscene_roots = ['хуй', 'пизд', 'еба', 'ебл', 'бля', 'хул', 'сук', 'ганд', 'дроч']
    
    for w in words:
        parsed = morph.parse(w)[0]
        normal = parsed.normal_form
        if normal == 'деньга': normal = 'деньги'

        if mode == 'normal':
            if len(normal) > 2 and normal not in russian_stopwords:
                if parsed.tag.POS in ['NOUN', 'ADJF']:
                    clean_words.append(normal)
        
        elif mode == 'mats':
            # Ищем совпадения с корнями
            if any(root in normal for root in obscene_roots):
                clean_words.append(normal)
                
    return clean_words

async def analyze_channel(username, limit=150):
    try:
        if not user_client.is_connected():
            await user_client.connect()
            
        entity = await user_client.get_entity(username)
        title = entity.title
        posts = [m.text async for m in user_client.iter_messages(entity, limit=limit) if m.text]
        
        if not posts: 
            return None, None, None, title

        all_words = []
        for p in posts:
            all_words.extend(get_clean_words(p, 'normal'))
        
        if not all_words:
            return None, None, None, title
        
# --- 1. ГЕНЕРАЦИЯ ОБЛАКА (УЛЬТРА-КОМПАКТ) ---
        wc = WordCloud(
            width=1000, 
            height=600, 
            background_color='white', 
            colormap='magma',
            max_words=200
        ).generate(" ".join(all_words))
        
        cloud_path = f"cloud_{username}.png"
        # Уменьшили высоту до 7
        fig = plt.figure(figsize=(12, 7), facecolor='white')
        
        # Облако теперь занимает место до 0.08 (почти до края)
        ax = fig.add_axes([0.0, 0.08, 1.0, 0.82]) 
        ax.imshow(wc.to_image(), interpolation='bilinear')
        ax.axis("off")
        
        clean_title = re.sub(r'[^\w\s-]', '', title).strip() 
        
        # Заголовок чуть выше
        fig.text(0.5, 0.95, f"Облако смыслов канала: {clean_title}", 
                 fontsize=24, fontweight='bold', ha='center', va='center', color='#1a1a1a')
        
        # Никнейм максимально низко (0.03)
        fig.text(0.5, 0.03, "@insight_tg_bot", 
                 fontsize=14, ha='center', va='center', color='#FFC0CB', alpha=0.9)
        
        plt.savefig(cloud_path, dpi=150, facecolor='white')
        plt.close()

        # --- 2. ГЕНЕРАЦИЯ ГРАФИКА (УЛЬТРА-КОМПАКТ) ---
        top_15 = Counter(all_words).most_common(15)
        w_labels = [x[0].upper() for x in top_15][::-1]
        counts = [x[1] for x in top_15][::-1]
        
        graph_path = f"graph_{username}.png"
        plt.style.use('ggplot') 
        # Уменьшили высоту до 7
        fig, ax = plt.subplots(figsize=(12, 7), facecolor='#f8f9fa')
        ax.set_facecolor('#f8f9fa')

        colors = cm.plasma(np.linspace(0.2, 0.8, len(w_labels)))
        bars = ax.barh(w_labels, counts, color=colors, edgecolor='white', linewidth=1)
        
        fig.text(0.5, 0.94, f"Топ-15 ключевых слов канала {clean_title}", 
                 fontsize=22, fontweight='bold', ha='center', va='center', color='#2d3436')
        
        for bar in bars:
            width = bar.get_width()
            ax.text(width + (max(counts if counts else [1]) * 0.01), bar.get_y() + bar.get_height()/2, 
                    f'{int(width)}', va='center', fontsize=13, fontweight='bold', color='#2d3436')
        
        # Никнейм максимально низко (0.03)
        fig.text(0.5, 0.03, "@insight_tg_bot", 
                 fontsize=14, ha='center', va='center', color='#FFC0CB', alpha=0.9)
        
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        # rect=[лево, низ, право, верх]
        # Низ 0.07 — график теперь почти касается подписи бота
        plt.tight_layout(rect=[0.01, 0.07, 0.99, 0.90]) 
        
        plt.savefig(graph_path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
        
        # Сбор статистики
        stats = {
            "meaning_load": len(all_words),
            "richness": round((len(set(all_words))/len(all_words)*100), 1),
            "avg_len": round(np.mean([len(p.split()) for p in posts]), 1)
        }
        
        return cloud_path, graph_path, stats, title

    except Exception as e:
        print(f"Ошибка в анализе: {e}")
        return None, None, None, str(e)

async def generate_mats_cloud(username, all_words):
    if not all_words: return None
    
    # Стиль: Черный фон, красные слова (инфернально!)
    wc = WordCloud(
        width=1200, height=700, 
        background_color='black', 
        colormap='Reds', 
        max_words=100
    ).generate(" ".join(all_words))
    
    path = f"mats_{username}.png"
    fig = plt.figure(figsize=(12, 7), facecolor='black')
    ax = fig.add_axes([0, 0.1, 1, 0.8])
    ax.imshow(wc, interpolation='bilinear', aspect='auto')
    ax.axis("off")
    
    fig.text(0.5, 0.92, "МАТЕРНЫЙ ИНДЕКС КАНАЛА", color='white', 
             fontsize=24, fontweight='bold', ha='center')
    fig.text(0.5, 0.05, "@insight_tg_bot | PREMUM EDITION", color='red', 
             fontsize=14, ha='center', fontweight='bold')
    
    plt.savefig(path, dpi=150, facecolor='black')
    plt.close()
    return path


# --- 5. ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("📊 TG Channel Analytics\n\nПришли мне юзернейм канала (например: `polozhnyak`), и я выверну его смыслы наизнанку!")

@dp.message(F.text)
async def handle_msg(message: types.Message):
    if message.text.startswith('/'): return
    
    username = message.text.replace('@', '').split('/')[-1].strip()
    status = await message.answer("🛸 Извлекаю смыслы и строю графики...")
    
    res = await analyze_channel(username)
    cloud_p, graph_p, stats, title = res
    
    if cloud_p and graph_p:
        caption = (
            f"📊 Канал: {title}\n\n"
            f"🧠 Смысловая нагрузка: {stats['meaning_load']} ед.\n"
            f"💎 Богатство речи: {stats['richness']}%\n"
            f"📏 Ср. длина поста: {stats['avg_len']} слов"
        )
        
        media = [
            InputMediaPhoto(media=FSInputFile(cloud_p), caption=caption),
            InputMediaPhoto(media=FSInputFile(graph_p))
        ]
        
        await message.answer_media_group(media=media)
        
        # Удаляем временные файлы
        for p in [cloud_p, graph_p]:
            if os.path.exists(p): os.remove(p)
    else:
        await message.answer(f"❌ Ошибка: {title}")
    
    await status.delete()

# --- 6. ЗАПУСК ---
async def main():
    print("Проверка авторизации...")
    await user_client.start() 
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())