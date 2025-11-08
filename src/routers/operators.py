from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import CallbackQuery

from sqlalchemy import select

from src.db.base import SessionLocal
from src.db.models import Ticket, TicketStatus, User, TicketMessage
from src.keyboards.operator import finish_kb, operator_controls_kb
from src.keyboards.main import ok_kb
from src.texts import OP_CONNECTED, OP_DISCONNECTED
from src.db.users import upsert_user_from_tg

router = Router()

def _fmt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


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

def _get_operator_nickname(s, operator_tg_id: int | None) -> str:
    """
    Находим имя оператора по tg_id из таблицы users.
    Приоритет: @username > first_name > tg_id.
    """
    if not operator_tg_id:
        return '👮 Оператор'
    
    op = s.scalar(select(User).where(User.tg_id == operator_tg_id))
    if op:
        if op.username:
            return f"👮 Оператор @{op.username}"
        if op.first_name:
            return f"👮 Оператор {op.first_name}"
    return f"👮 Оператор {operator_tg_id}"

def _label_for_sender(sender_type: str, content_type: str, operator_label: str | None = None) -> str:
    """
    Лейбл перед сообщением в истории:
    - Пользователь:
    - 👮Оператор @ник:
    """
    if sender_type == "user":
        who = "Пользователь"
    else:
        who = operator_label or 'Оператор'
    return f"{_ctype_emoji(content_type)} {who}:"



@router.callback_query(F.data.startswith('claim:'))
async def claim_ticket(c: CallbackQuery):
    ticket_id = int(c.data.split(':')[1])  # type: ignore
    operator_id = c.from_user.id

    with SessionLocal() as s:
        upsert_user_from_tg(s, c.from_user, mark_operator=True)
        s.commit()

        t = s.get(Ticket, ticket_id)
        if not t or t.status != TicketStatus.waiting:
            await c.answer('Уже занято или неактуально', show_alert=True)
            return

        t.status = TicketStatus.assigned
        t.operator_tg_id = operator_id
        s.commit()

        u = s.get(User, t.user_id)

        # все сообщения пользователя по тикету, по порядку
        user_msgs = s.scalars(
            select(TicketMessage)
            .where(
                TicketMessage.ticket_id == ticket_id,
                TicketMessage.sender_type == "user",
            )
            .order_by(TicketMessage.created_at.asc(), TicketMessage.id.asc())
        ).all()

    username = f"@{u.username}" if getattr(u, "username", None) else "—"
    first = u.first_name or "—"
    msg = (
        f"Вы взяли тикет #{ticket_id} (пользователь {first}, {username}).\n"
        f"Пишите ответы тут — бот всё перекинет пользователю."
    )

    # оператору служебка + кнопка завершения
    await c.bot.send_message(operator_id, msg, reply_markup=operator_controls_kb(ticket_id))  # type: ignore
    await c.answer('Тикет закреплен за вами')

    # сразу дублируем историю заявки в ЛС оператора
    if user_msgs:
        await c.bot.send_message(operator_id, f"Содержание заявки #{ticket_id}:")  # type: ignore
        for tm in user_msgs:
            try:
                # метка "кто и что"
                await c.bot.send_message(
                    operator_id,
                    _label_for_sender("user", tm.content_type, operator_id),  # type: ignore
                )
                await c.bot.copy_message(
                    chat_id=operator_id,
                    from_chat_id=u.tg_id,        # исходный чат пользователя с ботом
                    message_id=tm.tg_message_id, # его message_id
                )
            except Exception:
                pass


    # пользователю: оператор подключился
    await c.bot.send_message(u.tg_id, OP_CONNECTED)  # type: ignore


@router.callback_query(F.data.startswith('history:'))
async def show_user_history(c: CallbackQuery):
    ticket_id = int(c.data.split(':')[1])  # type: ignore
    operator_id = c.from_user.id

    # сразу отвечаем, чтобы callback не протух
    try:
        await c.answer('Загружаю историю...')
    except Exception:
        pass

    with SessionLocal() as s:
        curr = s.get(Ticket, ticket_id)
        if not curr:
            # тут уже лучше send_message, а не повторный answer
            await c.bot.send_message(operator_id, "Тикет не найден")  # type: ignore
            return

        if curr.operator_tg_id != operator_id:
            await c.bot.send_message(operator_id, "Это не ваш диалог")  # type: ignore
            return

        user = s.get(User, curr.user_id)
        if not user:
            await c.bot.send_message(operator_id, "Пользователь не найден")  # type: ignore
            return

        other_tickets = s.scalars(
            select(Ticket)
            .where(Ticket.user_id == curr.user_id, Ticket.id != curr.id)
            .order_by(Ticket.created_at.asc(), Ticket.id.asc())
        ).all()

    if not other_tickets:
        await c.bot.send_message(operator_id, "Других обращений не найдено")  # type: ignore
        return

    # один тикет → отдельный блок
    for t in other_tickets:
        with SessionLocal() as s:
            operator_label = _get_operator_nickname(s, t.operator_tg_id)

            header = (
                f"История: тикет #{t.id} | статус {t.status.value} | "
                f"{_fmt(t.created_at)} → {_fmt(t.closed_at) or '—'} | {operator_label}"
            )
            await c.bot.send_message(operator_id, header)  # type: ignore

            msgs = s.scalars(
                select(TicketMessage)
                .where(TicketMessage.ticket_id == t.id)
                .order_by(TicketMessage.created_at.asc(), TicketMessage.id.asc())
            ).all()

            last_sender: str | None = None # "user" / "operator"

            for tm in msgs:
                if tm.sender_type == "user":
                    from_chat = user.tg_id
                    label = _label_for_sender("user", tm.content_type)
                    sender_key = 'user'
                else:
                    if not t.operator_tg_id:
                        continue
                    from_chat = t.operator_tg_id
                    label = _label_for_sender(
                        "operator",
                        tm.content_type,
                        operator_label=operator_label,
                    )
                    sender_key = 'operator'

                try:
                    if sender_key != last_sender:
                        await c.bot.send_message(operator_id, label)
                        last_sender = sender_key

                    await c.bot.copy_message(
                        chat_id=operator_id,
                        from_chat_id=from_chat,
                        message_id=tm.tg_message_id,
                    )
                except Exception:
                    pass

            await c.bot.send_message(operator_id, f"— Конец истории по тикету #{t.id}")  # type: ignore

    await c.bot.send_message(
        operator_id,
        "ВЫШЕ ПРИВЕДЕНА ИСТОРИЯ ОБРАЩЕНИЙ ПОЛЬЗОВАТЕЛЯ",
        reply_markup=finish_kb(ticket_id)  # type: ignore
    )



@router.callback_query(F.data.startswith('finish:'))
async def finish_ticket(c: CallbackQuery):
    ticket_id = int(c.data.split(':')[1])  # type: ignore
    operator_id = c.from_user.id

    with SessionLocal() as s:
        upsert_user_from_tg(s, c.from_user, mark_operator=True)
        s.commit()

        t = s.get(Ticket, ticket_id)
        if not t or t.operator_tg_id != operator_id:
            await c.answer('Это не ваш диалог', show_alert=True)
            return
        t.status = TicketStatus.closed
        t.closed_at = datetime.now(timezone.utc)
        s.commit()
        user_tg = t.user.tg_id

    await c.bot.send_message(user_tg, OP_DISCONNECTED, reply_markup=ok_kb())  # type: ignore
    if c.message:
        await c.message.edit_text('Диалог закрыт.')
    await c.answer()


