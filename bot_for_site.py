import streamlit as st
import ssl
import re
import asyncio
from collections import Counter
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np
from wordcloud import WordCloud
import pymorphy2
import nltk
from nltk.corpus import stopwords
from telethon import TelegramClient

# --- 1. ФИКСЫ ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError: pass
else: ssl._create_default_https_context = _create_unverified_https_context

# Инициализация морфологии
morph = pymorphy2.MorphAnalyzer()

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

russian_stopwords = set(stopwords.words('russian'))
russian_stopwords.update({'это', 'который', 'свой', 'ваш', 'наш', 'весь', 'такой', 'очень', 'мочь', 'год', 'человек', 'тип', 'кароче', 'вообще', 'просто', 'почему', 'день'})

# --- 2. ДАННЫЕ ---
API_ID = 34404218 
API_HASH = '26f2cb869a2293037cc21c796750e616'

def clean_text(text):
    text = re.sub(r'http\S+', '', text)
    words = re.findall(r'[а-яА-ЯёЁ]+', text.lower())
    clean_words = []
    for w in words:
        parsed = morph.parse(w)[0]
        normal = parsed.normal_form
        if normal == 'деньга': normal = 'деньги'
        if len(normal) > 2 and normal not in russian_stopwords:
            if parsed.tag.POS in ['NOUN', 'ADJF']:
                clean_words.append(normal)
    return clean_words

# --- 3. ИНТЕРФЕЙС ---
st.set_page_config(page_title="TG Analytics", layout="wide")
st.title("📊 Анализатор Telegram-каналов")

with st.sidebar:
    st.header("Параметры")
    channel_url = st.text_input("Введите ссылку на канал", placeholder="polozhnyak")
    limit = st.slider("Количество постов", 50, 500, 150)
    start_btn = st.button("🚀 Запустить анализ")

if start_btn and channel_url:
    with st.spinner('Генерирую инфографику...'):
        try:
            client = TelegramClient('web_session', API_ID, API_HASH)
            
            async def get_data():
                await client.connect()
                entity = await client.get_entity(channel_url)
                title = entity.title
                msgs = [m.text async for m in client.iter_messages(entity, limit=limit) if m.text]
                return title, msgs

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            real_title, messages = loop.run_until_complete(get_data())

            all_words = []
            for m in messages:
                all_words.extend(clean_text(m))

            if all_words:
                # Метрики
                col1, col2, col3 = st.columns(3)
                col1.metric("Всего слов", len(all_words), help="Общее количество значимых слов.")
                col2.metric("Уникальных", len(set(all_words)), help="Словарный запас автора.")
                col3.metric("Богатство речи", f"{(len(set(all_words))/len(all_words)*100):.1f}%")

                st.divider()

                # --- КРУТОЙ ЗАГОЛОВОК И ОБЛАКО (БЕЗ ОШИБКИ ASARRAY) ---
                st.markdown(f"<h2 style='text-align: center; color: #1f77b4;'>ОБЛАКО СМЫСЛОВ КАНАЛА: {real_title.upper()}</h2>", unsafe_allow_html=True)
                
                # Генерируем облако и сразу превращаем в PIL-картинку (это обходит ошибку asarray)
                wc = WordCloud(width=1200, height=600, background_color='white', colormap='cool').generate(" ".join(all_words))
                cloud_img = wc.to_image() 
                
                # Выводим как обычное изображение
                st.image(cloud_img, use_container_width=True)

                st.divider()

                # --- ГРАФИК ТОП-15 (он обычно не выдает ошибку) ---
                st.markdown(f"<h2 style='text-align: center;'>ЧАСТОТНЫЙ СЛОВАРЬ: {real_title.upper()}</h2>", unsafe_allow_html=True)
                
                top_15 = Counter(all_words).most_common(15)
                w_labels = [x[0].upper() for x in top_15][::-1]
                counts = [x[1] for x in top_15][::-1]
                
                fig_bar, ax_bar = plt.subplots(figsize=(10, 8))
                colors = cm.cool(np.linspace(0.3, 0.9, len(w_labels)))
                bars = ax_bar.barh(w_labels, counts, color=colors)
                
                for bar in bars:
                    ax_bar.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2, 
                                f'{int(bar.get_width())}', va='center', fontweight='bold')
                
                ax_bar.spines['top'].set_visible(False)
                ax_bar.spines['right'].set_visible(False)
                st.pyplot(fig_bar)

            else:
                st.error("Слова не найдены.")

        except Exception as e:
            st.error(f"Ошибка: {e}")