from typing import cast

from aiogram import Router, F, types
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import CommandStart

from sqlalchemy import select

from src import texts
from src.keyboards.main import (
    main_menu_kb,
    return_kb,
    other_menu_kb,
    ok_kb,
    other_media_done_kb,
    warranty_media_done_kb,
)
from src.keyboards.operator import claim_kb
from src.db.base import SessionLocal
from src.db.models import User, Ticket, TicketStatus, TicketMessage
from src.config import settings
from src.utils.files import save_all_attachments_from_message

router = Router()


# -------------------------
# FSM СЦЕНАРИИ
# -------------------------

class WarrantyForm(StatesGroup):
    waiting_details = State()   # ждем текст с описанием проблемы и где купили
    waiting_media = State()     # ждем фото/видео/чек

class OtherForm(StatesGroup):
    waiting_question_text = State()  # ждем текст вопроса
    waiting_question_media = State() # ждем доп. вложения


# -------------------------
# УТИЛИТЫ
# -------------------------

def _upsert_user_and_create_ticket(m: types.Message) -> tuple[int, User]:
    """
    Создает (или обновляет) пользователя, создает тикет WAITING.
    Возвращает (ticket_id, user_obj).
    """
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.tg_id == m.from_user.id))  # type: ignore
        if not user:
            user = User(
                tg_id=m.from_user.id,              # type: ignore
                first_name=m.from_user.first_name, # type: ignore
                username=m.from_user.username,     # type: ignore
                phone=None,
            )
            s.add(user)
            s.flush()
        else:
            pass

        ticket = Ticket(
            user_id=user.id,
            status=TicketStatus.waiting,
            operator_tg_id=None,
        )
        s.add(ticket)
        s.commit()
        ticket_id = ticket.id

    return ticket_id, user


def _save_ticket_message(
    s,
    ticket_id: int,
    m: types.Message,
    sender_type: str,
):
    """
    Сохраняет одно сообщение пользователя/оператора в ticket_messages.
    Мы пишем content_type, текст и caption.
    """
    tm = TicketMessage(
        ticket_id=ticket_id,
        sender_tg_id=m.from_user.id,  # type: ignore
        sender_type=sender_type,
        tg_message_id=m.message_id,
        content_type=m.content_type,
        message_text=getattr(m, "text", None),
        caption=getattr(m, "caption", None),
    )
    s.add(tm)
    s.flush()
    # attachments / files мы можем обрабатывать отдельно,
    # но для базового MVP не обязательно


async def _notify_operators_about_ticket(
    m: types.Message,
    ticket_id: int,
    user: User,
    intro_text: str,
    extra_message_ids: list[int],
):
    """
    Отправляем в операторский чат сводку-заявку + кнопка "Взять в работу",
    потом пересылаем сами сообщения клиента (описание, вложения и т.д.).
    """
    username = f"@{user.username}" if user.username else "—"
    summary = (
        f"{intro_text} #{ticket_id}\n"
        f"Пользователь: {user.first_name or '—'} {username}\n"
        f"TG ID: {user.tg_id}\n"
        f"Статус: WAITING\n\n"
        f"Ниже — детали обращения."
    )

    # шлем карточку с кнопкой "Взять в работу"
    await m.bot.send_message(
        chat_id=settings.operators_chat_id,
        text=summary,
        reply_markup=claim_kb(ticket_id),
    )

    # пересылаем сообщения юзера (описание/документы/медиа)
    for mid in extra_message_ids:
        await m.bot.copy_message(
            chat_id=settings.operators_chat_id,
            from_chat_id=m.chat.id,
            message_id=mid,
        )


def _message_has_media(m: types.Message) -> bool:
    """
    Проверяем, что пользователь реально отправил медиа:
    фото / документ / видео / войс / аудио / анимация / видео-ноту.
    """
    return any([
        getattr(m, "photo", None),
        getattr(m, "document", None),
        getattr(m, "video", None),
        getattr(m, "voice", None),
        getattr(m, "audio", None),
        getattr(m, "animation", None),
        getattr(m, "video_note", None),
    ])


# -------------------------
# /start + главное меню
# -------------------------

@router.message(CommandStart())
async def cmd_start(m: types.Message, state: FSMContext):
    # чистим любые зависшие состояния
    await state.clear()
    await m.answer(texts.WELCOME, reply_markup=main_menu_kb())


@router.callback_query(F.data == "to_start")
async def to_start(c: CallbackQuery, state: FSMContext):
    # возврат в главное меню
    await state.clear()
    message = cast(Message, c.message)
    await message.edit_text(texts.WELCOME, reply_markup=main_menu_kb())
    await c.answer()


# -------------------------
# 1. ОБРАЩЕНИЕ ПО ГАРАНТИИ
# -------------------------

@router.callback_query(F.data == "warranty_start")
async def warranty_start(c: CallbackQuery, state: FSMContext):
    """
    Пользователь выбрал 'Обращение по гарантии'.
    Даём инструкцию: опиши проблему и где куплено.
    Вешаем состояние waiting_details.
    Кладём кнопку 'В начало'.
    """
    await state.clear()
    await state.set_state(WarrantyForm.waiting_details)

    message = cast(Message, c.message)
    await message.edit_text(
        texts.WARRANTY_INTRO,
        reply_markup=ok_kb()  # 'В начало'
    )
    await c.answer()


