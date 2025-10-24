from aiogram import Router, F, types
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.filters import CommandStart
from typing import cast

from src import texts
from src.keyboards.main import start_kb, topic_kb, ok_kb, yesno_kb
from src.keyboards.operator import claim_kb
from src.utils.phone import normalize_phone
from src.db.base import SessionLocal
from src.db.models import User, Ticket, TicketStatus
from src.config import settings

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

router = Router()

# ожидание телефона 
class PhoneForm(StatesGroup):
    waiting_phone = State()

@router.message(CommandStart)
async def start(m: types.Message):
    await m.answer(texts.WELCOME, reply_markup=start_kb())

@router.callback_query(F.data == 'to_start')
async def to_start(c: CallbackQuery):
    message = cast(Message, c.message)
    await message.edit_text(texts.WELCOME, reply_markup=start_kb())
    await c.answer()

@router.callback_query(F.data == 'topic_warranty')
async def warranty(c: CallbackQuery):
    message = cast(Message, c.message)
    await message.edit_text(texts.WARRANTY, reply_markup=topic_kb())
    await c.answer()


@router.callback_query(F.data == 'topic_refund')
async def refund(c: CallbackQuery):
    message = cast(Message, c.message)
    await message.edit_text(texts.REFUND, reply_markup=topic_kb())
    await c.answer()

@router.callback_query(F.data == 'ok')
async def ok_thanks(c: CallbackQuery):
    message = cast(Message, c.message)
    await message.edit_text(texts.THANKS, reply_markup=ok_kb())
    await c.answer()

@router.callback_query(F.data == 'topic_other')
async def other(c: CallbackQuery):
    message = cast(Message, c.message)
    await message.edit_text(texts.ASK_OPERATOR, reply_markup=yesno_kb())
    await c.answer()

@router.callback_query(F.data == 'to_operator')
async def ask_phone(c: CallbackQuery, state: FSMContext):
    message = cast(Message, c.message)
    await message.edit_text(texts.ASK_PHONE)
    await state.set_state(PhoneForm.waiting_phone)
    await c.answer()

@router.message(PhoneForm.waiting_phone)
async def receive_phone(m: types.Message, state: FSMContext):
    phone = normalize_phone(m.text or '')
    if not phone:
        await m.answer(texts.BAD_PHONE)
        return
    
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.tg_id == m.from_user.id)) #type: ignore
        if not user:
            user = User(tg_id=m.from_user.id, #type: ignore
                        first_name = m.from_user.first_name, #type: ignore
                        username = m.from_user.username, #type: ignore
                        phone = phone) #type: ignore
            s.add(user)
        else:
            user.phone = phone
        s.flush()

        ticket = Ticket(user_id = user.id, status = TicketStatus.waiting)
        s.add(ticket)
        s.commit()
        ticket_id = ticket.id

    await state.clear()
    await m.answer(texts.CONNECTING)

    #увед в операторский чат
    kb = claim_kb(ticket_id)
    username = f"@{m.from_user.username}" if m.from_user.username else "—" #type: ignore
    full = (
        f"Новый клиент #{ticket_id}\n"
        f"Имя: {m.from_user.first_name or '—'}\n" # type: ignore
        f"Username: {username}\n"
        f"TG ID: {m.from_user.id}\n" #type: ignore
        f"Телефон: {phone}"
    )

    await m.bot.send_message(chat_id=settings.operators_chat_id, text=full, reply_markup = kb) # type: ignore