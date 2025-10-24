from aiogram import Router, types, F
from src.db.base import SessionLocal
from src.db.models import Ticket, TicketStatus, TicketMessage, User
from sqlalchemy import select

router = Router()

# Пользователь -> Оператор (когда тикет ASSIGNED)
@router.message(F.chat.type == "private")
async def user_to_operator(m: types.Message):
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.tg_id == m.from_user.id)) #type: ignore
        if not user:
            return
        t = s.scalar(select(Ticket).where(Ticket.user_id==user.id, Ticket.status==TicketStatus.assigned))
        if not t:
            return
        # пересылаем оператору
        sent = await m.bot.copy_message(chat_id=t.operator_tg_id, from_chat_id=m.chat.id, message_id=m.message_id) #type: ignore
        s.add(TicketMessage(ticket_id=t.id, sender_tg_id=m.from_user.id, sender_type="user",#type: ignore
                            tg_message_id=m.message_id, content_type=m.content_type))
        s.commit()

# Оператор -> Пользователь (только если он владелец тикета)
@router.message(F.chat.type == "private", F.from_user.is_bot == False)
async def operator_to_user(m: types.Message):
    # попытка найти активный тикет, где оператор==from_user
    with SessionLocal() as s:
        t = s.scalar(select(Ticket).where(Ticket.operator_tg_id==m.from_user.id, Ticket.status==TicketStatus.assigned))#type: ignore
        if not t:
            return
        user_tg = t.user.tg_id
        sent = await m.bot.copy_message(chat_id=user_tg, from_chat_id=m.chat.id, message_id=m.message_id)#type: ignore
        s.add(TicketMessage(ticket_id=t.id, sender_tg_id=m.from_user.id, sender_type="operator",#type: ignore
                            tg_message_id=m.message_id, content_type=m.content_type))
        s.commit()
