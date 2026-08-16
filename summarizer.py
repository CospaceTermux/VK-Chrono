import json
import logging
from typing import List, Dict, Any, Optional
from config import config

logger = logging.getLogger(__name__)

class GeminiSummarizer:
    """Модуль генерации умных сводок диалогов через Google Gemini API."""

    def __init__(self):
        self.api_key = config.GEMINI_API_KEY
        self.model = config.GEMINI_MODEL
        self._client = None

    @property
    def client(self):
        if self._client is None and self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Не удалось инициализировать Google GenAI Client: {e}")
        return self._client

    def _call_gemini(self, prompt: str) -> Optional[str]:
        """Вызывает Gemini API через Interactions API."""
        if not self.client:
            return None
        try:
            interaction = self.client.interactions.create(
                model=self.model,
                input=prompt
            )
            return interaction.output_text
        except Exception as e:
            logger.error(f"Ошибка при вызове Gemini API: {e}")
            return None

    def summarize_day(self, messages: List[Dict[str, Any]], date_str: str) -> Dict[str, Any]:
        """
        Генерирует сводку диалога за день.
        Возвращает словарь со сводкой в Markdown и структурированными блоками.
        """
        if not messages:
            return {
                "summary_md": "За этот день в беседе не было зафиксировано сообщений.",
                "topics": [],
                "decisions": [],
                "participants": [],
                "stats": {"total_messages": 0, "active_users": 0}
            }

        # 1. Формируем статистику
        users_count: Dict[str, int] = {}
        for m in messages:
            name = m.get("full_name") or f"id{m.get('from_id')}"
            users_count[name] = users_count.get(name, 0) + 1

        top_participants = sorted(users_count.items(), key=lambda x: x[1], reverse=True)
        stats = {
            "total_messages": len(messages),
            "active_users": len(users_count),
            "top_users": top_participants[:5]
        }

        # 2. Формируем текстовый транскрипт для LLM
        lines = []
        for m in messages:
            time_str = m.get("time_str", "")
            author = m.get("full_name") or f"Пользователь {m.get('from_id')}"
            text = m.get("text", "").strip()
            
            # Добавляем информацию о вложениях если есть
            attachments = m.get("attachments", [])
            att_info = []
            for a in attachments:
                t = a.get("type", "attachment")
                if t == "photo":
                    att_info.append("[Фотография]")
                elif t == "doc":
                    att_info.append(f"[Документ: {a.get('title', '')}]")
                elif t == "audio_message":
                    dur = a.get("duration", 0)
                    trans = a.get("transcript", "").strip()
                    if trans:
                        att_info.append(f'[Голосовое сообщение ({dur} сек.): "{trans}"]')
                    else:
                        att_info.append(f'[Голосовое сообщение ({dur} сек.)]')
                elif t == "sticker":
                    att_info.append("[Стикер]")
                else:
                    att_info.append(f"[{t}]")
            
            att_str = (" " + ", ".join(att_info)) if att_info else ""
            
            # Пересланные сообщения или ответ
            reply_str = ""
            if m.get("reply"):
                reply_author = m['reply'].get('author_name', 'собеседника')
                reply_str = f" (в ответ на сообщение от {reply_author})"

            lines.append(f"[{time_str}] {author}{reply_str}: {text}{att_str}")

        transcript = "\n".join(lines)

        # Ограничиваем слишком огромный лог при необходимости (обычно 1M токенов Gemini хватает с запасом)
        if len(transcript) > 200_000:
            transcript = transcript[:200_000] + "\n...[часть сообщений сокращена]..."

        # Языковая инструкция
        lang_mode = config.SUMMARY_LANGUAGE.lower()
        if lang_mode == "en":
            lang_instruction = "Write the entire summary in English. Preserve original Russian terms/names if necessary."
        elif lang_mode == "auto":
            lang_instruction = "Определи основной язык общения участников за день (русский или английский) и напиши сводку на преобладающем языке. Сохраняй оригинальные термины."
        else:
            lang_instruction = "Пиши итоговую сводку на русском языке. В переписке могут встречаться сообщения на английском или смеси языков — понимай их суть и пересказывай на русском, сохраняя английские термины, ссылки и названия в оригинале."

        prompt = f"""Ты — главный летописец и аналитик сообщества. Твоя основная цель — составить четкий **Хронологический таймлайн событий дня** и выделить **самые яркие тезисы и ключевые темы**, чтобы любой участник мог мгновенно восстановить ход событий беседы за {date_str}.

Правила:
- {lang_instruction}
- Фокусируйся на фактах, событиях, ключевых мыслях и поворотах обсуждения (отсекай пустой спам, но сохраняй контекст и суть ярких диалогов).
- Группируй события по временным блокам (таймкодам) с кратким заголовком и тезисным раскрытием сути.
- Не выдумывай фактов, которых нет в логе.

Формат вывода строго в Markdown:
## 📌 Краткая суть дня (TL;DR)
(Главный итог и вектор дня в 1-2 емких предложениях)

### 🕒 Хроника событий и таймлайн обсуждения
- **[Время/Интервал] Название события / Темы:**
  - *Тезис:* о чем шла речь, какие аргументы приводились, к чему пришли.
  - *Кто участвовал:* ключевые действующие лица.
- **[Время/Интервал] Следующее событие / Тема:**
  - *Тезис:* ...

### 💡 Самые интересные инсайты, идеи и яркие моменты
- (Ключевые находки, интересные ссылки, горячие дискуссии, нестандартные идеи или шутки, вызвавшие резонанс)

### ✅ Зафиксированные решения и договоренности
- (Что решили делать, какие задачи распределили, назначенные встречи/дедлайны; если ничего конкретного — напиши "Конкретных договоренностей не зафиксировано")

---
Лог сообщений за {date_str}:
{transcript}
"""

        ai_summary = self._call_gemini(prompt)

        if not ai_summary:
            # Fallback: эвристическая сводка без AI
            ai_summary = self._generate_heuristic_daily_summary(date_str, stats, messages)

        return {
            "summary_md": ai_summary,
            "topics": [],
            "decisions": [],
            "participants": [{"name": k, "count": v} for k, v in top_participants],
            "stats": stats
        }

    def summarize_week(self, daily_summaries: List[Dict[str, Any]], week_key: str, 
                       start_date: str, end_date: str) -> str:
        """Генерирует сводный дайджест недели на основе 7 дневных сводок."""
        if not daily_summaries:
            return "За эту неделю нет данных для дайджеста."

        # Собираем выжимки за дни
        days_content = []
        for item in daily_summaries:
            d_str = item.get("date_str", "")
            d_sum = item.get("summary_md", "").strip()
            msg_cnt = item.get("message_count", 0)
            days_content.append(f"#### День {d_str} (Сообщений: {msg_cnt}):\n{d_sum}\n")

        all_days_text = "\n".join(days_content)

        lang_mode = config.SUMMARY_LANGUAGE.lower()
        if lang_mode == "en":
            lang_instruction = "Write the weekly digest in English."
        elif lang_mode == "auto":
            lang_instruction = "Пиши на основном языке общения недели."
        else:
            lang_instruction = "Пиши дайджест на русском языке, сохраняя оригинальные термины и названия."

        prompt = f"""Ты — ведущий аналитик и составитель летописи сообщества. Перед тобой дневные сводки и таймлайны беседы за неделю {week_key} (с {start_date} по {end_date}).
Составь цельный, структурированный **Недельный таймлайн и дайджест ключевых событий**.

Правила:
- {lang_instruction}
- Опирайся на хронологию: выдели главные сюжетные линии, поворотные моменты и смену фокуса внимания беседы за 7 дней.

Формат вывода строго в Markdown:
## 🏆 Главные вехи и итоги недели ({week_key})
(Краткий вводный обзор недели и ключевые тренды в 2 абзацах)

### 🗓️ Хронологическая карта недели (День за днем)
- **[Дата] Ключевое событие дня:** краткий тезис главного обсуждения и к чему пришли.
- **[Дата] Ключевое событие дня:** ...

### 🚀 Зафиксированные решения, прогресс и договоренности
- (Все ключевые договоренности и задачи, зафиксированные за неделю)

### 🔥 Самые горячие темы и яркие дискуссии
- (Темы, вызвавшие наибольший резонанс и активность участников)

---
Дневные хроники недели:
{all_days_text}
"""

        summary = self._call_gemini(prompt)
        if not summary:
            summary = f"## 🏆 Недельный дайджест ({week_key}: {start_date} — {end_date})\n\n"
            summary += f"За неделю накоплено {len(daily_summaries)} дневных отчетов.\n\n"
            summary += all_days_text

        return summary

    def summarize_month(self, weekly_summaries: List[Dict[str, Any]], month_key: str) -> str:
        """Генерирует месячный архивный обзор и летопись событий."""
        if not weekly_summaries:
            return f"За месяц {month_key} нет данных для формирования архива."

        weeks_text = []
        for w in weekly_summaries:
            w_key = w.get("week_key", "")
            w_sum = w.get("summary_md", "")
            weeks_text.append(f"### Неделя {w_key}:\n{w_sum}\n")

        lang_mode = config.SUMMARY_LANGUAGE.lower()
        if lang_mode == "en":
            lang_instruction = "Write the monthly chronicle in English."
        elif lang_mode == "auto":
            lang_instruction = "Пиши на основном языке общения месяца."
        else:
            lang_instruction = "Пиши месячную летопись на русском языке, сохраняя оригинальные термины и названия."

        prompt = f"""Составь масштабную **Летопись и карту событий месяца ({month_key})** на основе недельных дайджестов беседы.
Выдели макро-таймлайн месяца: с чего начинали, какие ключевые сюжетные линии развивались по неделям и к каким результатам пришли.

Правила:
- {lang_instruction}

Формат в Markdown:
# 📅 Летопись месяца: {month_key}
## 🌟 Главная сюжетная линия и итоги месяца
## 🗺️ Таймлайн развития событий по неделям
## 🎯 Итоговые результаты и решения месяца

---
Недельные дайджесты:
{chr(10).join(weeks_text)}
"""
        summary = self._call_gemini(prompt)
        if not summary:
            summary = f"# 📅 Месячный отчет: {month_key}\n\n" + "\n\n".join(weeks_text)
        return summary

    def _generate_heuristic_daily_summary(self, date_str: str, stats: dict, 
                                          messages: List[Dict[str, Any]]) -> str:
        """Эвристическая сводка и таймлайн при отсутствии API-ключа Gemini."""
        top_users_str = ", ".join([f"**{u[0]}** ({u[1]} сообщ.)" for u in stats.get("top_users", [])])
        
        md = f"## 📌 Краткая суть дня ({date_str})\n\n"
        md += f"За день участники отправили **{stats.get('total_messages', 0)}** сообщений. Активно вели беседу: {top_users_str}.\n\n"
        
        md += "### 🕒 Хроника событий и таймлайн обсуждения\n"
        # Выбираем ключевые сообщения
        sample_size = min(len(messages), 10)
        step = max(1, len(messages) // sample_size)
        sample_msgs = messages[::step][:sample_size]
        
        for m in sample_msgs:
            t = m.get("time_str", "")
            name = m.get("full_name") or f"id{m.get('from_id')}"
            text = m.get("text", "").strip()
            if text:
                md += f"- **`[{t}]` {name}:** {text[:140]}{'...' if len(text) > 140 else ''}\n"

        md += "\n> 💡 *Примечание: Для включения полноценного AI-анализа таймлайна укажите `GEMINI_API_KEY` в файле `.env`.*"
        return md

summarizer = GeminiSummarizer()
