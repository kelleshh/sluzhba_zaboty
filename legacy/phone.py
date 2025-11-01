import phonenumbers
from src.config import settings

def normalize_phone(raw: str) -> str | None:
    try:
        num = phonenumbers.parse(raw, settings.default_region)
        if phonenumbers.is_valid_number(num):
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        return None
    except Exception:
        return None
