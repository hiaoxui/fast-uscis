import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest

from fusi.config import TelegramConfig
from fusi.telegram import TelegramDeliveryError, send_message, send_message_sync


class SendMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = TelegramConfig(
            api="bot-token",
            update_chat_id="updates",
            no_update_chat_id="no-updates",
        )

    @patch("fusi.telegram.Bot")
    async def test_sends_text_to_configured_chat(self, bot_class: MagicMock) -> None:
        bot = MagicMock()
        bot.send_message = AsyncMock()
        bot_class.return_value.__aenter__ = AsyncMock(return_value=bot)
        bot_class.return_value.__aexit__ = AsyncMock(return_value=False)

        await send_message(self.config, "updates", "case result")

        bot_class.assert_called_once_with(token="bot-token")
        bot.send_message.assert_awaited_once_with(
            chat_id="updates",
            text="case result",
        )

    @patch("fusi.telegram.Bot")
    async def test_splits_messages_at_telegram_limit(self, bot_class: MagicMock) -> None:
        bot = MagicMock()
        bot.send_message = AsyncMock()
        bot_class.return_value.__aenter__ = AsyncMock(return_value=bot)
        bot_class.return_value.__aexit__ = AsyncMock(return_value=False)

        await send_message(self.config, "updates", "a" * 4097)

        self.assertEqual(bot.send_message.await_count, 2)
        self.assertEqual(len(bot.send_message.await_args_list[0].kwargs["text"]), 4096)
        self.assertEqual(bot.send_message.await_args_list[1].kwargs["text"], "a")

    @patch("fusi.telegram.Bot")
    async def test_wraps_telegram_errors(self, bot_class: MagicMock) -> None:
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=BadRequest("chat not found"))
        bot_class.return_value.__aenter__ = AsyncMock(return_value=bot)
        bot_class.return_value.__aexit__ = AsyncMock(return_value=False)

        with self.assertRaisesRegex(TelegramDeliveryError, "chat not found"):
            await send_message(self.config, "updates", "case result")

    @patch("fusi.telegram.send_message", new_callable=AsyncMock)
    async def test_sync_wrapper_works_inside_running_event_loop(
        self,
        send_message_mock: AsyncMock,
    ) -> None:
        send_message_sync(self.config, "updates", "case result")

        send_message_mock.assert_awaited_once_with(
            self.config,
            "updates",
            "case result",
        )