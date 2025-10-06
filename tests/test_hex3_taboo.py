import unittest

from hex3_taboo import Hex3TabooGame, HexBoard


class HexBoardTests(unittest.TestCase):
    def test_generate_coordinates_count(self):
        board = HexBoard(radius=4)
        # Known formula for number of cells in hex board of radius r: 1 + 3r(r+1)
        expected_cells = 1 + 3 * 4 * 5
        self.assertEqual(len(board.cells), expected_cells)

    def test_is_valid_and_get_set(self):
        board = HexBoard(radius=2)
        coord = (0, 0)
        self.assertTrue(board.is_valid(coord))
        self.assertIsNone(board.get(coord))
        board.set(coord, 1)
        self.assertEqual(board.get(coord), 1)
        with self.assertRaises(ValueError):
            board.get((5, 5))
        with self.assertRaises(ValueError):
            board.set((5, 5), None)


class Hex3TabooGameTests(unittest.TestCase):
    def test_loss_on_isolated_three(self):
        game = Hex3TabooGame(radius=3)
        # Sequence creates a vertical line of exactly three stones for player 1
        commands = [
            "place 0 0",
            "place 1 -1",
            "place 0 1",
            "place 1 0",
            "place 0 -1",
        ]
        result = None
        for command in commands:
            result = game.take_turn(command)
        self.assertIsNotNone(result)
        outcome, message = result
        self.assertEqual(outcome, "loss")
        self.assertIn("敗北", message)
        self.assertEqual(game.current_player, 1)

    def test_win_on_four_in_a_row(self):
        game = Hex3TabooGame(radius=3)
        commands = [
            "place 0 0",
            "place 2 -1",
            "place 0 1",
            "place 2 0",
            "place 0 -1",
            "place 2 1",
            "place 0 -2",
        ]
        result = None
        for command in commands:
            result = game.take_turn(command)
        self.assertIsNotNone(result)
        outcome, message = result
        self.assertEqual(outcome, "win")
        self.assertIn("勝利", message)
        self.assertEqual(game.current_player, 1)

    def test_second_player_can_remove_only_once(self):
        game = Hex3TabooGame(radius=2)
        game.take_turn("place 0 0")  # player 1
        game.take_turn("place 1 0")  # player 2
        game.take_turn("place -1 0")  # player 1
        # Player 2 can remove the last move (player 1's stone)
        result = game.take_turn("remove")
        self.assertIsNone(result)
        self.assertIsNone(game.board.get((-1, 0)))
        # Back to player 2 after an additional move
        game.take_turn("place 0 1")  # player 1 places, no immediate loss
        with self.assertRaises(ValueError):
            game.take_turn("remove")  # player 2 already spent the removal

    def test_can_remove_conditions(self):
        game = Hex3TabooGame(radius=2)
        self.assertFalse(game.can_remove())  # player 1's turn
        game.take_turn("place 0 0")  # player 1
        self.assertTrue(game.can_remove())   # player 2 may remove immediately
        game.take_turn("place 1 0")  # player 2 opts to place instead
        self.assertFalse(game.can_remove())  # player 1 cannot remove
        game.take_turn("place -1 0")  # player 1
        self.assertTrue(game.can_remove())   # player 2 can remove once more
        game.take_turn("remove")
        self.assertFalse(game.can_remove())  # player 1 turn
        game.take_turn("place 0 1")  # player 1
        self.assertFalse(game.can_remove())  # player 2 already used the removal


if __name__ == "__main__":
    unittest.main()
