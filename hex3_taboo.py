"""Hex 3-Taboo board game prototype.

This module implements the core rules described in the README:
- A hexagonal board with a configurable radius (default 4).
- Two players alternately place stones on empty cells.
- The second player may, once per game, neutralize the opponent's last
  placement instead of placing their own stone. Neutralized stones belong to
  neither player.
- After each turn we evaluate for a winning line (length >= 4) or a losing
  line (exactly length 3). Wins take precedence over losses.

The module exposes a ``Hex3TabooGame`` class for programmatic use and offers
both a command-line and a lightweight Tkinter GUI front end.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import sys
import time
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple, Union

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except Exception:  # pragma: no cover - Tk may be unavailable on some systems
    tk = None
    messagebox = None
    ttk = None


AxialCoord = Tuple[int, int]
GameOutcome = Tuple[str, str]


@dataclass(frozen=True)
class Move:
    """Record of a single action in the game history."""

    player: int
    action: str  # "place" or "disable"
    coordinate: Optional[AxialCoord]


class HexBoard:
    """Hexagonal board represented using axial coordinates."""

    AXIAL_DIRECTIONS: Tuple[AxialCoord, ...] = ((1, 0), (0, 1), (-1, 1))
    DISABLED_STONE: int = 0

    def __init__(self, radius: int = 4) -> None:
        if radius < 1:
            raise ValueError("半径は1以上でなければなりません。")
        self.radius = radius
        self.cells: Dict[AxialCoord, Optional[int]] = {
            (q, r): None for q, r in self._generate_coordinates(radius)
        }

    @staticmethod
    def _generate_coordinates(radius: int) -> Iterable[AxialCoord]:
        for q in range(-radius, radius + 1):
            for r in range(-radius, radius + 1):
                s = -q - r
                if -radius <= s <= radius:
                    yield q, r

    def is_valid(self, coord: AxialCoord) -> bool:
        return coord in self.cells

    def get(self, coord: AxialCoord) -> Optional[int]:
        if not self.is_valid(coord):
            raise ValueError(f"座標{coord}は盤外です。")
        return self.cells[coord]

    def set(self, coord: AxialCoord, value: Optional[int]) -> None:
        if not self.is_valid(coord):
            raise ValueError(f"座標{coord}は盤外です。")
        self.cells[coord] = value

    def empty_cells(self) -> List[AxialCoord]:
        return [coord for coord, occupant in self.cells.items() if occupant is None]

    def is_full(self) -> bool:
        return all(occupant is not None for occupant in self.cells.values())

    def render(self) -> str:
        """Render the board as ASCII art using axial coordinates."""
        lines: List[str] = []
        radius = self.radius
        for r in range(-radius, radius + 1):
            indent = " " * (radius - (r + radius) // 2)
            row: List[str] = []
            for q in range(-radius, radius + 1):
                coord = (q, r)
                if coord not in self.cells:
                    continue
                occupant = self.cells[coord]
                if occupant is None:
                    token = "."
                elif occupant == HexBoard.DISABLED_STONE:
                    token = "#"
                elif occupant == 1:
                    token = "X"
                else:
                    token = "O"
                row.append(token)
            if row:
                lines.append(f"{indent}{' '.join(row)}")
        return "\n".join(lines)


class Hex3TabooGame:
    """Encapsulates the rules and state of a Hex 3-Taboo match."""

    def __init__(self, radius: int = 4) -> None:
        self.board = HexBoard(radius)
        self.current_player = 1
        self.removal_used = {1: False, 2: False}
        self.history: List[Move] = []
        self.last_placed: Dict[int, Optional[AxialCoord]] = {1: None, 2: None}
        # Tracks coordinates that a player is temporarily forbidden to occupy.
        # This is used to prevent player 1 from immediately reclaiming a stone
        # that player 2 just neutralized.
        self.forbidden_placements: Dict[int, Optional[AxialCoord]] = {1: None, 2: None}
        self.last_detected_line: List[AxialCoord] = []

    def switch_player(self) -> None:
        self.current_player = 1 if self.current_player == 2 else 2

    def place_stone(self, coord: AxialCoord) -> None:
        if not self.board.is_valid(coord):
            raise ValueError("盤外には石を置けません。")
        forbidden = self.forbidden_placements.get(self.current_player)
        if forbidden is not None and coord == forbidden:
            raise ValueError("そのマスは直前に無効化されたため、このターンには置けません。")
        if self.board.get(coord) is not None:
            raise ValueError("そのマスには既に石があります。")
        self.board.set(coord, self.current_player)
        self.history.append(Move(self.current_player, "place", coord))
        self.last_placed[self.current_player] = coord

        self.forbidden_placements[self.current_player] = None

    def can_remove(self) -> bool:
        """Return True if the current player can perform a neutralization action."""
        if self.current_player != 2:
            return False
        if self.removal_used[2]:
            return False
        last_move = self.history[-1] if self.history else None
        if not last_move or last_move.action != "place":
            return False
        if last_move.player == self.current_player:
            return False
        return True

    def remove_last_opponent_stone(self) -> AxialCoord:
        """Neutralize the opponent's last placement and return its coordinate."""
        if not self.can_remove():
            raise ValueError("無効化は現在行えません。")
        last_move = self.history[-1]
        assert last_move.coordinate is not None
        self.board.set(last_move.coordinate, HexBoard.DISABLED_STONE)
        self.history.append(Move(self.current_player, "disable", last_move.coordinate))
        self.removal_used[self.current_player] = True
        # After neutralization, the opponent no longer has this stone as their last placement.
        self.last_placed[last_move.player] = None
        # Prevent the opponent from immediately replacing the neutralized stone.
        self.forbidden_placements[last_move.player] = last_move.coordinate
        return last_move.coordinate

    def evaluate_player_state(
        self, player: int
    ) -> Tuple[bool, bool, Optional[List[AxialCoord]], Optional[List[AxialCoord]]]:
        """Return flags and coordinates for potential winning/losing lines."""
        has_win = False
        has_loss = False
        winning_line: Optional[List[AxialCoord]] = None
        losing_line: Optional[List[AxialCoord]] = None
        for coord, occupant in self.board.cells.items():
            if occupant != player:
                continue
            for direction in HexBoard.AXIAL_DIRECTIONS:
                opposite = (-direction[0], -direction[1])
                prev_coord = (coord[0] + opposite[0], coord[1] + opposite[1])
                if self.board.cells.get(prev_coord) == player:
                    # This line will be considered when iterating its starting cell.
                    continue
                length = 0
                coords: List[AxialCoord] = []
                cursor = coord
                while self.board.cells.get(cursor) == player:
                    length += 1
                    coords.append(cursor)
                    cursor = (cursor[0] + direction[0], cursor[1] + direction[1])
                end_coord = cursor
                # Determine whether the line is bounded by non-player stones/off-board.
                next_occupant = self.board.cells.get(end_coord)
                start_occupant = self.board.cells.get(prev_coord)
                if length >= 4:
                    has_win = True
                    if winning_line is None:
                        winning_line = coords.copy()
                elif (
                    length == 3
                    and start_occupant != player
                    and next_occupant != player
                ):
                    has_loss = True
                    if losing_line is None:
                        losing_line = coords.copy()
            if has_win and has_loss:
                break
        return has_win, has_loss, winning_line, losing_line

    def check_game_end(self) -> Optional[GameOutcome]:
        """Evaluate the board and return (outcome, message) if the game is over."""
        has_win, has_loss, winning_line, losing_line = self.evaluate_player_state(
            self.current_player
        )
        self.last_detected_line = []
        if has_win and winning_line:
            self.last_detected_line = winning_line.copy()
            return (
                "win",
                f"プレイヤー{self.current_player}が4つ以上の連結で勝利しました。",
            )
        if has_loss and losing_line:
            self.last_detected_line = losing_line.copy()
            return (
                "loss",
                f"プレイヤー{self.current_player}は孤立した3連で敗北しました。",
            )
        if self.board.is_full():
            return "draw", "ボードが埋まりました。引き分けです。"
        return None

    def take_turn(self, command: str) -> Optional[GameOutcome]:
        """Process a command for the current player and return an end-state message."""
        parts = command.strip().split()
        if not parts:
            raise ValueError("コマンドが入力されていません。")
        action = parts[0].lower()
        if action == "place":
            if len(parts) != 3:
                raise ValueError("使い方: place <q> <r>")
            q, r = int(parts[1]), int(parts[2])
            self.place_stone((q, r))
        elif action == "remove":
            if len(parts) != 1:
                raise ValueError("使い方: remove")
            self.remove_last_opponent_stone()
        else:
            raise ValueError("不明なコマンドです。'place q r' または 'remove'（無効化）を入力してください。")

        result = self.check_game_end()
        if result is not None:
            return result
        self.switch_player()
        return None

    def format_prompt(self) -> str:
        if self.current_player == 2 and self.can_remove():
            return "プレイヤー2（O） - 'place q r' または 'remove'（無効化）を入力してください: "
        token = "X" if self.current_player == 1 else "O"
        return f"プレイヤー{self.current_player}（{token}） - 'place q r' を入力してください: "


