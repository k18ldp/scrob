import json
import unittest
from types import SimpleNamespace

import httpx

from core import emby
from core.profile_names import pick_linked_connection, unique_username


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


class PickLinkedConnectionTests(unittest.TestCase):
    @staticmethod
    def _c(cid: int, url: str, uid: str | None) -> SimpleNamespace:
        return SimpleNamespace(id=cid, url=url, server_user_id=uid)

    def test_routes_by_user_id_on_the_same_server(self) -> None:
        a = self._c(1, "https://emby.example/", "aaaa1111")
        b = self._c(2, "https://emby.example", "bbbb2222")
        c = self._c(3, "https://other.example", "bbbb2222")  # same user id, different server
        self.assertIs(pick_linked_connection([a, c, b], "https://EMBY.example/", "bbbb2222"), b)

    def test_dashes_and_case_in_ids_do_not_matter(self) -> None:
        a = self._c(1, "http://e", "0123456789ABCDEF0123456789ABCDEF")
        self.assertIs(pick_linked_connection([a], "http://e", "01234567-89ab-cdef-0123-456789abcdef"), a)

    def test_unknown_or_missing_user_matches_nothing(self) -> None:
        a = self._c(1, "http://e", "aaaa")
        self.assertIsNone(pick_linked_connection([a], "http://e", "zzzz"))
        self.assertIsNone(pick_linked_connection([a], "http://e", None))
        self.assertIsNone(pick_linked_connection([a], "http://e", ""))

    def test_connection_without_a_stored_user_never_matches(self) -> None:
        self.assertIsNone(pick_linked_connection([self._c(1, "http://e", None)], "http://e", "aaaa"))


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
