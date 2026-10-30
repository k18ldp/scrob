import json
import unittest

import httpx

from core import emby

TICKS = 10_000_000
ONE_HOUR = 3600 * TICKS


def _client(user_data: dict, calls: list, runtime_ticks: int = ONE_HOUR, post_status: int = 204,
            get_status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            if get_status >= 400:
                return httpx.Response(get_status)
            return httpx.Response(200, json={"RunTimeTicks": runtime_ticks, "UserData": user_data})
        return httpx.Response(post_status)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _push(client: httpx.AsyncClient, seconds: int) -> str:
    return await emby.set_playback_position(
        "http://emby.local:8096/", "token", "user-id", "47737", seconds, client=client,
    )


class SetPlaybackPositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_pushes_position_and_keeps_other_user_data(self) -> None:
        calls: list = []
        existing = {"Played": False, "PlayCount": 2, "IsFavorite": True, "Rating": 8.0, "PlaybackPositionTicks": 0}
        async with _client(existing, calls) as client:
            self.assertEqual(await _push(client, 600), "pushed")
        post = calls[-1]
        self.assertEqual(post.method, "POST")
        self.assertEqual(post.url.path, "/Users/user-id/Items/47737/UserData")
        body = json.loads(post.content)
        self.assertEqual(body["PlaybackPositionTicks"], 600 * TICKS)
        # POST replaces the whole object, so nothing else may be lost.
        self.assertEqual((body["Played"], body["PlayCount"], body["IsFavorite"], body["Rating"]), (False, 2, True, 8.0))

    async def test_played_item_is_never_touched(self) -> None:
        calls: list = []
        async with _client({"Played": True}, calls) as client:
            self.assertEqual(await _push(client, 600), "skipped_played")
        self.assertEqual([c.method for c in calls], ["GET"])

    async def test_does_not_move_emby_position_backwards_or_rewrite_same_value(self) -> None:
        for emby_seconds in (600, 598, 1200):
            calls: list = []
            data = {"Played": False, "PlaybackPositionTicks": emby_seconds * TICKS, "LastPlayedDate": "2026-10-30T10:00:00.0000000Z"}
            async with _client(data, calls) as client:
                self.assertEqual(await _push(client, 600), "skipped_emby_ahead", emby_seconds)
            self.assertEqual([c.method for c in calls], ["GET"])

    async def test_position_at_or_past_end_is_not_pushed(self) -> None:
        calls: list = []
        async with _client({"Played": False}, calls, runtime_ticks=ONE_HOUR) as client:
            self.assertEqual(await _push(client, 3600), "skipped_at_end")
        self.assertEqual([c.method for c in calls], ["GET"])

    async def test_non_positive_position_makes_no_request(self) -> None:
        calls: list = []
        async with _client({}, calls) as client:
            self.assertEqual(await _push(client, 0), "skipped")
            self.assertEqual(await _push(client, -5), "skipped")
        self.assertEqual(calls, [])

    async def test_info_reports_emby_state(self) -> None:
        calls: list = []
        info: dict = {}
        data = {"Played": False, "PlaybackPositionTicks": 900 * TICKS}
        async with _client(data, calls) as client:
            await emby.set_playback_position("http://emby.local:8096/", "t", "u", "1", 600, client=client, info=info)
        self.assertEqual(info, {"played": False, "emby_seconds": 900, "runtime_seconds": 3600})

    async def test_new_position_is_stamped_with_last_played_date(self) -> None:
        from datetime import datetime
        calls: list = []
        async with _client({"Played": False}, calls) as client:
            outcome = await emby.set_playback_position(
                "http://emby.local:8096/", "t", "u", "1", 600, client=client, played_at=datetime(2026, 10, 30, 14, 55, 7),
            )
        self.assertEqual(outcome, "pushed")
        self.assertEqual(json.loads(calls[-1].content)["LastPlayedDate"], "2026-10-30T14:55:07Z")

    async def test_existing_last_played_date_is_kept(self) -> None:
        calls: list = []
        data = {"Played": False, "LastPlayedDate": "2026-01-01T00:00:00.0000000Z"}
        async with _client(data, calls) as client:
            self.assertEqual(await _push(client, 600), "pushed")
        self.assertEqual(json.loads(calls[-1].content)["LastPlayedDate"], "2026-01-01T00:00:00.0000000Z")

    async def test_matching_position_without_date_only_adds_the_date(self) -> None:
        calls: list = []
        async with _client({"Played": False, "PlaybackPositionTicks": 600 * TICKS}, calls) as client:
            self.assertEqual(await _push(client, 600), "pushed")
        body = json.loads(calls[-1].content)
        self.assertEqual(body["PlaybackPositionTicks"], 600 * TICKS)
        self.assertIn("LastPlayedDate", body)

    async def test_emby_ahead_without_date_keeps_emby_position(self) -> None:
        calls: list = []
        async with _client({"Played": False, "PlaybackPositionTicks": 1200 * TICKS}, calls) as client:
            self.assertEqual(await _push(client, 600), "pushed")
        self.assertEqual(json.loads(calls[-1].content)["PlaybackPositionTicks"], 1200 * TICKS)

    async def test_retries_without_date_if_emby_rejects_it(self) -> None:
        posts: list = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"RunTimeTicks": ONE_HOUR, "UserData": {"Played": False}})
            body = json.loads(request.content)
            posts.append(body)
            return httpx.Response(400 if "LastPlayedDate" in body else 204)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(await _push(client, 600), "pushed")
        self.assertEqual(len(posts), 2)
        self.assertNotIn("LastPlayedDate", posts[1])
        self.assertEqual(posts[1]["PlaybackPositionTicks"], 600 * TICKS)

    async def test_server_errors_report_failed(self) -> None:
        calls: list = []
        async with _client({"Played": False}, calls, post_status=500) as client:
            self.assertEqual(await _push(client, 600), "failed")
        calls = []
        async with _client({}, calls, get_status=404) as client:
            self.assertEqual(await _push(client, 600), "failed")


if __name__ == "__main__":
    unittest.main()
