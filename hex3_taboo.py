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
from typing import Dict, Iterable, List, Optional, Tuple

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

    def evaluate_player_state(self, player: int) -> Tuple[bool, bool]:
        """Return (has_winning_line, has_exact_three_line) for a player."""
        has_win = False
        has_loss = False
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
                cursor = coord
                while self.board.cells.get(cursor) == player:
                    length += 1
                    cursor = (cursor[0] + direction[0], cursor[1] + direction[1])
                end_coord = cursor
                # Determine whether the line is bounded by non-player stones/off-board.
                next_occupant = self.board.cells.get(end_coord)
                start_occupant = self.board.cells.get(prev_coord)
                if length >= 4:
                    has_win = True
                elif length == 3 and start_occupant != player and next_occupant != player:
                    has_loss = True
            if has_win:
                break
        return has_win, has_loss

    def check_game_end(self) -> Optional[GameOutcome]:
        """Evaluate the board and return (outcome, message) if the game is over."""
        has_win, has_loss = self.evaluate_player_state(self.current_player)
        if has_win:
            return "win", f"プレイヤー{self.current_player}が4つ以上の連結で勝利しました。"
        if has_loss:
            return "loss", f"プレイヤー{self.current_player}は孤立した3連で敗北しました。"
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


class Hex3TabooGUI:
    """Simple Tkinter-based interface for playing Hex 3-Taboo."""

    DEFAULT_HEX_SIZE = 30
    EMPTY_COLOR = "#f5f5f5"
    PLAYER_COLORS = {1: "#d64550", 2: "#4072b0"}
    OUTLINE_COLOR = "#4a4a4a"

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

        self.hex_size: float = self.DEFAULT_HEX_SIZE
        self.cell_items: Dict[int, AxialCoord] = {}
        self._draw_board()
        self.update_board()
        self.update_status()

    def run(self) -> None:
        self.root.mainloop()

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

        self.canvas.delete("all")
        self.cell_items.clear()

        for coord in coordinates:
            x, y = self._axial_to_pixel(coord)
            polygon_points = self._hexagon_points(x, y)
            shifted_points: List[float] = []
            for index, value in enumerate(polygon_points):
                if index % 2 == 0:
                    shifted_points.append(value + offset_x)
                else:
                    shifted_points.append(value + offset_y)
            item = self.canvas.create_polygon(
                shifted_points,
                outline=self.OUTLINE_COLOR,
                fill=self.EMPTY_COLOR,
                width=2,
                tags=("cell",),
            )
            self.canvas.tag_bind(item, "<Button-1>", lambda _event, c=coord: self.on_cell_clicked(c))
            self.cell_items[item] = coord

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
            self.status_var.set(message)
            self.remove_button.config(state=tk.DISABLED)
            if messagebox is not None:
                messagebox.showinfo("ゲーム終了", message)
            self.canvas.tag_unbind("cell", "<Button-1>")
            if outcome == "win":
                self.root.after(200, self.reset_game)
            return
        self.game.switch_player()
        self.update_status()
        self.update_remove_button()

    def reset_game(self) -> None:
        """Reset the board for a new game."""
        self.game = Hex3TabooGame(radius=self.board_radius)
        self._draw_board()
        self.update_board()
        self.update_status()

    def update_board(self) -> None:
        occupant_to_color = {
            None: self.EMPTY_COLOR,
            HexBoard.DISABLED_STONE: "#bdbdbd",
            1: self.PLAYER_COLORS[1],
            2: self.PLAYER_COLORS[2],
        }
        for item_id, coord in self.cell_items.items():
            occupant = self.game.board.cells[coord]
            self.canvas.itemconfig(item_id, fill=occupant_to_color[occupant])
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
