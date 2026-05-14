import datetime
import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

HISTORY_FILE = Path("history.json")


def _load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_history(history: list) -> None:
    try:
        HISTORY_FILE.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

from analyzer import (
    LANGUAGES,
    build_bio_prompt,
    build_caption_prompt,
    build_competitor_prompt,
    build_niche_prompt,
    build_profile_prompt,
    build_scraped_prompt,
    markdown_to_docx,
    scrape_instagram_profile,
    stream_analysis,
    stream_chat,
)

load_dotenv()

st.set_page_config(page_title="Instagram AI Анализатор", page_icon="📸", layout="wide")

# ── Session state defaults ────────────────────────────────────────────────────
for k in ("profile", "niche", "caption", "bio", "competitor", "scrape"):
    st.session_state.setdefault(f"result_{k}", None)
    st.session_state.setdefault(f"usage_{k}", {})
    st.session_state.setdefault(f"chat_{k}", [])
if "history" not in st.session_state:
    st.session_state["history"] = _load_history()
st.session_state.setdefault("scraped_data_scrape", None)

# ── Constants ─────────────────────────────────────────────────────────────────
GOALS = ["Рост подписчиков", "Продажи / монетизация", "Охваты и узнаваемость", "Личный бренд"]
TONES = ["Экспертный", "Дружелюбный / разговорный", "С юмором", "Мотивационный / вдохновляющий"]

# ── Header ────────────────────────────────────────────────────────────────────
st.title("📸 Instagram AI Анализатор")
st.caption("Контент-план, анализ профиля и советы по росту — на основе Claude AI")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Настройки")

    env_key = os.getenv("ANTHROPIC_API_KEY", "")
    if env_key:
        st.success("API Key загружен")
        api_key = env_key
    else:
        api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            help="Ключ из console.anthropic.com",
        )

    env_apify = os.getenv("APIFY_TOKEN", "")
    if env_apify:
        st.success("Apify Token загружен")
        apify_token = env_apify
    else:
        apify_token = st.text_input(
            "Apify Token",
            type="password",
            help="Токен из apify.com/account → Integrations",
        )

    plan_days = st.select_slider(
        "Период контент-плана",
        options=[7, 14, 30],
        value=14,
        format_func=lambda x: f"{x} дней",
    )

    lang = st.selectbox("Язык ответа", LANGUAGES)

    if st.session_state.history:
        st.divider()
        st.subheader(f"История ({len(st.session_state.history)})")
        for idx, item in enumerate(reversed(st.session_state.history[-8:])):
            col_title, col_btn = st.columns([3, 1])
            with col_title:
                st.caption(f"**{item['title']}**\n\n{item['time']} · ↑{item['tokens_in']} ↓{item['tokens_out']}")
            with col_btn:
                if st.button("Открыть", key=f"hist_open_{idx}"):
                    st.session_state["viewed_history"] = item

    st.divider()
    st.caption("Powered by claude-sonnet-4-6")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _show_profile_card(data: dict) -> None:
    verified = " ✅" if data["is_verified"] else ""
    st.markdown(f"### @{data['username']}{verified}")
    if data["full_name"]:
        st.caption(data["full_name"])
    if data["bio"]:
        st.info(data["bio"])
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Подписчики", f"{data['followers']:,}")
    col2.metric("Постов", f"{data['posts_count']:,}")
    col3.metric("Engagement Rate", f"{data['engagement_rate']}%")
    col4.metric("Avg ❤️", f"{data['avg_likes']:,}")
    if data["top_hashtags"]:
        st.caption("Топ хэштеги: " + "  ".join(data["top_hashtags"][:10]))


def _run_scrape_pending() -> bool:
    pending = st.session_state.pop("pending_scrape", None)
    if not pending:
        return False
    if not api_key:
        st.error("Введи Anthropic API Key.")
        return False
    if not apify_token:
        st.error("Введи Apify Token в боковой панели.")
        return False

    with st.spinner("📡 Получаю данные профиля из Instagram... (30–60 сек)"):
        try:
            profile_data = scrape_instagram_profile(apify_token, pending["username"])
        except Exception as e:
            st.error(f"Ошибка парсинга: {e}")
            return False

    if not profile_data:
        st.error("Профиль не найден или недоступен.")
        return False

    st.session_state["scraped_data_scrape"] = profile_data
    _show_profile_card(profile_data)
    st.divider()

    prompt = build_scraped_prompt(profile_data, pending["plan_days"], pending["lang"])
    usage: dict = {}
    try:
        result = st.write_stream(stream_analysis(api_key, prompt, usage_container=usage))
    except Exception as e:
        st.error(f"Ошибка API: {e}")
        return False

    st.session_state["result_scrape"] = result
    st.session_state["usage_scrape"] = usage
    st.session_state["chat_scrape"] = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": result},
    ]
    st.session_state.history.append({
        "title": f"Парсинг: @{profile_data['username']}",
        "content": result,
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "time": datetime.datetime.now().strftime("%d.%m %H:%M"),
    })
    _save_history(st.session_state.history)
    return True


