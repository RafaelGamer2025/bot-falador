import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot


class BotHelperTests(unittest.TestCase):
    def test_extract_fact_uses_json_text_field(self):
        self.assertEqual(bot.extract_fact({"text": "  A fact\n from API.  ", "source": "example"}), "A fact from API.")

    def test_extract_fact_rejects_missing_or_invalid_text(self):
        self.assertIsNone(bot.extract_fact({"fact": "not the expected field"}))
        self.assertIsNone(bot.extract_fact({"text": "  \n "}))
        self.assertIsNone(bot.extract_fact(["not", "an object"]))

    def test_format_weather_builds_message_and_speech(self):
        payload = {
            "current_condition": [
                {
                    "temp_C": "18",
                    "FeelsLikeC": "17",
                    "weatherDesc": [{"value": "Light rain"}],
                    "humidity": "72",
                    "windspeedKmph": "9",
                }
            ]
        }
        result = bot.format_weather("Lisboa", payload)
        self.assertIsNotNone(result)
        message, speech = result
        self.assertIn("18 °C", message)
        self.assertIn("Umidade: 72%", message)
        self.assertIn("Light rain", speech)

    def test_format_weather_rejects_unexpected_payload(self):
        self.assertIsNone(bot.format_weather("Lisboa", {}))
        self.assertIsNone(bot.format_weather("Lisboa", {"current_condition": []}))

    def test_load_env_does_not_override_existing_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("DISCORD_TOKEN=file-token\nSAMPLE_VALUE='from-file'\n", encoding="utf-8")
            with patch.dict(os.environ, {"DISCORD_TOKEN": "existing-token"}, clear=False):
                bot.load_local_env(env_path)
                self.assertEqual(os.environ["DISCORD_TOKEN"], "existing-token")
                self.assertEqual(os.environ["SAMPLE_VALUE"], "from-file")
                os.environ.pop("SAMPLE_VALUE", None)


if __name__ == "__main__":
    unittest.main()
