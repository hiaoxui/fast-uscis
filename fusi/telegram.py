import asyncio
from concurrent.futures import ThreadPoolExecutor

from telegram import Bot
from telegram.error import TelegramError

from fusi.config import TelegramConfig

TELEGRAM_MESSAGE_LIMIT = 4096


class TelegramDeliveryError(Exception):
    pass


def send_message_sync(config: TelegramConfig, chat_id: str, text: str) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(send_message(config, chat_id, text))
        return

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(asyncio.run, send_message(config, chat_id, text)).result()


async def send_message(config: TelegramConfig, chat_id: str, text: str) -> None:
    try:
        async with Bot(token=config.api) as bot:
            for offset in range(0, len(text), TELEGRAM_MESSAGE_LIMIT):
                await bot.send_message(
                    chat_id=chat_id,
                    text=text[offset : offset + TELEGRAM_MESSAGE_LIMIT],
                )
    except TelegramError as exc:
        raise TelegramDeliveryError(f"Could not send result to Telegram: {exc}") from exc