import os
import time
import base64
import logging
import requests
from pathlib import Path
from typing import Optional
from config import config

logger = logging.getLogger(__name__)

class GitHubSync:
    """Модуль автоматической синхронизации и загрузки отчетов в GitHub репозиторий."""

    def __init__(self):
        self.token = config.GITHUB_TOKEN
        self.repo = config.GITHUB_REPO  # "owner/repo-name"
        self.branch = config.GITHUB_BRANCH
        self.path_prefix = config.GITHUB_PATH_PREFIX

    @property
    def is_enabled(self) -> bool:
        """Включена ли интеграция с GitHub."""
        return bool(config.GITHUB_ENABLED and self.token and self.repo)

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "VK-Chrono-Bot"
        }

    def _get_file_sha(self, remote_path: str) -> Optional[str]:
        """Получает SHA существующего файла в репозитории (нужно для перезаписи)."""
        url = f"https://api.github.com/repos/{self.repo}/contents/{remote_path}?ref={self.branch}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json().get("sha")
        except Exception as e:
            logger.warning(f"Не удалось проверить SHA файла на GitHub ({remote_path}): {e}")
        return None

    def ensure_repo_exists(self) -> bool:
        """
        Проверяет наличие репозитория на GitHub.
        Если репозитория не существует — автоматически создает его!
        """
        if not self.token or not self.repo:
            return False

        owner, repo_name = self.repo.split("/") if "/" in self.repo else ("", self.repo)
        
        # 1. Проверяем, существует ли репозиторий
        url = f"https://api.github.com/repos/{self.repo}"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                return True
            elif resp.status_code == 404:
                # 2. Репозиторий не найден -> Создаем его автоматически!
                logger.info(f"📁 [GitHub] Репозиторий '{self.repo}' не найден. Создаю новый репозиторий автоматически...")
                create_url = "https://api.github.com/user/repos"
                payload = {
                    "name": repo_name,
                    "description": "VK Chat Logs & AI Digests (сгенерировано VK Chrono)",
                    "private": config.GITHUB_REPO_PRIVATE,
                    "auto_init": True
                }
                create_resp = requests.post(create_url, headers=self._get_headers(), json=payload, timeout=15)
                if create_resp.status_code in [200, 201]:
                    logger.info(f"✨ [GitHub] Репозиторий '{self.repo}' успешно создан автоматически (Private: {config.GITHUB_REPO_PRIVATE})!")
                    time.sleep(2)  # Даем секунду GitHub на инициализацию ветки main
                    return True
                else:
                    logger.error(f"❌ Не удалось автоматически создать репозиторий: {create_resp.text}")
                    return False
        except Exception as e:
            logger.error(f"Ошибка при проверке/создании репозитория GitHub: {e}")
            return False
        return False

    def upload_file(self, local_path: Path, remote_subpath: str, commit_message: str) -> bool:
        """
        Загружает или обновляет локальный файл в GitHub репозитории через GitHub REST API.
        """
        if not self.is_enabled:
            return False

        if not local_path.exists():
            logger.error(f"Локальный файл не найден для выгрузки в GitHub: {local_path}")
            return False

        # Гарантируем, что репозиторий создан
        if not self.ensure_repo_exists():
            return False

        # Формируем путь внутри репозитория (например, reports/daily/day_...html)
        remote_path = f"{self.path_prefix.strip('/')}/{remote_subpath.strip('/')}".strip('/')

        try:
            with open(local_path, "rb") as f:
                content_base64 = base64.b64encode(f.read()).decode("utf-8")

            sha = self._get_file_sha(remote_path)
            url = f"https://api.github.com/repos/{self.repo}/contents/{remote_path}"

            payload = {
                "message": commit_message,
                "content": content_base64,
                "branch": self.branch
            }
            if sha:
                payload["sha"] = sha

            resp = requests.put(url, headers=self._get_headers(), json=payload, timeout=20)
            
            if resp.status_code in [200, 201]:
                logger.info(f"🚀 [GitHub] Файл успешно выгружен в {self.repo}/{remote_path} (коммит: {commit_message})")
                return True
            else:
                logger.error(f"Ошибка загрузки в GitHub ({resp.status_code}): {resp.text}")
                return False

        except Exception as e:
            logger.error(f"Исключение при выгрузке в GitHub ({remote_path}): {e}")
            return False

    def test_connection(self) -> bool:
        """Проверяет права доступа к репозиторию или создает его при отсутствии."""
        if not self.token or not self.repo:
            logger.error("GITHUB_TOKEN или GITHUB_REPO не указаны в .env")
            return False

        return self.ensure_repo_exists()

github_sync = GitHubSync()
