import json
from pathlib import Path
import re
import tempfile
import unittest

import pricing

PAGE = '''## Model pricing

| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
| :-- | :-- | :-- | :-- | :-- | :-- |
| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |
| Claude Opus 5 | $5 / MTok | $6.25 / MTok | $10 / MTok | $0.50 / MTok | $25 / MTok |
| Claude Opus 4.1 ([retired](https://x.test/a)) | $15 / MTok | $18.75 / MTok | $30 / MTok | $1.50 / MTok | $75 / MTok |
| Claude Sonnet 5.5 | $2 / MTok | $2.50 / MTok | $4 / MTok | $0.10 / MTok | $10 / MTok |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |
| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |

| Model | Input | Output |
| :-- | :-- | :-- |
| Claude Opus 5.5 | $8 USD / MTok | $40 USD / MTok |
'''


def lookup(models, name):
    return next((m for m in models if re.search(m['match'], name)), None)


class ParseTests(unittest.TestCase):
    def test_parses_main_table_only_and_matches_model_ids(self):
        models = pricing.parse_models(PAGE)
        self.assertEqual(lookup(models, 'claude-opus-5-5')['rates'], [4, 5, 8, 0.2, 20])
        self.assertEqual(lookup(models, 'claude-opus-5')['rates'], [5, 6.25, 10, 0.5, 25])
        self.assertEqual(lookup(models, 'claude-opus-4-1-20250805')['rates'][4], 75)
        self.assertEqual(lookup(models, 'claude-haiku-5-5')['long_rates'], [0.5, 0.625, 1, 0.05, 2.5])
        self.assertIsNone(lookup(models, 'claude-opus-9'))


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.calls = 0
        self.now = 1000.0

    def make(self, text=PAGE, fail=False):
        def fetch():
            self.calls += 1
            if fail:
                raise OSError('offline')
            return text
        return pricing.Pricing(self.dir / 'pricing.json', self.dir / 'config.json', fetch, lambda: self.now, self.dir / 'prices.json')

    def test_updates_once_a_day_and_survives_restart(self):
        p = self.make(PAGE.replace('$4 / MTok', '$4.5 / MTok'))
        p.update()
        p.update()
        self.assertEqual(self.calls, 1)
        self.assertEqual(lookup(self.make().snapshot()['models'], 'claude-opus-5-5')['rates'][0], 4.5)
        self.now += pricing.MAX_AGE + 1
        p.update()
        self.assertEqual(self.calls, 2)

    def test_failed_download_keeps_last_good_prices(self):
        self.make().update()
        self.now += pricing.MAX_AGE + 1
        p = self.make(fail=True)
        p.update()
        snap = p.snapshot()
        self.assertIn('offline', snap['error'])
        self.assertTrue(lookup(snap['models'], 'claude-opus-5-5'))

    def test_unrecognised_page_is_rejected(self):
        p = self.make('nothing here')
        p.update()
        self.assertEqual(p.snapshot()['models'], [])
        self.assertIn('not recognised', p.snapshot()['error'])

    def test_bundled_prices_are_the_last_resort(self):
        (self.dir / 'prices.json').write_text(json.dumps(dict(models=[dict(match='gpt-6-luna', rates=[1, 1, 1, 0.1, 2])])))
        p = self.make(fail=True)
        p.update()
        snap = p.snapshot()
        self.assertEqual(snap['source'], 'bundled')
        self.assertEqual(lookup(snap['models'], 'gpt-6-luna')['rates'][4], 2)
        self.make().update()
        online = self.make().snapshot()['models']
        self.assertEqual(lookup(online, 'claude-opus-5-5')['rates'][0], 4)
        self.assertTrue(lookup(online, 'gpt-6-luna'))

    def test_shipped_prices_file_is_valid(self):
        models = pricing.load_bundled()
        self.assertGreaterEqual(len(models), 15)
        self.assertTrue(all(len(m['rates']) == 5 for m in models))
        self.assertEqual(lookup(models, 'claude-opus-5-5')['rates'], [4, 5, 8, 0.2, 20])

    def test_config_overrides_and_opt_out(self):
        (self.dir / 'config.json').write_text(json.dumps(dict(prices={'gpt-6-luna': dict(input=1, cache_read=0.1, output=2), 'bad': {}}, price_updates=False)))
        p = self.make()
        p.update(force=True)
        self.assertEqual(self.calls, 0)
        snap = p.snapshot()
        self.assertEqual(lookup(snap['models'], 'gpt-6-luna')['rates'], [1, 1, 1, 0.1, 2])
        self.assertIn('bad', snap['warning'])
        self.assertFalse(snap['updates'])


if __name__ == '__main__':
    unittest.main()
