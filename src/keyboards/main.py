from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Гарантия", callback_data="topic_warranty")],
        [InlineKeyboardButton(text="Возврат", callback_data="topic_refund")],
        [InlineKeyboardButton(text="Другой вопрос", callback_data="topic_other")],
    ])

def topic_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Понятно", callback_data="ok")],
        [InlineKeyboardButton(text="Обратиться к оператору", callback_data="to_operator")],
    ])

def ok_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В начало", callback_data="to_start")],
    ])

def yesno_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="to_operator")],
        [InlineKeyboardButton(text="Нет", callback_data="ok")],
    ])
