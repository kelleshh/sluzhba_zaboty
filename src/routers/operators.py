from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import CallbackQuery

from sqlalchemy import select

from src.db.base import SessionLocal
from src.db.models import Ticket, TicketStatus, User, TicketMessage
from src.keyboards.operator import finish_kb, operator_controls_kb
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
    await c.bot.send_message(operator_id, msg, reply_markup=operator_controls_kb(ticket_id))  # type: ignore
    await c.answer('Тикет закреплен за вами')

    # сразу дублируем историю заявки в ЛС оператора
    if user_msgs:
        await c.bot.send_message(operator_id, f"Содержание заявки #{ticket_id}:")  # type: ignore
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


@router.callback_query(F.data.startswith('history:'))
async def show_user_history(c: CallbackQuery):
    ticket_id = int(c.data.split(':')[1])  # type: ignore
    operator_id = c.from_user.id

    with SessionLocal() as s:
        curr = s.get(Ticket, ticket_id)
        if not curr:
            await c.answer('Тикет не найден', show_alert=True)
            return
        # защита: историю показывает только тот, кто реально держит диалог
        if curr.operator_tg_id != operator_id:
            await c.answer('Это не ваш диалог', show_alert=True)
            return

        user = s.get(User, curr.user_id)
        if not user:
            await c.answer('Пользователь не найден', show_alert=True)
            return

        # все другие тикеты этого пользователя, КРОМЕ текущего
        other_tickets = s.scalars(
            select(Ticket)
            .where(Ticket.user_id == curr.user_id, Ticket.id != curr.id)
            .order_by(Ticket.created_at.asc(), Ticket.id.asc())
        ).all()

    if not other_tickets:
        await c.answer('Других обращений не найдено', show_alert=True)
        return

    # прогоняем по каждому тикету: один тикет → отдельный блок сообщений
    for t in other_tickets:
        # шапка тикета
        header = (
            f"История: тикет #{t.id} | статус {t.status.value} | "
            f"{t.created_at} → {t.closed_at or '—'} | оператор: {t.operator_tg_id or '—'}"
        )
        await c.bot.send_message(operator_id, header)  # type: ignore

        # сообщения тикета в хронологическом порядке
        with SessionLocal() as s:
            msgs = s.scalars(
                select(TicketMessage)
                .where(TicketMessage.ticket_id == t.id)
                .order_by(TicketMessage.created_at.asc(), TicketMessage.id.asc())
            ).all()

        # копируем ИМЕННО ИЗ исходных чатов, чтобы подтянулись и медиа
        for tm in msgs:
            if tm.sender_type == "user":
                from_chat = user.tg_id
            else:
                from_chat = t.operator_tg_id  # оператор того тикета
                if not from_chat:
                    continue
            try:
                await c.bot.copy_message(
                    chat_id=operator_id,
                    from_chat_id=from_chat,
                    message_id=tm.tg_message_id
                )  # type: ignore
            except Exception:
                # старые сообщения могли быть удалены/подчищены — не валимся
                pass

        # низ тикета, чисто визуальный разделитель
        await c.bot.send_message(operator_id, f"— Конец истории по тикету #{t.id}")  # type: ignore

    # финальный футер + кнопка "Завершить диалог" (для ТЕКУЩЕГО тикета)
    await c.bot.send_message(
        operator_id,
        "ВЫШЕ ПРИВЕДЕНА ИСТОРИЯ ОБРАЩЕНИЙ ПОЛЬЗОВАТЕЛЯ",
        reply_markup=finish_kb(ticket_id)  # type: ignore
    )
    await c.answer("История загружена")


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


