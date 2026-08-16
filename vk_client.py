import os
import time
import random
import logging
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from config import config
from database import db

logger = logging.getLogger(__name__)

class VKBotClient:
    """Клиент для работы с VK Bots API и LongPoll."""

    def __init__(self):
        self.token = config.VK_TOKEN
        self.group_id = config.VK_GROUP_ID
        self.target_peer_id = config.TARGET_PEER_ID
        self.vk_session = None
        self.vk = None
        self.longpoll = None
        self._user_cache = {}

    def connect(self) -> bool:
        """Инициализирует сессию VK API."""
        if not self.token or not self.group_id:
            logger.warning("VK_TOKEN или VK_GROUP_ID не заданы в конфигурации.")
            return False

        try:
            self.vk_session = vk_api.VkApi(token=self.token)
            self.vk = self.vk_session.get_api()
            self.longpoll = VkBotLongPoll(self.vk_session, group_id=self.group_id)
            logger.info(f"Успешное подключение к VK API сообщества ID {self.group_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к VK API: {e}")
            return False

    def send_message(self, peer_id: int, message: str) -> bool:
        """Отправляет текстовое сообщение в беседу VK."""
        if not self.vk:
            if not self.connect():
                return False

        try:
            self.vk.messages.send(
                peer_id=peer_id,
                message=message,
                random_id=random.randint(1, 2147483647)
            )
            logger.info(f"📤 [VK] Сообщение успешно отправлено в беседу {peer_id}: {message[:60]}...")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка отправки сообщения в беседу {peer_id}: {e}")
            return False

    def ensure_user(self, user_id: int) -> Dict[str, Any]:
        """
        Проверяет наличие пользователя в кэше и БД,
        при необходимости запрашивает данные у VK API и скачивает аватар.
        """
        if user_id in self._user_cache:
            return self._user_cache[user_id]

        existing = db.get_user(user_id)
        if existing and existing.get("avatar_path") and Path(existing["avatar_path"]).exists():
            self._user_cache[user_id] = existing
            return existing

        # Пользователь - это группа или бот (id < 0)
        if user_id < 0:
            group_info = self._fetch_group_info(abs(user_id))
            if group_info:
                self._user_cache[user_id] = group_info
                return group_info

        # Запрашиваем информацию о пользователе у VK
        first_name = f"User"
        last_name = str(user_id)
        domain = ""
        avatar_url = ""
        avatar_local_path = ""

        if self.vk:
            try:
                res = self.vk.users.get(user_ids=user_id, fields="photo_200,domain")
                if res and len(res) > 0:
                    u = res[0]
                    first_name = u.get("first_name", "Пользователь")
                    last_name = u.get("last_name", str(user_id))
                    domain = u.get("domain", "")
                    avatar_url = u.get("photo_200", "")
            except Exception as e:
                logger.warning(f"Не удалось получить инфо о пользователе {user_id}: {e}")

        # Скачиваем аватар
        if avatar_url:
            avatar_local_path = self._download_avatar(user_id, avatar_url)

        db.upsert_user(
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            domain=domain,
            avatar_path=avatar_local_path,
            avatar_url=avatar_url
        )

        user_data = db.get_user(user_id) or {
            "user_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "domain": domain,
            "avatar_path": avatar_local_path,
            "avatar_url": avatar_url
        }
        self._user_cache[user_id] = user_data
        return user_data

    def _fetch_group_info(self, group_id: int) -> Dict[str, Any]:
        """Получает информацию о сообществе/боте."""
        first_name = "Сообщество"
        last_name = str(group_id)
        domain = ""
        avatar_url = ""
        avatar_local_path = ""

        if self.vk:
            try:
                res = self.vk.groups.getById(group_id=group_id, fields="photo_200,screen_name")
                if res and len(res) > 0:
                    g = res[0]
                    first_name = g.get("name", "Сообщество")
                    last_name = ""
                    domain = g.get("screen_name", "")
                    avatar_url = g.get("photo_200", "")
            except Exception as e:
                logger.warning(f"Не удалось получить инфо о сообществе {group_id}: {e}")

        if avatar_url:
            avatar_local_path = self._download_avatar(-group_id, avatar_url)

        db.upsert_user(
            user_id=-group_id,
            first_name=first_name,
            last_name=last_name,
            domain=domain,
            avatar_path=avatar_local_path,
            avatar_url=avatar_url
        )
        return db.get_user(-group_id)

    def _download_avatar(self, user_id: int, url: str) -> str:
        """Скачивает аватар в локальную папку data/avatars/{user_id}.jpg."""
        if not url:
            return ""
        dest = config.AVATARS_DIR / f"{user_id}.jpg"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    f.write(resp.content)
                return str(dest)
        except Exception as e:
            logger.warning(f"Ошибка скачивания аватара {url}: {e}")
        return ""

    def _download_photo(self, photo_id: int, url: str, date_str: str) -> str:
        """Скачивает фотографию из беседы в локальную папку data/photos/{date_str}/{photo_id}.jpg."""
        if not url or not config.DOWNLOAD_PHOTOS:
            return ""
        
        target_dir = config.PHOTOS_DIR / date_str
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / f"{photo_id}.jpg"

        if dest.exists():
            return str(dest)

        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    f.write(resp.content)
                logger.info(f"📷 [Медиа] Фотография сохранена локально: {dest}")
                return str(dest)
        except Exception as e:
            logger.warning(f"Ошибка скачивания фотографии {url}: {e}")
        return ""

    def _download_audio(self, audio_id: int, url: str, date_str: str) -> str:
        """Скачивает голосовое сообщение в локальную папку data/audio/{date_str}/{audio_id}.mp3."""
        if not url or not config.DOWNLOAD_AUDIO:
            return ""

        target_dir = config.AUDIO_DIR / date_str
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / f"{audio_id}.mp3"

        if dest.exists():
            return str(dest)

        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    f.write(resp.content)
                logger.info(f"🎙️ [Медиа] Голосовое сообщение сохранено локально: {dest}")
                return str(dest)
        except Exception as e:
            logger.warning(f"Ошибка скачивания аудио {url}: {e}")
        return ""

    def parse_attachments(self, attachments: list, date_str: str = "") -> List[Dict[str, Any]]:
        """Парсит и скачивает вложения VK сообщения (фото, голосовые, документы)."""
        parsed = []
        for a in (attachments or []):
            att_type = a.get("type")
            if att_type == "photo":
                photo_obj = a.get("photo", {})
                photo_id = photo_obj.get("id", int(time.time()))
                sizes = photo_obj.get("sizes", [])
                best_photo = sizes[-1]["url"] if sizes else ""
                preview = sizes[0]["url"] if sizes else best_photo
                
                local_photo_path = ""
                if best_photo and date_str:
                    local_photo_path = self._download_photo(photo_id, best_photo, date_str)

                parsed.append({
                    "type": "photo",
                    "id": photo_id,
                    "url": best_photo,
                    "preview_url": preview,
                    "local_path": local_photo_path
                })
            elif att_type == "doc":
                doc_obj = a.get("doc", {})
                parsed.append({
                    "type": "doc",
                    "title": doc_obj.get("title", "Документ"),
                    "url": doc_obj.get("url", ""),
                    "size_str": f"{doc_obj.get('size', 0) // 1024} КБ"
                })
            elif att_type == "audio_message":
                aud_obj = a.get("audio_message", {})
                audio_id = aud_obj.get("id", int(time.time()))
                duration = aud_obj.get("duration", 0)
                audio_url = aud_obj.get("link_mp3") or aud_obj.get("link_ogg", "")
                transcript = aud_obj.get("transcript", "")  # Авто-расшифровка текста от VK
                
                local_audio_path = ""
                if audio_url and date_str:
                    local_audio_path = self._download_audio(audio_id, audio_url, date_str)

                parsed.append({
                    "type": "audio_message",
                    "id": audio_id,
                    "duration": duration,
                    "url": audio_url,
                    "transcript": transcript,
                    "local_path": local_audio_path
                })
            elif att_type == "sticker":
                st_obj = a.get("sticker", {})
                images = st_obj.get("images", [])
                st_url = images[-1]["url"] if images else ""
                parsed.append({
                    "type": "sticker",
                    "url": st_url
                })
            else:
                parsed.append({"type": att_type or "unknown"})
        return parsed

    def handle_message(self, message_obj: dict):
        """Обрабатывает одно входящее сообщение из LongPoll."""
        msg_id = message_obj.get("conversation_message_id") or message_obj.get("id", 0)
        peer_id = message_obj.get("peer_id", 0)
        from_id = message_obj.get("from_id", 0)
        text = message_obj.get("text", "")
        timestamp = message_obj.get("date", int(time.time()))
        date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else datetime.now().strftime("%Y-%m-%d")

        # Фильтр по беседе если настроен TARGET_PEER_ID > 0
        if self.target_peer_id > 0 and peer_id != self.target_peer_id:
            return

        # Гарантируем наличие пользователя в базе и скачивание аватара
        self.ensure_user(from_id)

        # Обработка вложений со скачиванием фото
        attachments = self.parse_attachments(message_obj.get("attachments", []), date_str=date_str)

        # Обработка ответа на сообщение (reply_message)
        reply = None
        if "reply_message" in message_obj:
            rm = message_obj["reply_message"]
            reply_from_id = rm.get("from_id", 0)
            reply_user = self.ensure_user(reply_from_id)
            reply_author = f"{reply_user.get('first_name', '')} {reply_user.get('last_name', '')}".strip()
            reply = {
                "author_name": reply_author,
                "text": rm.get("text", "")[:150]
            }

        # Обработка пересланных сообщений (fwd_messages)
        fwd_list = []
        if "fwd_messages" in message_obj:
            for fm in message_obj["fwd_messages"]:
                f_uid = fm.get("from_id", 0)
                f_user = self.ensure_user(f_uid)
                fwd_list.append({
                    "from_name": f"{f_user.get('first_name', '')} {f_user.get('last_name', '')}".strip(),
                    "text": fm.get("text", "")[:100]
                })

        db.save_message(
            vk_msg_id=msg_id,
            peer_id=peer_id,
            from_id=from_id,
            text=text,
            attachments=attachments,
            reply=reply,
            fwd=fwd_list,
            timestamp=timestamp
        )

        logger.info(f"[Peer {peer_id}] Сообщение от {from_id} сохранено: {text[:40]}")

    def run_polling(self):
        """Запускает бесконечный цикл прослушивания сообщений через LongPoll."""
        if not self.vk_session or not self.longpoll:
            if not self.connect():
                logger.error("Невозможно запустить LongPoll: нет подключения.")
                return

        logger.info("VK Chrono запущен и слушает новые сообщения...")
        while True:
            try:
                for event in self.longpoll.listen():
                    if event.type == VkBotEventType.MESSAGE_NEW:
                        self.handle_message(event.obj.message)
            except Exception as e:
                logger.error(f"Ошибка в цикле LongPoll: {e}")
                time.sleep(5)

vk_client = VKBotClient()
