import sys
import unittest
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "scripts"))

import interactive as ia  # noqa: E402


def play(state, *moves):
    for i, uci in enumerate(moves):
        ia.play_move(state, uci, state["game"], f"user{i % 2}")


class ChessTests(unittest.TestCase):
    def test_legal_move_is_recorded_with_san_and_player_count(self):
        state = ia.new_game_state(1)
        self.assertEqual(ia.play_move(state, "e2e4", 1, "alice"), "e4")
        self.assertEqual(state["moves"], [{"uci": "e2e4", "san": "e4", "user": "alice"}])
        self.assertEqual(state["players"], {"alice": 1})

    def test_illegal_move_is_rejected_without_changing_state(self):
        state = ia.new_game_state(1)
        with self.assertRaises(ia.VisitorError):
            ia.play_move(state, "e2e5", 1, "alice")
        self.assertEqual(state["moves"], [])

    def test_malformed_move_is_rejected(self):
        with self.assertRaises(ia.VisitorError):
            ia.play_move(ia.new_game_state(1), "zz", 1, "alice")

    def test_same_user_cannot_move_twice_in_a_row(self):
        state = ia.new_game_state(1)
        ia.play_move(state, "e2e4", 1, "alice")
        with self.assertRaises(ia.VisitorError):
            ia.play_move(state, "e7e5", 1, "alice")

    def test_move_for_old_game_is_rejected(self):
        with self.assertRaises(ia.VisitorError):
            ia.play_move(ia.new_game_state(2), "e2e4", 1, "alice")

    def test_new_game_only_after_game_over_and_keeps_leaderboard(self):
        state = ia.new_game_state(1)
        with self.assertRaises(ia.VisitorError):
            ia.start_new_game(state)
        play(state, "f2f3", "e7e5", "g2g4", "d8h4")  # fool's mate
        self.assertTrue(ia.board_from_state(state).is_checkmate())
        with self.assertRaises(ia.VisitorError):
            ia.play_move(state, "a2a3", 1, "someone")
        fresh = ia.start_new_game(state)
        self.assertEqual((fresh["game"], fresh["moves"]), (2, []))
        self.assertEqual(fresh["players"], {"user0": 2, "user1": 2})

    def test_render_lists_every_legal_move_as_issue_link(self):
        text = ia.render_chess(ia.new_game_state(1))
        self.assertEqual(text.count("chess%7Cmove%7C"), 20)
        self.assertIn("**White** to move", text)
        self.assertIn("chess|move|g1f3|1", unquote(text))

    def test_render_is_compact_with_moves_folded(self):
        text = ia.render_chess(ia.new_game_state(1))
        self.assertIn('width="170" align="right"', text)
        self.assertLess(text.index("<details>"), text.index("chess%7Cmove%7C"))
        self.assertIn(ia.PLAY_URL, text)

    def test_render_game_over_offers_new_game(self):
        state = ia.new_game_state(1)
        play(state, "f2f3", "e7e5", "g2g4", "d8h4")
        text = ia.render_chess(state)
        self.assertIn("Black wins by checkmate", text)
        self.assertIn("chess%7Cnew", text)
        self.assertNotIn("chess%7Cmove", text)

    def test_promotion_label(self):
        import chess
        self.assertEqual(ia.move_label(chess.Move.from_uci("a7a8q")), "A8=Q")

    def test_board_svg_renders(self):
        self.assertTrue(ia.render_board_svg(ia.new_game_state(1)).startswith("<svg"))


class GuestbookTests(unittest.TestCase):
    def test_message_is_single_line_trimmed_and_escaped(self):
        cleaned = ia.clean_message("Hi <script>x</script>\n[link](http://evil) **bold**")
        self.assertNotIn("<", cleaned)
        self.assertNotIn("\n", cleaned)
        self.assertIn("\\[link\\]\\(http://evil\\)", cleaned)
        self.assertIn("\\*\\*bold\\*\\*", cleaned)

    def test_template_and_comments_are_stripped(self):
        with self.assertRaises(ia.VisitorError):
            ia.clean_message(ia.GUESTBOOK_BODY + "\n<!-- hidden -->")

    def test_message_is_capped(self):
        self.assertEqual(len(ia.clean_message("a" * 500)), ia.GUESTBOOK_MAX_CHARS)

    def test_one_entry_per_user_newest_first(self):
        entries = ia.sign_guestbook([], "alice", "one", "2026-01-01")
        entries = ia.sign_guestbook(entries, "bob", "hi", "2026-01-02")
        entries = ia.sign_guestbook(entries, "alice", "two", "2026-01-03")
        self.assertEqual([(e["user"], e["message"]) for e in entries], [("alice", "two"), ("bob", "hi")])

    def test_render_empty_and_count(self):
        self.assertIn("Be the first", ia.render_guestbook([]))
        text = ia.render_guestbook([{"user": "a", "message": "m", "date": "d"}])
        self.assertIn("1 signature ·", text)
        self.assertLess(text.index("a.png"), text.index("<details>"))
        self.assertGreater(text.index("**[@a]"), text.index("<details>"))


class HandleTests(unittest.TestCase):
    def test_unknown_title_is_a_visitor_error(self):
        with self.assertRaises(ia.VisitorError):
            ia.handle("hello", "", "alice", "2026-01-01")

    def test_replace_section_requires_markers(self):
        with self.assertRaises(ValueError):
            ia.replace_section("nothing", ia.CHESS_START, ia.CHESS_END, "x")


if __name__ == "__main__":
    unittest.main()
