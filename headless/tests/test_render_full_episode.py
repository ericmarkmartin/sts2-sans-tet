from __future__ import annotations

import unittest

from headless.render_full_episode import validate_video_probe


class RenderedVideoValidationTests(unittest.TestCase):
    def test_accepts_silent_h264_at_requested_dimensions(self) -> None:
        video = {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1280,
            "height": 720,
        }
        self.assertIs(validate_video_probe({"streams": [video]}, 1280, 720), video)

    def test_rejects_audio_stream(self) -> None:
        with self.assertRaisesRegex(ValueError, "audio"):
            validate_video_probe(
                {
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 1280,
                            "height": 720,
                        },
                        {"codec_type": "audio", "codec_name": "aac"},
                    ]
                },
                1280,
                720,
            )

    def test_rejects_wrong_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimensions"):
            validate_video_probe(
                {
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 2560,
                            "height": 1440,
                        }
                    ]
                },
                1280,
                720,
            )


if __name__ == "__main__":
    unittest.main()
