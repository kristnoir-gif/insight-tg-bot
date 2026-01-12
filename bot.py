import ssl
import asyncio
import re
import os
from collections import Counter

# Настройки для Mac
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from wordcloud import WordCloud
import pymorphy2
import nltk
from nltk.corpus import stopwords
from telethon import TelegramClient

# Настройка шрифтов
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# Загрузка базы слов
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

# --- НАСТРОЙКИ ---
api_id = '34404218'  # Замените на свой
api_hash = '26f2cb869a2293037cc21c796750e616'  # Замените на свой
channel_username = 'polozhnyak'  # Юзернейм канала для анализа
limit_posts = 150  # Сколько постов анализировать

morph = pymorphy2.MorphAnalyzer()
russian_stopwords = set(stopwords.words('russian'))
russian_stopwords.update({'это', 'который', 'типа', 'свой', 'ваш', 'наш', 'весь', 'такой', 'очень', 'мочь', 'год', 'человек'})

# МАТЕРНЫЙ СЛОВАРЬ (корни и формы)
MAT_WORDS = {
    'хуй', 'хуйня', 'хуево', 'охуеть', 'похуй', 'хуило', 'хуячить',
    'пизда', 'пиздец', 'пиздит', 'пиздобол', 'распиздяй', 'спиздить',
    'ебать', 'ебнуть', 'ебаный', 'долбоеб', 'заебать', 'выебоны', 'ебучий',
    'блять', 'блядь', 'бля', 'сука', 'сучка', 'гандон', 'манда', 'хер'
}
MAT_ROOTS = ['хуй', 'хуя', 'пизд', 'еба', 'ебл', 'бля']

# --- ОБНОВЛЕННЫЕ НАСТРОЙКИ СТОП-СЛОВ ---
russian_stopwords = set(stopwords.words('russian'))
# Добавляем "тип" и другие паразиты сюда
extra_stop = {
    'это', 'который', 'свой', 'ваш', 'наш', 'весь', 'такой', 
    'очень', 'мочь', 'год', 'человек', 'тип', 'кароче', 'вообще'
}
russian_stopwords.update(extra_stop)

def clean_text(text, mode='normal'):
    text = re.sub(r'http\S+', '', text)
    words = re.findall(r'[а-яА-ЯёЁ]+', text.lower())
    clean_words = []
    
    for w in words:
        parsed = morph.parse(w)[0]
        normal = parsed.normal_form
        
        # КОРРЕКЦИЯ СЛОВ
        if normal == 'деньга':
            normal = 'деньги'
            
        if mode == 'mats':
            if normal in MAT_WORDS or any(root in normal for root in MAT_ROOTS):
                clean_words.append(normal)
        else:
            # Проверяем, что слова нет в обновленном списке стоп-слов
            if len(normal) > 2 and normal not in russian_stopwords:
                if parsed.tag.POS in ['NOUN', 'ADJF']:
                    clean_words.append(normal)
    return clean_words

async def main():
    async with TelegramClient('my_session', api_id, api_hash) as client:
        entity = await client.get_entity(channel_username)
        clean_title = re.sub(r'[^а-яА-ЯёЁa-zA-Z0-9\s!?-]', '', entity.title)
        
        print(f"Анализирую канал: {clean_title}...")
        
        all_posts = []
        async for message in client.iter_messages(entity, limit=limit_posts):
            if message.text: all_posts.append(message.text)
        
        # Сбор слов
        normal_words = []
        obscene_words = []
        post_lengths = [len(p) for p in all_posts]

        for post in all_posts:
            normal_words.extend(clean_text(post, mode='normal'))
            obscene_words.extend(clean_text(post, mode='mats'))

        # --- ОСНОВНОЕ ОБЛАКО ---
        wc_main = WordCloud(
            width=1000, 
            height=600, 
            background_color='white', 
            colormap='cool'  # Новая палитра
        ).generate(" ".join(normal_words))
        wc_main.to_file('temp_main.png')

        img1 = mpimg.imread('temp_main.png')
        plt.figure(figsize=(12, 8))
        plt.imshow(img1)
        plt.title(f'Облако смыслов канала «{clean_title}»', fontsize=20, fontweight='bold', pad=20, color='black') # Черный текст
        plt.axis("off")
        plt.savefig('wordcloud_main.png', bbox_inches='tight')
        plt.close()
        
        # Рисуем с заголовком
        img1 = mpimg.imread('temp_main.png')
        plt.figure(figsize=(12, 8))
        plt.imshow(img1)
        plt.title(f'облако смыслов канала «{clean_title}»', fontsize=20, fontweight='bold', pad=20)
        plt.axis("off")
        plt.savefig('wordcloud_main.png', bbox_inches='tight')
        plt.close()

        # 2. ГЕНЕРАЦИЯ МАТЕРНОГО ОБЛАКА
        if obscene_words:
            print("Создаю матерное облако...")
            wc_mats = WordCloud(width=1000, height=600, background_color='white', colormap='Reds').generate(" ".join(obscene_words))
            wc_mats.to_file('temp_mats.png')
            
            img2 = mpimg.imread('temp_mats.png')
            plt.figure(figsize=(12, 8))
            plt.imshow(img2)
            plt.title(f'облако мата телеграм канала «{clean_title}»', fontsize=20, color='darkred', fontweight='bold', pad=20)
            plt.axis("off")
            plt.savefig('wordcloud_mats.png', bbox_inches='tight')
            plt.close()
        
