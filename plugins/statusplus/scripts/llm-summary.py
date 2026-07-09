#!/usr/bin/env python3
"""statusplus LLM headline helper.

Two modes:
  default (no args): read CC session JSON on stdin, print cached headline
    instantly, and spawn a detached `--refresh` if the cache is stale and
    not yet frozen.
  --refresh: do the actual API call sync, write the new headline to cache,
    exit. Always invoked detached from the statusline so the foreground
    call returns in single-digit ms.

The headline is a *start-of-session anchor*: it summarizes the opening
stretch of the transcript (first ~12000 chars of kept user/assistant text),
not the current state. Because that window only grows until the budget is
full and then never changes, a `.full` sentinel freezes refreshing once a
full window has been summarized — one stable line per session.

Config: ~/.claude/.statusplus/config.json (chmod 600, set by /statusplus:statusplus-llm-setup)
  {
    "provider":      "anthropic" | "openai",
    "endpoint":      "https://api.anthropic.com/v1/messages",
    "api_key":       "...",
    "model":         "claude-haiku-4-5-20251001",
    "max_tokens":    50,
    "timeout_s":     8,
    "cache_ttl_s":   60
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

HOME = pathlib.Path(os.path.expanduser('~'))
CONFIG = HOME / '.claude' / '.statusplus' / 'config.json'
CACHE_DIR = HOME / '.claude' / '.statusplus' / 'cache'

# Transcript-building budget. Walk from the start of the session, keep
# user/assistant text, and stop once the next prefixed line would exceed
# this many chars. MSG_CAP truncates any single message first.
BUDGET = 12000
MSG_CAP = 800

# User turns whose text starts with one of these carry no topic signal
# (harness-injected wrappers, interrupts, bash plumbing). startswith()
# takes the tuple directly.
_NOISE_PREFIXES = (
    '<local-command',
    '<command-',
    'Caveat:',
    '<system-reminder',
    '<bash-input',
    '<bash-stdout',
    '[Request interrupted',
)

SYSTEM_PROMPT = 'You write terse one-line summaries of coding sessions.'

# Smart-quote / dash / ellipsis -> ASCII. Keeps cache files cp1252-safe on
# Windows and avoids double-encoding bugs with LLM-emitted punctuation.
_UNICODE = {
    '‘': "'", '’': "'",   # curly single quotes
    '“': '"', '”': '"',   # curly double quotes
    '–': '-', '—': '-',   # en/em dashes
    '…': '...',                 # ellipsis
}


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    except Exception:
        return None


def cache_path(sid):
    return CACHE_DIR / f'{sid}.summary'


def full_marker(sid):
    return CACHE_DIR / f'{sid}.full'


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


def freeze(sid):
    """Mark this session's window as full so we stop refreshing."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        m = full_marker(sid)
        m.write_text('1', encoding='utf-8')
        m.chmod(0o600)
    except Exception:
        pass


def prune_cache(max_age_days=14):
    """Remove cache + sentinel files older than max_age_days. Best-effort.
    Sentinels are pruned alongside summaries so a long-resumed session
    doesn't lose its summary yet keep a stale .full that blocks refresh."""
    cutoff = time.time() - max_age_days * 86400
    try:
        for pat in ('*.summary', '*.full'):
            for p in CACHE_DIR.glob(pat):
                try:
                    if p.stat().st_mtime < cutoff:
                        p.unlink()
                except Exception:
                    pass
    except Exception:
        pass


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


def _iter_messages(path):
    """Yield (role, text) for user/assistant records in file order.

    Skips isMeta records. For list content, keeps only text blocks (drops
    thinking, tool_use, tool_result). Collapses internal whitespace so each
    message stays a single line. Streams line-by-line — the caller breaks
    early once the budget fills, so we never read the whole (often huge) file.
    """
    with open(path, 'rb') as f:
        for raw in f:
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            if rec.get('isMeta'):
                continue
            msg = rec.get('message') or {}
            if msg.get('isMeta'):
                continue
            role = msg.get('role') or rec.get('type') or ''
            if role not in ('user', 'assistant'):
                continue
            content = msg.get('content')
            if isinstance(content, list):
                text = ' '.join(
                    blk.get('text', '') for blk in content
                    if isinstance(blk, dict) and blk.get('type') == 'text'
                )
            elif isinstance(content, str):
                text = content
            else:
                continue
            text = ' '.join(text.split()).strip()
            if not text:
                continue
            yield role, text


