from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_kb() -> InlineKeyboardMarkup:
    """
    Главное меню:
    1) Обращение по гарантии
    2) Возврат товара
    3) Другой вопрос
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Обращение по гарантии", callback_data="warranty_start")],
        [InlineKeyboardButton(text="2️⃣ Возврат товара", callback_data="return_start")],
        [InlineKeyboardButton(text="3️⃣ Другой вопрос", callback_data="other_start")],
    ])

def return_kb() -> InlineKeyboardMarkup:
    """
    Кнопки после инфы про возврат.
    - Нет, вопрос по возврату → отправляем в 'Другой вопрос'
    - Да, перейти в раздел гарантии → запускаем сценарий гарантии
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👉 Нет, вопрос по возврату", callback_data="other_start")],
        [InlineKeyboardButton(text="Да, перейти в раздел гарантии", callback_data="warranty_start")],
    ])

def other_menu_kb() -> InlineKeyboardMarkup:
    """
    Кнопки в разделе 'Другой вопрос'
    - Отправить сотруднику
    - Вернуться в меню
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👉 Отправить сообщение сотруднику", callback_data="other_send")],
        [InlineKeyboardButton(text="Вернуться в меню", callback_data="to_start")],
    ])

def ok_kb() -> InlineKeyboardMarkup:
    """
    Кнопка 'В начало' — юзер вернется в главное меню
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В начало", callback_data="to_start")],
    ])