class Tween:
    """Simple tween helper class for Tkinter animations."""

    def __init__(
        self,
        widget: "tk.Misc",
        duration_ms: int,
        update: Callable[[float], None],
        easing: Optional[Callable[[float], float]] = None,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        self.widget = widget
        self.duration_ms = max(1, duration_ms)
        self.update = update
        self.easing = easing
        self.on_complete = on_complete
        self._start_time = 0.0
        self._cancelled = False

    def start(self) -> None:
        self._start_time = time.perf_counter()
        self._step()

    def cancel(self) -> None:
        self._cancelled = True

    def _step(self) -> None:
        if self._cancelled:
            return
        elapsed_ms = (time.perf_counter() - self._start_time) * 1000.0
        progress = min(1.0, elapsed_ms / self.duration_ms)
        eased = self.easing(progress) if self.easing else progress
        self.update(eased)
        if progress >= 1.0:
            if self.on_complete:
                self.on_complete()
            return
        self.widget.after(16, self._step)


def ease_out_quad(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def ease_out_cubic(t: float) -> float:
    return 1 - pow(1 - t, 3)


def ease_in_out_quad(t: float) -> float:
    return 2 * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 2) / 2


def ease_out_bounce(t: float) -> float:
    n1 = 7.5625
    d1 = 2.75
    if t < 1 / d1:
        return n1 * t * t
    elif t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    elif t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625 / d1
        return n1 * t * t + 0.984375


@dataclass
class Theme:
    """Color theme definition for the GUI."""
    name: str
    # Window
    window_bg: str
    # Board
    board_bg_top: str
    board_bg_bottom: str
    board_border: str
    # Cells
    cell_base: str
    cell_accent: str
    cell_edge: str
    # Players
    player1_color: str
    player1_outline: str
    player1_glow: str
    player2_color: str
    player2_outline: str
    player2_glow: str
    # Other
    disabled_stone: str
    disabled_outline: str
    empty_stone: str
    hover_outline: str
    shadow_color: str
    coord_text: str
    # UI Elements
    text_primary: str
    text_secondary: str
    text_accent: str
    panel_bg: str
    panel_border: str
    button_bg: str
    button_fg: str
    button_hover: str
    button_active: str
    button_border: str
    highlight_color: str
    success_color: str
    warning_color: str
    error_color: str


THEMES: Dict[str, Theme] = {
    "light": Theme(
        name="ライト",
        window_bg="#f0f4f8",
        board_bg_top="#f3f7ff",
        board_bg_bottom="#dce6f6",
        board_border="#9fb0c9",
        cell_base="#fefefe",
        cell_accent="#e1e9f5",
        cell_edge="#9da7b7",
        player1_color="#e63946",
        player1_outline="#7e1b26",
        player1_glow="#ffcdd2",
        player2_color="#457b9d",
        player2_outline="#1d3557",
        player2_glow="#bbdefb",
        disabled_stone="#aab0bc",
        disabled_outline="#5b626f",
        empty_stone="#f5f5f5",
        hover_outline="#ffb347",
        shadow_color="#2a2e45",
        coord_text="#6f7d95",
        text_primary="#1d3557",
        text_secondary="#457b9d",
        text_accent="#e63946",
        panel_bg="#ffffff",
        panel_border="#e0e4e8",
        button_bg="#457b9d",
        button_fg="#ffffff",
        button_hover="#1d3557",
        button_active="#e63946",
        button_border="#1d3557",
        highlight_color="#ffd166",
        success_color="#06d6a0",
        warning_color="#ffd166",
        error_color="#ef476f",
    ),
    "dark": Theme(
        name="ダーク",
        window_bg="#1a1d23",
        board_bg_top="#252830",
        board_bg_bottom="#1e2127",
        board_border="#3d4250",
        cell_base="#2d323c",
        cell_accent="#363c4a",
        cell_edge="#4a5260",
        player1_color="#ff6b6b",
        player1_outline="#c92a2a",
        player1_glow="#ff8787",
        player2_color="#4dabf7",
        player2_outline="#1971c2",
        player2_glow="#74c0fc",
        disabled_stone="#495057",
        disabled_outline="#343a40",
        empty_stone="#343a40",
        hover_outline="#fcc419",
        shadow_color="#0d0e10",
        coord_text="#868e96",
        text_primary="#f8f9fa",
        text_secondary="#adb5bd",
        text_accent="#fcc419",
        panel_bg="#252830",
        panel_border="#3d4250",
        button_bg="#4dabf7",
        button_fg="#1a1d23",
        button_hover="#74c0fc",
        button_active="#ff6b6b",
        button_border="#1971c2",
        highlight_color="#fcc419",
        success_color="#51cf66",
        warning_color="#fcc419",
        error_color="#ff6b6b",
    ),
    "ocean": Theme(
        name="オーシャン",
        window_bg="#0a192f",
        board_bg_top="#112240",
        board_bg_bottom="#0a192f",
        board_border="#233554",
        cell_base="#172a45",
        cell_accent="#1f3a5f",
        cell_edge="#233554",
        player1_color="#f07178",
        player1_outline="#c92a2a",
        player1_glow="#ff8a80",
        player2_color="#64ffda",
        player2_outline="#00bfa5",
        player2_glow="#a7ffeb",
        disabled_stone="#495670",
        disabled_outline="#3d5175",
        empty_stone="#233554",
        hover_outline="#ffd54f",
        shadow_color="#020c1b",
        coord_text="#8892b0",
        text_primary="#ccd6f6",
        text_secondary="#8892b0",
        text_accent="#64ffda",
        panel_bg="#112240",
        panel_border="#233554",
        button_bg="#64ffda",
        button_fg="#0a192f",
        button_hover="#a7ffeb",
        button_active="#f07178",
        button_border="#00bfa5",
        highlight_color="#ffd54f",
        success_color="#64ffda",
        warning_color="#ffd54f",
        error_color="#f07178",
    ),
}


@dataclass
class GameStats:
    """Statistics tracking for games played."""
    player1_wins: int = 0
    player2_wins: int = 0
    draws: int = 0
    total_games: int = 0
    current_streak: int = 0
    streak_player: int = 0

    def record_result(self, outcome: str, player: int) -> None:
        self.total_games += 1
        if outcome == "win":
            if player == 1:
                self.player1_wins += 1
            else:
                self.player2_wins += 1
            if self.streak_player == player:
                self.current_streak += 1
            else:
                self.streak_player = player
                self.current_streak = 1
        elif outcome == "loss":
            # Loss means the other player wins
            other = 2 if player == 1 else 1
            if other == 1:
                self.player1_wins += 1
            else:
                self.player2_wins += 1
            if self.streak_player == other:
                self.current_streak += 1
            else:
                self.streak_player = other
                self.current_streak = 1
        else:
            self.draws += 1
            self.current_streak = 0
            self.streak_player = 0


class AIPlayer:
    """AI player for Hex 3-Taboo with multiple difficulty levels."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

    def __init__(self, difficulty: str = "medium", player_id: int = 2) -> None:
        if difficulty not in (self.EASY, self.MEDIUM, self.HARD):
            raise ValueError(f"無効な難易度: {difficulty}")
        self.difficulty = difficulty
        self.player_id = player_id
        self._max_depth = {self.EASY: 1, self.MEDIUM: 2, self.HARD: 4}[difficulty]

    def get_difficulty_name(self) -> str:
        names = {self.EASY: "かんたん", self.MEDIUM: "ふつう", self.HARD: "むずかしい"}
        return names[self.difficulty]

    def choose_action(self, game: "Hex3TabooGame") -> Tuple[str, Optional[AxialCoord]]:
        """Choose the best action for the current game state.

        Returns: ("place", coord) or ("remove", None)
        """
        if self.difficulty == self.EASY:
            return self._choose_easy(game)
        elif self.difficulty == self.MEDIUM:
            return self._choose_medium(game)
        else:
            return self._choose_hard(game)

    def _choose_easy(self, game: "Hex3TabooGame") -> Tuple[str, Optional[AxialCoord]]:
        """Random move selection."""
        empty = game.board.empty_cells()
        forbidden = game.forbidden_placements.get(game.current_player)
        valid = [c for c in empty if c != forbidden]
        if valid:
            return ("place", random.choice(valid))
        return ("place", None)

    def _choose_medium(self, game: "Hex3TabooGame") -> Tuple[str, Optional[AxialCoord]]:
        """Basic strategy: block wins, seek wins, avoid losses."""
        empty = game.board.empty_cells()
        forbidden = game.forbidden_placements.get(game.current_player)
        valid = [c for c in empty if c != forbidden]

        if not valid:
            return ("place", None)

        opponent = 1 if self.player_id == 2 else 2

        # Check for immediate win
        for coord in valid:
            if self._would_win(game, coord, self.player_id):
                return ("place", coord)

        # Block opponent's win
        for coord in valid:
            if self._would_win(game, coord, opponent):
                return ("place", coord)

        # Avoid creating isolated 3-line (loss)
        safe_moves = [c for c in valid if not self._would_lose(game, c, self.player_id)]

        # Consider neutralization
        if game.current_player == 2 and game.can_remove():
            if self._should_neutralize(game):
                return ("remove", None)

        # Prefer center positions
        if safe_moves:
            return ("place", self._pick_strategic(game, safe_moves))

        # If all moves cause loss, pick random
        return ("place", random.choice(valid))

    def _choose_hard(self, game: "Hex3TabooGame") -> Tuple[str, Optional[AxialCoord]]:
        """Minimax with alpha-beta pruning."""
        empty = game.board.empty_cells()
        forbidden = game.forbidden_placements.get(game.current_player)
        valid = [c for c in empty if c != forbidden]

        if not valid:
            return ("place", None)

        best_score = float("-inf")
        best_move: Optional[AxialCoord] = None
        alpha = float("-inf")
        beta = float("inf")

        # Consider neutralization first
        if game.current_player == 2 and game.can_remove():
            neutralize_score = self._evaluate_neutralization(game)
            if neutralize_score > 500:
                return ("remove", None)

        # Sort moves by heuristic for better pruning
        scored_moves = [(c, self._quick_eval(game, c)) for c in valid]
        scored_moves.sort(key=lambda x: x[1], reverse=True)

        for coord, _ in scored_moves:
            score = self._minimax(game, coord, self._max_depth, alpha, beta, False)
            if score > best_score:
                best_score = score
                best_move = coord
            alpha = max(alpha, score)
            if beta <= alpha:
                break

        return ("place", best_move if best_move else random.choice(valid))

    def _minimax(
        self,
        game: "Hex3TabooGame",
        move: AxialCoord,
        depth: int,
        alpha: float,
        beta: float,
        is_maximizing: bool,
    ) -> float:
        """Minimax algorithm with alpha-beta pruning."""
        # Simulate move
        original_cell = game.board.cells[move]
        current = game.current_player
        game.board.set(move, current)

        # Check terminal state
        has_win, has_loss, _, _ = game.evaluate_player_state(current)

        if has_win:
            game.board.set(move, original_cell)
            return 10000 if current == self.player_id else -10000

        if has_loss:
            game.board.set(move, original_cell)
            return -10000 if current == self.player_id else 10000

        if depth == 0 or game.board.is_full():
            score = self._evaluate_board(game)
            game.board.set(move, original_cell)
            return score

        # Get valid moves for next player
        next_player = 1 if current == 2 else 2
        empty = game.board.empty_cells()
        forbidden = game.forbidden_placements.get(next_player)
        valid_moves = [c for c in empty if c != forbidden]

        if not valid_moves:
            game.board.set(move, original_cell)
            return self._evaluate_board(game)

        # Switch player for simulation
        game.current_player = next_player

        if is_maximizing:
            max_eval = float("-inf")
            for next_move in valid_moves[:10]:  # Limit branching
                eval_score = self._minimax(game, next_move, depth - 1, alpha, beta, False)
                max_eval = max(max_eval, eval_score)
                alpha = max(alpha, eval_score)
                if beta <= alpha:
                    break
            game.board.set(move, original_cell)
            game.current_player = current
            return max_eval
        else:
            min_eval = float("inf")
            for next_move in valid_moves[:10]:  # Limit branching
                eval_score = self._minimax(game, next_move, depth - 1, alpha, beta, True)
                min_eval = min(min_eval, eval_score)
                beta = min(beta, eval_score)
                if beta <= alpha:
                    break
            game.board.set(move, original_cell)
            game.current_player = current
            return min_eval

    def _evaluate_board(self, game: "Hex3TabooGame") -> float:
        """Evaluate board position for the AI player."""
        score = 0.0
        opponent = 1 if self.player_id == 2 else 2

        for coord, occupant in game.board.cells.items():
            if occupant is None or occupant == HexBoard.DISABLED_STONE:
                continue

            for direction in HexBoard.AXIAL_DIRECTIONS:
                line_length, open_ends = self._count_line(game, coord, direction, occupant)

                if occupant == self.player_id:
                    if line_length >= 4:
                        score += 1000
                    elif line_length == 3:
                        if open_ends == 0:
                            score -= 500  # Isolated 3 = loss risk
                        elif open_ends >= 1:
                            score += 100  # Potential win
                    elif line_length == 2 and open_ends >= 1:
                        score += 20
                else:  # Opponent
                    if line_length >= 4:
                        score -= 1000
                    elif line_length == 3:
                        if open_ends == 0:
                            score += 500  # Opponent's loss = good
                        elif open_ends >= 1:
                            score -= 100  # Block this
                    elif line_length == 2 and open_ends >= 1:
                        score -= 20

        # Prefer center positions
        for coord, occupant in game.board.cells.items():
            if occupant == self.player_id:
                dist = abs(coord[0]) + abs(coord[1]) + abs(-coord[0] - coord[1])
                score += max(0, 10 - dist)
            elif occupant == opponent:
                dist = abs(coord[0]) + abs(coord[1]) + abs(-coord[0] - coord[1])
                score -= max(0, 5 - dist)

        return score

    def _count_line(
        self, game: "Hex3TabooGame", start: AxialCoord, direction: AxialCoord, player: int
    ) -> Tuple[int, int]:
        """Count consecutive stones and open ends for a line."""
        opposite = (-direction[0], -direction[1])
        prev = (start[0] + opposite[0], start[1] + opposite[1])

        # Only count from line start
        if game.board.cells.get(prev) == player:
            return 0, 0

        length = 0
        cursor = start
        while game.board.cells.get(cursor) == player:
            length += 1
            cursor = (cursor[0] + direction[0], cursor[1] + direction[1])

        # Count open ends
        open_ends = 0
        end_occupant = game.board.cells.get(cursor)
        start_occupant = game.board.cells.get(prev)

        if end_occupant is None:
            open_ends += 1
        if start_occupant is None:
            open_ends += 1

        return length, open_ends

    def _would_win(self, game: "Hex3TabooGame", coord: AxialCoord, player: int) -> bool:
        """Check if placing at coord would create a winning line."""
        original = game.board.cells[coord]
        game.board.set(coord, player)

        for direction in HexBoard.AXIAL_DIRECTIONS:
            length = 1
            # Check forward
            cursor = (coord[0] + direction[0], coord[1] + direction[1])
            while game.board.cells.get(cursor) == player:
                length += 1
                cursor = (cursor[0] + direction[0], cursor[1] + direction[1])
            # Check backward
            opposite = (-direction[0], -direction[1])
            cursor = (coord[0] + opposite[0], coord[1] + opposite[1])
            while game.board.cells.get(cursor) == player:
                length += 1
                cursor = (cursor[0] + opposite[0], cursor[1] + opposite[1])

            if length >= 4:
                game.board.set(coord, original)
                return True

        game.board.set(coord, original)
        return False

    def _would_lose(self, game: "Hex3TabooGame", coord: AxialCoord, player: int) -> bool:
        """Check if placing at coord would create an isolated 3-line (loss)."""
        original = game.board.cells[coord]
        game.board.set(coord, player)

        for direction in HexBoard.AXIAL_DIRECTIONS:
            length = 1
            coords_in_line = [coord]

            # Check forward
            cursor = (coord[0] + direction[0], coord[1] + direction[1])
            while game.board.cells.get(cursor) == player:
                length += 1
                coords_in_line.append(cursor)
                cursor = (cursor[0] + direction[0], cursor[1] + direction[1])
            end_coord = cursor

            # Check backward
            opposite = (-direction[0], -direction[1])
            cursor = (coord[0] + opposite[0], coord[1] + opposite[1])
            while game.board.cells.get(cursor) == player:
                length += 1
                coords_in_line.insert(0, cursor)
                cursor = (cursor[0] + opposite[0], cursor[1] + opposite[1])
            start_coord = cursor

            # Check for isolated 3-line
            if length == 3:
                start_occupant = game.board.cells.get(start_coord)
                end_occupant = game.board.cells.get(end_coord)
                if start_occupant != player and end_occupant != player:
                    # But not if it's also part of a 4+ line
                    is_part_of_longer = False
                    for c in coords_in_line:
                        for d in HexBoard.AXIAL_DIRECTIONS:
                            if d == direction or d == opposite:
                                continue
                            test_length = 1
                            tc = (c[0] + d[0], c[1] + d[1])
                            while game.board.cells.get(tc) == player:
                                test_length += 1
                                tc = (tc[0] + d[0], tc[1] + d[1])
                            opp_d = (-d[0], -d[1])
                            tc = (c[0] + opp_d[0], c[1] + opp_d[1])
                            while game.board.cells.get(tc) == player:
                                test_length += 1
                                tc = (tc[0] + opp_d[0], tc[1] + opp_d[1])
                            if test_length >= 4:
                                is_part_of_longer = True
                                break
                        if is_part_of_longer:
                            break

                    if not is_part_of_longer:
                        game.board.set(coord, original)
                        return True

        game.board.set(coord, original)
        return False

    def _should_neutralize(self, game: "Hex3TabooGame") -> bool:
        """Determine if neutralization is a good move."""
        if not game.history:
            return False

        last_move = game.history[-1]
        if last_move.action != "place" or last_move.coordinate is None:
            return False

        coord = last_move.coordinate
        opponent = last_move.player

        # Check if opponent's last move created a strong position
        for direction in HexBoard.AXIAL_DIRECTIONS:
            length = 1
            cursor = (coord[0] + direction[0], coord[1] + direction[1])
            while game.board.cells.get(cursor) == opponent:
                length += 1
                cursor = (cursor[0] + direction[0], cursor[1] + direction[1])
            opposite = (-direction[0], -direction[1])
            cursor = (coord[0] + opposite[0], coord[1] + opposite[1])
            while game.board.cells.get(cursor) == opponent:
                length += 1
                cursor = (cursor[0] + opposite[0], cursor[1] + opposite[1])

            if length >= 3:
                return True

        return False

    def _evaluate_neutralization(self, game: "Hex3TabooGame") -> float:
        """Evaluate how valuable neutralization would be."""
        if not game.history:
            return 0

        last_move = game.history[-1]
        if last_move.action != "place" or last_move.coordinate is None:
            return 0

        coord = last_move.coordinate
        opponent = last_move.player
        score = 0.0

        for direction in HexBoard.AXIAL_DIRECTIONS:
            length = 1
            cursor = (coord[0] + direction[0], coord[1] + direction[1])
            while game.board.cells.get(cursor) == opponent:
                length += 1
                cursor = (cursor[0] + direction[0], cursor[1] + direction[1])
            opposite = (-direction[0], -direction[1])
            cursor = (coord[0] + opposite[0], coord[1] + opposite[1])
            while game.board.cells.get(cursor) == opponent:
                length += 1
                cursor = (cursor[0] + opposite[0], cursor[1] + opposite[1])

            if length >= 4:
                score += 1000  # Block a win
            elif length == 3:
                score += 300

        return score

    def _pick_strategic(self, game: "Hex3TabooGame", valid: List[AxialCoord]) -> AxialCoord:
        """Pick a strategically good position."""
        scored = [(c, self._quick_eval(game, c)) for c in valid]
        scored.sort(key=lambda x: x[1], reverse=True)
        # Add some randomness among top choices
        top = [c for c, s in scored[:3]]
        return random.choice(top) if top else valid[0]

    def _quick_eval(self, game: "Hex3TabooGame", coord: AxialCoord) -> float:
        """Quick heuristic evaluation for move ordering."""
        score = 0.0
        # Prefer center
        dist = abs(coord[0]) + abs(coord[1]) + abs(-coord[0] - coord[1])
        score += max(0, 20 - dist * 2)

        # Check adjacent stones
        for direction in HexBoard.AXIAL_DIRECTIONS:
            adj = (coord[0] + direction[0], coord[1] + direction[1])
            opp = (coord[0] - direction[0], coord[1] - direction[1])
            if game.board.cells.get(adj) == self.player_id:
                score += 10
            if game.board.cells.get(opp) == self.player_id:
                score += 10

        return score


@dataclass
class Particle:
    """Particle for celebration effects."""
    x: float
    y: float
    vx: float
    vy: float
    color: str
    size: float
    life: float
    max_life: float
    shape: str = "circle"  # circle, star, hexagon


class ParticleSystem:
    """Manages particle effects for celebrations."""

    def __init__(self, canvas: "tk.Canvas") -> None:
        self.canvas = canvas
        self.particles: List[Particle] = []
        self._particle_items: Dict[int, int] = {}  # particle index -> canvas item
        self._running = False
        self._gravity = 0.15
        self._friction = 0.99

    def emit_burst(
        self,
        x: float,
        y: float,
        count: int = 50,
        colors: Optional[List[str]] = None,
        spread: float = 8.0,
    ) -> None:
        if colors is None:
            colors = ["#ffd700", "#ff6b6b", "#4dabf7", "#51cf66", "#cc5de8"]

        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(2, spread)
            particle = Particle(
                x=x,
                y=y,
                vx=math.cos(angle) * speed,
                vy=math.sin(angle) * speed - random.uniform(2, 5),
                color=random.choice(colors),
                size=random.uniform(3, 8),
                life=1.0,
                max_life=1.0,
                shape=random.choice(["circle", "star"]),
            )
            self.particles.append(particle)

        if not self._running:
            self._running = True
            self._animate()

    def emit_confetti(
        self,
        width: int,
        height: int,
        count: int = 100,
        colors: Optional[List[str]] = None,
    ) -> None:
        if colors is None:
            colors = ["#ffd700", "#ff6b6b", "#4dabf7", "#51cf66", "#cc5de8", "#fcc419"]

        for _ in range(count):
            particle = Particle(
                x=random.uniform(0, width),
                y=random.uniform(-50, -10),
                vx=random.uniform(-1, 1),
                vy=random.uniform(1, 3),
                color=random.choice(colors),
                size=random.uniform(4, 10),
                life=1.0,
                max_life=1.0,
                shape=random.choice(["circle", "star", "hexagon"]),
            )
            self.particles.append(particle)

        if not self._running:
            self._running = True
            self._animate()

    def clear(self) -> None:
        self._running = False
        for item_id in self._particle_items.values():
            self.canvas.delete(item_id)
        self._particle_items.clear()
        self.particles.clear()

    def _animate(self) -> None:
        if not self._running or not self.particles:
            self._running = False
            return

        # Update and draw particles
        alive_particles: List[Particle] = []
        new_items: Dict[int, int] = {}

        for i, p in enumerate(self.particles):
            # Update physics
            p.vy += self._gravity
            p.vx *= self._friction
            p.x += p.vx
            p.y += p.vy
            p.life -= 0.02

            if p.life > 0:
                alive_particles.append(p)
                alpha = max(0, min(1, p.life))
                size = p.size * alpha

                # Get or create canvas item
                old_item = self._particle_items.get(i)
                if old_item:
                    self.canvas.delete(old_item)

                if size > 0.5:
                    item = self._draw_particle(p, size, alpha)
                    new_items[len(alive_particles) - 1] = item
            else:
                old_item = self._particle_items.get(i)
                if old_item:
                    self.canvas.delete(old_item)

        self._particle_items = new_items
        self.particles = alive_particles

        if self.particles:
            self.canvas.after(16, self._animate)
        else:
            self._running = False

    def _draw_particle(self, p: Particle, size: float, alpha: float) -> int:
        if p.shape == "star":
            return self._draw_star(p.x, p.y, size, p.color)
        elif p.shape == "hexagon":
            return self._draw_hexagon(p.x, p.y, size, p.color)
        else:
            return self.canvas.create_oval(
                p.x - size, p.y - size, p.x + size, p.y + size,
                fill=p.color, outline=""
            )

    def _draw_star(self, x: float, y: float, size: float, color: str) -> int:
        points = []
        for i in range(10):
            angle = math.pi / 2 + i * math.pi / 5
            r = size if i % 2 == 0 else size * 0.4
            points.extend([x + r * math.cos(angle), y - r * math.sin(angle)])
        return self.canvas.create_polygon(points, fill=color, outline="")

    def _draw_hexagon(self, x: float, y: float, size: float, color: str) -> int:
        points = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            points.extend([x + size * math.cos(angle), y + size * math.sin(angle)])
        return self.canvas.create_polygon(points, fill=color, outline="")


class Tooltip:
    """Tooltip widget for hover information."""

    def __init__(self, widget: "tk.Widget", text: str, theme: Theme) -> None:
        self.widget = widget
        self.text = text
        self.theme = theme
        self.tooltip_window: Optional["tk.Toplevel"] = None
        self._after_id: Optional[str] = None

        widget.bind("<Enter>", self._schedule_show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<Button>", self._hide)

    def update_text(self, text: str) -> None:
        self.text = text
        if self.tooltip_window:
            for child in self.tooltip_window.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(text=text)

    def _schedule_show(self, event: "tk.Event") -> None:
        self._after_id = self.widget.after(500, self._show)

    def _show(self) -> None:
        if self.tooltip_window:
            return

        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        frame = tk.Frame(
            self.tooltip_window,
            bg=self.theme.panel_bg,
            relief="solid",
            borderwidth=1,
        )
        frame.pack()

        label = tk.Label(
            frame,
            text=self.text,
            bg=self.theme.panel_bg,
            fg=self.theme.text_primary,
            font=("Helvetica", 10),
            padx=8,
            pady=4,
        )
        label.pack()

    def _hide(self, event: Optional["tk.Event"] = None) -> None:
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


# GUI widget classes that inherit from Tkinter require tk to be available
_TkCanvasBase = tk.Canvas if tk is not None else object
_TkFrameBase = tk.Frame if tk is not None else object
_TkToplevelBase = tk.Toplevel if tk is not None else object


class StyledButton(_TkCanvasBase):  # type: ignore[misc]
    """Custom styled button with hover effects and rounded corners."""

    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        theme: Theme,
        command: Optional[Callable[[], None]] = None,
        width: int = 160,
        height: int = 40,
        icon: Optional[str] = None,
        style: str = "primary",  # primary, secondary, danger
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=theme.panel_bg,
            highlightthickness=0,
        )
        self.theme = theme
        self.text = text
        self.command = command
        self._width = width
        self._height = height
        self.icon = icon
        self.style = style
        self._state = "normal"
        self._hovered = False

        self._colors = self._get_style_colors()
        self._draw()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _get_style_colors(self) -> Dict[str, str]:
        if self.style == "danger":
            return {
                "bg": self.theme.error_color,
                "fg": "#ffffff",
                "hover": self.theme.warning_color,
                "border": self.theme.error_color,
            }
        elif self.style == "secondary":
            return {
                "bg": self.theme.panel_bg,
                "fg": self.theme.text_primary,
                "hover": self.theme.cell_accent,
                "border": self.theme.panel_border,
            }
        else:  # primary
            return {
                "bg": self.theme.button_bg,
                "fg": self.theme.button_fg,
                "hover": self.theme.button_hover,
                "border": self.theme.button_border,
            }

    def _draw(self) -> None:
        self.delete("all")

        radius = 8
        color = self._colors["hover"] if self._hovered else self._colors["bg"]
        if self._state == "disabled":
            color = self.theme.disabled_stone

        # Draw rounded rectangle
        self._draw_rounded_rect(2, 2, self._width - 2, self._height - 2, radius, color)

        # Draw border
        self._draw_rounded_rect_outline(
            2, 2, self._width - 2, self._height - 2, radius,
            self._colors["border"] if self._state != "disabled" else self.theme.disabled_outline
        )

        # Draw text
        text_color = self._colors["fg"] if self._state != "disabled" else self.theme.coord_text
        display_text = self.icon + " " + self.text if self.icon else self.text
        self.create_text(
            self._width // 2,
            self._height // 2,
            text=display_text,
            fill=text_color,
            font=("Helvetica", 11, "bold"),
        )

    def _draw_rounded_rect(
        self, x1: float, y1: float, x2: float, y2: float, radius: float, color: str
    ) -> None:
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
            x1 + radius, y1,
        ]
        self.create_polygon(points, fill=color, outline="", smooth=True)

    def _draw_rounded_rect_outline(
        self, x1: float, y1: float, x2: float, y2: float, radius: float, color: str
    ) -> None:
        # Top
        self.create_line(x1 + radius, y1, x2 - radius, y1, fill=color, width=2)
        # Right
        self.create_line(x2, y1 + radius, x2, y2 - radius, fill=color, width=2)
        # Bottom
        self.create_line(x2 - radius, y2, x1 + radius, y2, fill=color, width=2)
        # Left
        self.create_line(x1, y2 - radius, x1, y1 + radius, fill=color, width=2)
        # Corners (arcs)
        self.create_arc(x1, y1, x1 + 2*radius, y1 + 2*radius, start=90, extent=90, style="arc", outline=color, width=2)
        self.create_arc(x2 - 2*radius, y1, x2, y1 + 2*radius, start=0, extent=90, style="arc", outline=color, width=2)
        self.create_arc(x2 - 2*radius, y2 - 2*radius, x2, y2, start=270, extent=90, style="arc", outline=color, width=2)
        self.create_arc(x1, y2 - 2*radius, x1 + 2*radius, y2, start=180, extent=90, style="arc", outline=color, width=2)

    def _on_enter(self, event: tk.Event) -> None:
        if self._state != "disabled":
            self._hovered = True
            self._draw()
            self.config(cursor="hand2")

    def _on_leave(self, event: tk.Event) -> None:
        self._hovered = False
        self._draw()
        self.config(cursor="")

    def _on_click(self, event: tk.Event) -> None:
        if self._state != "disabled" and self.command:
            self._colors["bg"], self._colors["hover"] = self._colors["hover"], self._colors["bg"]
            self._draw()

    def _on_release(self, event: tk.Event) -> None:
        if self._state != "disabled":
            self._colors["bg"], self._colors["hover"] = self._colors["hover"], self._colors["bg"]
            self._draw()
            if self.command:
                self.command()

    def set_state(self, state: str) -> None:
        self._state = state
        self._draw()

    def update_theme(self, theme: Theme) -> None:
        self.theme = theme
        self._colors = self._get_style_colors()
        self.config(bg=theme.panel_bg)
        self._draw()


class PlayerPanel(_TkFrameBase):  # type: ignore[misc]
    """Panel showing player information and turn status."""

    def __init__(
        self,
        parent: tk.Widget,
        player: int,
        theme: Theme,
        player_name: str = "",
    ) -> None:
        super().__init__(parent, bg=theme.panel_bg, padx=15, pady=15)
        self.player = player
        self.theme = theme
        self.player_name = player_name or f"プレイヤー {player}"
        self._is_active = False
        self._stone_count = 0
        self._can_neutralize = False

        self._create_widgets()

    def _create_widgets(self) -> None:
        # Player indicator (colored circle)
        self.indicator_canvas = tk.Canvas(
            self, width=50, height=50, bg=self.theme.panel_bg, highlightthickness=0
        )
        self.indicator_canvas.pack(pady=(0, 10))
        self._draw_indicator()

        # Player name
        self.name_label = tk.Label(
            self,
            text=self.player_name,
            font=("Helvetica", 14, "bold"),
            bg=self.theme.panel_bg,
            fg=self.theme.text_primary,
        )
        self.name_label.pack()

        # Symbol
        symbol = "X" if self.player == 1 else "O"
        self.symbol_label = tk.Label(
            self,
            text=f"（{symbol}）",
            font=("Helvetica", 12),
            bg=self.theme.panel_bg,
            fg=self.theme.text_secondary,
        )
        self.symbol_label.pack()

        # Stone count
        self.count_label = tk.Label(
            self,
            text="石: 0",
            font=("Helvetica", 11),
            bg=self.theme.panel_bg,
            fg=self.theme.text_secondary,
        )
        self.count_label.pack(pady=(10, 0))

        # Turn indicator
        self.turn_frame = tk.Frame(self, bg=self.theme.panel_bg)
        self.turn_frame.pack(pady=(10, 0))

        self.turn_label = tk.Label(
            self.turn_frame,
            text="",
            font=("Helvetica", 10, "bold"),
            bg=self.theme.panel_bg,
            fg=self.theme.success_color,
        )
        self.turn_label.pack()

        # Neutralize indicator (for player 2)
        if self.player == 2:
            self.neutralize_label = tk.Label(
                self,
                text="",
                font=("Helvetica", 9),
                bg=self.theme.panel_bg,
                fg=self.theme.text_accent,
            )
            self.neutralize_label.pack(pady=(5, 0))

    def _draw_indicator(self) -> None:
        self.indicator_canvas.delete("all")
        cx, cy = 25, 25
        radius = 20

        # Get player color
        if self.player == 1:
            color = self.theme.player1_color
            outline = self.theme.player1_outline
            glow = self.theme.player1_glow
        else:
            color = self.theme.player2_color
            outline = self.theme.player2_outline
            glow = self.theme.player2_glow

        # Draw glow if active
        if self._is_active:
            for i in range(3):
                glow_radius = radius + 8 - i * 2
                alpha_hex = hex(int(80 - i * 20))[2:].zfill(2)
                self.indicator_canvas.create_oval(
                    cx - glow_radius, cy - glow_radius,
                    cx + glow_radius, cy + glow_radius,
                    fill=glow, outline=""
                )

        # Draw stone
        self.indicator_canvas.create_oval(
            cx - radius, cy - radius,
            cx + radius, cy + radius,
            fill=color, outline=outline, width=3
        )

        # Draw symbol
        symbol = "X" if self.player == 1 else "O"
        self.indicator_canvas.create_text(
            cx, cy, text=symbol,
            fill="#ffffff", font=("Helvetica", 14, "bold")
        )

    def set_active(self, active: bool) -> None:
        self._is_active = active
        self._draw_indicator()
        if active:
            self.turn_label.config(text="▶ あなたの番です")
            self.config(relief="solid", borderwidth=2)
        else:
            self.turn_label.config(text="")
            self.config(relief="flat", borderwidth=0)

    def set_stone_count(self, count: int) -> None:
        self._stone_count = count
        self.count_label.config(text=f"石: {count}")

    def set_can_neutralize(self, can_neutralize: bool, used: bool = False) -> None:
        self._can_neutralize = can_neutralize
        if self.player == 2:
            if used:
                self.neutralize_label.config(text="⚡ 無効化：使用済み", fg=self.theme.text_secondary)
            elif can_neutralize:
                self.neutralize_label.config(text="⚡ 無効化：使用可能", fg=self.theme.text_accent)
            else:
                self.neutralize_label.config(text="⚡ 無効化：待機中", fg=self.theme.text_secondary)

    def update_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.config(bg=theme.panel_bg)
        self.indicator_canvas.config(bg=theme.panel_bg)
        self.name_label.config(bg=theme.panel_bg, fg=theme.text_primary)
        self.symbol_label.config(bg=theme.panel_bg, fg=theme.text_secondary)
        self.count_label.config(bg=theme.panel_bg, fg=theme.text_secondary)
        self.turn_frame.config(bg=theme.panel_bg)
        self.turn_label.config(bg=theme.panel_bg, fg=theme.success_color)
        if self.player == 2:
            self.neutralize_label.config(bg=theme.panel_bg)
        self._draw_indicator()


class SettingsDialog(_TkToplevelBase):  # type: ignore[misc]
    """Settings dialog for game configuration."""

    def __init__(self, parent: tk.Widget, current_theme: str, current_radius: int, on_apply: Callable) -> None:
        super().__init__(parent)
        self.title("設定")
        self.geometry("400x350")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.current_theme = current_theme
        self.current_radius = current_radius
        self.on_apply = on_apply

        theme = THEMES[current_theme]
        self.config(bg=theme.window_bg)

        self._create_widgets(theme)

        # Center the dialog
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self, theme: Theme) -> None:
        # Title
        title_label = tk.Label(
            self, text="ゲーム設定", font=("Helvetica", 18, "bold"),
            bg=theme.window_bg, fg=theme.text_primary
        )
        title_label.pack(pady=(20, 20))

        # Settings frame
        settings_frame = tk.Frame(self, bg=theme.window_bg)
        settings_frame.pack(padx=30, fill="x")

        # Theme selection
        theme_label = tk.Label(
            settings_frame, text="テーマ:", font=("Helvetica", 12),
            bg=theme.window_bg, fg=theme.text_primary
        )
        theme_label.grid(row=0, column=0, sticky="w", pady=10)

        self.theme_var = tk.StringVar(value=self.current_theme)
        theme_options = [(t.name, k) for k, t in THEMES.items()]

        theme_frame = tk.Frame(settings_frame, bg=theme.window_bg)
        theme_frame.grid(row=0, column=1, sticky="w", padx=(20, 0))

        for i, (display_name, key) in enumerate(theme_options):
            rb = tk.Radiobutton(
                theme_frame, text=display_name, variable=self.theme_var, value=key,
                bg=theme.window_bg, fg=theme.text_primary,
                selectcolor=theme.panel_bg, activebackground=theme.window_bg,
                activeforeground=theme.text_primary
            )
            rb.pack(anchor="w")

        # Board radius selection
        radius_label = tk.Label(
            settings_frame, text="盤の半径:", font=("Helvetica", 12),
            bg=theme.window_bg, fg=theme.text_primary
        )
        radius_label.grid(row=1, column=0, sticky="w", pady=10)

        radius_frame = tk.Frame(settings_frame, bg=theme.window_bg)
        radius_frame.grid(row=1, column=1, sticky="w", padx=(20, 0))

        self.radius_var = tk.IntVar(value=self.current_radius)
        for r in [3, 4, 5, 6]:
            rb = tk.Radiobutton(
                radius_frame, text=str(r), variable=self.radius_var, value=r,
                bg=theme.window_bg, fg=theme.text_primary,
                selectcolor=theme.panel_bg, activebackground=theme.window_bg,
                activeforeground=theme.text_primary
            )
            rb.pack(side="left", padx=5)

        # Info text
        info_label = tk.Label(
            self, text="※ 盤の半径を変更すると新しいゲームが開始されます",
            font=("Helvetica", 9), bg=theme.window_bg, fg=theme.text_secondary
        )
        info_label.pack(pady=(20, 10))

        # Buttons
        button_frame = tk.Frame(self, bg=theme.window_bg)
        button_frame.pack(pady=20)

        apply_btn = tk.Button(
            button_frame, text="適用", command=self._apply,
            bg=theme.button_bg, fg=theme.button_fg,
            font=("Helvetica", 11), width=10, relief="flat"
        )
        apply_btn.pack(side="left", padx=10)

        cancel_btn = tk.Button(
            button_frame, text="キャンセル", command=self.destroy,
            bg=theme.panel_bg, fg=theme.text_primary,
            font=("Helvetica", 11), width=10, relief="flat"
        )
        cancel_btn.pack(side="left", padx=10)

    def _apply(self) -> None:
        new_theme = self.theme_var.get()
        new_radius = self.radius_var.get()
        self.on_apply(new_theme, new_radius)
        self.destroy()


class RulesDialog(_TkToplevelBase):  # type: ignore[misc]
    """Dialog showing game rules."""

    def __init__(self, parent: tk.Widget, theme: Theme) -> None:
        super().__init__(parent)
        self.title("ゲームルール")
        self.geometry("500x500")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.config(bg=theme.window_bg)
        self._create_widgets(theme)

        # Center the dialog
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self, theme: Theme) -> None:
        # Title
        title_label = tk.Label(
            self, text="ヘックス3-タブー ルール", font=("Helvetica", 18, "bold"),
            bg=theme.window_bg, fg=theme.text_primary
        )
        title_label.pack(pady=(20, 15))

        # Rules text
        rules_frame = tk.Frame(self, bg=theme.panel_bg, padx=20, pady=20)
        rules_frame.pack(padx=20, fill="both", expand=True)

        rules_text = """
【基本ルール】

1. 二人のプレイヤーが交互に六角形のマスに石を置きます。

2. プレイヤー1は赤（X）、プレイヤー2は青（O）の石を使います。

【勝利条件】
• 4つ以上の石を一直線に並べると勝利！

【敗北条件】
• 両端がブロックされた状態で3つの石が一直線に
  並んでしまうと敗北（タブー）

【特殊アクション】
• プレイヤー2は、ゲーム中1回だけ、相手が最後に
  置いた石を「無効化」することができます。
• 無効化された石はどちらのプレイヤーのものでも
  なくなります。

【戦略のヒント】
• 4連を目指しながら、うっかり3タブーを作らない
  ように注意！
• 相手を3タブーに追い込む戦略も有効です。
• プレイヤー2の無効化は貴重な切り札です。
  使うタイミングを慎重に選びましょう。
        """

        text_label = tk.Label(
            rules_frame, text=rules_text.strip(),
            font=("Helvetica", 11), bg=theme.panel_bg, fg=theme.text_primary,
            justify="left", anchor="nw"
        )
        text_label.pack(fill="both", expand=True)

        # Close button
        close_btn = tk.Button(
            self, text="閉じる", command=self.destroy,
            bg=theme.button_bg, fg=theme.button_fg,
            font=("Helvetica", 11), width=10, relief="flat"
        )
        close_btn.pack(pady=15)


class StartScreen(_TkFrameBase):  # type: ignore[misc]
    """Animated start screen."""

    def __init__(self, parent: tk.Widget, theme: Theme, on_start: Callable, on_settings: Callable, on_rules: Callable) -> None:
        super().__init__(parent, bg=theme.window_bg)
        self.theme = theme
        self.on_start = on_start  # Called with (game_mode, ai_difficulty)
        self.on_settings = on_settings
        self.on_rules = on_rules
        self._animation_id: Optional[str] = None
        self._particles: List[Dict] = []
        self._selected_difficulty = "medium"

        self._create_widgets()
        self._start_animation()

    def _create_widgets(self) -> None:
        # Background canvas for particles
        self.bg_canvas = tk.Canvas(
            self, bg=self.theme.window_bg, highlightthickness=0
        )
        self.bg_canvas.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Content frame
        content = tk.Frame(self, bg=self.theme.window_bg)
        content.place(relx=0.5, rely=0.5, anchor="center")

        # Title with shadow effect
        title_frame = tk.Frame(content, bg=self.theme.window_bg)
        title_frame.pack(pady=(0, 10))

        # Shadow title
        self.shadow_label = tk.Label(
            title_frame,
            text="ヘックス3-タブー",
            font=("Helvetica", 42, "bold"),
            bg=self.theme.window_bg,
            fg=self.theme.shadow_color,
        )
        self.shadow_label.place(x=3, y=3)

        # Main title
        self.title_label = tk.Label(
            title_frame,
            text="ヘックス3-タブー",
            font=("Helvetica", 42, "bold"),
            bg=self.theme.window_bg,
            fg=self.theme.text_primary,
        )
        self.title_label.pack()

        # Subtitle
        subtitle = tk.Label(
            content,
            text="〜 戦略的六角形ボードゲーム 〜",
            font=("Helvetica", 14),
            bg=self.theme.window_bg,
            fg=self.theme.text_secondary,
        )
        subtitle.pack(pady=(0, 40))

        # Hexagon decoration
        self.hex_canvas = tk.Canvas(
            content, width=120, height=120, bg=self.theme.window_bg, highlightthickness=0
        )
        self.hex_canvas.pack(pady=(0, 40))
        self._draw_hex_logo()

        # Buttons
        button_frame = tk.Frame(content, bg=self.theme.window_bg)
        button_frame.pack()

        # Game mode label
        mode_label = tk.Label(
            button_frame, text="ゲームモード",
            font=("Helvetica", 12, "bold"), bg=self.theme.window_bg, fg=self.theme.text_primary
        )
        mode_label.pack(pady=(0, 8))

        self.pvp_button = StyledButton(
            button_frame, "対人対戦", self.theme,
            command=self._start_pvp, width=200, height=50, icon="👥"
        )
        self.pvp_button.pack(pady=5)

        self.cpu_button = StyledButton(
            button_frame, "CPU対戦", self.theme,
            command=self._show_difficulty_selector, width=200, height=50, icon="🤖"
        )
        self.cpu_button.pack(pady=5)

        # Difficulty selector (initially hidden)
        self.difficulty_frame = tk.Frame(button_frame, bg=self.theme.window_bg)

        diff_label = tk.Label(
            self.difficulty_frame, text="難易度を選択",
            font=("Helvetica", 11), bg=self.theme.window_bg, fg=self.theme.text_secondary
        )
        diff_label.pack(pady=(5, 5))

        diff_buttons_frame = tk.Frame(self.difficulty_frame, bg=self.theme.window_bg)
        diff_buttons_frame.pack()

        self.easy_btn = StyledButton(
            diff_buttons_frame, "かんたん", self.theme,
            command=lambda: self._start_cpu("easy"), width=90, height=35, style="secondary"
        )
        self.easy_btn.pack(side="left", padx=3)

        self.medium_btn = StyledButton(
            diff_buttons_frame, "ふつう", self.theme,
            command=lambda: self._start_cpu("medium"), width=90, height=35, style="secondary"
        )
        self.medium_btn.pack(side="left", padx=3)

        self.hard_btn = StyledButton(
            diff_buttons_frame, "むずかしい", self.theme,
            command=lambda: self._start_cpu("hard"), width=90, height=35, style="secondary"
        )
        self.hard_btn.pack(side="left", padx=3)

        # Separator
        separator = tk.Frame(button_frame, bg=self.theme.panel_border, height=1)
        separator.pack(fill="x", pady=15)

        self.rules_button = StyledButton(
            button_frame, "ルール説明", self.theme,
            command=self.on_rules, width=200, height=40, style="secondary", icon="📖"
        )
        self.rules_button.pack(pady=5)

        self.settings_button = StyledButton(
            button_frame, "設定", self.theme,
            command=self.on_settings, width=200, height=40, style="secondary", icon="⚙"
        )
        self.settings_button.pack(pady=5)

        # Version
        version_label = tk.Label(
            content, text="v3.0 - AI対戦対応",
            font=("Helvetica", 10), bg=self.theme.window_bg, fg=self.theme.text_secondary
        )
        version_label.pack(pady=(20, 0))

    def _start_pvp(self) -> None:
        """Start player vs player game."""
        self.on_start("pvp", None)

    def _show_difficulty_selector(self) -> None:
        """Show difficulty selection buttons."""
        self.difficulty_frame.pack(pady=5)

    def _start_cpu(self, difficulty: str) -> None:
        """Start player vs CPU game with selected difficulty."""
        self._selected_difficulty = difficulty
        self.on_start("cpu", difficulty)

    def _draw_hex_logo(self) -> None:
        cx, cy = 60, 60
        size = 45

        # Draw outer hexagon
        points = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            points.extend([cx + size * math.cos(angle), cy + size * math.sin(angle)])
        self.hex_canvas.create_polygon(
            points, fill=self.theme.cell_base, outline=self.theme.cell_edge, width=3
        )

        # Draw inner decorations
        inner_size = 25
        inner_points = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            inner_points.extend([cx + inner_size * math.cos(angle), cy + inner_size * math.sin(angle)])
        self.hex_canvas.create_polygon(
            inner_points, fill="", outline=self.theme.text_secondary, width=2
        )

        # Draw center stones
        stone_positions = [(-12, -8), (12, -8), (0, 12)]
        colors = [self.theme.player1_color, self.theme.player2_color, self.theme.text_accent]
        for (dx, dy), color in zip(stone_positions, colors):
            self.hex_canvas.create_oval(
                cx + dx - 8, cy + dy - 8, cx + dx + 8, cy + dy + 8,
                fill=color, outline=""
            )

    def _start_animation(self) -> None:
        # Initialize floating particles
        self._particles = []
        for _ in range(15):
            self._particles.append({
                "x": random.uniform(0, 800),
                "y": random.uniform(0, 600),
                "vx": random.uniform(-0.5, 0.5),
                "vy": random.uniform(-0.5, 0.5),
                "size": random.uniform(20, 50),
                "color": random.choice([
                    self.theme.player1_color, self.theme.player2_color,
                    self.theme.text_accent, self.theme.cell_accent
                ]),
                "alpha": random.uniform(0.1, 0.3),
            })
        self._animate_particles()

    def _animate_particles(self) -> None:
        self.bg_canvas.delete("particle")
        width = self.winfo_width() or 800
        height = self.winfo_height() or 600

        for p in self._particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]

            # Wrap around
            if p["x"] < -50:
                p["x"] = width + 50
            elif p["x"] > width + 50:
                p["x"] = -50
            if p["y"] < -50:
                p["y"] = height + 50
            elif p["y"] > height + 50:
                p["y"] = -50

            # Draw hexagon particle
            points = []
            for i in range(6):
                angle = math.radians(60 * i - 30)
                points.extend([
                    p["x"] + p["size"] * math.cos(angle),
                    p["y"] + p["size"] * math.sin(angle)
                ])
            self.bg_canvas.create_polygon(
                points, fill="", outline=p["color"], width=1,
                stipple="gray25", tags="particle"
            )

        self._animation_id = self.after(50, self._animate_particles)

    def stop_animation(self) -> None:
        if self._animation_id:
            self.after_cancel(self._animation_id)
            self._animation_id = None

    def update_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.config(bg=theme.window_bg)
        self.bg_canvas.config(bg=theme.window_bg)
        self.title_label.config(bg=theme.window_bg, fg=theme.text_primary)
        self.shadow_label.config(bg=theme.window_bg, fg=theme.shadow_color)
        self.hex_canvas.config(bg=theme.window_bg)
        self._draw_hex_logo()
        self.pvp_button.update_theme(theme)
        self.cpu_button.update_theme(theme)
        self.easy_btn.update_theme(theme)
        self.medium_btn.update_theme(theme)
        self.hard_btn.update_theme(theme)
        self.rules_button.update_theme(theme)
        self.settings_button.update_theme(theme)


class Hex3TabooGUI:
    """Production-level Tkinter interface for playing Hex 3-Taboo."""

    DEFAULT_HEX_SIZE = 30
    SHADOW_OFFSET = (3, 4)

    def __init__(self, game: Hex3TabooGame, theme_name: str = "light") -> None:
        if tk is None:
            raise RuntimeError("Tkinter is not available in this environment.")

        self.game = game
        self.board_radius = game.board.radius
        self.theme_name = theme_name
        self.theme = THEMES[theme_name]
        self.stats = GameStats()

        # Setup main window
        self.root = tk.Tk()
        self.root.title("ヘックス3-タブー")
        self.root.geometry("1100x750")
        self.root.minsize(900, 650)
        self.root.config(bg=self.theme.window_bg)

        # Initialize state variables
        self.hex_size: float = self.DEFAULT_HEX_SIZE
        self.cell_items: Dict[int, AxialCoord] = {}
        self.coord_to_item: Dict[AxialCoord, int] = {}
        self.cell_shadows: Dict[AxialCoord, int] = {}
        self.stone_items: Dict[AxialCoord, int] = {}
        self._stone_bounds: Dict[int, Tuple[float, float, float, float]] = {}
        self._tile_base_colors: Dict[AxialCoord, str] = {}
        self._cell_states: Dict[AxialCoord, Optional[int]] = {
            coord: None for coord in self.game.board.cells
        }
        self._target_stone_colors: Dict[int, str] = {}
        self._active_tweens: Dict[Tuple[int, str], Tween] = {}
        self._line_animation_items: List[int] = []
        self._line_animation_cycle = 0
        self._base_line_colors: Dict[int, str] = {}
        self._line_highlight_tween: Optional[Tween] = None
        self._hovered_item: Optional[int] = None
        self._game_started = False
        self._game_over = False

        # AI settings
        self._game_mode: str = "pvp"  # "pvp" or "cpu"
        self._ai_player: Optional[AIPlayer] = None
        self._ai_thinking = False

        # Create UI
        self._create_menu()
        self._create_start_screen()

    def _create_menu(self) -> None:
        self.menubar = tk.Menu(self.root)
        self.root.config(menu=self.menubar)

        # Game menu
        game_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="ゲーム", menu=game_menu)
        game_menu.add_command(label="新規ゲーム", command=self._new_game, accelerator="Ctrl+N")
        game_menu.add_command(label="タイトルに戻る", command=self._return_to_title)
        game_menu.add_separator()
        game_menu.add_command(label="終了", command=self.root.quit, accelerator="Ctrl+Q")

        # Settings menu
        settings_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="設定", menu=settings_menu)
        settings_menu.add_command(label="設定を開く...", command=self._show_settings)

        # Theme submenu
        theme_menu = tk.Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label="テーマ", menu=theme_menu)
        self.theme_var = tk.StringVar(value=self.theme_name)
        for key, t in THEMES.items():
            theme_menu.add_radiobutton(
                label=t.name, variable=self.theme_var, value=key,
                command=lambda: self._change_theme(self.theme_var.get())
            )

        # Help menu
        help_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="ヘルプ", menu=help_menu)
        help_menu.add_command(label="ルール", command=self._show_rules, accelerator="F1")
        help_menu.add_separator()
        help_menu.add_command(label="このゲームについて", command=self._show_about)

        # Keyboard shortcuts
        self.root.bind("<Control-n>", lambda e: self._new_game())
        self.root.bind("<Control-q>", lambda e: self.root.quit())
        self.root.bind("<F1>", lambda e: self._show_rules())

    def _create_start_screen(self) -> None:
        self.start_screen = StartScreen(
            self.root, self.theme,
            on_start=self._start_game,
            on_settings=self._show_settings,
            on_rules=self._show_rules
        )
        self.start_screen.pack(fill="both", expand=True)

    def _create_game_ui(self) -> None:
        # Main container
        self.main_frame = tk.Frame(self.root, bg=self.theme.window_bg)

        # Left panel (Player 1)
        self.left_panel = tk.Frame(self.main_frame, bg=self.theme.window_bg, width=180)
        self.left_panel.pack(side="left", fill="y", padx=(10, 0), pady=10)
        self.left_panel.pack_propagate(False)

        # Set player names based on game mode
        if self._game_mode == "cpu":
            player1_name = "あなた"
        else:
            player1_name = "プレイヤー 1"
        self.player1_panel = PlayerPanel(self.left_panel, 1, self.theme, player1_name)
        self.player1_panel.pack(pady=20)

        # Stats display
        self.stats_frame = tk.Frame(self.left_panel, bg=self.theme.panel_bg, padx=10, pady=10)
        self.stats_frame.pack(pady=20, fill="x", padx=10)

        stats_title = tk.Label(
            self.stats_frame, text="統計",
            font=("Helvetica", 12, "bold"),
            bg=self.theme.panel_bg, fg=self.theme.text_primary
        )
        stats_title.pack()

        self.stats_label = tk.Label(
            self.stats_frame, text="",
            font=("Helvetica", 10),
            bg=self.theme.panel_bg, fg=self.theme.text_secondary,
            justify="left"
        )
        self.stats_label.pack(pady=(5, 0))
        self._update_stats_display()

        # Center area (Board)
        self.center_frame = tk.Frame(self.main_frame, bg=self.theme.window_bg)
        self.center_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        # Status area
        self.status_frame = tk.Frame(self.center_frame, bg=self.theme.window_bg)
        self.status_frame.pack(fill="x", pady=(0, 10))

        self.status_var = tk.StringVar()
        self.status_label = tk.Label(
            self.status_frame,
            textvariable=self.status_var,
            font=("Helvetica", 14, "bold"),
            bg=self.theme.window_bg,
            fg=self.theme.text_primary,
        )
        self.status_label.pack()

        self.outcome_var = tk.StringVar(value="")
        self.outcome_label = tk.Label(
            self.status_frame,
            textvariable=self.outcome_var,
            font=("Helvetica", 16, "bold"),
            bg=self.theme.window_bg,
            fg=self.theme.text_accent,
            wraplength=500,
        )
        self.outcome_label.pack(pady=(5, 0))

        # Canvas
        self.canvas = tk.Canvas(
            self.center_frame,
            bg=self.theme.board_bg_top,
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.on_canvas_configure)

        # Particle system for celebrations
        self.particle_system = ParticleSystem(self.canvas)

        # Button area
        self.button_frame = tk.Frame(self.center_frame, bg=self.theme.window_bg)
        self.button_frame.pack(fill="x", pady=(10, 0))

        self.neutralize_button = StyledButton(
            self.button_frame, "相手の石を無効化", self.theme,
            command=self.on_remove, width=180, height=40, icon="⚡", style="danger"
        )
        self.neutralize_button.pack(side="left", padx=5)
        self.neutralize_button.set_state("disabled")
        self.neutralize_tooltip = Tooltip(
            self.neutralize_button, "相手が最後に置いた石を無効化します（1回のみ使用可能）", self.theme
        )

        self.reset_button = StyledButton(
            self.button_frame, "新しいゲーム", self.theme,
            command=self._new_game, width=150, height=40, icon="🔄", style="secondary"
        )
        self._reset_button_visible = False

        # Right panel (Player 2)
        self.right_panel = tk.Frame(self.main_frame, bg=self.theme.window_bg, width=180)
        self.right_panel.pack(side="right", fill="y", padx=(0, 10), pady=10)
        self.right_panel.pack_propagate(False)

        # Set player 2 name based on game mode
        if self._game_mode == "cpu" and self._ai_player:
            player2_name = f"CPU（{self._ai_player.get_difficulty_name()}）"
        else:
            player2_name = "プレイヤー 2"
        self.player2_panel = PlayerPanel(self.right_panel, 2, self.theme, player2_name)
        self.player2_panel.pack(pady=20)

        # History display
        self.history_frame = tk.Frame(self.right_panel, bg=self.theme.panel_bg, padx=10, pady=10)
        self.history_frame.pack(pady=20, fill="both", expand=True, padx=10)

        history_title = tk.Label(
            self.history_frame, text="最近の手",
            font=("Helvetica", 12, "bold"),
            bg=self.theme.panel_bg, fg=self.theme.text_primary
        )
        history_title.pack()

        self.history_listbox = tk.Listbox(
            self.history_frame,
            font=("Helvetica", 10),
            bg=self.theme.panel_bg,
            fg=self.theme.text_secondary,
            selectbackground=self.theme.cell_accent,
            relief="flat",
            height=10,
        )
        self.history_listbox.pack(fill="both", expand=True, pady=(5, 0))

    def _start_game(self, game_mode: str = "pvp", ai_difficulty: Optional[str] = None) -> None:
        if hasattr(self, 'start_screen'):
            self.start_screen.stop_animation()
            self.start_screen.pack_forget()
            self.start_screen.destroy()

        # Set game mode and AI
        self._game_mode = game_mode
        if game_mode == "cpu" and ai_difficulty:
            self._ai_player = AIPlayer(difficulty=ai_difficulty, player_id=2)
        else:
            self._ai_player = None

        self._game_started = True
        self._game_over = False
        self._ai_thinking = False
        self._create_game_ui()
        self.main_frame.pack(fill="both", expand=True)
        self._draw_board()
        self.update_board()
        self.update_status()

    def _return_to_title(self) -> None:
        if self._game_started:
            if hasattr(self, 'main_frame'):
                self.main_frame.pack_forget()
                self.main_frame.destroy()
            self._game_started = False
            self._create_start_screen()

    def _new_game(self) -> None:
        if not self._game_started:
            self._start_game()
            return

        self._hide_reset_button()
        self.game = Hex3TabooGame(radius=self.board_radius)
        self._cell_states = {coord: None for coord in self.game.board.cells}
        self._target_stone_colors.clear()
        self._active_tweens.clear()
        self._game_over = False
        self._ai_thinking = False
        self._stop_line_highlight()
        self.particle_system.clear()
        self._draw_board()
        self.update_board()
        self.update_status()
        self.outcome_var.set("")
        self.history_listbox.delete(0, tk.END)
        self.canvas.tag_bind("cell", "<Button-1>", self._handle_cell_click)

    def _show_settings(self) -> None:
        SettingsDialog(
            self.root, self.theme_name, self.board_radius,
            self._apply_settings
        )

    def _apply_settings(self, theme_name: str, radius: int) -> None:
        theme_changed = theme_name != self.theme_name
        radius_changed = radius != self.board_radius

        if theme_changed:
            self._change_theme(theme_name)

        if radius_changed:
            self.board_radius = radius
            if self._game_started:
                self._new_game()

    def _change_theme(self, theme_name: str) -> None:
        self.theme_name = theme_name
        self.theme = THEMES[theme_name]
        self.theme_var.set(theme_name)

        self.root.config(bg=self.theme.window_bg)

        if not self._game_started:
            if hasattr(self, 'start_screen'):
                self.start_screen.update_theme(self.theme)
        else:
            self._update_game_theme()

    def _update_game_theme(self) -> None:
        # Update all widgets with new theme
        self.main_frame.config(bg=self.theme.window_bg)
        self.left_panel.config(bg=self.theme.window_bg)
        self.right_panel.config(bg=self.theme.window_bg)
        self.center_frame.config(bg=self.theme.window_bg)
        self.status_frame.config(bg=self.theme.window_bg)
        self.status_label.config(bg=self.theme.window_bg, fg=self.theme.text_primary)
        self.outcome_label.config(bg=self.theme.window_bg, fg=self.theme.text_accent)
        self.button_frame.config(bg=self.theme.window_bg)
        self.canvas.config(bg=self.theme.board_bg_top)

        self.player1_panel.update_theme(self.theme)
        self.player2_panel.update_theme(self.theme)
        self.neutralize_button.update_theme(self.theme)
        self.reset_button.update_theme(self.theme)

        self.stats_frame.config(bg=self.theme.panel_bg)
        for child in self.stats_frame.winfo_children():
            child.config(bg=self.theme.panel_bg)
        self.stats_label.config(fg=self.theme.text_secondary)

        self.history_frame.config(bg=self.theme.panel_bg)
        for child in self.history_frame.winfo_children():
            if isinstance(child, tk.Label):
                child.config(bg=self.theme.panel_bg, fg=self.theme.text_primary)
        self.history_listbox.config(
            bg=self.theme.panel_bg, fg=self.theme.text_secondary,
            selectbackground=self.theme.cell_accent
        )

        self._draw_board()
        self.update_board()

    def _show_rules(self) -> None:
        RulesDialog(self.root, self.theme)

    def _show_about(self) -> None:
        if messagebox:
            messagebox.showinfo(
                "このゲームについて",
                "ヘックス3-タブー v2.0\n\n"
                "戦略的な六角形ボードゲーム\n\n"
                "4連で勝利、孤立した3連で敗北！\n"
                "シンプルなルールで奥深い戦略性を楽しめます。"
            )

    def _update_stats_display(self) -> None:
        if hasattr(self, 'stats_label'):
            text = f"P1勝利: {self.stats.player1_wins}\n"
            text += f"P2勝利: {self.stats.player2_wins}\n"
            text += f"引分け: {self.stats.draws}\n"
            text += f"総ゲーム: {self.stats.total_games}"
            if self.stats.current_streak > 1:
                text += f"\n連勝: P{self.stats.streak_player} ({self.stats.current_streak})"
            self.stats_label.config(text=text)

    def run(self) -> None:
        self.root.mainloop()

    def _draw_background(self, width: int, height: int) -> None:
        steps = 24
        for step in range(steps):
            factor_top = step / steps
            factor_bottom = (step + 1) / steps
            color = self._interpolate_color(
                self.theme.board_bg_top,
                self.theme.board_bg_bottom,
                (factor_top + factor_bottom) / 2,
            )
            y0 = height * factor_top
            y1 = height * factor_bottom
            self.canvas.create_rectangle(0, y0, width, y1, fill=color, outline="")
        self.canvas.create_rectangle(
            2, 2, width - 2, height - 2,
            outline=self.theme.board_border, width=3
        )

    def _compute_tile_color(self, coord: AxialCoord) -> str:
        radius = max(1, self.board_radius)
        normalized_q = (coord[0] + radius) / (2 * radius)
        normalized_r = (coord[1] + radius) / (2 * radius)
        wave = (math.sin((coord[0] - coord[1]) * math.pi / 3) + 1.0) / 2.0
        blend = (normalized_q + normalized_r + wave) / 3.0
        blend = max(0.0, min(1.0, blend * 0.6))
        return self._interpolate_color(self.theme.cell_base, self.theme.cell_accent, blend)

    def _tile_hover_color(self, coord: AxialCoord) -> str:
        base = self._tile_base_colors.get(coord, self.theme.cell_base)
        return self._interpolate_color(base, "#ffffff", 0.18)

    def _draw_board(self) -> None:
        if not hasattr(self, 'canvas'):
            return

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            return

        self._update_hex_size(canvas_width, canvas_height)

        coordinates = list(self.game.board.cells.keys())
        bounds = self._board_bounds(self.hex_size)
        min_x, max_x, min_y, max_y = bounds
        board_width = max_x - min_x
        board_height = max_y - min_y
        offset_x = (canvas_width - board_width) / 2 - min_x
        offset_y = (canvas_height - board_height) / 2 - min_y

        self._stop_line_highlight()
        self.canvas.delete("all")
        for tween in self._active_tweens.values():
            tween.cancel()
        self._active_tweens.clear()
        self.cell_items.clear()
        self.coord_to_item.clear()
        self.cell_shadows.clear()
        self.stone_items.clear()
        self._stone_bounds.clear()
        self._tile_base_colors.clear()
        self._target_stone_colors.clear()
        self._hovered_item = None

        self._draw_background(canvas_width, canvas_height)

        for coord in coordinates:
            x, y = self._axial_to_pixel(coord)
            polygon_points = self._hexagon_points(x, y)
            shifted_points: List[float] = []
            for index, value in enumerate(polygon_points):
                if index % 2 == 0:
                    shifted_points.append(value + offset_x)
                else:
                    shifted_points.append(value + offset_y)

            shadow_points: List[float] = []
            shadow_dx, shadow_dy = self.SHADOW_OFFSET
            for index, value in enumerate(shifted_points):
                if index % 2 == 0:
                    shadow_points.append(value + shadow_dx)
                else:
                    shadow_points.append(value + shadow_dy)
            shadow_item = self.canvas.create_polygon(
                shadow_points, outline="", fill=self.theme.shadow_color,
                stipple="gray50", tags=("shadow",)
            )
            self.cell_shadows[coord] = shadow_item

            tile_color = self._compute_tile_color(coord)
            self._tile_base_colors[coord] = tile_color
            item = self.canvas.create_polygon(
                shifted_points, outline=self.theme.cell_edge, fill=tile_color,
                width=2, joinstyle=tk.ROUND, tags=("cell",)
            )
            self.cell_items[item] = coord
            self.coord_to_item[coord] = item

            center_x = x + offset_x
            center_y = y + offset_y
            stone_radius = self.hex_size * 0.48
            stone_item = self.canvas.create_oval(
                center_x - stone_radius, center_y - stone_radius,
                center_x + stone_radius, center_y + stone_radius,
                fill=self.theme.empty_stone, outline=self.theme.cell_edge,
                width=3, state=tk.HIDDEN, tags=("stone",)
            )
            self.stone_items[coord] = stone_item
            self._stone_bounds[stone_item] = (
                center_x - stone_radius, center_y - stone_radius,
                center_x + stone_radius, center_y + stone_radius
            )
            self._target_stone_colors[stone_item] = self.theme.empty_stone

            label_font_size = max(8, int(self.hex_size * 0.26))
            label = self.canvas.create_text(
                center_x, center_y + self.hex_size * 0.62,
                text=f"{coord[0]},{coord[1]}", fill=self.theme.coord_text,
                font=("Helvetica", label_font_size, "bold"), tags=("coord_label",)
            )
            self.canvas.itemconfig(label, state=tk.DISABLED)
            self.canvas.tag_lower(label)

        self.canvas.tag_lower("shadow")
        self.canvas.tag_lower("coord_label")
        self.canvas.tag_raise("stone")
        self.canvas.tag_bind("cell", "<Button-1>", self._handle_cell_click)
        self.canvas.tag_bind("cell", "<Enter>", self._handle_cell_enter)
        self.canvas.tag_bind("cell", "<Leave>", self._handle_cell_leave)

    def _handle_cell_click(self, event: tk.Event) -> None:
        if self._game_over:
            return
        # Block clicks during AI turn
        if self._ai_thinking:
            return
        # In CPU mode, block clicks when it's AI's turn
        if self._game_mode == "cpu" and self.game.current_player == 2:
            return
        current = event.widget.find_withtag("current")
        if not current:
            return
        coord = self.cell_items.get(current[0])
        if coord is not None:
            self.on_cell_clicked(coord)

    def _handle_cell_enter(self, event: tk.Event) -> None:
        current = event.widget.find_withtag("current")
        if not current:
            return
        self._on_cell_enter(current[0])

    def _handle_cell_leave(self, event: tk.Event) -> None:
        current = event.widget.find_withtag("current")
        if not current:
            return
        self._on_cell_leave(current[0])

    def _on_cell_enter(self, item_id: int) -> None:
        if self._hovered_item == item_id or self._game_over:
            return
        coord = self.cell_items.get(item_id)
        if coord is None:
            return
        self._hovered_item = item_id
        hover_color = self._tile_hover_color(coord)
        self.canvas.itemconfig(item_id, fill=hover_color, outline=self.theme.hover_outline, width=3)
        stone_id = self.stone_items.get(coord)
        if stone_id is not None:
            self.canvas.tag_raise(stone_id)

    def _on_cell_leave(self, item_id: int) -> None:
        if self._hovered_item != item_id:
            return
        coord = self.cell_items.get(item_id)
        if coord is None:
            return
        self._hovered_item = None
        base_color = self._tile_base_colors.get(coord, self.theme.cell_base)
        self.canvas.itemconfig(item_id, fill=base_color, outline=self.theme.cell_edge, width=2)

    def _animate_stone_placement(self, stone_id: int, duration_ms: int = 260) -> None:
        bounds = self._stone_bounds.get(stone_id)
        if bounds is None:
            return
        key = (stone_id, "scale")
        if key in self._active_tweens:
            self._active_tweens[key].cancel()
        x0, y0, x1, y1 = bounds
        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2

        def update(progress: float) -> None:
            eased = ease_out_bounce(progress)
            eased = max(0.0, min(1.0, eased))
            radius_x = (x1 - x0) / 2 * eased
            radius_y = (y1 - y0) / 2 * eased
            self.canvas.coords(
                stone_id,
                center_x - radius_x, center_y - radius_y,
                center_x + radius_x, center_y + radius_y
            )

        def finish() -> None:
            self.canvas.coords(stone_id, x0, y0, x1, y1)
            self._active_tweens.pop(key, None)

        tween = Tween(self.canvas, duration_ms, update, on_complete=finish)
        self._active_tweens[key] = tween
        tween.start()

    def _axial_to_pixel(self, coord: AxialCoord, hex_size: Optional[float] = None) -> Tuple[float, float]:
        size = hex_size if hex_size is not None else self.hex_size
        q, r = coord
        x = size * math.sqrt(3) * (q + r / 2)
        y = size * 1.5 * r
        return x, y

    def _hexagon_points(self, center_x: float, center_y: float, hex_size: Optional[float] = None) -> List[float]:
        size = hex_size if hex_size is not None else self.hex_size
        points: List[float] = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            x = center_x + size * math.cos(angle)
            y = center_y + size * math.sin(angle)
            points.extend((x, y))
        return points

    def _board_bounds(self, hex_size: float) -> Tuple[float, float, float, float]:
        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")
        for coord in self.game.board.cells.keys():
            polygon = self._hexagon_points(*self._axial_to_pixel(coord, hex_size), hex_size)
            for index in range(0, len(polygon), 2):
                x = polygon[index]
                y = polygon[index + 1]
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
        if not math.isfinite(min_x):
            min_x = max_x = min_y = max_y = 0.0
        return min_x, max_x, min_y, max_y

    def _update_hex_size(self, canvas_width: int, canvas_height: int) -> None:
        base_min_x, base_max_x, base_min_y, base_max_y = self._board_bounds(1.0)
        board_width = base_max_x - base_min_x
        board_height = base_max_y - base_min_y
        if board_width <= 0 or board_height <= 0:
            return
        scale = min(canvas_width / board_width, canvas_height / board_height)
        target_size = max(5.0, scale * 0.85)
        if abs(target_size - self.hex_size) > 1e-6:
            self.hex_size = target_size

    def on_cell_clicked(self, coord: AxialCoord) -> None:
        try:
            acting_player = self.game.current_player
            self.game.place_stone(coord)
        except Exception as exc:
            if messagebox is not None:
                messagebox.showinfo("無効な手", str(exc))
            return
        self._add_history_entry(acting_player, "place", coord)
        self._finalize_turn(acting_player)

    def on_remove(self) -> None:
        try:
            acting_player = self.game.current_player
            removed = self.game.remove_last_opponent_stone()
        except Exception as exc:
            if messagebox is not None:
                messagebox.showinfo("無効化できません", str(exc))
            return
        if removed is not None:
            self._add_history_entry(acting_player, "disable", removed)
        self._finalize_turn(acting_player)

    def _add_history_entry(self, player: int, action: str, coord: AxialCoord) -> None:
        symbol = "X" if player == 1 else "O"
        if action == "place":
            text = f"P{player}({symbol}): 配置 {coord}"
        else:
            text = f"P{player}({symbol}): 無効化 {coord}"
        self.history_listbox.insert(0, text)
        if self.history_listbox.size() > 10:
            self.history_listbox.delete(10)

    def _finalize_turn(self, acting_player: int) -> None:
        result = self.game.check_game_end()
        self.update_board()

        if result:
            outcome, message = result
            line_coords = self.game.last_detected_line
            self._game_over = True

            # Record stats
            self.stats.record_result(outcome, acting_player)
            self._update_stats_display()

            self.status_var.set("ゲーム終了")
            self.outcome_var.set(message)
            self.neutralize_button.set_state("disabled")

            if self._hovered_item is not None:
                self._on_cell_leave(self._hovered_item)
            self.canvas.tag_unbind("cell", "<Button-1>")

            if line_coords:
                self._animate_line_highlight(line_coords)

            # Celebration particles
            if outcome == "win":
                # Get center of winning line for particle burst
                if line_coords:
                    center_coord = line_coords[len(line_coords) // 2]
                    if center_coord in self.stone_items:
                        stone_id = self.stone_items[center_coord]
                        bounds = self._stone_bounds.get(stone_id)
                        if bounds:
                            cx = (bounds[0] + bounds[2]) / 2
                            cy = (bounds[1] + bounds[3]) / 2
                            colors = [self.theme.highlight_color, self.theme.success_color,
                                      self.theme.player1_color if acting_player == 1 else self.theme.player2_color]
                            self.particle_system.emit_burst(cx, cy, count=80, colors=colors)

                # Confetti effect
                self.root.after(300, lambda: self.particle_system.emit_confetti(
                    self.canvas.winfo_width(), self.canvas.winfo_height(), count=150
                ))

            self._show_reset_button()
            return

        self.game.switch_player()
        self.update_status()
        self.update_remove_button()

        # Trigger AI turn if in CPU mode and it's AI's turn
        if self._game_mode == "cpu" and self._ai_player and self.game.current_player == 2:
            self._schedule_ai_turn()

    def _schedule_ai_turn(self) -> None:
        """Schedule AI to make a move after a short delay."""
        if self._ai_thinking or self._game_over:
            return
        self._ai_thinking = True
        # Add delay for better UX
        delay = 500 if self._ai_player and self._ai_player.difficulty == AIPlayer.HARD else 300
        self.root.after(delay, self._execute_ai_turn)

    def _execute_ai_turn(self) -> None:
        """Execute AI's turn."""
        if self._game_over or not self._ai_player:
            self._ai_thinking = False
            return

        action, coord = self._ai_player.choose_action(self.game)
        acting_player = self.game.current_player

        try:
            if action == "remove":
                removed = self.game.remove_last_opponent_stone()
                if removed:
                    self._add_history_entry(acting_player, "disable", removed)
            elif action == "place" and coord:
                self.game.place_stone(coord)
                self._add_history_entry(acting_player, "place", coord)
        except Exception:
            # If AI makes invalid move, try random valid move
            empty = self.game.board.empty_cells()
            forbidden = self.game.forbidden_placements.get(self.game.current_player)
            valid = [c for c in empty if c != forbidden]
            if valid:
                coord = random.choice(valid)
                self.game.place_stone(coord)
                self._add_history_entry(acting_player, "place", coord)

        self._ai_thinking = False
        self._finalize_turn(acting_player)

    def update_board(self) -> None:
        if not hasattr(self, 'canvas'):
            return

        occupant_to_color = {
            None: self.theme.empty_stone,
            HexBoard.DISABLED_STONE: self.theme.disabled_stone,
            1: self.theme.player1_color,
            2: self.theme.player2_color,
        }
        occupant_to_outline = {
            None: self.theme.cell_edge,
            HexBoard.DISABLED_STONE: self.theme.disabled_outline,
            1: self.theme.player1_outline,
            2: self.theme.player2_outline,
        }

        player1_stones = 0
        player2_stones = 0

        for coord, stone_id in self.stone_items.items():
            occupant = self.game.board.cells[coord]
            target_color = occupant_to_color[occupant]
            target_outline = occupant_to_outline[occupant]
            previous = self._cell_states.get(coord)
            previous_color = occupant_to_color.get(previous, self.theme.empty_stone)

            if occupant == 1:
                player1_stones += 1
            elif occupant == 2:
                player2_stones += 1

            if occupant is None:
                if previous is None:
                    self.canvas.itemconfig(stone_id, state=tk.HIDDEN)
                else:
                    self._start_fill_animation(stone_id, previous_color, target_color, hide_after=True)
                self._target_stone_colors[stone_id] = target_color
                self._cell_states[coord] = None
                continue

            self.canvas.itemconfig(
                stone_id, state=tk.NORMAL, outline=target_outline, width=3,
                dash=(3, 2) if occupant == HexBoard.DISABLED_STONE else None
            )

            if previous is None:
                self.canvas.itemconfig(stone_id, fill=self.theme.empty_stone)
                self._start_fill_animation(stone_id, self.theme.empty_stone, target_color)
                self._animate_stone_placement(stone_id)
            elif previous != occupant:
                self._start_fill_animation(stone_id, previous_color, target_color)
            else:
                self.canvas.itemconfig(stone_id, fill=target_color)

            self._target_stone_colors[stone_id] = target_color
            self._cell_states[coord] = occupant

        self.canvas.tag_raise("stone")
        self.update_remove_button()

        # Update player panels
        if hasattr(self, 'player1_panel'):
            self.player1_panel.set_stone_count(player1_stones)
            self.player2_panel.set_stone_count(player2_stones)

    def update_status(self) -> None:
        if not hasattr(self, 'status_var'):
            return

        token = "X" if self.game.current_player == 1 else "O"

        # CPU mode specific status
        if self._game_mode == "cpu" and self.game.current_player == 2:
            if self._ai_thinking:
                difficulty_name = self._ai_player.get_difficulty_name() if self._ai_player else ""
                self.status_var.set(f"CPU（{difficulty_name}）が考え中...")
            else:
                self.status_var.set(f"CPUの番（{token}）")
        else:
            if self.game.current_player == 2 and self.game.can_remove():
                action_hint = " - 石を置くか無効化できます"
            else:
                action_hint = " - 石を置いてください"

            if self._game_mode == "cpu":
                self.status_var.set(f"あなたの番（{token}）{action_hint}")
            else:
                self.status_var.set(f"プレイヤー{self.game.current_player}（{token}）の番{action_hint}")

        # Update player panels
        if hasattr(self, 'player1_panel'):
            self.player1_panel.set_active(self.game.current_player == 1)
            self.player2_panel.set_active(self.game.current_player == 2)
            self.player2_panel.set_can_neutralize(
                self.game.can_remove(),
                self.game.removal_used[2]
            )

    def update_remove_button(self) -> None:
        if not hasattr(self, 'neutralize_button'):
            return

        if self.game.current_player == 2 and self.game.can_remove():
            self.neutralize_button.set_state("normal")
        else:
            self.neutralize_button.set_state("disabled")

    def on_canvas_configure(self, event: tk.Event) -> None:
        if event.width <= 1 or event.height <= 1:
            return
        self._update_hex_size(event.width, event.height)
        self._draw_board()
        self.update_board()

    def _hex_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))

    def _rgb_to_hex(self, rgb: Tuple[float, float, float]) -> str:
        return "#" + "".join(
            f"{int(max(0, min(255, round(component)))):02x}" for component in rgb
        )

    def _interpolate_color(self, start_color: str, end_color: str, factor: float) -> str:
        start_r, start_g, start_b = self._hex_to_rgb(start_color)
        end_r, end_g, end_b = self._hex_to_rgb(end_color)
        rgb = (
            start_r + (end_r - start_r) * factor,
            start_g + (end_g - start_g) * factor,
            start_b + (end_b - start_b) * factor,
        )
        return self._rgb_to_hex(rgb)

    def _start_fill_animation(
        self, item_id: int, start_color: str, end_color: str,
        duration_ms: int = 250, hide_after: bool = False
    ) -> None:
        key = (item_id, "color")
        if key in self._active_tweens:
            self._active_tweens[key].cancel()
        self.canvas.itemconfig(item_id, fill=start_color, state=tk.NORMAL)
        self._target_stone_colors[item_id] = end_color

        def update(progress: float) -> None:
            eased = ease_out_quad(progress)
            color = self._interpolate_color(start_color, end_color, eased)
            self.canvas.itemconfig(item_id, fill=color)

        def finish() -> None:
            self.canvas.itemconfig(item_id, fill=end_color)
            if hide_after:
                bounds = self._stone_bounds.get(item_id)
                if bounds:
                    self.canvas.coords(item_id, *bounds)
                self.canvas.itemconfig(item_id, state=tk.HIDDEN)
            self._active_tweens.pop(key, None)

        tween = Tween(self.canvas, duration_ms, update, on_complete=finish)
        self._active_tweens[key] = tween
        tween.start()

    def _stop_line_highlight(self) -> None:
        if self._line_highlight_tween is not None:
            self._line_highlight_tween.cancel()
        for item in self._line_animation_items:
            base_color = self._base_line_colors.get(item)
            if base_color:
                self.canvas.itemconfig(item, fill=base_color)
        self._line_animation_items.clear()
        self._base_line_colors.clear()
        self._line_animation_cycle = 0
        self._line_highlight_tween = None

    def _animate_line_highlight(self, coords: List[AxialCoord]) -> None:
        self._stop_line_highlight()
        items = [self.stone_items[c] for c in coords if c in self.stone_items]
        if not items:
            return
        self._line_animation_items = items
        self._base_line_colors = {
            item: self._target_stone_colors.get(item, self.canvas.itemcget(item, "fill"))
            for item in items
        }
        for item in items:
            self.canvas.tag_raise(item)
        self._line_animation_cycle = 0
        self._run_line_highlight_cycle(self.theme.highlight_color)

    def _run_line_highlight_cycle(self, highlight_color: str) -> None:
        if not self._line_animation_items:
            return
        base_colors = self._base_line_colors
        items = list(self._line_animation_items)

        def forward_complete() -> None:
            self._line_highlight_tween = Tween(
                self.canvas, 260,
                lambda progress: self._update_line_colors(items, highlight_color, base_colors, progress),
                on_complete=backward_complete
            )
            self._line_highlight_tween.start()

        def backward_complete() -> None:
            self._line_animation_cycle += 1
            if self._line_animation_cycle < 3:
                self.root.after(140, lambda: self._run_line_highlight_cycle(highlight_color))
            else:
                for item in items:
                    base = base_colors.get(item)
                    if base:
                        self.canvas.itemconfig(item, fill=base)
                self._line_animation_items.clear()
                self._line_highlight_tween = None

        self._line_highlight_tween = Tween(
            self.canvas, 260,
            lambda progress: self._update_line_colors(items, base_colors, highlight_color, progress),
            on_complete=forward_complete
        )
        self._line_highlight_tween.start()

    def _update_line_colors(
        self, items: List[int],
        start_colors: Union[Dict[int, str], str],
        end_colors: Union[Dict[int, str], str],
        progress: float
    ) -> None:
        eased = ease_out_quad(progress)
        for item in items:
            start_color = start_colors[item] if isinstance(start_colors, dict) else start_colors
            end_color = end_colors[item] if isinstance(end_colors, dict) else end_colors
            color = self._interpolate_color(start_color, end_color, eased)
            self.canvas.itemconfig(item, fill=color)

    def _show_reset_button(self) -> None:
        if not self._reset_button_visible:
            self.reset_button.pack(side="left", padx=5)
            self._reset_button_visible = True

    def _hide_reset_button(self) -> None:
        if self._reset_button_visible:
            self.reset_button.pack_forget()
            self._reset_button_visible = False


