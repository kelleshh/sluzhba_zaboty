from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, BigInteger, ForeignKey, Text, Enum, Index, func, Integer
import enum
from datetime import datetime

class Base(DeclarativeBase): pass

class TicketStatus(str, enum.Enum):
    waiting = "WAITING"    # ждем оператора
    assigned = "ASSIGNED"  # оператор подключился
    closed = "CLOSED"      # диалог завершён

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=func.now())

class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    operator_tg_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus), index=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    closed_at: Mapped[datetime | None]

    user: Mapped[User] = relationship()

    __table_args__ = (
        Index("ix_ticket_user_active", "user_id", "status"),
    )

class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    sender_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    sender_type: Mapped[str] = mapped_column(String(16))  # "user" / "operator"
    tg_message_id: Mapped[int] = mapped_column()
    content_type: Mapped[str] = mapped_column(String(32)) # text/photo/document/voice/video/...
    message_text: Mapped[str | None] = mapped_column(Text)   # текст сообщения
    caption: Mapped[str | None] = mapped_column(Text)        # подпись к медиа
    created_at: Mapped[datetime] = mapped_column(default=func.now())

class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_message_id: Mapped[int] = mapped_column(
        ForeignKey("ticket_messages.id", ondelete="CASCADE"), index=True
    )
    ticket_id: Mapped[int | None] = mapped_column(
        Integer,
        index=True,
    )
    media_type: Mapped[str] = mapped_column(String(32))      # photo/document/video/voice/...
    file_id: Mapped[str] = mapped_column(String(256), index=True)
    file_unique_id: Mapped[str | None] = mapped_column(String(128))
    file_name: Mapped[str | None] = mapped_column(String(256))
    mime_type: Mapped[str | None] = mapped_column(String(64))
    size: Mapped[int | None] = mapped_column(Integer)        # bytes
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[int | None] = mapped_column(Integer)    # seconds
    local_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(default=func.now())