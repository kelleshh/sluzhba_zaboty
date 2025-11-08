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
    ok_kb,
    other_media_done_kb,
    warranty_media_done_kb,
)
from src.keyboards.operator import claim_kb
from src.db.base import SessionLocal
from src.config import settings
from src.db.users import upsert_user_from_tg
from src.db.models import (
    User,
    Ticket,
    TicketStatus,
    TicketMessage,
    MessageAttachment,
)
from src.utils.files import (
    download_by_file_id,
    build_rel_path,
)

router = Router()


# -------------------------
# FSM СЦЕНАРИИ
# -------------------------

class WarrantyForm(StatesGroup):
    waiting_details = State()   # ждем текст с описанием проблемы и где купили
    waiting_media = State()     # ждем фото/видео/чек

class OtherForm(StatesGroup):
    waiting_question_text = State()   # ждем текст вопроса
    waiting_question_media = State()  # ждем доп. вложения


# -------------------------
# УТИЛИТЫ
# -------------------------

def _upsert_user_and_create_ticket(m: types.Message) -> tuple[int, User]:
    with SessionLocal() as s:
        user = upsert_user_from_tg(s, m.from_user, mark_operator=False)
        s.flush()

        ticket = Ticket(
            user_id=user.id,
            status=TicketStatus.waiting,
            operator_tg_id=None,
        )
        s.add(ticket)
        s.commit()
        ticket_id = ticket.id

    return ticket_id, user


async def _attach_photo(bot, s, ticket_id: int, tm_id: int, m: types.Message):
    ph = m.photo[-1]
    att = MessageAttachment(
        ticket_message_id=tm_id,
        ticket_id=ticket_id,
        media_type="photo",
        file_id=ph.file_id,
        file_unique_id=ph.file_unique_id,
        size=getattr(ph, "file_size", None),
        width=ph.width,
        height=ph.height,
    )
    if settings.store_media_local:
        rel = build_rel_path(ticket_id, tm_id, "photo", ph.file_unique_id, None)
        att.local_path = await download_by_file_id(bot, ph.file_id, rel)
    s.add(att)


async def _attach_document(bot, s, ticket_id: int, tm_id: int, m: types.Message):
    d = m.document
    att = MessageAttachment(
        ticket_message_id=tm_id,
        ticket_id=ticket_id,
        media_type="document",
        file_id=d.file_id,
        file_unique_id=d.file_unique_id,
        size=getattr(d, "file_size", None),
        mime_type=getattr(d, "mime_type", None),
        file_name=getattr(d, "file_name", None),
    )
    if settings.store_media_local:
        rel = build_rel_path(ticket_id, tm_id, "document", d.file_unique_id, getattr(d, "mime_type", None))
        att.local_path = await download_by_file_id(bot, d.file_id, rel)
    s.add(att)


async def _attach_video(bot, s, ticket_id: int, tm_id: int, m: types.Message):
    v = m.video
    att = MessageAttachment(
        ticket_message_id=tm_id,
        ticket_id=ticket_id,
        media_type="video",
        file_id=v.file_id,
        file_unique_id=v.file_unique_id,
        size=getattr(v, "file_size", None),
        width=getattr(v, "width", None),
        height=getattr(v, "height", None),
        duration=getattr(v, "duration", None),
        mime_type=getattr(v, "mime_type", None),
    )
    if settings.store_media_local:
        rel = build_rel_path(ticket_id, tm_id, "video", v.file_unique_id, getattr(v, "mime_type", None))
        att.local_path = await download_by_file_id(bot, v.file_id, rel)
    s.add(att)


async def _attach_voice(bot, s, ticket_id: int, tm_id: int, m: types.Message):
    v = m.voice
    att = MessageAttachment(
        ticket_message_id=tm_id,
        ticket_id=ticket_id,
        media_type="voice",
        file_id=v.file_id,
        file_unique_id=v.file_unique_id,
        size=getattr(v, "file_size", None),
        duration=getattr(v, "duration", None),
        mime_type=getattr(v, "mime_type", None),
    )
    if settings.store_media_local:
        rel = build_rel_path(ticket_id, tm_id, "voice", v.file_unique_id, getattr(v, "mime_type", None))
        att.local_path = await download_by_file_id(bot, v.file_id, rel)
    s.add(att)


