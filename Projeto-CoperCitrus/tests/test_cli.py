import argparse
import unittest
from unittest.mock import patch

from copercitrus_price_collector.cli import main


class CliKeyboardInterruptTest(unittest.TestCase):
    @patch("copercitrus_price_collector.cli._parser")
    def test_main_handles_keyboard_interrupt(self, parser_mock):
        parser_mock.return_value.parse_args.side_effect = KeyboardInterrupt()

        result = main([])

        self.assertEqual(130, result)


if __name__ == "__main__":
    unittest.main()
