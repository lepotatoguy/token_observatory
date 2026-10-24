"""Keep per-token prices current from Anthropic's published pricing page.

The page is downloaded (nothing is uploaded) at most once a day and the parsed table is cached beside
config.json. A failed download keeps the last good prices. OpenAI publishes no machine-readable page,
so those prices come from the dashboard's built-in table or from "prices" in config.json:
    {"prices": {"gpt-6-luna": {"input": 0.1, "cache_read": 0.01, "output": 0.5}},
     "price_updates": false}
"""
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.request

URL = 'https://platform.claude.com/docs/en/about-claude/pricing.md'
MAX_AGE = 24 * 3600
LONG_PROMPT_NOTE = re.compile(r'over 100,000', re.I)
# Version digits must not continue into another short number: "opus-5" must not match "opus-5-5".
NOT_FOLLOWED = r'(?![-.]?\d{1,2}(?!\d))'


def rates(cells):
    """[input, 5m write, 1h write, cache read, output] in USD per million tokens, or None."""
    values = [re.search(r'\$\s*([\d.]+)', cell) for cell in cells]
    if not all(values):
        return None
    result = [float(v.group(1)) for v in values]
    return result if all(r > 0 for r in result) else None


def parse_models(markdown):
    """Parse the model pricing table into [{match, rates, long_rates}] entries, most specific first."""
    entries = {}
    for line in markdown.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) != 6 or not cells[0].lower().startswith('claude '):
            continue
        name = cells[0]
        label = re.sub(r'\[[^\]]*\]\([^)]*\)', '', name)
        parts = re.sub(r'\(.*?\)', '', label).strip().lower().split()
        parsed = rates(cells[1:])
        if len(parts) < 3 or parsed is None:
            continue
        family, version = parts[1], parts[2].replace('.', '-')
        match = f'{family}-{re.escape(version)}{NOT_FOLLOWED}'
        entry = entries.setdefault(match, dict(match=match, rates=None, long_rates=None))
        if LONG_PROMPT_NOTE.search(name):
            entry['long_rates'] = parsed
        elif entry['rates'] is None:
            entry['rates'] = parsed
    models = [e for e in entries.values() if e['rates']]
    # Longer version strings first so that "4-8" is tried before "4".
    return sorted(models, key=lambda e: -len(e['match']))


def fetch_markdown(url=URL, timeout=15):
    request = urllib.request.Request(url, headers={'User-Agent': 'token-observatory-pricing'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2_000_000).decode('utf-8')


def load_overrides(config_path):
    """Return (overrides, enabled, warning) from config.json."""
    try:
        config = json.loads(Path(config_path).read_text())
    except FileNotFoundError:
        return [], True, None
    except (OSError, ValueError) as error:
        return [], True, f'Config {config_path} is unreadable: {error}'
    enabled = config.get('price_updates', True) is not False
    overrides, invalid = [], []
    prices = config.get('prices', {})
    for model, p in (prices.items() if isinstance(prices, dict) else []):
        try:
            inp, out = float(p['input']), float(p['output'])
            read = float(p.get('cache_read', inp))
            write = float(p.get('cache_write', inp))
        except (KeyError, TypeError, ValueError, AttributeError):
            invalid.append(model)
            continue
        if min(inp, out, read, write) < 0:
            invalid.append(model)
            continue
        overrides.append(dict(match=re.escape(str(model).lower()), rates=[inp, write, write, read, out], long_rates=None, custom=True))
    warning = f'Config {config_path}: ignored invalid prices for {", ".join(sorted(invalid))}' if invalid else None
    return overrides, enabled, warning


class Pricing:
    def __init__(self, cache_path, config_path, fetch=fetch_markdown, clock=time.time):
        self.cache_path, self.config_path, self.fetch, self.clock = Path(cache_path), Path(config_path), fetch, clock
        self.lock = threading.Lock()
        self.models, self.fetched_at, self.error = [], None, None
        try:
            cached = json.loads(self.cache_path.read_text())
            self.models, self.fetched_at = cached['models'], cached['fetched_at']
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def update(self, force=False):
        enabled = load_overrides(self.config_path)[1]
        with self.lock:
            if not enabled or not force and self.fetched_at and self.clock() - self.fetched_at < MAX_AGE:
                return
        try:
            models = parse_models(self.fetch())
            if len(models) < 5:
                raise ValueError('pricing table not recognised')
        except (OSError, ValueError) as error:
            with self.lock:
                self.error = f'Price update failed: {error}'
            return
        payload = dict(models=models, fetched_at=self.clock())
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(payload))
            os.replace(tmp, self.cache_path)
        except OSError:
            pass
        with self.lock:
            self.models, self.fetched_at, self.error = models, payload['fetched_at'], None

    def snapshot(self):
        overrides, enabled, warning = load_overrides(self.config_path)
        with self.lock:
            return dict(models=overrides + self.models, fetched_at=self.fetched_at, source=URL if self.models else None,
                        updates=enabled, error=self.error, warning=warning)
