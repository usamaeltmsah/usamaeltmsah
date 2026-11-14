"""Handle visitor issues for the README's community chess game and guestbook.

Visitors interact by opening a pre-filled issue. Titles look like:
    chess|move|e2e4|3   play e2e4 in game 3
    chess|new           start a new game once the current one has ended
    guestbook|sign      sign the guestbook with the issue body as the message
The workflow passes the issue through environment variables (never through
shell interpolation), this script updates state and the README, and writes the
reply that the workflow posts on the issue before closing it.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import chess
import chess.svg

REPO = "usamaeltmsah/usamaeltmsah"
DATA_DIR = Path("interactive")
CHESS_STATE = DATA_DIR / "chess.json"
BOARD_SVG = DATA_DIR / "board.svg"
GUESTBOOK_STATE = DATA_DIR / "guestbook.json"

CHESS_START, CHESS_END = "<!--CHESS:START-->", "<!--CHESS:END-->"
GUESTBOOK_START, GUESTBOOK_END = "<!--GUESTBOOK:START-->", "<!--GUESTBOOK:END-->"

GUESTBOOK_SHOWN = 10
GUESTBOOK_MAX_CHARS = 140
RECENT_MOVES_SHOWN = 5
LEADERBOARD_SHOWN = 5


class VisitorError(Exception):
    """A problem with the visitor's request, reported back on their issue."""


@dataclass(frozen=True)
class Reply:
    message: str
    changed: bool


# ---------- issue links ----------

def issue_link(title: str, body: str) -> str:
    return f"https://github.com/{REPO}/issues/new?title={quote(title, safe='')}&body={quote(body, safe='')}"


MOVE_BODY = "Just press **Create** — no need to write anything. Your move is applied within about a minute."
GUESTBOOK_BODY = "Replace this line with your message (up to 140 characters), then press **Create**."


# ---------- chess ----------

def new_game_state(game: int, players: dict[str, int] | None = None) -> dict:
    return {"game": game, "moves": [], "players": players or {}}


def board_from_state(state: dict) -> chess.Board:
    board = chess.Board()
    for move in state["moves"]:
        board.push_uci(move["uci"])
    return board


def play_move(state: dict, uci: str, game: int, user: str) -> str:
    """Apply a visitor's move to state in place and return its SAN."""
    if game != state["game"]:
        raise VisitorError(f"That move was for game {game}, but game {state['game']} is in progress now.")
    board = board_from_state(state)
    if board.is_game_over():
        raise VisitorError("This game is already over. Start a new one from the README.")
    if state["moves"] and state["moves"][-1]["user"] == user:
        raise VisitorError("You made the last move. Let someone else play the other side first!")
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        raise VisitorError(f"`{uci}` isn't a valid move.") from None
    if move not in board.legal_moves:
        raise VisitorError(f"`{uci}` isn't legal in the current position. The board may have changed; pick a move from the README.")
    san = board.san(move)
    state["moves"].append({"uci": uci, "san": san, "user": user})
    state["players"][user] = state["players"].get(user, 0) + 1
    return san


def start_new_game(state: dict) -> dict:
    if not board_from_state(state).is_game_over():
        raise VisitorError("The current game is still in progress. Finish it first!")
    return new_game_state(state["game"] + 1, state["players"])


def result_text(board: chess.Board) -> str:
    outcome = board.outcome()
    if outcome is None:
        return ""
    if outcome.winner is None:
        return f"🤝 Draw ({outcome.termination.name.replace('_', ' ').lower()})."
    winner = "White" if outcome.winner == chess.WHITE else "Black"
    return f"🏁 {winner} wins by {outcome.termination.name.lower()}!"


def move_label(move: chess.Move) -> str:
    label = chess.square_name(move.to_square).upper()
    if move.promotion:
        label += "=" + chess.piece_symbol(move.promotion).upper()
    return label


def render_moves_table(board: chess.Board, game: int) -> str:
    by_square: dict[int, list[chess.Move]] = {}
    for move in board.legal_moves:
        by_square.setdefault(move.from_square, []).append(move)
    rows = ["| Piece | Moves (click to play) |", "| :---: | :--- |"]
    for square in sorted(by_square, key=lambda s: (chess.square_file(s), chess.square_rank(s))):
        moves = sorted(by_square[square], key=lambda m: m.uci())
        links = ", ".join(
            f"[{move_label(m)}]({issue_link(f'chess|move|{m.uci()}|{game}', MOVE_BODY)})" for m in moves
        )
        piece = board.piece_at(square)
        rows.append(f"| {piece.unicode_symbol()} **{chess.square_name(square).upper()}** | {links} |")
    return "\n".join(rows)


