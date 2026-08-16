import base64
import html
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import markdown
from jinja2 import Environment, FileSystemLoader
from config import config

class ReportRenderer:
    """Генератор автономных HTML и Markdown отчетов."""

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(config.TEMPLATES_DIR)),
            autoescape=False
        )
        self._avatars_base64_cache = {}

    def _get_avatar_base64(self, local_path: Optional[str], avatar_url: Optional[str]) -> Optional[str]:
        """Возвращает base64 data-uri аватара для создания полностью автономного HTML."""
        if not local_path:
            return avatar_url or None

        p = Path(local_path)
        if not p.is_absolute():
            p = config.BASE_DIR / local_path

        if str(p) in self._avatars_base64_cache:
            return self._avatars_base64_cache[str(p)]

        if p.exists() and p.is_file():
            try:
                with open(p, "rb") as f:
                    data = base64.b64encode(f.read()).decode("utf-8")
                    data_uri = f"data:image/jpeg;base64,{data}"
                    self._avatars_base64_cache[str(p)] = data_uri
                    return data_uri
            except Exception:
                pass
        
        return avatar_url or None

    def _get_image_base64(self, local_path: Optional[str], fallback_url: Optional[str]) -> Optional[str]:
        """Возвращает base64 data-uri картинки или fallback URL."""
        if local_path:
            p = Path(local_path)
            if not p.is_absolute():
                p = config.BASE_DIR / local_path
            if p.exists() and p.is_file():
                try:
                    with open(p, "rb") as f:
                        data = base64.b64encode(f.read()).decode("utf-8")
                        return f"data:image/jpeg;base64,{data}"
                except Exception:
                    pass
        return fallback_url or None

    def _format_message_text(self, text: str) -> str:
        """Экранирует HTML и делает ссылки кликабельными."""
        if not text:
            return ""
        escaped = html.escape(text)
        # Преобразуем URL в активные ссылки
        url_pattern = re.compile(r'(https?://[^\s<>"]+|www\.[^\s<>"]+)')
        formatted = url_pattern.sub(r'<a href="\1" target="_blank" rel="noopener noreferrer" style="color: var(--accent);">\1</a>', escaped)
        return formatted.replace("\n", "<br>")

    def render_daily_report(self, peer_id: int, date_str: str, 
                            messages: List[Dict[str, Any]], summary_md: str, 
                            stats: Dict[str, Any], output_html_path: Path, 
                            output_md_path: Path):
        """Рендерит дневной отчет в HTML и Markdown."""
        # Готовим список уникальных авторов для фильтра
        authors_map = {}
        for m in messages:
            uid = m.get("from_id")
            name = m.get("full_name") or f"id{uid}"
            if uid not in authors_map:
                authors_map[uid] = {"user_id": uid, "name": name, "count": 0}
            authors_map[uid]["count"] += 1

        authors = sorted(authors_map.values(), key=lambda x: x["count"], reverse=True)

        # Обрабатываем сообщения и вложения для шаблона
        processed_msgs = []
        for m in messages:
            msg_copy = dict(m)
            msg_copy["avatar_src"] = self._get_avatar_base64(m.get("avatar_path"), m.get("avatar_url"))
            msg_copy["text_html"] = self._format_message_text(m.get("text", ""))

            # Обрабатываем вложенные фотографии (встраиваем base64 если есть локальный файл)
            processed_attachments = []
            for att in msg_copy.get("attachments", []):
                att_copy = dict(att)
                if att_copy.get("type") == "photo":
                    local_p = att_copy.get("local_path")
                    att_copy["src"] = self._get_image_base64(local_p, att_copy.get("preview_url") or att_copy.get("url"))
                    att_copy["full_src"] = self._get_image_base64(local_p, att_copy.get("url"))
                processed_attachments.append(att_copy)
            msg_copy["attachments"] = processed_attachments

            processed_msgs.append(msg_copy)

        # Конвертируем markdown сводки в HTML
        summary_html = markdown.markdown(
            summary_md or "",
            extensions=["extra", "nl2br", "sane_lists"]
        )

        template = self.env.get_template("daily_report.html")
        html_content = template.render(
            peer_id=peer_id,
            date_str=date_str,
            messages=processed_msgs,
            authors=authors,
            stats=stats,
            summary_html=summary_html,
            current_year=datetime.now().year
        )

        output_html_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Создаем текстовый Markdown отчет
        md_content = f"# 💬 Дневной отчет беседы — {date_str}\n\n"
        md_content += f"- **Беседа ID:** `{peer_id}`\n"
        md_content += f"- **Сообщений:** {len(messages)}\n"
        md_content += f"- **Участников:** {stats.get('active_users', len(authors))}\n\n"
        md_content += "---\n\n"
        md_content += f"## ✨ Сводка дня\n\n{summary_md}\n\n"
        
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

    def render_weekly_report(self, peer_id: int, week_key: str, start_date: str, end_date: str,
                             daily_data: List[Dict[str, Any]], weekly_summary_md: str,
                             output_html_path: Path, output_md_path: Path):
        """Рендерит недельный дайджест в HTML и Markdown."""
        processed_days = []
        total_messages = 0

        for d in daily_data:
            total_messages += d.get("message_count", 0)
            d_copy = dict(d)
            d_copy["summary_html"] = markdown.markdown(
                d.get("summary_md", ""),
                extensions=["extra", "nl2br", "sane_lists"]
            )
            # Относительный путь к дневному HTML
            if d.get("html_path"):
                d_copy["html_rel_path"] = f"../daily/{Path(d['html_path']).name}"
            else:
                d_copy["html_rel_path"] = ""
            processed_days.append(d_copy)

        weekly_summary_html = markdown.markdown(
            weekly_summary_md or "",
            extensions=["extra", "nl2br", "sane_lists"]
        )

        template = self.env.get_template("weekly_report.html")
        html_content = template.render(
            peer_id=peer_id,
            week_key=week_key,
            start_date=start_date,
            end_date=end_date,
            days=processed_days,
            total_messages=total_messages,
            weekly_summary_html=weekly_summary_html,
            current_year=datetime.now().year
        )

        output_html_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Markdown
        md_content = f"# 📊 Недельный дайджест беседы — {week_key}\n\n"
        md_content += f"**Период:** {start_date} — {end_date} | **Беседа:** `{peer_id}` | **Сообщений:** {total_messages}\n\n"
        md_content += f"## 🏆 Главные итоги недели\n\n{weekly_summary_md}\n\n"
        
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

    def render_monthly_report(self, peer_id: int, month_key: str,
                              weeks_data: List[Dict[str, Any]], monthly_summary_md: str,
                              output_html_path: Path, output_md_path: Path):
        """Рендерит месячный архив в HTML и Markdown."""
        total_messages = 0
        processed_weeks = []

        for w in weeks_data:
            total_messages += w.get("message_count", 0)
            w_copy = dict(w)
            w_copy["summary_html"] = markdown.markdown(
                w.get("summary_md", ""),
                extensions=["extra", "nl2br", "sane_lists"]
            )
            if w.get("html_path"):
                w_copy["html_rel_path"] = f"../weekly/{Path(w['html_path']).name}"
            else:
                w_copy["html_rel_path"] = ""
            processed_weeks.append(w_copy)

        monthly_summary_html = markdown.markdown(
            monthly_summary_md or "",
            extensions=["extra", "nl2br", "sane_lists"]
        )

        template = self.env.get_template("monthly_report.html")
        html_content = template.render(
            peer_id=peer_id,
            month_key=month_key,
            weeks=processed_weeks,
            total_messages=total_messages,
            monthly_summary_html=monthly_summary_html,
            current_year=datetime.now().year
        )

        output_html_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        md_content = f"# 📚 Месячный архив беседы — {month_key}\n\n"
        md_content += f"**Беседа:** `{peer_id}` | **Сообщений:** {total_messages}\n\n"
        md_content += f"{monthly_summary_md}\n\n"

        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

renderer = ReportRenderer()
