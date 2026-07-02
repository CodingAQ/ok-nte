# Test case
import unittest
from pathlib import Path

from ok.test.TaskTestCase import TaskTestCase

from src.config import config
from src.tasks.trigger.AutoCombatTask import AutoCombatTask


class TestCurrentChar(TaskTestCase):
    task_class = AutoCombatTask

    config = config

    def assert_current_char(self, image, expected_index, char_count=4):
        if not Path(image).exists():
            self.skipTest(f"{image} not found")

        self.set_image(image)
        self.logger.info(f"target {image}")
        self.task.in_team()
        self.assertEqual(self.task.get_current_char_index(char_count=char_count), expected_index)
        for index in range(4):
            result = self.task.is_char_at_index(index, char_count=char_count)
            self.assertEqual(
                result is True,
                index == expected_index,
                f"{image} index={index} "
                f"scores={self.task._get_char_match_scores(char_count=char_count)}",
            )

    def test_current_char_count_limits_candidates(self):
        image = "tests/images/current_char/current_1.png"
        if not Path(image).exists():
            self.skipTest(f"{image} not found")

        self.set_image(image)
        self.task._init_char_ui_state()
        self.assertLess(self.task.get_current_char_index(char_count=1), 1)
        self.assertEqual(self.task.get_current_char_index(char_count=2), 1)

    def test_current_char_temp_images(self):
        cases = [
            ("tests/images/02.png", 1),
            ("tests/images/01.png", 2),
            ("tests/images/current_char/current_0.png", 0),
            ("tests/images/current_char/current_1.png", 1),
            ("tests/images/current_char/current_2_covered.png", 2),
            ("tests/images/current_char/current_2_light.png", 2),
            ("tests/images/current_char/current_2_similar_back.png", 2),
            ("tests/images/current_char/current_2_low_conf.png", 2),
            ("tests/images/current_char/current_3_light_2.png", 3),
            ("tests/images/current_char/current_0_yellow.png", 0),
            ("tests/images/current_char/current_1_yellow.png", 1),
            ("tests/images/current_char/current_2_yellow.png", 2),
            ("tests/images/current_char/current_3_yellow.png", 3),
            ("tests/images/current_char/current_1_1_yellow.png", 1),
        ]
        for image, expected_index in cases:
            with self.subTest(image=image):
                self.assert_current_char(image, expected_index)


if __name__ == "__main__":
    unittest.main()