async def _save_ticket_message(
    bot,
    s,
    ticket_id: int,
    m: types.Message,
    sender_type: str,
):
    """
    Логируем одно входящее сообщение в БД:
    - создаём TicketMessage
    - если это медиа, создаём и MessageAttachment с ticket_id
    - при необходимости скачиваем файл в media/
    """

    content_type = m.content_type

    tm = TicketMessage(
        ticket_id=ticket_id,
        sender_tg_id=m.from_user.id,      # type: ignore
        sender_type=sender_type,
        tg_message_id=m.message_id,
        content_type=content_type,
        message_text=m.text if content_type == "text" else None,
        caption=getattr(m, "caption", None),
    )
    s.add(tm)
    s.flush()  # теперь у нас есть tm.id

    try:
        if content_type == "photo" and getattr(m, "photo", None):
            await _attach_photo(bot, s, ticket_id, tm.id, m)

        elif content_type == "document" and getattr(m, "document", None):
            await _attach_document(bot, s, ticket_id, tm.id, m)

        elif content_type == "video" and getattr(m, "video", None):
            await _attach_video(bot, s, ticket_id, tm.id, m)

        elif content_type == "voice" and getattr(m, "voice", None):
            await _attach_voice(bot, s, ticket_id, tm.id, m)

        # сюда можно добавить audio / animation / video_note / sticker и т.д.
    except Exception:
        # не даём боту умереть от проблем скачивания
        pass

    s.commit()


async def _notify_operators_about_ticket(
    m: types.Message,
    ticket_id: int,
    user: User,
    intro_text: str,
    extra_message_ids: list[int],
):
    """
    Кидаем в операторский чат карточку с claim-кнопкой
    + форвардим ВСЕ сообщения клиента по тикету.
    """
    username = f"@{user.username}" if user.username else "—"
    summary = (
        f"{intro_text} #{ticket_id}\n"
        f"Пользователь: {user.first_name or '—'} {username}\n"
        f"TG ID: {user.tg_id}\n"
        f"Статус: WAITING\n\n"
        f"Ниже — детали обращения."
    )

    # карточка с кнопкой "Взять в работу"
    await m.bot.send_message(
        chat_id=settings.operators_chat_id,
        text=summary,
        reply_markup=claim_kb(ticket_id),
    )

    # пересылаем ВСЕ собранные сообщения юзера
    for mid in extra_message_ids:
        await m.bot.copy_message(
            chat_id=settings.operators_chat_id,
            from_chat_id=m.chat.id,
            message_id=mid,
        )


def _message_has_media(m: types.Message) -> bool:
    """
    Проверяем, что пользователь реально прислал медиа:
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
        reply_markup=ok_kb(),  # кнопка "В начало"
    )
    await c.answer()


@router.message(WarrantyForm.waiting_details)
async def warranty_details_step(m: types.Message, state: FSMContext):
    """
    Это первое сообщение по гарантии.
    Делаем тикет, логируем это сообщение (текст + вложения), начинаем копить.
    Потом просим докинуть медиа и даём кнопку "Отправить оператору ✅".
    """

    data = await state.get_data()
    if data.get("ticket_id") is not None:
        # если внезапно приехало ещё одно сообщение до переключения стейта,
        # обрабатываем как будто это уже вложения
        return await warranty_collect_media(m, state)

    # создаём тикет WAITING
    ticket_id, user = _upsert_user_and_create_ticket(m)

    # логируем первое сообщение целиком
    with SessionLocal() as s:
        await _save_ticket_message(
            bot=m.bot,
            s=s,
            ticket_id=ticket_id,
            m=m,
            sender_type="user",
        )

    # сохраняем инфу для последующих шагов
    await state.update_data(
        ticket_id=ticket_id,
        user_tg_id=m.from_user.id,        # type: ignore
        collected_msg_ids=[m.message_id], # список всех сообщений для оператора
    )

    # переходим в стадию ожидания медиа
    await state.set_state(WarrantyForm.waiting_media)

    # просим докинуть фотки/чеки/видосы и даём кнопку "Отправить оператору ✅"
    await m.answer(
        texts.WARRANTY_MEDIA_STEP,
        reply_markup=warranty_media_done_kb(),
    )


@router.message(WarrantyForm.waiting_media)
async def warranty_collect_media(m: types.Message, state: FSMContext):
    """
    Мы уже создали тикет. Теперь просто копим дополнительные сообщения:
    фотки, документы, голосовые. Ничего не шлем оператору до "✅".
    """
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    if ticket_id is None:
        # состояние потерялось — не создаём новый тикет
        return

    # логируем это сообщение (и текст, и медиавложения)
    with SessionLocal() as s:
        await _save_ticket_message(
            bot=m.bot,
            s=s,
            ticket_id=ticket_id,
            m=m,
            sender_type="user",
        )

    # запоминаем message_id для последующей отправки оператору
    collected = data.get("collected_msg_ids", [])
    collected.append(m.message_id)
    await state.update_data(collected_msg_ids=collected)

    # ничего не отвечаем здесь пользователю, он уже видит инструкцию


@router.callback_query(F.data == "warranty_done")
async def warranty_done(c: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал 'Отправить оператору ✅' в гарантии.
    Делаем одно уведомление оператору со всеми собранными сообщениями.
    Благодарим пользователя и чистим стейт.
    """
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    collected_ids = data.get("collected_msg_ids", [])
    user_tg_id = data.get("user_tg_id")

    if ticket_id is None or user_tg_id is None:
        await c.answer("Ошибка состояния. Попробуйте заново.", show_alert=True)
        await state.clear()
        return

    # берём юзера из БД, чтобы красиво подписать карточку
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

    # чистим состояние
    await state.clear()

    await c.answer("Отправлено оператору")