def _print_instructions(game: Hex3TabooGame) -> None:
    print("Hex 3-Taboo CLI プロトタイプ")
    print("盤の半径:", game.board.radius)
    print("座標は軸座標 (q, r) で指定します。例: place 0 0")
    print("プレイヤー1はX、プレイヤー2はOを使用します。プレイヤー2は1回だけ相手の最後の石を無効化できます。")


def run_cli(radius: int = 4, ai_difficulty: Optional[str] = None) -> None:
    game = Hex3TabooGame(radius=radius)
    ai_player: Optional[AIPlayer] = None

    if ai_difficulty:
        ai_player = AIPlayer(difficulty=ai_difficulty, player_id=2)
        print(f"CPU対戦モード（難易度: {ai_player.get_difficulty_name()}）")
    else:
        print("対人対戦モード")

    _print_instructions(game)

    while True:
        print(game.board.render())

        # AI's turn
        if ai_player and game.current_player == 2:
            print(f"CPU（{ai_player.get_difficulty_name()}）が考え中...")
            action, coord = ai_player.choose_action(game)
            acting_player = game.current_player

            try:
                if action == "remove":
                    removed = game.remove_last_opponent_stone()
                    print(f"CPUが石{removed}を無効化しました。")
                elif action == "place" and coord:
                    game.place_stone(coord)
                    print(f"CPUが{coord}に石を置きました。")
            except Exception:
                # Fallback to random move
                empty = game.board.empty_cells()
                forbidden = game.forbidden_placements.get(game.current_player)
                valid = [c for c in empty if c != forbidden]
                if valid:
                    coord = random.choice(valid)
                    game.place_stone(coord)
                    print(f"CPUが{coord}に石を置きました。")

            result = game.check_game_end()
            if result:
                outcome, message = result
                print(game.board.render())
                print(message)
                if game.last_detected_line:
                    print("ライン座標:", game.last_detected_line)
                break
            game.switch_player()
            continue

        # Human player's turn
        try:
            command = input(game.format_prompt())
        except EOFError:
            print("\nゲームを中断しました。")
            break
        try:
            acting_player = game.current_player
            result = game.take_turn(command)
        except Exception as exc:
            print(f"エラー: {exc}")
            continue
        else:
            if (
                game.history
                and game.history[-1].action == "disable"
                and game.history[-1].player == acting_player
            ):
                coord = game.history[-1].coordinate
                if coord is not None:
                    print(f"相手の石{coord}を無効化しました。")
        if result:
            outcome, message = result
            print(game.board.render())
            print(message)
            if game.last_detected_line:
                print("ライン座標:", game.last_detected_line)
            break


