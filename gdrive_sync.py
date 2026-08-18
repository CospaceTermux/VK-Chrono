import os
import json
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
import requests
from config import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive"
]

class GoogleDriveSync:
    """Модуль автоматической загрузки HTML-отчетов в Google Drive (OAuth2 / Service Account / Local)."""

    def __init__(self):
        self.folder_id = config.GDRIVE_FOLDER_ID
        self.service_account_file = config.GDRIVE_SERVICE_ACCOUNT_FILE
        self.credentials_file = os.getenv("GDRIVE_OAUTH_CREDENTIALS", "credentials.json")
        self.token_file = os.getenv("GDRIVE_TOKEN_FILE", "token.json")
        self.local_gdrive_path = config.GDRIVE_LOCAL_PATH

    @property
    def is_enabled(self) -> bool:
        """Проверяет, включена ли интеграция с Google Drive."""
        if not config.GDRIVE_ENABLED:
            return False
        # Включено через локальную папку, OAuth2 или Service Account
        has_oauth = Path(self.credentials_file).exists() or Path(self.token_file).exists()
        has_sa = self.service_account_file and Path(self.service_account_file).exists()
        return bool(self.local_gdrive_path or has_oauth or has_sa)

    def _get_oauth_access_token(self, interactive: bool = False) -> Optional[str]:
        """Получает токен пользователя через OAuth 2.0 (для личных Google аккаунтов)."""
        token_path = Path(self.token_file)
        if not token_path.is_absolute():
            token_path = config.BASE_DIR / token_path

        creds_path = Path(self.credentials_file)
        if not creds_path.is_absolute():
            creds_path = config.BASE_DIR / creds_path

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            import google.auth.transport.requests

            creds = None
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    auth_req = google.auth.transport.requests.Request()
                    creds.refresh(auth_req)
                    with open(token_path, "w", encoding="utf-8") as token_f:
                        token_f.write(creds.to_json())
                elif interactive and creds_path.exists():
                    logger.info("Открытие браузера для авторизации Google Drive...")
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                    creds = flow.run_local_server(port=0)
                    with open(token_path, "w", encoding="utf-8") as token_f:
                        token_f.write(creds.to_json())
                    logger.info(f"✅ Авторизация успешна! Токен сохранен в {token_path.name}")
                elif not creds:
                    return None

            return creds.token if creds else None
        except Exception as e:
            logger.error(f"Ошибка OAuth2 авторизации Google: {e}")
            return None

    def _get_access_token(self, interactive: bool = False) -> Optional[str]:
        """Получает токен доступа: сначала OAuth 2.0 (личный аккаунт), затем Service Account."""
        # 1. Проверяем OAuth 2.0 пользователя (рекомендуется для личных Google Drive)
        oauth_token = self._get_oauth_access_token(interactive=interactive)
        if oauth_token:
            return oauth_token

        # 2. Проверяем Service Account (для Workspace / Shared Drives)
        sa_path = Path(self.service_account_file) if self.service_account_file else None
        if sa_path:
            if not sa_path.is_absolute():
                sa_path = config.BASE_DIR / sa_path

            if sa_path.exists():
                try:
                    from google.oauth2 import service_account
                    import google.auth.transport.requests

                    creds = service_account.Credentials.from_service_account_file(str(sa_path), scopes=SCOPES)
                    auth_req = google.auth.transport.requests.Request()
                    creds.refresh(auth_req)
                    return creds.token
                except Exception as e:
                    logger.error(f"Ошибка аутентификации Google Service Account: {e}")

        return None

    def _find_existing_file_id(self, token: str, filename: str) -> Optional[str]:
        """Ищет ID существующего файла в целевой папке Google Drive для обновления."""
        headers = {"Authorization": f"Bearer {token}"}
        query = f"name = '{filename}' and '{self.folder_id}' in parents and trashed = false"
        url = f"https://www.googleapis.com/drive/v3/files?q={query}&fields=files(id, name)"
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                files = resp.json().get("files", [])
                if files:
                    return files[0]["id"]
        except Exception as e:
            logger.warning(f"Не удалось проверить наличие файла на Google Drive: {e}")
        return None

    def upload_html(self, local_path: Path, target_filename: Optional[str] = None) -> bool:
        """
        Загружает HTML-отчет в Google Drive:
        1. Если настроен GDRIVE_LOCAL_PATH (приложение Google Диск для ПК) — копирует файл туда.
        2. Если настроен OAuth2 или Service Account API — отправляет файл в папку на Google Drive по API.
        """
        if not self.is_enabled:
            return False

        if not local_path.exists():
            logger.error(f"Локальный файл не найден для выгрузки в Google Drive: {local_path}")
            return False

        filename = target_filename or local_path.name
        success = False

        # Вариант 1: Копирование в локальную папку Google Диска для ПК
        if self.local_gdrive_path:
            local_target_dir = Path(self.local_gdrive_path)
            if local_target_dir.exists():
                try:
                    dest = local_target_dir / filename
                    shutil.copy2(local_path, dest)
                    logger.info(f"📂 [Google Drive] HTML-отчет скопирован в локальную папку Диска: {dest}")
                    success = True
                except Exception as e:
                    logger.error(f"Ошибка копирования в локальную папку Google Drive: {e}")

        # Вариант 2: Загрузка через Google Drive API (OAuth 2.0 / Service Account)
        if self.folder_id:
            token = self._get_access_token(interactive=False)
            if token:
                try:
                    with open(local_path, "rb") as f:
                        file_content = f.read()

                    existing_file_id = self._find_existing_file_id(token, filename)
                    headers = {"Authorization": f"Bearer {token}"}

                    if existing_file_id:
                        # Обновляем существующий файл (PATCH)
                        upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{existing_file_id}?uploadType=media&supportsAllDrives=true"
                        resp = requests.patch(upload_url, headers=headers, data=file_content, timeout=30)
                        if resp.status_code == 200:
                            logger.info(f"☁️ [Google Drive] HTML-отчет успешно обновлен в папке: {filename}")
                            success = True
                        else:
                            logger.error(f"Ошибка обновления файла на Google Drive ({resp.status_code}): {resp.text}")
                    else:
                        # Создаем новый файл через multipart/related (POST)
                        metadata = {
                            "name": filename,
                            "parents": [self.folder_id],
                            "mimeType": "text/html"
                        }
                        files = {
                            "data": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
                            "file": (filename, file_content, "text/html")
                        }
                        upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true"
                        resp = requests.post(upload_url, headers=headers, files=files, timeout=30)
                        if resp.status_code in [200, 201]:
                            logger.info(f"☁️ [Google Drive] HTML-отчет успешно загружен в папку: {filename}")
                            success = True
                        else:
                            logger.error(f"Ошибка загрузки на Google Drive ({resp.status_code}): {resp.text}")
                            if "storage quota" in resp.text.lower():
                                logger.warning("💡 Сервисные аккаунты Google не имеют квоты на личных дисках. Используйте OAuth2 (credentials.json) или Google Диск для ПК.")

                except Exception as e:
                    logger.error(f"Исключение при выгрузке HTML на Google Drive: {e}")

        return success

    def test_connection(self) -> bool:
        """Проверяет подключение к Google Drive."""
        if not self.is_enabled:
            logger.error("Интеграция с Google Drive отключена в .env (GDRIVE_ENABLED=false)")
            return False

        if self.local_gdrive_path:
            p = Path(self.local_gdrive_path)
            if p.exists() and p.is_dir():
                logger.info(f"✅ Локальная папка Google Drive найдена: {p}")
                return True
            else:
                logger.error(f"❌ Локальная папка Google Drive не найдена: {self.local_gdrive_path}")

        if self.folder_id:
            token = self._get_access_token(interactive=True)
            if not token:
                logger.error("Не удалось получить токен доступа Google Drive.")
                return False

            headers = {"Authorization": f"Bearer {token}"}
            url = f"https://www.googleapis.com/drive/v3/files/{self.folder_id}?fields=id,name,capabilities&supportsAllDrives=true"
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info(f"✅ Успешное подключение к Google Drive! Папка: '{data.get('name')}' (ID: {data.get('id')})")
                    return True
                else:
                    logger.error(f"❌ Ошибка доступа к папке Google Drive ({resp.status_code}): {resp.text}")
                    return False
            except Exception as e:
                logger.error(f"❌ Ошибка сети при проверке Google Drive: {e}")
                return False

        return False

gdrive_sync = GoogleDriveSync()