def render_chess(state: dict) -> str:
    board = board_from_state(state)
    turn = "White" if board.turn == chess.WHITE else "Black"
    lines = [f"**Game {state['game']}** · move {board.fullmove_number}"]
    if board.is_game_over():
        lines += ["", result_text(board), "", f"[**♻️ Start a new game**]({issue_link('chess|new', MOVE_BODY)})"]
    else:
        check = " — **check!**" if board.is_check() else ""
        lines[0] += f" · it's **{turn}'s** turn{check}"
    lines += ["", '<img src="interactive/board.svg" width="360" alt="Current chess board" />', ""]
    if not board.is_game_over():
        lines += [render_moves_table(board, state["game"]), ""]
    recent = state["moves"][-RECENT_MOVES_SHOWN:][::-1]
    if recent:
        lines += ["**Last moves**", "", "| Move | Played by |", "| :---: | :--- |"]
        lines += [f"| {m['san']} | [@{m['user']}](https://github.com/{m['user']}) |" for m in recent]
        lines.append("")
    leaders = sorted(state["players"].items(), key=lambda kv: (-kv[1], kv[0]))[:LEADERBOARD_SHOWN]
    if leaders:
        lines.append("**🏆 Top players:** " + " · ".join(f"[@{u}](https://github.com/{u}) ({n})" for u, n in leaders))
    return "\n".join(lines).strip()


def render_board_svg(state: dict) -> str:
    board = board_from_state(state)
    lastmove = board.peek() if board.move_stack else None
    check = board.king(board.turn) if board.is_check() else None
    return chess.svg.board(board, size=360, lastmove=lastmove, check=check)


# ---------- guestbook ----------

def clean_message(raw: str) -> str:
    """Reduce visitor text to one short line that can't inject HTML, links or markdown."""
    text = raw.replace(GUESTBOOK_BODY, "")
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = " ".join(text.split())
    if not text:
        raise VisitorError("Your message was empty. Write something in the issue body and try again!")
    text = text[:GUESTBOOK_MAX_CHARS]
    text = html.escape(text, quote=True)
    return re.sub(r"([\\`*_{}\[\]()#+\-!|~>])", r"\\\1", text)


def sign_guestbook(entries: list[dict], user: str, message: str, when: str) -> list[dict]:
    """Return entries with the user's message first; one entry per user, newest wins."""
    others = [e for e in entries if e["user"] != user]
    return [{"user": user, "message": message, "date": when}, *others]


def render_guestbook(entries: list[dict]) -> str:
    lines = [f"[**✍️ Sign the guestbook**]({issue_link('guestbook|sign', GUESTBOOK_BODY)}) · {len(entries)} signature{'s' if len(entries) != 1 else ''} so far", ""]
    for e in entries[:GUESTBOOK_SHOWN]:
        lines.append(
            f'- <a href="https://github.com/{e["user"]}"><img src="https://github.com/{e["user"]}.png?size=40" width="20" height="20" alt="" /></a> '
            f"**[@{e['user']}](https://github.com/{e['user']})**: {e['message']} <sub>{e['date']}</sub>"
        )
    if not entries:
        lines.append("_Be the first to sign!_")
    return "\n".join(lines)


# ---------- README ----------

def replace_section(readme: str, start: str, end: str, body: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(readme):
        raise ValueError(f"README is missing the {start} ... {end} markers")
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", readme, count=1)


# ---------- entry point ----------

def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def handle(title: str, body: str, user: str, when: str) -> Reply:
    parts = title.strip().split("|")
    if parts[:2] == ["chess", "move"] and len(parts) == 4 and parts[3].isdigit():
        state = load_json(CHESS_STATE, new_game_state(1))
        san = play_move(state, parts[2].lower(), int(parts[3]), user)
        save_json(CHESS_STATE, state)
        board = board_from_state(state)
        ending = f" {result_text(board)}" if board.is_game_over() else " Ask a friend to play the next move!"
        return Reply(f"♟️ Thanks @{user}, you played **{san}**.{ending}", True)
    if parts == ["chess", "new"]:
        state = start_new_game(load_json(CHESS_STATE, new_game_state(1)))
        save_json(CHESS_STATE, state)
        return Reply(f"♻️ Game {state['game']} has started, @{user}. White to move!", True)
    if parts == ["guestbook", "sign"]:
        entries = sign_guestbook(load_json(GUESTBOOK_STATE, []), user, clean_message(body), when)
        save_json(GUESTBOOK_STATE, entries)
        return Reply(f"✍️ Thanks for signing the guestbook, @{user}! 💙", True)
    raise VisitorError("I didn't recognise that request. Use the links in the README.")


def render_all(readme_path: Path) -> None:
    state = load_json(CHESS_STATE, new_game_state(1))
    if not CHESS_STATE.exists():
        save_json(CHESS_STATE, state)
    BOARD_SVG.write_text(render_board_svg(state), encoding="utf-8")
    readme = readme_path.read_text(encoding="utf-8")
    readme = replace_section(readme, CHESS_START, CHESS_END, render_chess(state))
    readme = replace_section(readme, GUESTBOOK_START, GUESTBOOK_END, render_guestbook(load_json(GUESTBOOK_STATE, [])))
    readme_path.write_text(readme, encoding="utf-8")


def main() -> int:
    readme_path = Path(os.environ.get("README_PATH", "README.md"))
    if os.environ.get("RENDER_ONLY"):
        render_all(readme_path)
        return 0
    reply_path = Path(os.environ["REPLY_PATH"])
    try:
        reply = handle(
            os.environ["ISSUE_TITLE"],
            os.environ.get("ISSUE_BODY", ""),
            os.environ["ISSUE_USER"],
            os.environ["ISSUE_DATE"][:10],
        )
    except VisitorError as error:
        reply = Reply(f"⚠️ {error}", False)
    if reply.changed:
        render_all(readme_path)
    reply_path.write_text(reply.message + "\n", encoding="utf-8")
    print(reply.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