def _run_pending(tab_key: str) -> bool:
    """Consume pending generation request; return True if ran."""
    pending = st.session_state.pop(f"pending_{tab_key}", None)
    if not pending:
        return False
    if not api_key:
        st.error("Введи Anthropic API Key в боковой панели.")
        return False

    usage: dict = {}
    try:
        result = st.write_stream(stream_analysis(api_key, pending["prompt"], usage_container=usage))
    except Exception as e:
        st.error(f"Ошибка API: {e}")
        return False

    st.session_state[f"result_{tab_key}"] = result
    st.session_state[f"usage_{tab_key}"] = usage
    st.session_state[f"chat_{tab_key}"] = [
        {"role": "user", "content": pending["prompt"]},
        {"role": "assistant", "content": result},
    ]
    st.session_state.history.append({
        "title": pending["title"],
        "content": result,
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        "time": datetime.datetime.now().strftime("%d.%m %H:%M"),
    })
    _save_history(st.session_state.history)
    return True


def _show_exports(tab_key: str) -> None:
    result = st.session_state.get(f"result_{tab_key}")
    if not result:
        return
    usage = st.session_state.get(f"usage_{tab_key}", {})

    col_info, col_txt, col_docx, col_raw = st.columns([3, 1, 1, 1])
    with col_info:
        ti = usage.get("input_tokens", "?")
        to = usage.get("output_tokens", "?")
        st.caption(f"Токены: ↑{ti} вход / ↓{to} выход")
    with col_txt:
        st.download_button(
            "⬇ .txt", result, f"{tab_key}.txt", "text/plain",
            key=f"dl_txt_{tab_key}",
        )
    with col_docx:
        try:
            st.download_button(
                "⬇ .docx", markdown_to_docx(result), f"{tab_key}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"dl_docx_{tab_key}",
            )
        except Exception:
            pass
    with col_raw:
        with st.expander("📋 Копировать"):
            st.code(result, language=None)


def _show_chat(tab_key: str) -> None:
    msgs = st.session_state.get(f"chat_{tab_key}", [])
    if not msgs:
        return

    # Show previous refinement turns (skip initial prompt+response pair)
    if len(msgs) > 2:
        st.divider()
        for msg in msgs[2:]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # Refinement input
    st.divider()
    col_in, col_btn = st.columns([5, 1])
    with col_in:
        refine = st.text_input(
            "Уточнение",
            placeholder="Добавь идеи для рилсов / перепиши советы жёстче...",
            key=f"refine_{tab_key}",
            label_visibility="collapsed",
        )
    with col_btn:
        send = st.button("→ Отправить", key=f"refine_btn_{tab_key}")

    if send and refine.strip():
        if not api_key:
            st.error("Введи API Key.")
            return
        new_msgs = list(msgs) + [{"role": "user", "content": refine}]
        usage2: dict = {}
        try:
            reply = st.write_stream(stream_chat(api_key, new_msgs, usage_container=usage2))
        except Exception as e:
            st.error(f"Ошибка: {e}")
            return
        new_msgs.append({"role": "assistant", "content": reply})
        st.session_state[f"chat_{tab_key}"] = new_msgs

        col_t, col_d = st.columns(2)
        with col_t:
            st.download_button(
                "⬇ .txt", reply, f"{tab_key}_reply.txt", "text/plain",
                key=f"rtxt_{tab_key}_{len(new_msgs)}",
            )
        with col_d:
            try:
                st.download_button(
                    "⬇ .docx", markdown_to_docx(reply), f"{tab_key}_reply.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"rdocx_{tab_key}_{len(new_msgs)}",
                )
            except Exception:
                pass


def _result_section(tab_key: str, just_generated: bool) -> None:
    """Render stored result (skip markdown if just streamed), then exports and chat."""
    result = st.session_state.get(f"result_{tab_key}")
    if not result:
        return
    if not just_generated:
        st.markdown(result)
    _show_exports(tab_key)
    _show_chat(tab_key)


