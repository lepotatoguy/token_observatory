import datetime as dt

FIELDS = ('input', 'cached', 'write', 'output', 'reasoning')

def number(value):
    return max(0, int(value)) if isinstance(value, (int, float)) else 0

def tokens(usage, claude=False):
    cached = number(usage.get('cache_read_input_tokens' if claude else 'cached_input_tokens'))
    write = number(usage.get('cache_creation_input_tokens' if claude else 'cache_write_input_tokens'))
    raw_input = number(usage.get('input_tokens'))
    return dict(input=raw_input if claude else max(0, raw_input-cached-write),
                cached=cached, write=write, output=number(usage.get('output_tokens')),
                reasoning=number((usage.get('output_tokens_details') or {}).get('thinking_tokens'))
                if claude else number(usage.get('reasoning_output_tokens')))

def total(usage):
    # Reasoning is already included in output tokens.
    return sum(usage.get(k, 0) for k in FIELDS if k != 'reasoning')

def timestamp(value):
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None
