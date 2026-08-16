import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from config import config
from database import db
from summarizer import summarizer
from renderer import renderer
from github_sync import github_sync
from gdrive_sync import gdrive_sync
from vk_client import vk_client

logger = logging.getLogger(__name__)

class ReportAggregator:
    """Сервис компиляции отчетов и агрегации (Дни -> Недели -> Месяцы)."""

    def compile_day(self, peer_id: int, date_str: str) -> bool:
        """
        Компилирует дневной лог:
        1. Получает сообщения из БД
        2. Генерирует AI-сводку через Gemini
        3. Рендерит автономный HTML и Markdown
        4. Сохраняет метаданные в SQLite
        5. Автоматически выгружает в GitHub (если включено)
        6. Автоматически выгружает HTML в Google Drive (если включено)
        7. Отправляет уведомление в беседу VK
        """
        messages = db.get_messages_for_date(peer_id, date_str)
        if not messages:
            logger.info(f"[Peer {peer_id}] Нет сообщений за {date_str} для компиляции.")
            return False

        logger.info(f"[Peer {peer_id}] Компиляция дневного отчета за {date_str} ({len(messages)} сообщ.)...")

        # Получаем AI сводку
        day_analysis = summarizer.summarize_day(messages, date_str)
        summary_md = day_analysis["summary_md"]
        stats = day_analysis.get("stats", {"active_users": 0})

        # Пути сохранения
        html_filename = f"day_{peer_id}_{date_str}.html"
        md_filename = f"day_{peer_id}_{date_str}.md"

        html_path = config.DAILY_REPORTS_DIR / html_filename
        md_path = config.DAILY_REPORTS_DIR / md_filename

        # Рендеринг
        renderer.render_daily_report(
            peer_id=peer_id,
            date_str=date_str,
            messages=messages,
            summary_md=summary_md,
            stats=stats,
            output_html_path=html_path,
            output_md_path=md_path
        )

        # Сохранение в БД
        db.save_daily_summary(
            date_str=date_str,
            peer_id=peer_id,
            summary_md=summary_md,
            topics=day_analysis.get("topics", []),
            decisions=day_analysis.get("decisions", []),
            participants=day_analysis.get("participants", []),
            message_count=len(messages),
            html_path=str(html_path),
            md_path=str(md_path)
        )

        # Выгрузка в GitHub
        if github_sync.is_enabled:
            github_sync.upload_file(html_path, f"daily/{html_filename}", f"Add daily HTML report: {date_str}")
            github_sync.upload_file(md_path, f"daily/{md_filename}", f"Add daily MD report: {date_str}")

        # Выгрузка HTML в Google Drive
        if gdrive_sync.is_enabled:
            gdrive_sync.upload_html(html_path, html_filename)

        # Отправка уведомления в беседу
        if config.NOTIFY_CHAT_ON_DAILY_REPORT:
            try:
                formatted_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
            except Exception:
                formatted_date = date_str

            vk_client.send_message(
                peer_id=peer_id,
                message=f"Бот успешно сохранил сообщения за {formatted_date}, продолжайте в том же духе!"
            )

        logger.info(f"✅ Дневной отчет успешно создан: {html_path}")
        return True

    def compile_week(self, peer_id: int, week_key: str, daily_summaries: List[Dict[str, Any]]) -> bool:
        """Компилирует недельный дайджест на основе списка дневных сводок."""
        if not daily_summaries:
            return False

        start_date = daily_summaries[0]["date_str"]
        end_date = daily_summaries[-1]["date_str"]
        total_msgs = sum(d.get("message_count", 0) for d in daily_summaries)

        logger.info(f"[Peer {peer_id}] Компиляция недели {week_key} ({start_date} — {end_date}, {len(daily_summaries)} дн.)...")

        # Генерируем недельный AI-дайджест
        weekly_summary_md = summarizer.summarize_week(
            daily_summaries=daily_summaries,
            week_key=week_key,
            start_date=start_date,
            end_date=end_date
        )

        html_filename = f"week_{peer_id}_{week_key}.html"
        md_filename = f"week_{peer_id}_{week_key}.md"

        html_path = config.WEEKLY_REPORTS_DIR / html_filename
        md_path = config.WEEKLY_REPORTS_DIR / md_filename

        # Рендерим недельный отчет
        renderer.render_weekly_report(
            peer_id=peer_id,
            week_key=week_key,
            start_date=start_date,
            end_date=end_date,
            daily_data=daily_summaries,
            weekly_summary_md=weekly_summary_md,
            output_html_path=html_path,
            output_md_path=md_path
        )

        # Сохраняем в БД
        db.save_weekly_report(
            week_key=week_key,
            peer_id=peer_id,
            start_date=start_date,
            end_date=end_date,
            summary_md=weekly_summary_md,
            days_count=len(daily_summaries),
            message_count=total_msgs,
            html_path=str(html_path),
            md_path=str(md_path)
        )

        # Выгрузка в GitHub
        if github_sync.is_enabled:
            github_sync.upload_file(html_path, f"weekly/{html_filename}", f"Add weekly HTML digest: {week_key}")
            github_sync.upload_file(md_path, f"weekly/{md_filename}", f"Add weekly MD digest: {week_key}")

        # Выгрузка HTML в Google Drive
        if gdrive_sync.is_enabled:
            gdrive_sync.upload_html(html_path, html_filename)

        logger.info(f"✅ Недельный дайджест успешно создан: {html_path}")
        return True

    def compile_month(self, peer_id: int, month_key: str, weeks_data: List[Dict[str, Any]]) -> bool:
        """Компилирует месячный архив."""
        if not weeks_data:
            return False

        logger.info(f"[Peer {peer_id}] Компиляция месяца {month_key} ({len(weeks_data)} нед.)...")

        monthly_summary_md = summarizer.summarize_month(
            weekly_summaries=weeks_data,
            month_key=month_key
        )

        total_msgs = sum(w.get("message_count", 0) for w in weeks_data)
        total_days = sum(w.get("days_count", 0) for w in weeks_data)

        html_filename = f"month_{peer_id}_{month_key}.html"
        md_filename = f"month_{peer_id}_{month_key}.md"

        html_path = config.MONTHLY_REPORTS_DIR / html_filename
        md_path = config.MONTHLY_REPORTS_DIR / md_filename

        renderer.render_monthly_report(
            peer_id=peer_id,
            month_key=month_key,
            weeks_data=weeks_data,
            monthly_summary_md=monthly_summary_md,
            output_html_path=html_path,
            output_md_path=md_path
        )

        db.save_monthly_report(
            month_key=month_key,
            peer_id=peer_id,
            summary_md=monthly_summary_md,
            days_count=total_days,
            message_count=total_msgs,
            html_path=str(html_path),
            md_path=str(md_path)
        )

        # Выгрузка в GitHub
        if github_sync.is_enabled:
            github_sync.upload_file(html_path, f"monthly/{html_filename}", f"Add monthly HTML archive: {month_key}")
            github_sync.upload_file(md_path, f"monthly/{md_filename}", f"Add monthly MD archive: {month_key}")

        # Выгрузка HTML в Google Drive
        if gdrive_sync.is_enabled:
            gdrive_sync.upload_html(html_path, html_filename)

        # Отправка уведомления в беседу
        if config.NOTIFY_CHAT_ON_MONTHLY_REPORT:
            repo_link = f"\n🔗 Репозиторий: https://github.com/{config.GITHUB_REPO}" if config.GITHUB_REPO else ""
            vk_client.send_message(
                peer_id=peer_id,
                message=f"Бот Хранитель успешно создал сводку за месяц. Вы можете ознакомиться с ней в репозитории.{repo_link}"
            )

        logger.info(f"✅ Месячный архив успешно создан: {html_path}")
        return True

    def check_and_aggregate_all(self, peer_id: int):
        """
        Проверяет все дни в беседе:
        1. Компилирует все отдельные нескомпилированные дни
        2. Группирует дни по неделям (по 7 дней или по завершенным календарным неделям ISO)
        3. Объединяет завершенные недели в месячные архивы
        """
        distinct_dates = db.get_distinct_dates_for_peer(peer_id)
        if not distinct_dates:
            return

        # 1. Компилируем все отдельные дни
        for d_str in distinct_dates:
            existing = db.get_daily_summary(d_str, peer_id)
            if not existing:
                self.compile_day(peer_id, d_str)

        # 2. Группируем дни по ISO-неделям (YYYY-Www)
        weeks_map: Dict[str, List[Dict[str, Any]]] = {}
        for d_str in distinct_dates:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
            week_key = f"{d_obj.year}-W{d_obj.isocalendar()[1]:02d}"
            
            d_summary = db.get_daily_summary(d_str, peer_id)
            if d_summary:
                if week_key not in weeks_map:
                    weeks_map[week_key] = []
                weeks_map[week_key].append(d_summary)

        # Компилируем недели: если накопилось >= 7 дней или неделя завершилась, либо если в неделе есть дни
        compiled_weeks = []
        for week_key, days_list in weeks_map.items():
            if len(days_list) >= config.AUTO_AGGREGATE_DAYS or self._is_past_week(week_key) or len(days_list) >= 7:
                self.compile_week(peer_id, week_key, days_list)
            
            # Проверяем наличие отчета в БД
            with db.get_connection() as conn:
                row = conn.execute("SELECT * FROM weekly_reports WHERE week_key = ? AND peer_id = ?", (week_key, peer_id)).fetchone()
                if row:
                    compiled_weeks.append(dict(row))

        # 3. Группируем недели по месяцам (YYYY-MM)
        months_map: Dict[str, List[Dict[str, Any]]] = {}
        for w in compiled_weeks:
            start_date = w["start_date"]
            month_key = start_date[:7]  # YYYY-MM
            if month_key not in months_map:
                months_map[month_key] = []
            months_map[month_key].append(w)

        for month_key, weeks_list in months_map.items():
            if len(weeks_list) >= 4 or self._is_past_month(month_key) or len(weeks_list) >= 1:
                self.compile_month(peer_id, month_key, weeks_list)

    def _is_past_week(self, week_key: str) -> bool:
        """Проверяет, прошла ли уже указанная неделя по календарю."""
        try:
            year, week_num = week_key.split("-W")
            curr_year = datetime.now().year
            curr_week = datetime.now().isocalendar()[1]
            return (int(year) < curr_year) or (int(year) == curr_year and int(week_num) < curr_week)
        except Exception:
            return False

    def _is_past_month(self, month_key: str) -> bool:
        """Проверяет, прошел ли уже указанный месяц."""
        try:
            curr_month_key = datetime.now().strftime("%Y-%m")
            return month_key < curr_month_key
        except Exception:
            return False

aggregator = ReportAggregator()
