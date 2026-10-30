import unittest
from datetime import datetime, timedelta, timezone

import httpx

from core import emby, jellyfin


def _capture_client(captured: dict, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(status)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class FormatDatePlayedTests(unittest.TestCase):
    def test_emby_format_is_compact_utc(self) -> None:
        self.assertEqual(
            jellyfin.format_date_played(datetime(2026, 1, 10, 21, 49, 3), jellyfin.EMBY_DATE_PLAYED_FORMAT),
            "20260110214903",
        )

    def test_jellyfin_format_stays_iso(self) -> None:
        self.assertEqual(
            jellyfin.format_date_played(datetime(2026, 3, 27, 21, 52, 14)),
            "2026-03-27T21:52:14Z",
        )

    def test_unknown_format_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            jellyfin.format_date_played(datetime(2026, 1, 10), "%Y&evil=1")

    def test_aware_datetime_is_converted_to_utc(self) -> None:
        bst = timezone(timedelta(hours=1))
        aware = datetime(2026, 7, 1, 0, 30, 0, tzinfo=bst)  # 2026-06-30 23:30 UTC
        self.assertEqual(
            jellyfin.format_date_played(aware, jellyfin.EMBY_DATE_PLAYED_FORMAT),
            "20260630233000",
        )


class MarkWatchedDateFormatTests(unittest.IsolatedAsyncioTestCase):
    async def test_emby_sends_compact_date_played(self) -> None:
        captured: dict = {}
        async with _capture_client(captured) as client:
            ok = await emby.mark_watched(
                "http://emby.local:8096/", "token", "user-id", "47737",
                client=client, played_at=datetime(2026, 1, 10, 21, 49, 3),
            )
        self.assertTrue(ok)
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/Users/user-id/PlayedItems/47737")
        self.assertEqual(captured["params"], {"DatePlayed": "20260110214903"})

    async def test_jellyfin_still_sends_iso_date_played(self) -> None:
        captured: dict = {}
        async with _capture_client(captured) as client:
            ok = await jellyfin.mark_watched(
                "http://jellyfin.local:8096", "token", "user-id", "abc",
                client=client, played_at=datetime(2026, 1, 10, 21, 49, 3),
            )
        self.assertTrue(ok)
        self.assertEqual(captured["params"], {"DatePlayed": "2026-01-10T21:49:03Z"})

    async def test_emby_without_date_sends_no_date_played(self) -> None:
        captured: dict = {}
        async with _capture_client(captured) as client:
            ok = await emby.mark_watched("http://emby.local", "token", "user-id", "1", client=client)
        self.assertTrue(ok)
        self.assertEqual(captured["params"], {})

    async def test_server_error_returns_false(self) -> None:
        captured: dict = {}
        async with _capture_client(captured, status=500) as client:
            ok = await emby.mark_watched(
                "http://emby.local", "token", "user-id", "1",
                client=client, played_at=datetime(2026, 1, 10, 21, 49, 3),
            )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
