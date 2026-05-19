#!/usr/bin/env python3
"""statusplus LLM headline helper.

Two modes:
  default (no args): read CC session JSON on stdin, print cached headline
    instantly, and spawn a detached `--refresh` if the cache is stale.
  --refresh: do the actual API call sync, write the new headline to cache,
    exit. Always invoked detached from the statusline so the foreground
    call returns in single-digit ms.

Config: ~/.claude/.statusplus/config.json (chmod 600, set by /statusplus:statusplus-llm-setup)
  {
    "provider":      "anthropic" | "openai",
    "endpoint":      "https://api.anthropic.com/v1/messages",
    "api_key":       "...",
    "model":         "claude-haiku-4-5-20251001",
    "max_tokens":    30,
    "timeout_s":     8,
    "cache_ttl_s":   60,
    "head_messages": 2,
    "tail_messages": 6
  }

The helper is fully silent on any error. A misconfigured key, a network
blip, or a missing transcript all collapse to "no line 3 today" rather
than a broken statusline. Cache files are 0600 — they contain
transcript-derived text.
"""
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Slash commands that carry no topic signal and should be skipped when
# collecting head messages. Matched case-insensitively against the first
# whitespace-delimited token of a user message.
_NOISY_COMMANDS = {
    '/clear', '/model', '/effort', '/compact', '/cost',
    '/config', '/vim', '/theme', '/status', '/memory',
    '/help', '/reset', '/logout', '/login',
}

HOME = pathlib.Path(os.path.expanduser('~'))
CONFIG = HOME / '.claude' / '.statusplus' / 'config.json'
CACHE_DIR = HOME / '.claude' / '.statusplus' / 'cache'

# Reinforced before AND after the input - small models routinely break the
# word limit when told only once. See bearchat spec §10.
PROMPT = (
    "Summarize the user-AI conversation as a 5-word newspaper-style headline. "
    "Exactly 5 words. Active voice. Specific nouns and verbs. "
    "No quotes. No trailing punctuation. No filler words like 'work', "
    "'task', 'help', or 'session'."
)


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    except Exception:
        return None


def cache_path(sid):
    return CACHE_DIR / f'{sid}.summary'


def read_cache(sid):
    p = cache_path(sid)
    if not p.exists():
        return None, 0.0
    try:
        return p.read_text(encoding='utf-8').strip(), p.stat().st_mtime
    except Exception:
        return None, 0.0


def write_cache(sid, text):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = cache_path(sid)
    p.write_text(text, encoding='utf-8')
    try:
        p.chmod(0o600)
    except Exception:
        pass


def prune_cache(max_age_days=14):
    """Remove cache files older than max_age_days. Best-effort."""
    cutoff = time.time() - max_age_days * 86400
    try:
        for p in CACHE_DIR.glob('*.summary'):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _parse_msg(line):
    """Parse one JSONL line. Return (role, text[:600]) or None."""
    try:
        rec = json.loads(line)
    except Exception:
        return None
    msg = rec.get('message') or {}
    role = msg.get('role') or rec.get('type') or ''
    if role not in ('user', 'assistant'):
        return None
    content = msg.get('content')
    if isinstance(content, list):
        text = ' '.join(
            blk.get('text', '') for blk in content
            if isinstance(blk, dict) and blk.get('type') == 'text'
        )
    elif isinstance(content, str):
        text = content
    else:
        return None
    text = ' '.join(text.split()).strip()
    if not text:
        return None
    return role, text[:600]


def _resolve_transcript(path):
    """Return a Path to read, or None.

    If path exists, use it directly. If not (common for 'Continue from where
    you left off' sessions whose .jsonl isn't flushed yet), fall back to the
    most recently modified .jsonl in the same directory.
    """
    p = pathlib.Path(path) if path else None
    if p and p.exists():
        return p
    if p and p.parent.is_dir():
        candidates = sorted(
            p.parent.glob('*.jsonl'),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
    return None


def build_transcript(path, head_n=2, tail_n=6):
    """Return transcript excerpt as `role: text` lines for LLM context.

    Collects the first head_n messages (goal anchor) and last tail_n messages
    (current state). Deduplicates when windows overlap (short sessions).
    Inserts a separator line between the two blocks when they are non-contiguous.
    head_n=0 gives pure tail-only behaviour (backwards compatible).
    """
    if not path:
        return ''
    resolved = _resolve_transcript(path)
    if not resolved:
        return ''
    path = str(resolved)
    try:
        head_msgs = []
        if head_n > 0:
            with open(path, 'rb') as f:
                blob = f.read(32 * 1024)
            skip_next_assistant = False
            for line in blob.splitlines():
                parsed = _parse_msg(line)
                if not parsed:
                    continue
                role, text = parsed
                if role == 'user':
                    first_token = text.split()[0].lower() if text.split() else ''
                    if first_token in _NOISY_COMMANDS:
                        skip_next_assistant = True
                        continue
                    skip_next_assistant = False
                    head_msgs.append(parsed)
                elif role == 'assistant':
                    if skip_next_assistant:
                        skip_next_assistant = False
                        continue
                    head_msgs.append(parsed)
                if len(head_msgs) >= head_n:
                    break

        tail_msgs = []
        if tail_n > 0:
            with open(path, 'rb') as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 128 * 1024))
                blob = f.read()
            collected = []
            for line in reversed(blob.splitlines()):
                parsed = _parse_msg(line)
                if parsed:
                    collected.append(parsed)
                    if len(collected) >= tail_n:
                        break
            tail_msgs = list(reversed(collected))

        head_set = set(head_msgs)
        tail_only = [m for m in tail_msgs if m not in head_set]

        parts = []
        if head_msgs:
            parts.extend(f'{r}: {t}' for r, t in head_msgs)
        if tail_only:
            if head_msgs:
                parts.append('[... session continues ...]')
            parts.extend(f'{r}: {t}' for r, t in tail_only)
        return '\n'.join(parts)
    except Exception:
        return ''


