import os
import mimetypes
from aiogram import Bot
from src.config import settings

def _guess_ext(mime: str | None, fallback: str = ".bin") -> str:
    if mime:
        ext = mimetypes.guess_extension(mime)
        if ext:
            return ext
    return fallback

async def download_by_file_id(bot: Bot, file_id: str, rel_path: str) -> str:
    """
    Скачивает файл из TG по file_id в media_root/rel_path, создает директории.
    Возвращает абсолютный путь.
    """
    base = settings.media_root  # см. п.2
    abs_path = os.path.join(base, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    tg_file = await bot.get_file(file_id)
    await bot.download(tg_file, destination=abs_path)
    return abs_path

def build_rel_path(ticket_id: int, msg_id: int, media_type: str,
                   unique_id: str | None, mime: str | None) -> str:
    ext = _guess_ext(mime, ".bin")
    stem = unique_id or "file"
    return f"{ticket_id}/{msg_id}/{media_type}_{stem}{ext}"
