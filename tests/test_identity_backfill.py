import unittest

from app.services.identity_backfill import backfill_historical_user_identity, identity_token_expr


class FakeCursor:
    def __init__(self, rowcounts):
        self._rowcounts = list(rowcounts)
        self.queries = []
        self.rowcount = 0

    def execute(self, sql):
        self.queries.append(sql)
        self.rowcount = self._rowcounts.pop(0) if self._rowcounts else 0


class IdentityBackfillTests(unittest.TestCase):
    def test_identity_token_expr_normalizes_tokens(self):
        self.assertEqual(
            identity_token_expr("src.user_name"),
            "LOWER(LTRIM(BTRIM(COALESCE(src.user_name, '')), '@'))",
        )

    def test_backfill_covers_votes_attendance_progress_and_proposals(self):
        cursor = FakeCursor([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])

        summary = backfill_historical_user_identity(cursor)

        self.assertEqual(summary["book_proposals_updated"], 1)
        self.assertEqual(summary["book_votes_deleted"], 2)
        self.assertEqual(summary["book_votes_updated"], 3)
        self.assertEqual(summary["theme_votes_deleted"], 4)
        self.assertEqual(summary["theme_votes_updated"], 5)
        self.assertEqual(summary["meeting_attendance_deleted"], 6)
        self.assertEqual(summary["meeting_attendance_updated"], 7)
        self.assertEqual(summary["book_ratings_deleted"], 8)
        self.assertEqual(summary["book_ratings_updated"], 9)
        self.assertEqual(summary["reading_progress_deleted"], 10)
        self.assertEqual(summary["reading_progress_updated"], 11)

        joined = "\n".join(cursor.queries)
        self.assertIn("UPDATE book_proposals src", joined)
        self.assertIn("DELETE FROM book_votes target", joined)
        self.assertIn("DELETE FROM meeting_attendance target", joined)
        self.assertIn("DELETE FROM reading_progress target", joined)


if __name__ == "__main__":
    unittest.main()
