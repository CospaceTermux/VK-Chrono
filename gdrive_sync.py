import os
import json
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
import requests
from config import config

logger = logging.getLogger(__name__)

class GoogleDriveSync:
    """Модуль автоматической загрузки HTML-отчетов в Google Drive."""

    def __init__(self):
        self.folder_id = config.GDRIVE_FOLDER_ID
        self.service_account_file = config.GDRIVE_SERVICE_ACCOUNT_FILE
        self.local_gdrive_path = config.GDRIVE_LOCAL_PATH
        self._credentials = None

    @property
    def is_enabled(self) -> bool:
        """Проверяет, включена ли интеграция с Google Drive."""
        if not config.GDRIVE_ENABLED:
            return False
        # Включено либо через локальную папку синхронизации, либо через API
        return bool(self.local_gdrive_path or (self.service_account_file and self.folder_id))

    def _get_access_token(self) -> Optional[str]:
        """Получает токен доступа через Google Service Account."""
        sa_path = Path(self.service_account_file) if self.service_account_file else None
        if not sa_path:
            return None
        
        if not sa_path.is_absolute():
            sa_path = config.BASE_DIR / sa_path

        if not sa_path.exists():
            logger.error(f"Файл ключа сервисного аккаунта Google не найден: {sa_path}")
            return None

        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests

            scopes = ["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
            creds = service_account.Credentials.from_service_account_file(str(sa_path), scopes=scopes)
            
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
        2. Если настроен Service Account API — отправляет файл в папку на Google Drive по API.
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

        # Вариант 2: Загрузка через Google Drive REST API
        if self.service_account_file and self.folder_id:
            token = self._get_access_token()
            if token:
                try:
                    with open(local_path, "rb") as f:
                        file_content = f.read()

                    existing_file_id = self._find_existing_file_id(token, filename)
                    headers = {"Authorization": f"Bearer {token}"}

                    if existing_file_id:
                        # Обновляем существующий файл (PATCH)
                        upload_url = f"https://www.googleapis.com/upload/drive/v3/files/{existing_file_id}?uploadType=media"
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
                        upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
                        resp = requests.post(upload_url, headers=headers, files=files, timeout=30)
                        if resp.status_code in [200, 201]:
                            logger.info(f"☁️ [Google Drive] HTML-отчет успешно загружен в папку: {filename}")
                            success = True
                        else:
                            logger.error(f"Ошибка загрузки на Google Drive ({resp.status_code}): {resp.text}")

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

        if self.service_account_file and self.folder_id:
            token = self._get_access_token()
            if not token:
                return False

            headers = {"Authorization": f"Bearer {token}"}
            url = f"https://www.googleapis.com/drive/v3/files/{self.folder_id}?fields=id,name,capabilities"
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info(f"✅ Успешное подключение к Google Drive! Папка: '{data.get('name')}' (ID: {data.get('id')})")
                    return True
                else:
                    logger.error(f"❌ Ошибка доступа к папке Google Drive ({resp.status_code}): {resp.text}")
                    logger.info("Убедитесь, что вы предоставили доступ (Редактор) сервисному аккаунту к этой папке на Google Диске!")
                    return False
            except Exception as e:
                logger.error(f"❌ Ошибка сети при проверке Google Drive: {e}")
                return False

        return False

gdrive_sync = GoogleDriveSync()