# --- ГЕНЕРАЦИЯ УЛУЧШЕННОГО ГРАФИКА ТОП-СЛОВ ---
        print("Создаю профессиональный график топ-слов...")
        
        # 1. Подготовка данных (Топ-15)
        top_15 = Counter(normal_words).most_common(15)
        words_labels = [item[0].upper() for item in top_15][::-1]
        counts = [item[1] for item in top_15][::-1]

        # 2. Создание фигуры
        plt.figure(figsize=(12, 9))
        
        # Генерируем цвета из палитры 'cool' для каждого столбца
        import matplotlib.cm as cm
        import numpy as np
        colors = cm.cool(np.linspace(0.3, 0.9, len(words_labels)))

        # 3. Рисуем горизонтальные столбцы
        bars = plt.barh(words_labels, counts, color=colors, edgecolor='none', height=0.7)
        
        # 4. Настройка заголовка (черным цветом)
        plt.title(f'топ слов телеграм канала «{clean_title}»', fontsize=20, color='darkred', fontweight='bold', pad=20)

        # 5. Настройка осей
        plt.xlabel('КОЛИЧЕСТВО УПОМИНАНИЙ', fontsize=12, labelpad=15, color='black', fontweight='bold')
        plt.yticks(fontsize=11, color='black', fontweight='bold') # Слова теперь слева и черные
        
        # Добавляем сетку только по вертикали для удобства считывания шкалы
        plt.gca().xaxis.grid(True, linestyle='--', alpha=0.4, color='gray')
        plt.gca().set_axisbelow(True) # Сетка за столбцами

        # Убираем лишние границы рамки
        plt.gca().spines['top'].set_visible(False)
        plt.gca().spines['right'].set_visible(False)
        plt.gca().spines['left'].set_color('#dddddd')
        plt.gca().spines['bottom'].set_color('#dddddd')

        # 6. Добавляем точные значения в конце каждого столбца (черным)
        for bar in bars:
            width = bar.get_width()
            plt.text(width + (max(counts)*0.01), bar.get_y() + bar.get_height()/2,
                     f'{int(width)}', 
                     va='center', ha='left', color='black', fontsize=11, fontweight='bold')

        plt.tight_layout()
        plt.savefig('topwords.png', dpi=150, bbox_inches='tight')
        plt.close()

        # --- ГРАФИК ДЛИНЫ ---
        plt.figure(figsize=(10, 5))
        plt.plot(post_lengths[::-1], color='#00b4d8', linewidth=2) # Голубая линия
        plt.title(f'Динамика объема постов: {clean_title}', color='black', fontweight='bold')
        plt.grid(True, alpha=0.1)
        plt.savefig('lengths_graph.png')
        plt.close()

        # Чистка временных файлов
        for f in ['temp_main.png', 'temp_mats.png']:
            if os.path.exists(f): os.remove(f)

        print(f"ГОТОВО! Анализ завершен. Проверь файлы в папке.")

if __name__ == '__main__':
    asyncio.run(main())