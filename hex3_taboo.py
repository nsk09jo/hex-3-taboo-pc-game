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

from dataclasses import dataclass
import math
import sys
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import messagebox
except Exception:  # pragma: no cover - Tk may be unavailable on some systems
    tk = None
    messagebox = None


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
        self.last_detected_outcome: Optional[str] = None

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
        self.last_detected_outcome = None
        if has_win and winning_line:
            self.last_detected_line = winning_line.copy()
            self.last_detected_outcome = "win"
            return (
                "win",
                f"プレイヤー{self.current_player}が4つ以上の連結で勝利しました。",
            )
        if has_loss and losing_line:
            self.last_detected_line = losing_line.copy()
            self.last_detected_outcome = "loss"
            return (
                "loss",
                f"プレイヤー{self.current_player}は孤立した3連で敗北しました。",
            )
        if self.board.is_full():
            self.last_detected_outcome = "draw"
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


class Hex3TabooGUI:
    """Simple Tkinter-based interface for playing Hex 3-Taboo."""

    DEFAULT_HEX_SIZE = 30
    BOARD_BACKGROUND_TOP = "#f3f7ff"
    BOARD_BACKGROUND_BOTTOM = "#dce6f6"
    CELL_BASE_COLOR = "#fefefe"
    CELL_ACCENT_COLOR = "#e1e9f5"
    CELL_EDGE_COLOR = "#9da7b7"
    PLAYER_COLORS = {1: "#d64550", 2: "#4072b0"}
    PLAYER_OUTLINES = {1: "#7e1b26", 2: "#123b66"}
    DISABLED_STONE_COLOR = "#aab0bc"
    DISABLED_OUTLINE_COLOR = "#5b626f"
    EMPTY_STONE_COLOR = "#f5f5f5"
    OUTLINE_COLOR = "#4a4a4a"
    HOVER_OUTLINE_COLOR = "#ffb347"
    HOVER_FILL_BLEND = 0.18
    SHADOW_COLOR = "#2a2e45"
    SHADOW_OFFSET = (3, 4)
    COORD_TEXT_COLOR = "#6f7d95"
    HIGHLIGHT_COLORS = {"win": "#ffd166", "loss": "#ff7b7b", "draw": "#70d6ff"}
    LINE_ANIMATION_INTERVAL_MS = 120
    LINE_ANIMATION_STEP = math.pi / 22

    def __init__(self, game: Hex3TabooGame) -> None:
        if tk is None:
            raise RuntimeError("Tkinter is not available in this environment.")

        self.game = game
        self.board_radius = game.board.radius
        self.root = tk.Tk()
        self.root.title("ヘックス3-タブー")

        self.status_var = tk.StringVar()
        status_label = tk.Label(self.root, textvariable=self.status_var, font=("Helvetica", 12))
        status_label.pack(pady=6)

        self.canvas = tk.Canvas(self.root, background="white", highlightthickness=0)
        self.canvas.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self.on_canvas_configure)

        controls = tk.Frame(self.root)
        controls.pack(pady=4)

        self.remove_button = tk.Button(
            controls,
            text="相手の最後の石を無効化",
            command=self.on_remove,
            state=tk.DISABLED,
        )
        self.remove_button.pack()

        self.reset_button = tk.Button(
            controls,
            text="ゲームをリセット",
            command=self.reset_game,
        )
        self._reset_button_visible = False

        self.hex_size: float = self.DEFAULT_HEX_SIZE
        self.cell_items: Dict[int, AxialCoord] = {}
        self.coord_to_item: Dict[AxialCoord, int] = {}
        self.cell_shadows: Dict[AxialCoord, int] = {}
        self._tile_base_colors: Dict[AxialCoord, str] = {}
        self._cell_states: Dict[AxialCoord, Optional[int]] = {
            coord: None for coord in self.game.board.cells
        }
        self._target_cell_colors: Dict[int, str] = {}
        self._active_tweens: Dict[Tuple[int, str], Tween] = {}
        self._line_animation_items: List[int] = []
        self._base_line_colors: Dict[int, str] = {}
        self._line_highlight_job: Optional[str] = None
        self._line_highlight_color: str = self.HIGHLIGHT_COLORS["win"]
        self._line_animation_phase: float = 0.0
        self._hovered_item: Optional[int] = None
        self._draw_board()
        self.update_board()
        self.update_status()

    def run(self) -> None:
        self.root.mainloop()

    def _draw_background(self, width: int, height: int) -> None:
        steps = 24
        for step in range(steps):
            factor_top = step / steps
            factor_bottom = (step + 1) / steps
            color = self._interpolate_color(
                self.BOARD_BACKGROUND_TOP,
                self.BOARD_BACKGROUND_BOTTOM,
                (factor_top + factor_bottom) / 2,
            )
            y0 = height * factor_top
            y1 = height * factor_bottom
            self.canvas.create_rectangle(0, y0, width, y1, fill=color, outline="")
        border_color = self._interpolate_color(
            self.BOARD_BACKGROUND_BOTTOM, "#9fb0c9", 0.25
        )
        self.canvas.create_rectangle(
            2,
            2,
            width - 2,
            height - 2,
            outline=border_color,
            width=3,
        )

    def _compute_tile_color(self, coord: AxialCoord) -> str:
        radius = max(1, self.board_radius)
        normalized_q = (coord[0] + radius) / (2 * radius)
        normalized_r = (coord[1] + radius) / (2 * radius)
        wave = (math.sin((coord[0] - coord[1]) * math.pi / 3) + 1.0) / 2.0
        blend = (normalized_q + normalized_r + wave) / 3.0
        blend = max(0.0, min(1.0, blend * 0.6))
        return self._interpolate_color(self.CELL_BASE_COLOR, self.CELL_ACCENT_COLOR, blend)

    def _tile_hover_color(self, coord: AxialCoord) -> str:
        base = self._tile_base_colors.get(coord, self.CELL_BASE_COLOR)
        return self._interpolate_color(base, "#ffffff", self.HOVER_FILL_BLEND)

    def _target_color_for_state(
        self, coord: AxialCoord, occupant: Optional[int]
    ) -> str:
        base = self._tile_base_colors.get(coord, self.CELL_BASE_COLOR)
        if occupant is None:
            return base
        if occupant == HexBoard.DISABLED_STONE:
            return self.DISABLED_STONE_COLOR
        return self.PLAYER_COLORS.get(occupant, base)

    def _outline_for_state(self, occupant: Optional[int]) -> str:
        if occupant is None:
            return self.CELL_EDGE_COLOR
        if occupant == HexBoard.DISABLED_STONE:
            return self.DISABLED_OUTLINE_COLOR
        return self.PLAYER_OUTLINES.get(occupant, self.CELL_EDGE_COLOR)

    def _current_fill_color(self, coord: AxialCoord) -> str:
        return self._target_color_for_state(coord, self.game.board.cells[coord])

    def _current_outline_color(self, coord: AxialCoord) -> str:
        return self._outline_for_state(self.game.board.cells[coord])

    def _hover_fill_color(self, coord: AxialCoord) -> str:
        occupant = self.game.board.cells[coord]
        if occupant is None:
            return self._tile_hover_color(coord)
        base = self._target_color_for_state(coord, occupant)
        blend = 0.22 if occupant != HexBoard.DISABLED_STONE else 0.16
        return self._interpolate_color(base, "#ffffff", blend)

    def _draw_board(self) -> None:
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
        self._tile_base_colors.clear()
        self._target_cell_colors.clear()
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
                shadow_points,
                outline="",
                fill=self.SHADOW_COLOR,
                stipple="gray50",
                tags=("shadow",),
            )
            self.cell_shadows[coord] = shadow_item

            tile_color = self._compute_tile_color(coord)
            self._tile_base_colors[coord] = tile_color
            item = self.canvas.create_polygon(
                shifted_points,
                outline=self.CELL_EDGE_COLOR,
                fill=tile_color,
                width=2,
                joinstyle=tk.ROUND,
                tags=("cell",),
            )
            self.cell_items[item] = coord
            self.coord_to_item[coord] = item

            center_x = x + offset_x
            center_y = y + offset_y
            self._target_cell_colors[item] = tile_color

            label_font_size = max(8, int(self.hex_size * 0.26))
            label = self.canvas.create_text(
                center_x,
                center_y + self.hex_size * 0.62,
                text=f"{coord[0]},{coord[1]}",
                fill=self.COORD_TEXT_COLOR,
                font=("Helvetica", label_font_size, "bold"),
                tags=("coord_label",),
            )
            self.canvas.itemconfig(label, state=tk.DISABLED)
            self.canvas.tag_lower(label)

        self.canvas.tag_lower("shadow")
        self.canvas.tag_lower("coord_label")
        self.canvas.tag_bind("cell", "<Button-1>", self._handle_cell_click)
        self.canvas.tag_bind("cell", "<Enter>", self._handle_cell_enter)
        self.canvas.tag_bind("cell", "<Leave>", self._handle_cell_leave)

    def _handle_cell_click(self, event: tk.Event) -> None:  # type: ignore[override]
        current = event.widget.find_withtag("current")
        if not current:
            return
        coord = self.cell_items.get(current[0])
        if coord is not None:
            self.on_cell_clicked(coord)

    def _handle_cell_enter(self, event: tk.Event) -> None:  # type: ignore[override]
        current = event.widget.find_withtag("current")
        if not current:
            return
        self._on_cell_enter(current[0])

    def _handle_cell_leave(self, event: tk.Event) -> None:  # type: ignore[override]
        current = event.widget.find_withtag("current")
        if not current:
            return
        self._on_cell_leave(current[0])

    def _on_cell_enter(self, item_id: int) -> None:
        if self._hovered_item == item_id:
            return
        coord = self.cell_items.get(item_id)
        if coord is None:
            return
        self._hovered_item = item_id
        hover_color = self._hover_fill_color(coord)
        self.canvas.itemconfig(
            item_id,
            fill=hover_color,
            outline=self.HOVER_OUTLINE_COLOR,
            width=3,
        )

    def _on_cell_leave(self, item_id: int) -> None:
        if self._hovered_item != item_id:
            return
        coord = self.cell_items.get(item_id)
        if coord is None:
            return
        self._hovered_item = None
        base_color = self._current_fill_color(coord)
        outline_color = self._current_outline_color(coord)
        outline_width = 2 if self.game.board.cells[coord] is None else 3
        self.canvas.itemconfig(
            item_id,
            fill=base_color,
            outline=outline_color,
            width=outline_width,
            dash=(3, 2)
            if self.game.board.cells[coord] == HexBoard.DISABLED_STONE
            else None,
        )

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
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
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
        target_size = max(5.0, scale * 0.9)
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
        self._finalize_turn(acting_player)

    def on_remove(self) -> None:
        try:
            acting_player = self.game.current_player
            removed = self.game.remove_last_opponent_stone()
        except Exception as exc:
            if messagebox is not None:
                messagebox.showinfo("無効化できません", str(exc))
            return
        if removed is not None and messagebox is not None:
            messagebox.showinfo("無効化", f"{removed}の石を無効化しました。")
        self._finalize_turn(acting_player)

    def _finalize_turn(self, acting_player: int) -> None:
        result = self.game.check_game_end()
        self.update_board()
        if result:
            outcome, message = result
            line_coords = self.game.last_detected_line
            self.status_var.set(message)
            self.remove_button.config(state=tk.DISABLED)
            if messagebox is not None:
                messagebox.showinfo("ゲーム終了", message)
            if self._hovered_item is not None:
                self._on_cell_leave(self._hovered_item)
            self.canvas.tag_unbind("cell", "<Button-1>")
            if line_coords:
                highlight_color = self._highlight_color_for_outcome(outcome)
                self._animate_line_highlight(line_coords, highlight_color)
            self._show_reset_button()
            return
        self.game.switch_player()
        self.update_status()
        self.update_remove_button()

    def reset_game(self) -> None:
        """Reset the board for a new game."""
        self._hide_reset_button()
        self.game = Hex3TabooGame(radius=self.board_radius)
        self._cell_states = {coord: None for coord in self.game.board.cells}
        self._target_cell_colors.clear()
        self._active_tweens.clear()
        self._stop_line_highlight()
        self._draw_board()
        self.update_board()
        self.update_status()

    def update_board(self) -> None:
        for coord, item_id in self.coord_to_item.items():
            occupant = self.game.board.cells[coord]
            target_color = self._target_color_for_state(coord, occupant)
            target_outline = self._outline_for_state(occupant)
            previous = self._cell_states.get(coord)
            previous_color = self._target_color_for_state(coord, previous)
            dash_pattern = (3, 2) if occupant == HexBoard.DISABLED_STONE else None

            if previous is None and occupant is None:
                self.canvas.itemconfig(
                    item_id,
                    fill=target_color,
                    outline=self.CELL_EDGE_COLOR,
                    width=2,
                    dash=None,
                )
            elif previous == occupant:
                self.canvas.itemconfig(
                    item_id,
                    fill=target_color,
                    outline=target_outline,
                    width=3 if occupant is not None else 2,
                    dash=dash_pattern,
                )
            else:
                self.canvas.itemconfig(
                    item_id,
                    outline=target_outline,
                    width=3 if occupant is not None else 2,
                    dash=dash_pattern,
                )
                self._start_fill_animation(item_id, previous_color, target_color)

            self._target_cell_colors[item_id] = target_color
            self._cell_states[coord] = occupant
        self.update_remove_button()

    def update_status(self) -> None:
        token = "X" if self.game.current_player == 1 else "O"
        if self.game.current_player == 2 and self.game.can_remove():
            action_hint = "：石を置くか無効化できます"
        else:
            action_hint = "：石を置いてください"
        self.status_var.set(f"プレイヤー{self.game.current_player}（{token}）{action_hint}")

    def update_remove_button(self) -> None:
        if self.game.current_player == 2 and self.game.can_remove():
            self.remove_button.config(state=tk.NORMAL)
        else:
            self.remove_button.config(state=tk.DISABLED)

    def on_canvas_configure(self, event: tk.Event) -> None:  # type: ignore[override]
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

    def _interpolate_color(
        self, start_color: str, end_color: str, factor: float
    ) -> str:
        start_r, start_g, start_b = self._hex_to_rgb(start_color)
        end_r, end_g, end_b = self._hex_to_rgb(end_color)
        rgb = (
            start_r + (end_r - start_r) * factor,
            start_g + (end_g - start_g) * factor,
            start_b + (end_b - start_b) * factor,
        )
        return self._rgb_to_hex(rgb)

    def _start_fill_animation(
        self,
        item_id: int,
        start_color: str,
        end_color: str,
        duration_ms: int = 250,
    ) -> None:
        key = (item_id, "color")
        if key in self._active_tweens:
            self._active_tweens[key].cancel()
        self.canvas.itemconfig(item_id, fill=start_color, state=tk.NORMAL)
        self._target_cell_colors[item_id] = end_color

        def update(progress: float) -> None:
            eased = ease_out_quad(progress)
            color = self._interpolate_color(start_color, end_color, eased)
            self.canvas.itemconfig(item_id, fill=color)

        def finish() -> None:
            self.canvas.itemconfig(item_id, fill=end_color)
            self._active_tweens.pop(key, None)

        tween = Tween(self.canvas, duration_ms, update, on_complete=finish)
        self._active_tweens[key] = tween
        tween.start()

    def _stop_line_highlight(self) -> None:
        if self._line_highlight_job is not None:
            try:
                self.root.after_cancel(self._line_highlight_job)
            except Exception:
                pass
            self._line_highlight_job = None
        for item in self._line_animation_items:
            base_color = self._base_line_colors.get(item)
            if base_color:
                self.canvas.itemconfig(item, fill=base_color)
        self._line_animation_items.clear()
        self._base_line_colors.clear()
        self._line_animation_phase = 0.0
        self._line_highlight_job = None
        self._line_highlight_color = self.HIGHLIGHT_COLORS["win"]

    def _highlight_color_for_outcome(self, outcome: str) -> str:
        if outcome in self.HIGHLIGHT_COLORS:
            return self.HIGHLIGHT_COLORS[outcome]
        return self.HIGHLIGHT_COLORS["win"]

    def _animate_line_highlight(self, coords: List[AxialCoord], highlight_color: str) -> None:
        self._stop_line_highlight()
        items = [self.coord_to_item[c] for c in coords if c in self.coord_to_item]
        if not items:
            return
        self._line_animation_items = items
        self._base_line_colors = {
            item: self._target_cell_colors.get(item, self.canvas.itemcget(item, "fill"))
            for item in items
        }
        self._line_highlight_color = highlight_color
        self._line_animation_phase = 0.0
        for item in items:
            self.canvas.tag_raise(item)
        self._run_line_highlight_cycle()

    def _run_line_highlight_cycle(self) -> None:
        if not self._line_animation_items:
            return

        intensity = 0.5 - 0.5 * math.cos(self._line_animation_phase)
        for item in self._line_animation_items:
            base = self._base_line_colors.get(item, self._line_highlight_color)
            color = self._interpolate_color(base, self._line_highlight_color, intensity)
            self.canvas.itemconfig(item, fill=color)

        self._line_animation_phase = (
            self._line_animation_phase + self.LINE_ANIMATION_STEP
        ) % (2 * math.pi)
        self._line_highlight_job = self.root.after(
            self.LINE_ANIMATION_INTERVAL_MS, self._run_line_highlight_cycle
        )

    def _show_reset_button(self) -> None:
        if not self._reset_button_visible:
            self.reset_button.pack(pady=(6, 0))
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


def run_cli(radius: int = 4) -> None:
    game = Hex3TabooGame(radius=radius)
    _print_instructions(game)
    while True:
        print(game.board.render())
        try:
            command = input(game.format_prompt())
        except EOFError:
            print("\nゲームを中断しました。")
            break
        try:
            acting_player = game.current_player
            result = game.take_turn(command)
        except Exception as exc:  # broad for CLI feedback
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


def run_gui(radius: int = 4) -> None:
    game = Hex3TabooGame(radius=radius)
    gui = Hex3TabooGUI(game)
    gui.run()


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Hex 3-Taboo プロトタイプ")
    parser.add_argument("--radius", type=int, default=4, help="盤の半径 (既定値: 4)")
    parser.add_argument(
        "--mode",
        choices=("cli", "gui"),
        default="cli",
        help="CLI または GUI モードで実行します。",
    )
    args = parser.parse_args(argv)

    if args.mode == "gui":
        if tk is None:
            raise RuntimeError("Tkinter is not available; GUI mode cannot be used.")
        run_gui(radius=args.radius)
    else:
        run_cli(radius=args.radius)


if __name__ == "__main__":
    main(sys.argv[1:])