# ── History viewer ────────────────────────────────────────────────────────────
if viewed := st.session_state.get("viewed_history"):
    col_h, col_close = st.columns([6, 1])
    with col_h:
        st.subheader(f"📂 {viewed['title']}")
        st.caption(f"{viewed['time']}  ·  ↑{viewed['tokens_in']} ↓{viewed['tokens_out']} токенов")
    with col_close:
        if st.button("✕ Закрыть", key="close_history"):
            del st.session_state["viewed_history"]
            st.rerun()

    st.markdown(viewed["content"])

    col_txt, col_docx, col_raw = st.columns(3)
    with col_txt:
        st.download_button(
            "⬇ .txt", viewed["content"], "history.txt", "text/plain",
            key="hist_dl_txt",
        )
    with col_docx:
        try:
            st.download_button(
                "⬇ .docx", markdown_to_docx(viewed["content"]), "history.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="hist_dl_docx",
            )
        except Exception:
            pass
    with col_raw:
        with st.expander("📋 Копировать"):
            st.code(viewed["content"], language=None)
    st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_profile, tab_niche, tab_caption, tab_bio, tab_competitor, tab_scrape = st.tabs([
    "📊 Анализ профиля",
    "🚀 По нише",
    "✍️ Генератор подписей",
    "💼 Оптимизатор Bio",
    "🔍 Анализ конкурентов",
    "📡 Парсинг Instagram",
])

# ── Tab 1: Profile ────────────────────────────────────────────────────────────
with tab_profile:
    st.subheader("Опиши свой профиль")
    col1, col2 = st.columns(2)
    with col1:
        p_niche = st.text_input("Ниша / тематика *", placeholder="Фитнес для женщин 30+", key="p_niche")
        p_followers = st.number_input("Подписчиков", 0, 100_000_000, 1000, 100, key="p_fol")
        p_posts = st.number_input("Постов", 0, 100_000, 30, key="p_posts")
        p_goal = st.selectbox("Цель", GOALS, key="p_goal")
    with col2:
        p_audience = st.text_input("Целевая аудитория", placeholder="Женщины 25–40, ЗОЖ", key="p_aud")
        p_tone = st.selectbox("Тон", TONES, key="p_tone")
        p_content = st.text_area(
            "Текущий контент", placeholder="Фото блюд, рецепты раз в неделю...",
            height=118, key="p_content",
        )

    if st.button("Сгенерировать анализ и план", type="primary", key="btn_profile"):
        if not p_niche.strip():
            st.warning("Заполни поле «Ниша».")
        else:
            data = {
                "niche": p_niche, "followers": p_followers, "posts_count": p_posts,
                "target_audience": p_audience, "goal": p_goal,
                "tone": p_tone, "current_content": p_content,
            }
            st.session_state["pending_profile"] = {
                "prompt": build_profile_prompt(data, plan_days, lang),
                "title": f"Профиль: {p_niche}",
            }

    st.divider()
    gen = _run_pending("profile")
    _result_section("profile", gen)

# ── Tab 2: Niche ──────────────────────────────────────────────────────────────
with tab_niche:
    st.subheader("Быстрый старт по нише")
    n_niche = st.text_input(
        "Ниша *", placeholder="Путешествия соло, продуктивность, уходовая косметика", key="n_niche",
    )
    n_goal = st.selectbox("Цель", GOALS, key="n_goal")

    if st.button("Сгенерировать стратегию", type="primary", key="btn_niche"):
        if not n_niche.strip():
            st.warning("Введи нишу.")
        else:
            st.session_state["pending_niche"] = {
                "prompt": build_niche_prompt({"niche": n_niche, "goal": n_goal}, plan_days, lang),
                "title": f"Ниша: {n_niche}",
            }

    st.divider()
    gen = _run_pending("niche")
    _result_section("niche", gen)

