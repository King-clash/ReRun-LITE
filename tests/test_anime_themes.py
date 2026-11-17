"""The 16 anime themes: palettes that stay readable, a background video for each, and a matching artwork collection."""
import unittest
from pathlib import Path

from rerun_lite import appearance, artwork, palettes

ROOT = Path(__file__).resolve().parents[1]


def _lum(h):
    c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


class AnimeThemes(unittest.TestCase):
    def test_sixteen_themes_exist(self):
        self.assertEqual(len(palettes.ANIME_KEYS), 16)
        for k in palettes.ANIME_KEYS:
            self.assertIn(k, palettes.LOOKS)
            self.assertIn(k, appearance.LOOKS)

    def test_text_is_readable(self):
        for k in palettes.ANIME_KEYS:
            p, look = palettes.LOOKS[k].palette, palettes.LOOKS[k]
            self.assertGreaterEqual(contrast(p["label"], p["bg"]), 4.5, k)
            self.assertGreaterEqual(contrast(p["secondary"], p["card"]), 4.5, k)
            self.assertGreaterEqual(contrast(look.mark[1], look.mark[0]), 4.5, k)

    def test_each_has_a_video_and_an_artwork_collection(self):
        cols = artwork.load_collections(ROOT)
        for k in palettes.ANIME_KEYS:
            self.assertTrue((ROOT / "assets" / palettes.LOOKS[k].video).is_file(), k)
            self.assertIn(k, cols, k)

    def test_dark_flag_matches_page_colour(self):
        for k in palettes.ANIME_KEYS:
            look = palettes.LOOKS[k]
            self.assertEqual(look.dark, _lum(look.palette["bg"]) < 0.3, k)


if __name__ == "__main__":
    unittest.main()