# -------------------------
# 2. ВОЗВРАТ ТОВАРА
# -------------------------

@router.callback_query(F.data == "return_start")
async def return_start(c: CallbackQuery, state: FSMContext):
    """
    Показываем инфу про возврат (2 сообщения),
    затем вопрос "Хотите перейти в гарантию?" с клавиатурой return_kb().
    """
    await state.clear()

    message = cast(Message, c.message)

    # редактируем исходное сообщение
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

    Требование:
    - После нажатия кнопки пользователь СРАЗУ может написать сообщение.
    - Никаких промежуточных кнопок "Отправить сообщение сотруднику".
    - Остаётся только кнопка "В начало".
    """

    await state.clear()
    await state.set_state(OtherForm.waiting_question_text)

    message = cast(Message, c.message)

    # Первый текст
    await message.answer(texts.OTHER_INTRO_1)

    # Второй текст
    await c.message.answer(texts.OTHER_INTRO_2, reply_markup=ok_kb())

    await c.answer()


@router.message(OtherForm.waiting_question_text)
async def other_question_text(m: types.Message, state: FSMContext):
    """
    Первое сообщение пользователя в 'Другой вопрос'.
    Создаём тикет, логируем это сообщение, переходим в стадию сбора доп. медиа.
    Потом даём инструкцию + кнопку 'Отправить оператору ✅'.
    """

    data = await state.get_data()
    if data.get("ticket_id") is not None:
        # если каким-то чудом прилетело сразу несколько сообщений до смены стейта,
        # считаем текущее сообщением с вложениями
        return await other_collect_media(m, state)

    # создаём тикет
    ticket_id, user = _upsert_user_and_create_ticket(m)

    # логируем первое сообщение целиком (текст/медиа)
    with SessionLocal() as s:
        await _save_ticket_message(
            bot=m.bot,
            s=s,
            ticket_id=ticket_id,
            m=m,
            sender_type="user",
        )

    # записываем данные в FSM
    await state.update_data(
        ticket_id=ticket_id,
        user_tg_id=m.from_user.id,        # type: ignore
        collected_msg_ids=[m.message_id], # список всех сообщений для оператора
    )

    # переключаемся в стадию сбора доп. медиа
    await state.set_state(OtherForm.waiting_question_media)

    # даём инструкцию + кнопку 'Отправить оператору ✅'
    await m.answer(
        texts.OTHER_SEND_MEDIA_STEP,
        reply_markup=other_media_done_kb(),
    )


@router.message(OtherForm.waiting_question_media)
async def other_collect_media(m: types.Message, state: FSMContext):
    """
    Пользователь кидает доп. фотки/видосы/пдф/голосовые.
    Мы просто копим их в том же тикете и не пишем оператору до "✅".
    """
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    if ticket_id is None:
        return  # если состояние утеряно, не создаём новый тикет тут

    # логируем сообщение (и его вложения)
    with SessionLocal() as s:
        await _save_ticket_message(
            bot=m.bot,
            s=s,
            ticket_id=ticket_id,
            m=m,
            sender_type="user",
        )

    # дописываем id сообщения в список collected_msg_ids
    collected = data.get("collected_msg_ids", [])
    collected.append(m.message_id)
    await state.update_data(collected_msg_ids=collected)

    # не отвечаем заново, чтобы не спамить


@router.callback_query(F.data == "other_done")
async def other_done(c: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал 'Отправить оператору ✅' в 'Другой вопрос'.
    Шлём одно уведомление оператору, благодарим пользователя и чистим стейт.
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

    # сообщаем пользователю, что запрос ушёл, и даём кнопку "В начало"
    await c.message.answer(texts.OTHER_AFTER_SEND, reply_markup=ok_kb())

    # чистим FSM
    await state.clear()

    await c.answer("Передано оператору")
