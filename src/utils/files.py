import mimetypes
from pathlib import Path
from aiogram import Bot, types
from src.config import settings


def _guess_ext(mime: str | None, fallback: str = ".bin") -> str:
    """
    Пытаемся угадать расширение файла по mime.
    Если не знаем, кладем .bin
    """
    if mime:
        ext = mimetypes.guess_extension(mime)
        if ext:
            return ext
    return fallback


def _collect_attachments(m: types.Message) -> list[dict]:
    """
    Собираем вообще все возможные вложения из сообщения.
    Возвращаем список словарей:
    {
      "media_type": "photo"/"video"/"document"/...,
      "file_id": "...",
      "unique_id": "...",
      "mime": "image/jpeg" или None,
    }
    """

    out: list[dict] = []

    # фото (телега дает массив вариантов размера, берем последнее = самое большое)
    if m.photo:
        p = m.photo[-1]
        out.append({
            "media_type": "photo",
            "file_id": p.file_id,
            "unique_id": getattr(p, "file_unique_id", p.file_id),
            "mime": "image/jpeg",  # телега не всегда дает mime у photo
        })

    # документ
    if m.document:
        d = m.document
        out.append({
            "media_type": "document",
            "file_id": d.file_id,
            "unique_id": d.file_unique_id,
            "mime": getattr(d, "mime_type", None),
        })

    # видео
    if m.video:
        v = m.video
        out.append({
            "media_type": "video",
            "file_id": v.file_id,
            "unique_id": v.file_unique_id,
            "mime": getattr(v, "mime_type", None),
        })

    # voice
    if m.voice:
        v = m.voice
        out.append({
            "media_type": "voice",
            "file_id": v.file_id,
            "unique_id": v.file_unique_id,
            "mime": getattr(v, "mime_type", None),
        })

    # audio
    if m.audio:
        a = m.audio
        out.append({
            "media_type": "audio",
            "file_id": a.file_id,
            "unique_id": a.file_unique_id,
            "mime": getattr(a, "mime_type", None),
        })

    # gif-анимация
    if m.animation:
        a = m.animation
        out.append({
            "media_type": "animation",
            "file_id": a.file_id,
            "unique_id": a.file_unique_id,
            "mime": getattr(a, "mime_type", None),
        })

    # кружочек (video_note)
    if m.video_note:
        v = m.video_note
        out.append({
            "media_type": "video_note",
            "file_id": v.file_id,
            "unique_id": v.file_unique_id,
            "mime": None,
        })

    return out

# ОНА ПОКА НЕ НУЖНА, НО ПУСТЬ ЛЕЖИТ
async def save_all_attachments_from_message(bot: Bot, m: types.Message, ticket_id: int) -> list[str]:
    """
    "Новая" логика, которой пользуется public.py.

    Сохраняем все вложения из одного сообщения пользователя в папку:
    media_root / ticket_<ticket_id> / <telegram_message_id> / <media_type>_<unique>.ext

    Возвращаем список абсолютных путей до сохраненных файлов.
    """
    base_dir = Path(settings.media_root) / f"ticket_{ticket_id}" / str(m.message_id)
    base_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[str] = []

    for att in _collect_attachments(m):
        media_type = att["media_type"]
        file_id = att["file_id"]
        unique_id = att["unique_id"]
        mime = att["mime"]

        ext = _guess_ext(mime)
        filename = f"{media_type}_{unique_id}{ext}"

        abs_path = base_dir / filename

        tg_file = await bot.get_file(file_id)
        await bot.download(tg_file, destination=abs_path)

        saved_paths.append(str(abs_path))

    return saved_paths


# ===== Ниже два хелпера для логики живого чата proxy.py =====
# Они нужны, чтобы живой чат тоже продолжал складывать файлы.

async def download_by_file_id(bot: Bot, file_id: str, rel_path: str) -> str:
    """
    "Старый" интерфейс, которым пользуется proxy.py.
    Скачивает один файл по file_id в media_root/rel_path.
    Возвращает абсолютный путь как строку.
    """
    base_dir = Path(settings.media_root)
    abs_path = base_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    tg_file = await bot.get_file(file_id)
    await bot.download(tg_file, destination=abs_path)

    return str(abs_path)


def build_rel_path(
    ticket_id: int,
    tm_id: int,
    media_type: str,
    unique_id: str | None,
    mime: str | None,
) -> str:
    """
    "Старый" интерфейс для proxy.py:
    строит относительный путь для вложения, привязанного к ticket_message_id.

    Пример результата:
    ticket_5/42/photo_ABCDEF12345.jpg

    Где:
    - ticket_5      тикет
    - 42            id строки TicketMessage
    - photo_...     тип вложения + уникальный id файла
    """
    ext = _guess_ext(mime)
    stem = unique_id or "file"
    return f"ticket_{ticket_id}/{tm_id}/{media_type}_{stem}{ext}"
