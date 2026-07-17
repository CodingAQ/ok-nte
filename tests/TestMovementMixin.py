from collections import deque
import unittest

from src.tasks.mixin.MovementMixin import LATERAL_DIRECTION_CHANGE_WINDOW, MovementMixin


class TestMovementMixin(unittest.TestCase):
    def test_frequent_lateral_direction_triggers_after_four_fast_lateral_decisions(self):
        changes = deque()

        self.assertFalse(
            MovementMixin._has_frequent_lateral_direction("a", changes, now=0.0)
        )
        self.assertFalse(
            MovementMixin._has_frequent_lateral_direction("d", changes, now=0.1)
        )
        self.assertFalse(
            MovementMixin._has_frequent_lateral_direction("s", changes, now=0.2)
        )
        self.assertFalse(
            MovementMixin._has_frequent_lateral_direction("a", changes, now=0.3)
        )
        self.assertTrue(
            MovementMixin._has_frequent_lateral_direction("d", changes, now=0.4)
        )

    def test_frequent_lateral_direction_expires_but_keeps_counts_across_vertical_moves(self):
        changes = deque([0.0, 0.1, 0.2])
        after_window = LATERAL_DIRECTION_CHANGE_WINDOW + 0.5

        self.assertFalse(
            MovementMixin._has_frequent_lateral_direction("a", changes, now=after_window)
        )
        self.assertEqual(deque([after_window]), changes)

        self.assertFalse(
            MovementMixin._has_frequent_lateral_direction("s", changes, now=after_window + 0.1)
        )
        self.assertEqual(deque([after_window]), changes)


if __name__ == "__main__":
    unittest.main()
