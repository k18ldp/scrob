import json
import unittest

import httpx

from core import emby
from core.profile_names import unique_username


class UniqueUsernameTests(unittest.TestCase):
    def test_free_name_is_kept(self) -> None:
        self.assertEqual(unique_username("Sam", set()), "Sam")

    def test_taken_name_gets_a_number_case_insensitively(self) -> None:
        self.assertEqual(unique_username("Sam", {"sam"}), "Sam 2")
        self.assertEqual(unique_username("Sam", {"sam", "sam 2", "sam 3"}), "Sam 4")

    def test_whitespace_is_collapsed_and_empty_gets_a_default(self) -> None:
        self.assertEqual(unique_username("  Sam   Jones ", set()), "Sam Jones")
        self.assertEqual(unique_username("   ", set()), "Profile")

    def test_long_names_are_cut(self) -> None:
        self.assertEqual(len(unique_username("x" * 200, set())), 60)


class ListUsersTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_ids_and_names(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json=[{"Id": "abc", "Name": "Sam"}, {"Id": "def"}, {"Name": "no id"}, "junk"])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            users = await emby.list_users("http://emby.local:8096/", "secret", client=client)
        self.assertEqual(users, [{"id": "abc", "name": "Sam"}, {"id": "def", "name": ""}])
        self.assertEqual(seen["path"], "/Users")
        self.assertEqual(seen["auth"], 'MediaBrowser Token="secret"')

    async def test_failure_returns_none(self) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401))) as client:
            self.assertIsNone(await emby.list_users("http://emby.local:8096", "bad", client=client))


if __name__ == "__main__":
    unittest.main()
