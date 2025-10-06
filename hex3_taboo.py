"""Command-line prototype for the Hex 3-Taboo board game.

This module implements the core rules described in the README:
- A hexagonal board with a configurable radius (default 4).
- Two players alternately place stones on empty cells.
- The second player may use a single removal action per game to remove the
  opponent's last placed stone instead of placing.
- After each turn we evaluate for a winning line (length >= 4) or a losing
  line (exactly length 3). Wins take precedence over losses.

The module exposes a ``Hex3TabooGame`` class for programmatic use and provides
an interactive command-line loop when executed as a script.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


AxialCoord = Tuple[int, int]


@dataclass(frozen=True)
class Move:
    """Record of a single action in the game history."""

    player: int
    action: str  # "place" or "remove"
    coordinate: Optional[AxialCoord]


class HexBoard:
    """Hexagonal board represented using axial coordinates."""

    AXIAL_DIRECTIONS: Tuple[AxialCoord, ...] = ((1, 0), (0, 1), (-1, 1))

    def __init__(self, radius: int = 4) -> None:
        if radius < 1:
            raise ValueError("Radius must be at least 1")
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
            raise ValueError(f"Coordinate {coord} is outside the board")
        return self.cells[coord]

    def set(self, coord: AxialCoord, value: Optional[int]) -> None:
        if not self.is_valid(coord):
            raise ValueError(f"Coordinate {coord} is outside the board")
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

    def switch_player(self) -> None:
        self.current_player = 1 if self.current_player == 2 else 2

    def place_stone(self, coord: AxialCoord) -> None:
        if not self.board.is_valid(coord):
            raise ValueError("Cannot place outside the board")
        if self.board.get(coord) is not None:
            raise ValueError("Cell already occupied")
        self.board.set(coord, self.current_player)
        self.history.append(Move(self.current_player, "place", coord))
        self.last_placed[self.current_player] = coord

    def can_remove(self) -> bool:
        """Return True if the current player can perform a removal action."""
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
        if not self.can_remove():
            raise ValueError("Removal not available")
        last_move = self.history[-1]
        assert last_move.coordinate is not None
        self.board.set(last_move.coordinate, None)
        self.history.append(Move(self.current_player, "remove", last_move.coordinate))
        self.removal_used[self.current_player] = True
        # After removal, the opponent no longer has this stone as their last placement.
        self.last_placed[last_move.player] = None
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

    def check_game_end(self) -> Optional[str]:
        """Evaluate the board and return a message if the game is over."""
        has_win, has_loss = self.evaluate_player_state(self.current_player)
        if has_win:
            return f"Player {self.current_player} wins with a line of four or more!"
        if has_loss:
            return f"Player {self.current_player} loses with an isolated three-in-a-row."
        if self.board.is_full():
            return "The board is full. The game is a draw."
        return None

    def take_turn(self, command: str) -> Optional[str]:
        """Process a command for the current player and return an end-state message."""
        parts = command.strip().split()
        if not parts:
            raise ValueError("Empty command")
        action = parts[0].lower()
        if action == "place":
            if len(parts) != 3:
                raise ValueError("Usage: place <q> <r>")
            q, r = int(parts[1]), int(parts[2])
            self.place_stone((q, r))
        elif action == "remove":
            if len(parts) != 1:
                raise ValueError("Usage: remove")
            removed = self.remove_last_opponent_stone()
            print(f"Removed opponent stone at {removed}.")
        else:
            raise ValueError("Unknown command. Use 'place q r' or 'remove'.")

        result = self.check_game_end()
        if result is not None:
            return result
        self.switch_player()
        return None

    def format_prompt(self) -> str:
        if self.current_player == 2 and self.can_remove():
            return "Player 2 (O) - enter 'place q r' or 'remove': "
        token = "X" if self.current_player == 1 else "O"
        return f"Player {self.current_player} ({token}) - enter 'place q r': "


def _print_instructions(game: Hex3TabooGame) -> None:
    print("Hex 3-Taboo CLI Prototype")
    print("Board radius:", game.board.radius)
    print("Coordinates use axial (q, r) pairs. Example: place 0 0")
    print("Player 1 uses X, Player 2 uses O. Player 2 may remove once per game.")


def main() -> None:
    game = Hex3TabooGame()
    _print_instructions(game)
    while True:
        print(game.board.render())
        try:
            command = input(game.format_prompt())
        except EOFError:
            print("\nGame aborted.")
            break
        try:
            result = game.take_turn(command)
        except Exception as exc:  # broad for CLI feedback
            print(f"Error: {exc}")
            continue
        if result:
            print(game.board.render())
            print(result)
            break


if __name__ == "__main__":
    main()
