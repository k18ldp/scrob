import unittest

from core.push_targets import file_belongs_to_connection, media_needing_lookup


class FileBelongsToConnectionTests(unittest.TestCase):
    def test_only_the_connection_it_was_read_from(self) -> None:
        self.assertTrue(file_belongs_to_connection(3, 3))
        self.assertFalse(file_belongs_to_connection(3, 4))

    def test_rows_from_before_connection_tracking_apply_everywhere(self) -> None:
        self.assertTrue(file_belongs_to_connection(None, 3))
        self.assertTrue(file_belongs_to_connection(None, 4))


class MediaNeedingLookupTests(unittest.TestCase):
    def test_each_connection_only_looks_up_what_it_is_missing(self) -> None:
        mapped = {(1, 10), (2, 11)}
        self.assertEqual(
            media_needing_lookup([1, 2], [10, 11, 12], mapped),
            {1: [11, 12], 2: [10, 12]},
        )

    def test_nothing_missing_means_no_entry(self) -> None:
        self.assertEqual(media_needing_lookup([1], [10], {(1, 10)}), {})

    def test_legacy_rows_count_as_known_everywhere(self) -> None:
        self.assertEqual(media_needing_lookup([1, 2], [10], {(None, 10)}), {})

    def test_connection_with_no_library_files_looks_up_everything(self) -> None:
        self.assertEqual(media_needing_lookup([5], [10, 11], set()), {5: [10, 11]})


if __name__ == "__main__":
    unittest.main()