@router.message(WarrantyForm.waiting_details)
async def warranty_details_step(m: types.Message, state: FSMContext):
    """
    Это ПЕРВОЕ сообщение по гарантии.
    Здесь мы:
    - создаём тикет (если его ещё нет)
    - сохраняем это сообщение в базу
    - сохраняем вложения этого сообщения (если юзер уже скинул фотки сразу)
    - переключаемся в waiting_media
    - говорим пользователю 'теперь докинь фото/видео/чек и нажми кнопку'
    """

    data = await state.get_data()
    if data.get("ticket_id") is not None:
        # Если по гонке пришло ещё одно сообщение сюда до переключения стейта,
        # то просто обрабатываем его как media-дополнение.
        return await warranty_collect_media(m, state)

    # 1. создаём тикет WAITING
    ticket_id, user = _upsert_user_and_create_ticket(m)

    # 2. сохранить вложения из этого сообщения на диск (фото, доки и т.д.)
    await save_all_attachments_from_message(
        bot=m.bot,
        m=m,
        ticket_id=ticket_id,
    )

    # 3. залогировать это сообщение в ticket_messages
    with SessionLocal() as s:
        _save_ticket_message(s, ticket_id, m, sender_type="user")
        s.commit()

    # 4. сохранить в FSM:
    #    - ticket_id для этого обращения
    #    - собранные message_id (начинаем список с этого первого сообщения)
    await state.update_data(
        ticket_id=ticket_id,
        user_tg_id=m.from_user.id,       # type: ignore
        collected_msg_ids=[m.message_id],
    )

    # 5. перейти в стадию ожидания медиа
    await state.set_state(WarrantyForm.waiting_media)

    # 6. попросить загрузить медиа и дать кнопку "Отправить оператору ✅"
    await m.answer(
        texts.WARRANTY_MEDIA_STEP,
        reply_markup=warranty_media_done_kb()
    )



@router.message(WarrantyForm.waiting_media)
async def warranty_collect_media(m: types.Message, state: FSMContext):
    """
    Мы уже создали тикет, теперь просто копим вложения и сообщения
    до тех пор, пока пользователь не нажмёт 'Отправить оператору ✅'.
    Никаких 'спасибо', никаких уведомлений оператору тут.
    """
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    if ticket_id is None:
        # стейт куда-то потерялся, не плодим новые тикеты
        return

    # 1. сохраняем вложения этого сообщения на диск
    await save_all_attachments_from_message(
        bot=m.bot,
        m=m,
        ticket_id=ticket_id,
    )

    # 2. логируем сообщение целиком в ticket_messages
    with SessionLocal() as s:
        _save_ticket_message(s, ticket_id, m, sender_type="user")
        s.commit()

    # 3. обновляем список message_id, чтобы потом оператору отправить ВСЁ
    collected = data.get("collected_msg_ids", [])
    collected.append(m.message_id)
    await state.update_data(collected_msg_ids=collected)

    # 4. НИЧЕГО не отвечаем. Пусть пользователь докидывает дальше.
    # (у него уже есть сообщение с инструкцией и кнопка warranty_media_done_kb())


