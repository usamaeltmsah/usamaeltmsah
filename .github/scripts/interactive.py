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

PLAY_URL = "https://usamaeltmsah.github.io/chess/"
PLAY_BADGE = "https://img.shields.io/badge/%E2%96%B6%EF%B8%8F%20Play%20with%20drag%20and%20drop-7c3aed?style=for-the-badge"

GUESTBOOK_SHOWN = 12
GUESTBOOK_MAX_CHARS = 140
LEADERBOARD_SHOWN = 3


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


def user_link(user: str) -> str:
    return f"[@{user}](https://github.com/{user})"


def render_chess(state: dict) -> str:
    """A compact card: small board floated right, one status line, the move list folded away."""
    board = board_from_state(state)
    turn = "White" if board.turn == chess.WHITE else "Black"
    status = f"Game {state['game']} · move {board.fullmove_number}"
    if board.is_game_over():
        status += f" · {result_text(board)}"
    else:
        status += f" · **{turn}** to move{' · **check!**' if board.is_check() else ''}"
    if state["moves"]:
        last = state["moves"][-1]
        status += f" · last: **{last['san']}** by {user_link(last['user'])}"
    lines = [
        f'<a href="{PLAY_URL}"><img src="interactive/board.svg" width="170" align="right" alt="Current chess board, click to play" /></a>',
        "",
        "**♟️ Community chess:** every visitor plays the same game.",
        "",
        status,
        "",
    ]
    if board.is_game_over():
        lines += [f"[**♻️ Start a new game**]({issue_link('chess|new', MOVE_BODY)})", ""]
    else:
        lines += [f'<a href="{PLAY_URL}"><img src="{PLAY_BADGE}" alt="Play with drag and drop" /></a>', ""]
    leaders = sorted(state["players"].items(), key=lambda kv: (-kv[1], kv[0]))[:LEADERBOARD_SHOWN]
    if leaders:
        lines += ["🏆 " + " · ".join(f"{user_link(u)} ({n})" for u, n in leaders), ""]
    if not board.is_game_over():
        lines += ["<details>", "  <summary>Or pick a move from the list</summary>", "", render_moves_table(board, state["game"]), "", "</details>", ""]
    lines.append('<br clear="right" />')
    return "\n".join(lines)


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
    """One line with a row of signer avatars; the messages stay folded until someone opens them."""
    count = f"{len(entries)} signature{'s' if len(entries) != 1 else ''}"
    lines = [f"**✍️ Guestbook** · {count} · [**Sign it**]({issue_link('guestbook|sign', GUESTBOOK_BODY)})", ""]
    if not entries:
        lines.append("_Be the first to sign!_")
        return "\n".join(lines)
    shown = entries[:GUESTBOOK_SHOWN]
    lines += [
        " ".join(
            f'<a href="https://github.com/{e["user"]}"><img src="https://github.com/{e["user"]}.png?size=64" width="32" height="32" alt="@{e["user"]}" /></a>'
            for e in shown
        ),
        "",
        "<details>",
        "  <summary>Read the messages</summary>",
        "",
        *(f"- **{user_link(e['user'])}**: {e['message']} <sub>{e['date']}</sub>" for e in shown),
        "",
        "</details>",
    ]
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
