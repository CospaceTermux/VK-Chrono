import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from config import config
from database import db
from vk_client import vk_client
from summarizer import summarizer
from renderer import renderer
from aggregator import aggregator
from scheduler import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("VKChrono")

def cmd_start(args):
    """Запуск бота в фоновом режиме со слушателем LongPoll и планировщиком."""
    logger.info("Запуск VK Chrono...")
    
    # 1. Проверяем настройки
    if not config.VK_TOKEN or not config.VK_GROUP_ID:
        logger.error("❌ Не заданы VK_TOKEN или VK_GROUP_ID в файле .env!")
        logger.info("Скопируйте .env.example в .env и укажите ваши ключи доступа.")
        return

    # 2. Запускаем планировщик
    scheduler.start()

    # 3. Запускаем LongPoll слушатель
    try:
        vk_client.run_polling()
    except KeyboardInterrupt:
        logger.info("Остановка бота по сигналу пользователя...")
        scheduler.stop()

def cmd_compile_day(args):
    """Ручная компиляция отчета за конкретную дату (автоматически для всех бесед, если peer не указан)."""
    peers = [args.peer] if args.peer else ([config.TARGET_PEER_ID] if config.TARGET_PEER_ID > 0 else db.get_distinct_peers())
    
    if not peers:
        logger.warning("В базе данных пока нет сообщений. Напишите что-нибудь в беседе с ботом!")
        return

    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    for peer_id in peers:
        logger.info(f"Компиляция дня {target_date} для беседы {peer_id}...")
        success = aggregator.compile_day(peer_id, target_date)
        if success:
            logger.info(f"✨ Готово для беседы {peer_id}! Отчет сохранен в {config.DAILY_REPORTS_DIR}")
        else:
            logger.warning(f"Для беседы {peer_id} нет сообщений за дату {target_date}.")

def cmd_compile_week(args):
    """Ручная компиляция конкретной недели (автоматически для всех бесед, если peer не указан)."""
    peers = [args.peer] if args.peer else ([config.TARGET_PEER_ID] if config.TARGET_PEER_ID > 0 else db.get_distinct_peers())
    
    if not peers:
        logger.warning("В базе данных пока нет сообщений.")
        return

    curr_year = datetime.now().year
    curr_week = datetime.now().isocalendar()[1]
    week_key = args.week or f"{curr_year}-W{curr_week:02d}"
    
    for peer_id in peers:
        distinct_dates = db.get_distinct_dates_for_peer(peer_id)
        matching_days = []
        for d_str in distinct_dates:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
            w_key = f"{d_obj.year}-W{d_obj.isocalendar()[1]:02d}"
            if w_key == week_key:
                d_sum = db.get_daily_summary(d_str, peer_id)
                if not d_sum:
                    aggregator.compile_day(peer_id, d_str)
                    d_sum = db.get_daily_summary(d_str, peer_id)
                if d_sum:
                    matching_days.append(d_sum)

        if matching_days:
            aggregator.compile_week(peer_id, week_key, matching_days)
            logger.info(f"✨ Недельный отчет {week_key} для беседы {peer_id} готов!")
        else:
            logger.warning(f"Нет дневных данных за неделю {week_key} для беседы {peer_id}")

def cmd_compile_month(args):
    """Ручная компиляция конкретного месяца (автоматически для всех бесед, если peer не указан)."""
    peers = [args.peer] if args.peer else ([config.TARGET_PEER_ID] if config.TARGET_PEER_ID > 0 else db.get_distinct_peers())
    
    if not peers:
        logger.warning("В базе данных пока нет сообщений.")
        return

    month_key = args.month or datetime.now().strftime("%Y-%m")
    
    for peer_id in peers:
        with db.get_connection() as conn:
            rows = conn.execute("SELECT * FROM weekly_reports WHERE peer_id = ? ORDER BY week_key ASC", (peer_id,)).fetchall()
            matching_weeks = [dict(r) for r in rows if r["start_date"].startswith(month_key)]

        if matching_weeks:
            aggregator.compile_month(peer_id, month_key, matching_weeks)
            logger.info(f"✨ Месячный отчет {month_key} для беседы {peer_id} готов!")
        else:
            logger.warning(f"Нет недельных дайджестов за месяц {month_key} для беседы {peer_id}")

def cmd_aggregate_all(args):
    """Агрегация всех нескомпилированных данных (дни, недели, месяцы)."""
    peers = [args.peer] if args.peer else db.get_distinct_peers()
    if not peers and config.TARGET_PEER_ID > 0:
        peers = [config.TARGET_PEER_ID]

    if not peers:
        logger.warning("Нет доступных бесед с сообщениями в базе данных.")
        return

    for p in peers:
        logger.info(f"Агрегация данных для беседы {p}...")
        aggregator.check_and_aggregate_all(p)
    logger.info("✨ Полная агрегация завершена!")

