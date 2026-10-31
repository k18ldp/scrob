import unittest
from unittest.mock import patch

from core import jellyfin


def _page(ids, total):
    return {"Items": [{"Id": i, "Name": f"n{i}"} for i in ids], "TotalRecordCount": total}


class GetItemsWithUserStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_played_then_resumable_pages_and_merges_duplicates(self) -> None:
        calls: list[dict] = []
        pages = {
            ("IsPlayed", 0): _page(["a", "b"], 3),
            ("IsPlayed", 2): _page(["c"], 3),
            ("IsResumable", 0): _page(["c", "d"], 2),   # "c" is both played and resumable
        }

        async def fake_get(url, token, path, params=None):
            calls.append({"path": path, **params})
            return pages[(params["Filters"], params["StartIndex"])]

        with patch.object(jellyfin, "_get", fake_get):
            items = await jellyfin.get_items_with_user_state("lib1", "http://e", "tok", "user1", "Movie", page_size=2)

        self.assertEqual(sorted(i["Id"] for i in items), ["a", "b", "c", "d"])
        self.assertEqual([(c["Filters"], c["StartIndex"]) for c in calls],
                         [("IsPlayed", 0), ("IsPlayed", 2), ("IsResumable", 0)])
        self.assertTrue(all(c["path"] == "Users/user1/Items" and c["ParentId"] == "lib1"
                            and c["IncludeItemTypes"] == "Movie" and c["Recursive"] is True for c in calls))
        self.assertNotIn("ExcludeLocationTypes", calls[0])

    async def test_episodes_exclude_virtual_and_missing_items(self) -> None:
        seen: list[dict] = []

        async def fake_get(url, token, path, params=None):
            seen.append(params)
            return _page([], 0)

        with patch.object(jellyfin, "_get", fake_get):
            self.assertEqual(await jellyfin.get_items_with_user_state("l", "u", "t", "x", "Episode"), [])
        self.assertTrue(all(p["ExcludeLocationTypes"] == "Virtual" and p["IsMissing"] is False for p in seen))
        self.assertEqual([p["Filters"] for p in seen], ["IsPlayed", "IsResumable"])

    async def test_an_empty_page_ends_the_loop_even_if_the_total_is_wrong(self) -> None:
        calls = 0

        async def fake_get(url, token, path, params=None):
            nonlocal calls
            calls += 1
            return {"Items": [], "TotalRecordCount": 999}

        with patch.object(jellyfin, "_get", fake_get):
            await jellyfin.get_items_with_user_state("l", "u", "t", "x", "Movie")
        self.assertEqual(calls, 2)  # one page per filter, then stop

    async def test_only_movies_and_episodes_are_supported(self) -> None:
        with self.assertRaises(ValueError):
            await jellyfin.get_items_with_user_state("l", "u", "t", "x", "Series")


if __name__ == "__main__":
    unittest.main()
