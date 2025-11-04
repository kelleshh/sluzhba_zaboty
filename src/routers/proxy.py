from aiogram import Router, types, F
from src.db.base import SessionLocal
from src.db.models import Ticket, TicketStatus, TicketMessage, User, MessageAttachment
from src.utils.files import download_by_file_id, build_rel_path
from sqlalchemy import select
from src.config import settings

router = Router()

def _ctype_emoji(ct: str) -> str:
    return {
        "text": "📝",
        "photo": "🖼",
        "document": "📎",
        "video": "📹",
        "voice": "🎙",
        "audio": "🎵",
        "animation": "🪄",
        "video_note": "📮",
    }.get(ct, "🗂")

def _label_for_sender(sender_type: str, content_type: str, operator_id: int | None) -> str:
    if sender_type == "user":
        who = "Пользователь"
    else:
        who = f"Оператор {operator_id or '—'}"
    return f"{_ctype_emoji(content_type)} {who}"


async def _attach_photo(bot, s, ticket_id: int, tm_id: int, m: types.Message):
    ph = m.photo[-1]
    att = MessageAttachment(
        ticket_message_id=tm_id,
        ticket_id=ticket_id,
        media_type="photo",
        file_id=ph.file_id,
        file_unique_id=ph.file_unique_id,
        size=getattr(ph, "file_size", None),
        width=ph.width,
        height=ph.height,
    )
    if settings.store_media_local:
        rel = build_rel_path(ticket_id, tm_id, "photo", ph.file_unique_id, None)
        att.local_path = await download_by_file_id(bot, ph.file_id, rel)
    s.add(att)

async def _attach_document(bot, s, ticket_id: int, tm_id: int, m: types.Message):
    d = m.document
    att = MessageAttachment(
        ticket_message_id=tm_id,
        ticket_id=ticket_id,
        media_type="document",
        file_id=d.file_id,
        file_unique_id=d.file_unique_id,
        size=getattr(d, "file_size", None),
        mime_type=getattr(d, "mime_type", None),
        file_name=getattr(d, "file_name", None),
    )
    if settings.store_media_local:
        rel = build_rel_path(ticket_id, tm_id, "document", d.file_unique_id, getattr(d, "mime_type", None))
        att.local_path = await download_by_file_id(bot, d.file_id, rel)
    s.add(att)

async def _attach_video(bot, s, ticket_id: int, tm_id: int, m: types.Message):
    v = m.video
    att = MessageAttachment(
        ticket_message_id=tm_id,
        ticket_id=ticket_id,
        media_type="video",
        file_id=v.file_id,
        file_unique_id=v.file_unique_id,
        size=getattr(v, "file_size", None),
        width=getattr(v, "width", None),
        height=getattr(v, "height", None),
        duration=getattr(v, "duration", None),
        mime_type=getattr(v, "mime_type", None),
    )
    if settings.store_media_local:
        rel = build_rel_path(ticket_id, tm_id, "video", v.file_unique_id, getattr(v, "mime_type", None))
        att.local_path = await download_by_file_id(bot, v.file_id, rel)
    s.add(att)

async def _attach_voice(bot, s, ticket_id: int, tm_id: int, m: types.Message):
    v = m.voice
    att = MessageAttachment(
        ticket_message_id=tm_id,
        ticket_id=ticket_id,
        media_type="voice",
        file_id=v.file_id,
        file_unique_id=v.file_unique_id,
        size=getattr(v, "file_size", None),
        duration=getattr(v, "duration", None),
        mime_type=getattr(v, "mime_type", None),
    )
    if settings.store_media_local:
        rel = build_rel_path(ticket_id, tm_id, "voice", v.file_unique_id, getattr(v, "mime_type", None))
        att.local_path = await download_by_file_id(bot, v.file_id, rel)
    s.add(att)

async def _log_message(bot, s, ticket_id: int, m: types.Message, sender_type: str):
    content_type = m.content_type
    tm = TicketMessage(
        ticket_id=ticket_id,
        sender_tg_id=m.from_user.id,      # type: ignore
        sender_type=sender_type,
        tg_message_id=m.message_id,
        content_type=content_type,
        message_text=m.text if content_type == "text" else None,
        caption=getattr(m, "caption", None),
    )
    s.add(tm)
    s.flush()  # получим tm.id

    try:
        if content_type == "photo" and m.photo:
            await _attach_photo(bot, s, ticket_id, tm.id, m)
        elif content_type == "document" and m.document:
            await _attach_document(bot, s, ticket_id, tm.id, m)
        elif content_type == "video" and m.video:
            await _attach_video(bot, s, ticket_id, tm.id, m)
        elif content_type == "voice" and m.voice:
            await _attach_voice(bot, s, ticket_id, tm.id, m)
        # при необходимости добавь audio / animation / video_note / sticker
    except Exception:
        # не роняем поток, если скачивание сломалось
        pass

    s.commit()

@router.message(F.chat.type == "private")
async def proxy_private(m: types.Message):
    # игнорим ботов на входе
    if m.from_user.is_bot:  # type: ignore
        return

    with SessionLocal() as s:
        #
        # 1) Оператор → Пользователь
        #
        t = s.scalar(
            select(Ticket).where(
                Ticket.operator_tg_id == m.from_user.id,    # type: ignore
                Ticket.status == TicketStatus.assigned,
            )
        )
        if t:
            # дублим пользователю
            await m.bot.copy_message(
                chat_id=t.user.tg_id,
                from_chat_id=m.chat.id,
                message_id=m.message_id
            )  # type: ignore

            # логируем как operator
            await _log_message(m.bot, s, t.id, m, sender_type="operator")  # type: ignore
            return

        #
        # 2) Пользователь → Оператор
        #
        user = s.scalar(select(User).where(User.tg_id == m.from_user.id))  # type: ignore
        if not user:
            return

        t = s.scalar(
            select(Ticket).where(
                Ticket.user_id == user.id,
                Ticket.status == TicketStatus.assigned,
            )
        )
        if not t:
            return

        # дублим оператору
        await m.bot.send_message(
            chat_id=t.operator_tg_id,
            text=_label_for_sender("user", m.content_type, t.operator_tg_id),  # метка
        )  # type: ignore
        await m.bot.copy_message(
            chat_id=t.operator_tg_id,
            from_chat_id=m.chat.id,
            message_id=m.message_id
        )  # type: ignore

        # логируем как user
        await _log_message(m.bot, s, t.id, m, sender_type="user")  # type: ignore
