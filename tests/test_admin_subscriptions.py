import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("GROUP_ID", "0")
os.environ.setdefault("CHANNEL_ID", "0")
os.environ.setdefault("API_ID", "0")
os.environ.setdefault("API_HASH", "0")
os.environ.setdefault("BOT_TOKEN", "0")
os.environ.setdefault("URI_DB", "mongodb://localhost:27017")
os.environ.setdefault("ADMIN_ID", "1")

import plugins.admin as admin


class AdminSubscriptionCommandTests(unittest.TestCase):
    def test_subp_stores_serializable_subscription_payload(self):
        message = types.SimpleNamespace(
            text="/subp 42 7",
            reply=AsyncMock(),
            stop_propagation=lambda: None,
        )
        client = types.SimpleNamespace()

        with patch.object(admin.database, "update_user", new=AsyncMock()) as update_user_mock, \
             patch.object(admin.storage, "get_user", new=AsyncMock(return_value={"subscription": {}})) as get_user_mock, \
             patch.object(admin.storage, "set_user", new=AsyncMock()) as set_user_mock, \
             patch.object(admin.storage, "add_subscription", new=AsyncMock()) as add_subscription_mock:
            import asyncio
            asyncio.run(admin.subadd(client, message))

        self.assertTrue(update_user_mock.await_count >= 1)
        payload = update_user_mock.await_args.args[1]["subscription"]
        self.assertEqual(payload["plan"], "premium")
        self.assertIsInstance(payload["expires_at"], str)
        self.assertTrue(get_user_mock.await_count >= 1)
        self.assertTrue(set_user_mock.await_count >= 1)
        self.assertTrue(add_subscription_mock.await_count >= 1)
        message.reply.assert_awaited_once()

    def test_subr_continues_when_group_member_lookup_fails(self):
        message = types.SimpleNamespace(
            text="/subr 42",
            reply=AsyncMock(),
            stop_propagation=lambda: None,
        )
        client = types.SimpleNamespace(
            get_chat_member=AsyncMock(side_effect=Exception("group lookup failed"))
        )

        with patch.object(admin.database, "update_user", new=AsyncMock()) as update_user_mock, \
             patch.object(admin.storage, "get_user", new=AsyncMock(return_value={"subscription": {"active": True}})) as get_user_mock, \
             patch.object(admin.storage, "set_user", new=AsyncMock()) as set_user_mock, \
             patch.object(admin.storage, "remove_subscription", new=AsyncMock()) as remove_subscription_mock:
            import asyncio
            asyncio.run(admin.subremove(client, message))

        self.assertTrue(update_user_mock.await_count >= 1)
        self.assertTrue(get_user_mock.await_count >= 1)
        self.assertTrue(set_user_mock.await_count >= 1)
        self.assertTrue(remove_subscription_mock.await_count >= 1)
        message.reply.assert_awaited_once()

    def test_subv_continues_when_unban_fails(self):
        message = types.SimpleNamespace(
            text="/subv 42 7",
            reply=AsyncMock(),
            stop_propagation=lambda: None,
        )
        client = types.SimpleNamespace(
            unban_chat_member=AsyncMock(side_effect=Exception("unban failed"))
        )

        with patch.object(admin.database, "update_user", new=AsyncMock()) as update_user_mock, \
             patch.object(admin.storage, "get_user", new=AsyncMock(return_value={"subscription": {}})) as get_user_mock, \
             patch.object(admin.storage, "set_user", new=AsyncMock()) as set_user_mock, \
             patch.object(admin.storage, "add_subscription", new=AsyncMock()) as add_subscription_mock:
            import asyncio
            asyncio.run(admin.subadd(client, message))

        self.assertTrue(update_user_mock.await_count >= 1)
        payload = update_user_mock.await_args.args[1]["subscription"]
        self.assertEqual(payload["plan"], "vip")
        self.assertTrue(get_user_mock.await_count >= 1)
        self.assertTrue(set_user_mock.await_count >= 1)
        self.assertTrue(add_subscription_mock.await_count >= 1)
        message.reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
