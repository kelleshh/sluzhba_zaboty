from aiogram import Router, F, types
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from typing import cast

from src import texts
from src.keyboards.main  import start_kb, topic_kb, ok_kb, yesno_kb

router = Router()

# ожидание телефона 
class PhoneForm(StatesGroup):
    waiting_phone = State()

@router.message(commands={'start'})
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
    #phone = normalize_phone(m.text or '')
    #TODO: сделать нормализацию номера телефона в утилитах
    pass