def cmd_simulate(args):
    """
    Симуляция реалистичной переписки за N дней.
    Создает виртуальных пользователей, скачивает/генерирует аватарки,
    заполняет сообщениями и запускает полную цепочку сборки:
    День -> 7 Дней (Неделя) -> Месяц.
    """
    num_days = args.days or 7
    peer_id = 2000000001
    logger.info(f"🧪 Запуск симуляции диалога на {num_days} дней для беседы {peer_id}...")

    # Создаем виртуальных участников
    users_data = [
        {"id": 101, "first": "Алексей", "last": "Смирнов", "domain": "alex_smirnov", "color": "#3b82f6"},
        {"id": 102, "first": "Екатерина", "last": "Волкова", "domain": "katya_volkova", "color": "#ec4899"},
        {"id": 103, "first": "Дмитрий", "last": "Ковалев", "domain": "dmitry_kov", "color": "#10b981"},
        {"id": 104, "first": "Ольга", "last": "Морозова", "domain": "olga_moroz", "color": "#f59e0b"},
    ]

    # Генерируем SVG/JPEG аватарки для виртуальных участников
    for u in users_data:
        avatar_path = config.AVATARS_DIR / f"{u['id']}.jpg"
        if not avatar_path.exists():
            # Создаем базовую картинку-аватар с инициалами (SVG или базовая заглушка)
            initials = f"{u['first'][0]}{u['last'][0]}"
            # Сохраняем SVG в jpg расширение (браузеры рендерят base64 отлично)
            svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="50" fill="{u['color']}"/>
                <text x="50%" y="55%" text-anchor="middle" dominant-baseline="middle" fill="#ffffff" font-size="36" font-family="Arial, sans-serif" font-weight="bold">{initials}</text>
            </svg>"""
            with open(avatar_path, "w", encoding="utf-8") as f:
                f.write(svg_content)

        db.upsert_user(
            user_id=u["id"],
            first_name=u["first"],
            last_name=u["last"],
            domain=u["domain"],
            avatar_path=str(avatar_path),
            avatar_url=""
        )

    # Заполняем сообщения по дням
    base_date = datetime.now() - timedelta(days=num_days)
    
    dialogues_by_day = [
        [
            (101, "Всем привет! Начинаем работу над новым релизом сервиса доставки."),
            (102, "Привет! Я подготовила макеты главной страницы и корзины. Ссылка: https://example.com/figma"),
            (103, "Отлично, я сегодня займусь настройкой базы данных и авторизации через VK ID."),
            (104, "Супер! Я соберу требования по аналитике и платежным шлюзам."),
            (101, "Договорились. Дедлайн по первой версии — следующая пятница. Встречаемся каждый день в 11:00."),
        ],
        [
            (103, "Настроил схемы SQLite и миграции. Авторизация работает стабильно."),
            (102, "Алексей, посмотри цвета кнопок в корзине, сделали синий акцент как в гайдлайнах."),
            (101, "Выглядит отлично! Главное не забыть про адаптивность для мобильных."),
            (104, "Подключила тестовый эквайринг, проверила успешную оплату на 1 рубль. Всё проходит."),
        ],
        [
            (101, "Коллеги, у нас возник вопрос по хранению логов и кэшированию аватарок."),
            (103, "Предлагаю сохранять аватары локально в base64 или файлы, чтобы отчеты открывались автономно."),
            (102, "Полностью поддерживаю! Так можно будет читать дайджесты даже без интернета."),
            (104, "Да, и добавим умную сводку через Gemini, чтобы быстро видеть ключевые решения."),
            (101, "Утверждено! Дмитрий, делай реализацию."),
        ],
        [
            (102, "Добавила анимации переходов и темную тему для мобильных экранов."),
            (103, "Тестирую фоновый планировщик компиляции. В 00:00 бот генерирует HTML и Markdown."),
            (101, "Протестировал на тестовой выборке сообщений — сводки формируются очень точно."),
            (104, "Подготовила документацию для команды. Завтра выкатываем на тестирование."),
        ],
        [
            (101, "Сегодня проводим нагрузочное тестирование чат-бота."),
            (103, "Обработали 5000 сообщений за 2 секунды. SQLite в WAL-режиме справляется отлично."),
            (102, "Исправила пару мелких багов с отображением стикеров и цитирования."),
            (104, "Пользователи в восторге от недельных дайджестов!"),
        ],
        [
            (102, "Обновила иконки и шрифты. Добавила фильтрацию сообщений по авторам прямо на странице отчета."),
            (101, "Шикарная фича, теперь можно в один клик отфильтровать сообщения любого участника."),
            (103, "Проверил генерацию недельных архивов — объединение 7 дней в один дайджест работает как часы."),
            (104, "Согласовали план на следующий месяц: интеграция с голосовыми сообщениями."),
        ],
        [
            (101, "Финальный день первой недели спринта! Подводим итоги."),
            (102, "Все макеты переданы в прод, дизайн-система зафиксирована."),
            (103, "Сервис логирования, сводок и компиляции в дни/недели/месяцы готов на 100%."),
            (104, "Все задачи закрыты без просрочек. Отличная работа, команда! 🎉"),
            (101, "Спасибо всем! Запускаем автоматическую компиляцию недели."),
        ]
    ]

    for day_idx in range(num_days):
        current_day = base_date + timedelta(days=day_idx)
        date_str = current_day.strftime("%Y-%m-%d")
        
        day_dialog = dialogues_by_day[day_idx % len(dialogues_by_day)]
        
        for msg_idx, (user_id, text) in enumerate(day_dialog):
            msg_time = current_day.replace(hour=10 + (msg_idx * 2), minute=(msg_idx * 15) % 60)
            db.save_message(
                vk_msg_id=1000 + day_idx * 100 + msg_idx,
                peer_id=peer_id,
                from_id=user_id,
                text=text,
                attachments=[],
                reply=None,
                fwd=[],
                timestamp=int(msg_time.timestamp())
            )

    logger.info("✅ База данных успешно заполнена тестовыми сообщениями.")
    
    # Запускаем агрегацию
    logger.info("🚀 Запуск полной сборки (Дни -> Неделя -> Месяц)...")
    aggregator.check_and_aggregate_all(peer_id)
    
    logger.info("\n========================================================")
    logger.info("🎉 СИМУЛЯЦИЯ И КОМПИЛЯЦИЯ УСПЕШНО ЗАВЕРШЕНЫ!")
    logger.info(f"📁 Дневные отчеты:  {config.DAILY_REPORTS_DIR}")
    logger.info(f"📁 Недельные отчеты: {config.WEEKLY_REPORTS_DIR}")
    logger.info(f"📁 Месячные отчеты:  {config.MONTHLY_REPORTS_DIR}")
    logger.info("========================================================\n")

def cmd_test_github(args):
    """Проверка подключения к GitHub репозиторию."""
    from github_sync import github_sync
    if github_sync.test_connection():
        logger.info("🎉 Подключение к GitHub работает корректно!")
    else:
        logger.error("Проверьте GITHUB_TOKEN и GITHUB_REPO в .env")

def main():
    parser = argparse.ArgumentParser(description="VK Chrono - Бот логирования бесед VK с AI-суммаризацией")
    subparsers = parser.add_subparsers(dest="command", help="Команда для выполнения")

    # start
    subparsers.add_parser("start", help="Запустить бота в режиме реального времени")

    # compile-day
    p_day = subparsers.add_parser("compile-day", help="Скомпилировать отчет за конкретный день")
    p_day.add_argument("--date", type=str, help="Дата в формате YYYY-MM-DD (по умолчанию сегодня)")
    p_day.add_argument("--peer", type=int, help="ID беседы")

    # compile-week
    p_week = subparsers.add_parser("compile-week", help="Скомпилировать отчет за неделю (YYYY-Www)")
    p_week.add_argument("--week", type=str, help="Неделя в формате YYYY-Www (например, 2026-W33)")
    p_week.add_argument("--peer", type=int, help="ID беседы")

    # compile-month
    p_month = subparsers.add_parser("compile-month", help="Скомпилировать отчет за месяц (YYYY-MM)")
    p_month.add_argument("--month", type=str, help="Месяц в формате YYYY-MM (например, 2026-08)")
    p_month.add_argument("--peer", type=int, help="ID беседы")

    # aggregate-all
    p_agg = subparsers.add_parser("aggregate-all", help="Скомпилировать все нескомпилированные дни, недели и месяцы")
    p_agg.add_argument("--peer", type=int, help="ID беседы")

    # test-github
    subparsers.add_parser("test-github", help="Проверить подключение и права на запись в GitHub репозиторий")

    # simulate
    p_sim = subparsers.add_parser("simulate", help="Запустить симуляцию 7 дней переписки и проверить всю цепочку")
    p_sim.add_argument("--days", type=int, default=7, help="Количество дней симуляции (по умолчанию 7)")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "compile-day":
        cmd_compile_day(args)
    elif args.command == "compile-week":
        cmd_compile_week(args)
    elif args.command == "compile-month":
        cmd_compile_month(args)
    elif args.command == "aggregate-all":
        cmd_aggregate_all(args)
    elif args.command == "test-github":
        cmd_test_github(args)
    elif args.command == "simulate":
        cmd_simulate(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