def build_transcript(path):
    """Walk from the start of the session. Return (transcript, budget_full).

    budget_full is True only when we stopped because the next line would
    exceed BUDGET — not when the file simply ran out of messages. A short
    session (window never filled) stays unfrozen so it keeps refreshing as
    more messages append.

    budget_full is forced False when the transcript came from the fallback
    (sibling .jsonl): a fresh concurrent session whose own file isn't
    flushed yet would otherwise freeze a *sibling session's* summary
    permanently. Unfrozen, the wrong line self-heals on the next TTL
    refresh once the session's own transcript exists.
    """
    resolved = _resolve_transcript(path)
    if not resolved:
        return '', False
    is_fallback = not (path and pathlib.Path(path).exists())
    try:
        total = 0
        parts = []
        budget_full = False
        for role, text in _iter_messages(str(resolved)):
            if role == 'user' and text.startswith(_NOISE_PREFIXES):
                continue
            prefix = 'USER: ' if role == 'user' else 'ASSISTANT: '
            line = prefix + text[:MSG_CAP]
            if total + len(line) > BUDGET:
                budget_full = True
                break
            parts.append(line)
            total += len(line)
        return '\n'.join(parts), budget_full and not is_fallback
    except Exception:
        return '', False


def find_title(path):
    """Return the aiTitle of the last ai-title record, or '' if absent.

    Separate full pass — the ai-title record is appended near the end of the
    file, past where build_transcript stops, so we can't piggyback on it.
    """
    resolved = _resolve_transcript(path)
    if not resolved:
        return ''
    title = ''
    try:
        with open(str(resolved), 'rb') as f:
            for raw in f:
                if b'ai-title' not in raw:
                    continue
                try:
                    rec = json.loads(raw)
                except Exception:
                    continue
                if rec.get('type') == 'ai-title':
                    title = rec.get('aiTitle') or rec.get('title') or ''
    except Exception:
        return ''
    return title


def build_user_prompt(transcript, title):
    clause = f' (Claude\'s own title for it: "{title}")' if title else ''
    return (
        f'Below is the start of a Claude Code coding session{clause}. '
        'In 14 words or fewer, state the high-level task or topic as a '
        'single concise phrase — not a full sentence, no semicolons, no '
        'lists. Output only the summary line: no quotes, no trailing '
        'period, no preamble.\n\n'
        f'TRANSCRIPT:\n{transcript}'
    )


def call_anthropic(cfg, user_prompt):
    body = json.dumps({
        'model': cfg['model'],
        'max_tokens': int(cfg.get('max_tokens', 50)),
        'system': SYSTEM_PROMPT,
        'messages': [{'role': 'user', 'content': user_prompt}],
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


def call_openai(cfg, user_prompt):
    body = json.dumps({
        'model': cfg['model'],
        'max_tokens': int(cfg.get('max_tokens', 50)),
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_prompt},
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


def postprocess(text):
    """Normalize the model reply before storing.

    unicode->ASCII, collapse whitespace to single spaces, strip a wrapping
    matched quote pair, strip one trailing period, hard-cap to 14 words.
    """
    text = text or ''
    for uc, asc in _UNICODE.items():
        text = text.replace(uc, asc)
    text = ' '.join(text.split())
    if len(text) >= 2 and text[0] in '"\'' and text[-1] == text[0]:
        text = text[1:-1].strip()
    if text.endswith('.'):
        text = text[:-1].rstrip()
    words = text.split()
    if len(words) > 14:
        text = ' '.join(words[:14])
    return text.strip()


def refresh(stdin_json):
    cfg = load_config()
    if not cfg or not cfg.get('api_key'):
        return
    sid = stdin_json.get('session_id') or ''
    if not sid:
        return
    path = stdin_json.get('transcript_path') or ''
    transcript, budget_full = build_transcript(path)
    if not transcript:
        return
    title = find_title(path)
    user_prompt = build_user_prompt(transcript, title)
    try:
        if cfg.get('provider') == 'openai':
            text = call_openai(cfg, user_prompt)
        else:
            text = call_anthropic(cfg, user_prompt)
    except Exception:
        return
    text = postprocess(text)
    if text:
        write_cache(sid, text)
        if budget_full:
            freeze(sid)
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

    # Frozen: a full start-window has been summarized; it can't change.
    if full_marker(sid).exists():
        return

    age = time.time() - mtime if mtime else float('inf')
    ttl = float(cfg.get('cache_ttl_s', 60))
    if age > ttl:
        spawn_refresh(d)


if __name__ == '__main__':
    main()
