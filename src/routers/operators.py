from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import CallbackQuery

from sqlalchemy import select

from src.db.base import SessionLocal
from src.db.models import Ticket, TicketStatus, User, TicketMessage
from src.keyboards.operator import finish_kb
from src.keyboards.main import ok_kb
from src.texts import OP_CONNECTED, OP_DISCONNECTED

router = Router()


@router.callback_query(F.data.startswith('claim:'))
async def claim_ticket(c: CallbackQuery):
    ticket_id = int(c.data.split(':')[1])  # type: ignore
    operator_id = c.from_user.id

    with SessionLocal() as s:
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
    await c.bot.send_message(operator_id, msg, reply_markup=finish_kb(ticket_id))  # type: ignore
    await c.answer('Тикет закреплен за вами')

    # сразу дублируем историю заявки в ЛС оператора
    if user_msgs:
        await c.bot.send_message(operator_id, f"История заявки #{ticket_id}:")  # type: ignore
        for tm in user_msgs:
            try:
                await c.bot.copy_message(
                    chat_id=operator_id,
                    from_chat_id=u.tg_id,        # исходный чат пользователя с ботом
                    message_id=tm.tg_message_id, # его message_id
                )
            except Exception:
                # если какое-то старое сообщение не скопировалось — не валимся
                pass

    # пользователю: оператор подключился
    await c.bot.send_message(u.tg_id, OP_CONNECTED)  # type: ignore




@router.callback_query(F.data.startswith('finish:'))
async def finish_ticket(c: CallbackQuery):
    ticket_id = int(c.data.split(':')[1])  # type: ignore
    operator_id = c.from_user.id

    with SessionLocal() as s:
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