# ── Tab 3: Caption Generator ──────────────────────────────────────────────────
with tab_caption:
    st.subheader("Генератор подписей для постов")
    c_topic = st.text_input(
        "Тема поста *", placeholder="Как я похудела на 10 кг без диет", key="c_topic",
    )
    col1, col2 = st.columns(2)
    with col1:
        c_tone = st.selectbox("Тон", TONES, key="c_tone")
    with col2:
        c_goal_opts = ["Получить комментарии", "Привести в профиль", "Продать продукт", "Сохранения / репосты"]
        c_goal = st.selectbox("Цель подписи", c_goal_opts, key="c_goal")
    c_audience = st.text_input(
        "Аудитория", placeholder="Женщины 28–45, хотят похудеть", key="c_aud",
    )

    if st.button("Написать подписи", type="primary", key="btn_caption"):
        if not c_topic.strip():
            st.warning("Введи тему поста.")
        else:
            data = {"topic": c_topic, "tone": c_tone, "goal": c_goal, "audience": c_audience}
            st.session_state["pending_caption"] = {
                "prompt": build_caption_prompt(data, lang),
                "title": f"Caption: {c_topic[:35]}",
            }

    st.divider()
    gen = _run_pending("caption")
    _result_section("caption", gen)

# ── Tab 4: Bio Optimizer ──────────────────────────────────────────────────────
with tab_bio:
    st.subheader("Оптимизатор Bio")
    b_bio = st.text_area(
        "Текущая Bio",
        placeholder="Нутрициолог | Помогаю худеть без диет ✨ | Консультации в директ",
        height=80, key="b_bio",
    )
    col1, col2 = st.columns(2)
    with col1:
        b_niche = st.text_input("Чем занимаешься / ниша *", placeholder="Нутрициология", key="b_niche")
    with col2:
        b_goal = st.selectbox("Цель профиля", GOALS, key="b_goal")
    b_audience = st.text_input("Целевая аудитория", placeholder="Женщины 30+", key="b_aud")

    if st.button("Оптимизировать Bio", type="primary", key="btn_bio"):
        if not b_niche.strip():
            st.warning("Укажи нишу.")
        else:
            data = {
                "current_bio": b_bio or "не указана",
                "niche": b_niche, "goal": b_goal, "audience": b_audience,
            }
            st.session_state["pending_bio"] = {
                "prompt": build_bio_prompt(data, lang),
                "title": f"Bio: {b_niche}",
            }

    st.divider()
    gen = _run_pending("bio")
    _result_section("bio", gen)

# ── Tab 5: Competitor Analysis ────────────────────────────────────────────────
with tab_competitor:
    st.subheader("Анализ конкурентных ниш")
    st.caption("Введи свою нишу и смежные — ИИ найдёт незанятые темы и способы выделиться.")

    comp_my = st.text_input("Моя основная ниша *", placeholder="Фитнес для мам после родов", key="comp_my")
    comp_goal = st.selectbox("Цель", GOALS, key="comp_goal")

    col1, col2, col3 = st.columns(3)
    comp1 = col1.text_input("Конкурент 1", placeholder="Фитнес для женщин", key="comp1")
    comp2 = col2.text_input("Конкурент 2", placeholder="Похудение и диеты", key="comp2")
    comp3 = col3.text_input("Конкурент 3", placeholder="Йога и медитация", key="comp3")

    if st.button("Проанализировать", type="primary", key="btn_comp"):
        if not comp_my.strip():
            st.warning("Введи свою основную нишу.")
        else:
            data = {
                "my_niche": comp_my,
                "niches": [comp_my, comp1, comp2, comp3],
                "goal": comp_goal,
            }
            st.session_state["pending_competitor"] = {
                "prompt": build_competitor_prompt(data, plan_days, lang),
                "title": f"Конкуренты: {comp_my}",
            }

    st.divider()
    gen = _run_pending("competitor")
    _result_section("competitor", gen)

# ── Tab 6: Instagram Scraping (Apify) ────────────────────────────────────────
with tab_scrape:
    st.subheader("Парсинг Instagram профиля")
    st.caption(
        "Получает реальные данные аккаунта (подписчики, посты, вовлечённость) "
        "через Apify и анализирует их с помощью Claude. "
        "Требует Apify Token — бесплатный план даёт $5/мес."
    )

    sc_username = st.text_input(
        "Instagram username *",
        placeholder="@natgeo  или  natgeo",
        key="sc_username",
    )

    if st.button("Спарсить и проанализировать", type="primary", key="btn_scrape"):
        if not sc_username.strip():
            st.warning("Введи username.")
        elif not apify_token:
            st.warning("Введи Apify Token в боковой панели.")
        else:
            st.session_state["pending_scrape"] = {
                "username": sc_username,
                "plan_days": plan_days,
                "lang": lang,
            }

    st.divider()

    gen = _run_scrape_pending()

    if not gen:
        if scraped := st.session_state.get("scraped_data_scrape"):
            _show_profile_card(scraped)
            st.divider()
    _result_section("scrape", gen)
