import os
import streamlit as st
from dotenv import load_dotenv
from analyzer import build_profile_prompt, build_niche_prompt, stream_analysis

load_dotenv()

st.set_page_config(
    page_title="Instagram AI Анализатор",
    page_icon="📸",
    layout="wide",
)

st.title("📸 Instagram AI Анализатор")
st.caption("Контент-план, анализ профиля и советы по росту — на основе Claude AI")

# --- Sidebar ---
with st.sidebar:
    st.header("Настройки")

    api_key = st.text_input(
        "Anthropic API Key",
        value=os.getenv("ANTHROPIC_API_KEY", ""),
        type="password",
        help="Ключ из console.anthropic.com. Можно задать в файле .env",
    )

    plan_days = st.select_slider(
        "Период контент-плана",
        options=[7, 14, 30],
        value=14,
        format_func=lambda x: f"{x} дней",
    )

    st.divider()
    st.caption("Powered by Claude claude-sonnet-4-6")

# --- Tabs ---
tab_profile, tab_niche = st.tabs(["Анализ профиля", "Быстрый старт по нише"])

GOALS = ["Рост подписчиков", "Продажи / монетизация", "Охваты и узнаваемость", "Личный бренд"]
TONES = ["Экспертный", "Дружелюбный / разговорный", "С юмором", "Мотивационный / вдохновляющий"]


def run_generation(api_key: str, prompt: str):
    if not api_key:
        st.error("Введи Anthropic API Key в боковой панели.")
        return

    result_container = st.empty()
    full_text = ""

    with st.spinner("Генерирую анализ..."):
        try:
            for chunk in stream_analysis(api_key, prompt):
                full_text += chunk
                result_container.markdown(full_text + "▌")
        except Exception as e:
            st.error(f"Ошибка API: {e}")
            return

    result_container.markdown(full_text)

    st.download_button(
        label="Скачать результат (.txt)",
        data=full_text,
        file_name="instagram_analysis.txt",
        mime="text/plain",
    )


# --- Tab 1: Profile Analysis ---
with tab_profile:
    st.subheader("Опиши свой Instagram-профиль")
    st.caption("Чем подробнее опишешь — тем точнее будет анализ и план.")

    col1, col2 = st.columns(2)

    with col1:
        niche = st.text_input(
            "Ниша / тематика *",
            placeholder="Например: фитнес для женщин 30+, кулинария, личные финансы",
        )
        followers = st.number_input(
            "Количество подписчиков",
            min_value=0,
            max_value=100_000_000,
            value=1000,
            step=100,
        )
        posts_count = st.number_input(
            "Количество постов",
            min_value=0,
            max_value=100_000,
            value=30,
            step=1,
        )
        goal = st.selectbox("Цель аккаунта", GOALS)

    with col2:
        target_audience = st.text_input(
            "Целевая аудитория",
            placeholder="Например: женщины 25–40, интересующиеся ЗОЖ",
        )
        tone = st.selectbox("Тон общения", TONES)
        current_content = st.text_area(
            "Что уже выходит (описание текущего контента)",
            placeholder="Например: фото блюд, рецепты раз в неделю, иногда сторис с закулисьем",
            height=120,
        )

    if st.button("Сгенерировать анализ и план", type="primary", key="btn_profile"):
        if not niche.strip():
            st.warning("Заполни поле «Ниша / тематика».")
        else:
            data = {
                "niche": niche,
                "followers": followers,
                "posts_count": posts_count,
                "target_audience": target_audience,
                "goal": goal,
                "tone": tone,
                "current_content": current_content,
            }
            prompt = build_profile_prompt(data, plan_days)
            st.divider()
            run_generation(api_key, prompt)


# --- Tab 2: Niche Quick Start ---
with tab_niche:
    st.subheader("Быстрый старт: задай только нишу")
    st.caption("Подходит если ты только начинаешь или хочешь исследовать новую тему.")

    niche_quick = st.text_input(
        "Ниша *",
        placeholder="Например: путешествия в одиночку, уходовая косметика, продуктивность",
        key="niche_quick",
    )
    goal_quick = st.selectbox("Цель", GOALS, key="goal_quick")

    if st.button("Сгенерировать стратегию", type="primary", key="btn_niche"):
        if not niche_quick.strip():
            st.warning("Введи нишу.")
        else:
            data = {"niche": niche_quick, "goal": goal_quick}
            prompt = build_niche_prompt(data, plan_days)
            st.divider()
            run_generation(api_key, prompt)
