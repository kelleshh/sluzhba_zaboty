from typing import cast
import time

from aiogram import Router, F, types
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import CommandStart

from sqlalchemy import select
from pathlib import Path

from src import texts
from src.keyboards.main import (
    main_menu_kb,
    return_kb,
    other_menu_kb,
    ok_kb,
)
from src.keyboards.operator import claim_kb
from src.db.base import SessionLocal
from src.db.models import User, Ticket, TicketStatus, TicketMessage
from src.config import settings
from src.utils.files import download_by_file_id

router = Router()


# -------------------------
# FSM СЦЕНАРИИ
# -------------------------

class WarrantyForm(StatesGroup):
    waiting_details = State()   # ждем текст с описанием проблемы и где купили
    waiting_media = State()     # ждем фото/видео/чек

class OtherForm(StatesGroup):
    waiting_question = State()  # ждем текст вопроса для "Другой вопрос"


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
    Пользователь выбрал "Обращение по гарантии".
    Шаг 1: просим описать проблему и где покупал.
    """
    await state.clear()
    await state.set_state(WarrantyForm.waiting_details)

    message = cast(Message, c.message)
    await message.edit_text(texts.WARRANTY_INTRO)
    await c.answer()


@router.message(WarrantyForm.waiting_details)
async def warranty_got_details(m: types.Message, state: FSMContext):
    """
    Пользователь написал текст с описанием проблемы.
    Теперь просим приложить фото/видео/чек.
    """
    # сохраняем первое сообщение во временное состояние
    await state.update_data(
        first_msg_id=m.message_id,
        first_msg_text=getattr(m, "text", None),
        first_msg_caption=getattr(m, "caption", None),
        first_msg_content_type=m.content_type,
    )

    await state.set_state(WarrantyForm.waiting_media)
    await m.answer(texts.WARRANTY_NEED_MEDIA)


@router.message(WarrantyForm.waiting_media)
async def warranty_got_media(m: types.Message, state: FSMContext):
    """
    Пользователь шлет медиа (фото/видео/чек).
    Если медиа нет — просим повторить.
    Если есть — создаем тикет, сохраняем медиа в media/, логируем,
    уведомляем операторов, благодарим пользователя.
    """
    # 1. проверяем, что реально есть вложение
    if not _message_has_media(m):
        await m.answer(texts.WARRANTY_NEED_MEDIA)
        return

    # 2. достаём то, что он писал на шаге 1
    data = await state.get_data()

    # 3. создаём/берём юзера и тикет в статусе WAITING
    ticket_id, user = _upsert_user_and_create_ticket(m)

    # 4. вытаскиваем file_id из присланного сообщения
    file_id = None
    if getattr(m, "photo", None):
        file_id = m.photo[-1].file_id          # самое большое фото
    elif getattr(m, "document", None):
        file_id = m.document.file_id
    elif getattr(m, "video", None):
        file_id = m.video.file_id
    elif getattr(m, "voice", None):
        file_id = m.voice.file_id
    elif getattr(m, "audio", None):
        file_id = m.audio.file_id
    elif getattr(m, "animation", None):
        file_id = m.animation.file_id
    elif getattr(m, "video_note", None):
        file_id = m.video_note.file_id

    # 5. если есть file_id, скачиваем файл в media/ticket_<id>/
    if file_id:
        ts = int(time.time())
        base_dir = Path("media") / f"ticket_{ticket_id}"
        base_dir.mkdir(parents=True, exist_ok=True)

        local_path = base_dir / f"{ts}_{m.message_id}"
        # сохраняем файл локально
        await download_by_file_id(m.bot, file_id, str(local_path))

        # сейчас мы путь к файлу в БД не пишем, потому что у TicketMessage нет поля file_path.
        # если захочешь хранить путь в базе — добавим колонку и будем писать.

    # 6. пишем в базу оба сообщения:
    #    - первое сообщение (текстовая жалоба с шага 1),
    #    - второе сообщение (медиа с этого шага)
    with SessionLocal() as s:
        # первое сообщение (описание проблемы)
        tm1 = TicketMessage(
            ticket_id=ticket_id,
            sender_tg_id=m.from_user.id,  # type: ignore
            sender_type="user",
            tg_message_id=data["first_msg_id"],
            content_type=data["first_msg_content_type"],
            message_text=data["first_msg_text"],
            caption=data["first_msg_caption"],
        )
        s.add(tm1)

        # второе сообщение (медиа и/или подпись к нему)
        _save_ticket_message(s, ticket_id, m, sender_type="user")

        s.commit()

    # 7. уведомляем операторов (карточка + пересылка оригинальных сообщений)
    await _notify_operators_about_ticket(
        m=m,
        ticket_id=ticket_id,
        user=user,
        intro_text="Новое обращение по гарантии",
        extra_message_ids=[data["first_msg_id"], m.message_id],
    )

    # 8. отвечаем пользователю + кнопка "В начало"
    await m.answer(texts.WARRANTY_THANKS, reply_markup=ok_kb())

    # 9. чистим FSM
    await state.clear()



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
    Раздел 'Другой вопрос': показываем два инфо-сообщения,
    потом клавиатуру: Отправить / Вернуться в меню.
    """
    await state.clear()

    message = cast(Message, c.message)
    # редактируем кнопочное сообщение
    await message.edit_text(texts.OTHER_INTRO_1)

    # второе сообщение
    await c.message.answer(texts.OTHER_INTRO_2)

    # третье сообщение с клавиатурой
    await c.message.answer(texts.OTHER_ASK_SEND, reply_markup=other_menu_kb())


    await c.answer()


@router.callback_query(F.data == "other_send")
async def other_send(c: CallbackQuery, state: FSMContext):
    """
    Пользователь нажал "Отправить сообщение сотруднику".
    Мы просим его написать вопрос следующим сообщением.
    """
    await state.set_state(OtherForm.waiting_question)

    await c.message.answer(texts.OTHER_PLEASE_DESCRIBE)
    await c.answer()


@router.message(OtherForm.waiting_question)
async def other_waiting_question(m: types.Message, state: FSMContext):
    """
    Пользователь прислал вопрос (любой контент).
    Создаем тикет WAITING, логируем сообщение,
    отправляем оператору карточку с claim-кнопкой,
    и говорим пользователю "ваш запрос передан".
    """
    # создаем тикет
    ticket_id, user = _upsert_user_and_create_ticket(m)

    # сохраняем сообщение в ticket_messages
    with SessionLocal() as s:
        _save_ticket_message(s, ticket_id, m, sender_type="user")
        s.commit()

    # уведомляем операторов:
    await _notify_operators_about_ticket(
        m=m,
        ticket_id=ticket_id,
        user=user,
        intro_text="Новый вопрос от клиента",
        extra_message_ids=[m.message_id],
    )

    # отвечаем пользователю и даем кнопку "В начало"
    await m.answer(texts.OTHER_AFTER_SEND, reply_markup=ok_kb())

    await state.clear()
