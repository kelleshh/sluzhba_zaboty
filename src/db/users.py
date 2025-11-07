from typing import Optional
from aiogram.types import User as TgUser
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from src.db.models import User

def upsert_user_from_tg(s: Session, tg: TgUser, *, mark_operator: bool = False) -> User:
    """
    Апсертим users по tg.id.
    - обновляем first_name/username при изменениях
    - last_seen = now()
    - is_operator |= mark_operator (True не сбрасываем обратно)
    """
    u: Optional[User] = s.scalar(select(User).where(User.tg_id == tg.id))
    if not u:
        u = User(
            tg_id=tg.id,
            first_name=tg.first_name,
            username=tg.username,
            is_operator=bool(mark_operator),
        )
        s.add(u)
        s.flush()
    else:
        changed = False
        if u.first_name != tg.first_name:
            u.first_name = tg.first_name
            changed = True
        if u.username != tg.username:
            u.username = tg.username
            changed = True
        if mark_operator and not u.is_operator:
            u.is_operator = True
            changed = True
        u.last_seen = func.now()
        if changed:
            s.flush()
    return u
