from aiogram import Router, F, types
from aiogram.types import CallbackQuery

router = Router()

@router.callback_query(F.data.startswith('claim:'))
async def claim_ticket(c: CallbackQuery):
    ticket_id = int(c.data.split(':')[1])
    operator_id = c.from_user.id

    #with SessionLocal

    # TODO: допилить датабазу сначала
    pass