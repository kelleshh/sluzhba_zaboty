from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def clain_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Взять в работу', callback_data=f'claim:{ticket_id}')]
    ])

def finish_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Завершить диалог', callback_data=f'finish:{ticket_id}')]
    ])