def run_gui(radius: int = 4, theme: str = "light") -> None:
    try:
        game = Hex3TabooGame(radius=radius)
        gui = Hex3TabooGUI(game, theme_name=theme)
        gui.run()
    except Exception as exc:
        print(f"エラー: GUIの初期化に失敗しました: {exc}")
        print()
        print("macOSをお使いの場合、システム付属のPythonではTkinterが")
        print("正常に動作しないことがあります。")
        print()
        print("解決方法:")
        print("  1. python.org から最新のPythonをダウンロードしてインストール")
        print("     https://www.python.org/downloads/")
        print("  2. または Homebrew を使用:")
        print("     brew install python-tk")
        print()
        print("CLIモードで実行する場合は: python hex3_taboo.py --mode cli")
        sys.exit(1)


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Hex 3-Taboo プロトタイプ")
    parser.add_argument("--radius", type=int, default=4, help="盤の半径 (既定値: 4)")
    parser.add_argument(
        "--mode", choices=("cli", "gui"), default="cli",
        help="CLI または GUI モードで実行します。"
    )
    parser.add_argument(
        "--theme", choices=list(THEMES.keys()), default="light",
        help="GUIのテーマを選択します (既定値: light)"
    )
    parser.add_argument(
        "--ai", choices=("easy", "medium", "hard"), default=None,
        help="CPU対戦モード（難易度を指定）。指定しない場合は対人対戦。"
    )
    args = parser.parse_args(argv)

    if args.mode == "gui":
        if tk is None:
            print("エラー: Tkinterが利用できないため、GUIモードを起動できません。")
            print()
            print("Tkinterをインストールするには:")
            print("  - Ubuntu/Debian: sudo apt-get install python3-tk")
            print("  - Fedora: sudo dnf install python3-tkinter")
            print("  - macOS: Pythonに同梱されています（python.orgからインストールしてください）")
            print("  - Windows: Pythonインストーラーで「tcl/tk and IDLE」を選択してください")
            print()
            print("CLIモードで実行する場合は: python hex3_taboo.py --mode cli")
            sys.exit(1)
        run_gui(radius=args.radius, theme=args.theme)
    else:
        run_cli(radius=args.radius, ai_difficulty=args.ai)


if __name__ == "__main__":
    main(sys.argv[1:])
