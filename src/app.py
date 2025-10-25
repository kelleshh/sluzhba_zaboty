import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from src.config import settings
from src.db.base import init_db
from src.routers import public, operators, proxy
from src.utils.logging import setup_logging
from src.db.bootstrap import bootstrap_indexes_and_tables

async def main():
    setup_logging()
    init_db() # если нет таблиц, то создаст их, а если есть то все в покое
    bootstrap_indexes_and_tables()
    bot = Bot(token=settings.bot_token, 
              default=DefaultBotProperties(parse_mode=ParseMode.HTML)
              )
    dp = Dispatcher()
    dp.include_router(public.router)
    dp.include_router(operators.router)
    dp.include_router(proxy.router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
