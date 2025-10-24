import asyncio
from aiogram import Bot, Dispatcher
from src.config import settings
from src.db.base import init_db
from src.routers import public, operators, proxy
from src.utils.logging import setup_logging

async def main():
    setup_logging()
    init_db() # если нет таблиц, то создаст их, а если есть то все в покое
    bot = Bot(token=settings.bot_token, parse_mode="HTML")
    dp = Dispatcher()
    dp.include_router(public.router)
    dp.include_router(operators.router)
    dp.include_router(proxy.router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