def call_anthropic(cfg, conv):
    body = json.dumps({
        'model': cfg['model'],
        'max_tokens': int(cfg.get('max_tokens', 30)),
        'system': PROMPT,
        'messages': [
            {'role': 'user', 'content': f'{conv}\n\n{PROMPT}'},
        ],
    }).encode('utf-8')
    req = urllib.request.Request(
        cfg.get('endpoint') or 'https://api.anthropic.com/v1/messages',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'x-api-key': cfg['api_key'],
            'anthropic-version': '2023-06-01',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=cfg.get('timeout_s', 8)) as resp:
        data = json.loads(resp.read())
    for b in data.get('content') or []:
        if b.get('type') == 'text':
            return b.get('text', '').strip()
    return ''


def call_openai(cfg, conv):
    body = json.dumps({
        'model': cfg['model'],
        'max_tokens': int(cfg.get('max_tokens', 30)),
        'messages': [
            {'role': 'system', 'content': PROMPT},
            {'role': 'user', 'content': f'{conv}\n\n{PROMPT}'},
        ],
    }).encode('utf-8')
    req = urllib.request.Request(
        cfg.get('endpoint') or 'https://api.openai.com/v1/chat/completions',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {cfg["api_key"]}',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=cfg.get('timeout_s', 8)) as resp:
        data = json.loads(resp.read())
    choices = data.get('choices') or []
    if not choices:
        return ''
    return (choices[0].get('message') or {}).get('content', '').strip()


def sanitize(text):
    text = (text or '').replace('\n', ' ').strip()
    # Normalize Unicode punctuation to ASCII — keeps cache files cp1252-safe
    # on Windows and avoids double-encoding bugs with smart quotes from LLMs.
    for uc, asc in {
        '‘': "'", '’': "'",  # curly single quotes
        '“': '"', '”': '"',  # curly double quotes
        '–': '-', '—': '-',  # en/em dashes
        '…': '...',               # ellipsis
    }.items():
        text = text.replace(uc, asc)
    while text and text[0] in '"\'`':
        text = text[1:]
    while text and text[-1] in '"\'`.,;:!?':
        text = text[:-1]
    if len(text) > 80:
        text = text[:80].rstrip() + '...'
    return text


def refresh(stdin_json):
    cfg = load_config()
    if not cfg or not cfg.get('api_key'):
        return
    sid = stdin_json.get('session_id') or ''
    if not sid:
        return
    head_n = int(cfg.get('head_messages', 2))
    tail_n = int(cfg.get('tail_messages', 6))
    conv = build_transcript(stdin_json.get('transcript_path') or '',
                            head_n, tail_n)
    if not conv:
        return
    try:
        if cfg.get('provider') == 'openai':
            text = call_openai(cfg, conv)
        else:
            text = call_anthropic(cfg, conv)
    except Exception:
        return
    text = sanitize(text)
    if text:
        write_cache(sid, text)
    prune_cache()


def spawn_refresh(stdin_json):
    """Fire-and-forget background refresh. Detached so the parent
    statusline exits without waiting for the API call."""
    try:
        payload = json.dumps(stdin_json).encode('utf-8')
        kw = {}
        if os.name == 'nt':
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            kw['creationflags'] = 0x00000008 | 0x00000200
        else:
            kw['start_new_session'] = True
        p = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), '--refresh'],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **kw,
        )
        try:
            p.stdin.write(payload)
        finally:
            p.stdin.close()
    except Exception:
        pass


def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        return

    if '--refresh' in sys.argv:
        refresh(d)
        return

    cfg = load_config()
    if not cfg or not cfg.get('api_key'):
        return
    sid = d.get('session_id') or ''
    if not sid:
        return

    cached, mtime = read_cache(sid)
    if cached:
        # Use stdout.buffer to avoid cp1252 UnicodeEncodeError on Windows.
        sys.stdout.buffer.write(cached.encode('utf-8') + b'\n')
        sys.stdout.buffer.flush()

    age = time.time() - mtime if mtime else float('inf')
    ttl = float(cfg.get('cache_ttl_s', 60))
    if age > ttl:
        spawn_refresh(d)


if __name__ == '__main__':
    main()
