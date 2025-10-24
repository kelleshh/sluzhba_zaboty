from aiogram import Router, F, types
from aiogram.types import CallbackQuery
from src.db.base import SessionLocal
from src.db.models import Ticket, TicketStatus, User
from src.keyboards.operator import finish_kb
from src.texts import OP_CONNECTED, OP_DISCONNECTED
from datetime import datetime

router = Router()

@router.callback_query(F.data.startswith('claim:'))
async def claim_ticket(c: CallbackQuery):
    ticket_id = int(c.data.split(':')[1])#type: ignore
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
    
    # сообщение оператору
    msg = f'Вы взяли тикет #{ticket_id} (пользователь {u.first_name}, айди @{u.username}. \n Ведите переписку тут - бот все перекинет пользователю.)' # type: ignore
    await c.bot.send_message(operator_id, msg, reply_markup=finish_kb(ticket_id)) # type: ignore
    await c.answer('Тикет закреплен за вами')
    await c.bot.send_message(u.tg_id, OP_CONNECTED) #type: ignore


    @router.callback_query(F.data.startswith('finish:'))
    async def finis_ticket(c: CallbackQuery):
        ticket_id = int(c.data.split(':')[1])#type: ignore
        operator_id = c.from_user.id

        with SessionLocal() as s:
            t = s.get(Ticket, ticket_id)
            if not t or t.operator_tg_id != operator_id:
                await c.answer('Это не ваш диалог', show_alert=True)
                return
            t.status = TicketStatus.closed
            t.closed_at = datetime.now()
            s.commit()
            user_tg = t.user.tg_id

        await c.bot.send_message(user_tg, OP_DISCONNECTED) #type: ignore
        await c.message.edit_text('Диалог закрыт.') # type:ignore
        await c.answer()

