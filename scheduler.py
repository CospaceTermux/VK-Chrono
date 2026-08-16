import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from config import config
from database import db
from aggregator import aggregator

logger = logging.getLogger(__name__)

class ChronoScheduler:
    """Фоновый планировщик задач для автоматической полуночной компиляции."""

    def __init__(self):
        self.scheduler = BackgroundScheduler()

    def _midnight_job(self):
        """Задача, выполняющаяся каждую полночь."""
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"⏰ [Планировщик] Запуск полуночной сборки за {yesterday_str}...")

        peers = db.get_distinct_peers()
        if not peers and config.TARGET_PEER_ID > 0:
            peers = [config.TARGET_PEER_ID]

        for peer_id in peers:
            try:
                # 1. Компилируем день
                aggregator.compile_day(peer_id, yesterday_str)
                # 2. Проверяем накопление недели и месяца
                aggregator.check_and_aggregate_all(peer_id)
            except Exception as e:
                logger.error(f"Ошибка при фоновой компиляции peer_id {peer_id}: {e}")

    def start(self):
        """Запуск планировщика."""
        # Запуск в 00:00:10 каждый день
        self.scheduler.add_job(
            self._midnight_job,
            trigger="cron",
            hour=0,
            minute=0,
            second=10,
            id="daily_midnight_compile",
            replace_existing=True
        )
        self.scheduler.start()
        logger.info("⏰ Планировщик VK Chrono активен (ежедневная компиляция в 00:00:10).")

    def stop(self):
        """Остановка планировщика."""
        if self.scheduler.running:
            self.scheduler.shutdown()

scheduler = ChronoScheduler()