@router.callback_query(F.data == "warranty_done")
async def warranty_done(c: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал 'Отправить оператору ✅' в гарантии.
    Тут мы:
    - отправляем одно уведомление операторам со всеми сообщениями
    - благодарим пользователя
    - даём кнопку 'В начало'
    - чистим стейт
    """
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    collected_ids = data.get("collected_msg_ids", [])
    user_tg_id = data.get("user_tg_id")

    if ticket_id is None or user_tg_id is None:
        await c.answer("Ошибка состояния. Попробуйте заново.", show_alert=True)
        await state.clear()
        return

    # достаём юзера из БД, чтобы красиво подписать карточку
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.tg_id == user_tg_id))  # type: ignore

    if user:
        await _notify_operators_about_ticket(
            m=c.message,
            ticket_id=ticket_id,
            user=user,
            intro_text="Новое обращение по гарантии",
            extra_message_ids=collected_ids,
        )

    # говорим пользователю финальный текст и даём кнопку "В начало"
    await c.message.answer(texts.WARRANTY_THANKS, reply_markup=ok_kb())

    # убираем состояние
    await state.clear()

    await c.answer("Отправлено оператору")


# -------------------------
# 2. ВОЗВРАТ ТОВАРА
# -------------------------

@router.callback_query(F.data == "return_start")
async def return_start(c: CallbackQuery, state: FSMContext):
    """
    Показываем инфу про возврат (2 сообщения),
    потом задаем вопрос "Хотите перейти в гарантию?"
    с клавиатурой return_kb().
    """
    await state.clear()

    # редактируем исходное сообщение, потом досылаем второе и третье
    message = cast(Message, c.message)
    await message.edit_text(texts.RETURN_NOTICE_1)

    # второе сообщение
    await c.message.answer(texts.RETURN_NOTICE_2)

    # третье сообщение с клавиатурой
    await c.message.answer(texts.RETURN_ASK, reply_markup=return_kb())

    await c.answer()


# -------------------------
# 3. ДРУГОЙ ВОПРОС
# -------------------------

@router.callback_query(F.data == "other_start")
async def other_start(c: CallbackQuery, state: FSMContext):
    """
    Раздел 'Другой вопрос'.
    Показываем описание, сценарии, потом клавиатуру
    с кнопкой 'Отправить сообщение сотруднику' / 'В начало'.
    """
    await state.clear()

    message = cast(Message, c.message)

    # редактируем исходное сообщение на первый текст
    await message.edit_text(texts.OTHER_INTRO_1)

    # шлём второй текст
    await c.message.answer(texts.OTHER_INTRO_2)

    # шлём клавиатуру с кнопками
    await c.message.answer(texts.OTHER_ASK_SEND, reply_markup=other_menu_kb())

    await c.answer()


@router.callback_query(F.data == "other_send")
async def other_send(c: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал 'Отправить сообщение сотруднику'.
    Шаг 1: просим описать вопрос словами.
    Ждём первое содержательное сообщение в состоянии waiting_question_text.
    """
    await state.set_state(OtherForm.waiting_question_text)

    await c.message.answer(texts.OTHER_PLEASE_DESCRIBE)
    await c.answer()


@router.message(OtherForm.waiting_question_text)
async def other_question_text(m: types.Message, state: FSMContext):
    """
    Это первое сообщение пользователя в 'Другой вопрос'.
    Здесь:
    - создаём тикет (если ещё нет)
    - сохраняем это сообщение
    - сохраняем вложения с этого сообщения
    - переходим в режим сбора доп. медиа (waiting_question_media)
    - показываем инструкцию + кнопку 'Отправить оператору ✅'
    """

    data = await state.get_data()
    if data.get("ticket_id") is not None:
        # гонка: если прилетело сразу несколько сообщений (альбомом)
        # до переключения состояния, то не создаём новый тикет,
        # а просто трактуем это сообщение как "доп. медиа"
        return await other_collect_media(m, state)

    # создаём тикет
    ticket_id, user = _upsert_user_and_create_ticket(m)

    # сохраняем вложения с этого сообщения на диск
    await save_all_attachments_from_message(
        bot=m.bot,
        m=m,
        ticket_id=ticket_id,
    )

    # логируем это сообщение в ticket_messages
    with SessionLocal() as s:
        _save_ticket_message(s, ticket_id, m, sender_type="user")
        s.commit()

    # записываем в FSM всё, что надо
    await state.update_data(
        ticket_id=ticket_id,
        user_tg_id=m.from_user.id,   # type: ignore
        collected_msg_ids=[m.message_id],
    )

    # переключаемся в стадию сбора медиа
    await state.set_state(OtherForm.waiting_question_media)

    # даём инструкцию + кнопку 'Отправить оператору ✅'
    await m.answer(
        texts.OTHER_SEND_MEDIA_STEP,
        reply_markup=other_media_done_kb()
    )


@router.message(OtherForm.waiting_question_media)
async def other_collect_media(m: types.Message, state: FSMContext):
    """
    Пользователь кидает ещё фотки, видео, pdf, голосовые.
    Мы просто складываем их в тот же тикет и в список сообщений.
    Ничего не шлём операторам пока не нажмут 'Отправить оператору ✅'.
    """
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    if ticket_id is None:
        return  # защита от сломанного состояния

    # сохраняем вложения из этого сообщения
    await save_all_attachments_from_message(
        bot=m.bot,
        m=m,
        ticket_id=ticket_id,
    )

    # логируем сообщение в БД
    with SessionLocal() as s:
        _save_ticket_message(s, ticket_id, m, sender_type="user")
        s.commit()

    # дописываем id сообщения в список collected_msg_ids
    collected = data.get("collected_msg_ids", [])
    collected.append(m.message_id)
    await state.update_data(collected_msg_ids=collected)

    # не отвечаем пользователю заново, не спамим инструкцией второй раз.


@router.callback_query(F.data == "other_done")
async def other_done(c: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал 'Отправить оператору ✅' в "Другой вопрос".
    Тут мы формируем одно уведомление, кидаем всё оператору,
    благодарим пользователя и чистим состояние.
    """
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    collected_ids = data.get("collected_msg_ids", [])
    user_tg_id = data.get("user_tg_id")

    if ticket_id is None or user_tg_id is None:
        await c.answer("Ошибка состояния. Попробуйте заново.", show_alert=True)
        await state.clear()
        return

    # достаём объект юзера, чтобы красиво подписать карточку
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.tg_id == user_tg_id))  # type: ignore

    if user:
        await _notify_operators_about_ticket(
            m=c.message,
            ticket_id=ticket_id,
            user=user,
            intro_text="Новый вопрос от клиента",
            extra_message_ids=collected_ids,
        )

    # сообщаем пользователю, что запрос ушёл
    await c.message.answer(texts.OTHER_AFTER_SEND, reply_markup=ok_kb())

    # чистим FSM
    await state.clear()

    await c.answer("Передано оператору")
