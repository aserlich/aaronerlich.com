#!/usr/bin/env python3
"""
translate-cv.py — Fill in multilingual CV fields via Claude API.

Reads  _data/cv.yml               and adds missing language keys in place
Reads  ~/.config/anthropic/api_key  or  $ANTHROPIC_API_KEY
Cache  _data/_translation_cache.json (content-hash keyed; re-runs are free)

Usage:
  python3 scripts/translate-cv.py                  # all 6 non-English languages
  python3 scripts/translate-cv.py --lang fr        # only French
  python3 scripts/translate-cv.py --lang fr es de  # subset
  python3 scripts/translate-cv.py --dry-run        # show counts, no API calls
  python3 scripts/translate-cv.py --force          # ignore cache, retranslate

Preserves the top-of-file header comments in cv.yml (everything up to the first
non-comment line). Inline section comments are lost on save — if that matters,
switch to ruamel.yaml later.

Uses Claude Sonnet 4.6. Model ID baked into the script; adjust if needed.
Batches ~40 strings per API call to minimize round-trips.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Install PyYAML: pip3 install --user --break-system-packages pyyaml")

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("Install Anthropic SDK: pip3 install --user --break-system-packages anthropic")


REPO = Path(__file__).resolve().parents[1]
CV_YAML = REPO / "_data" / "cv.yml"
CACHE_PATH = REPO / "_data" / "_translation_cache.json"
KEY_FILE = Path.home() / ".config" / "anthropic" / "api_key"

SUPPORTED = ["en", "fr", "es", "ru", "uk", "ka", "de"]
NON_EN = ["fr", "es", "ru", "uk", "ka", "de"]
LANG_NAMES = {
    "fr": "French",
    "es": "Spanish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "ka": "Georgian (ქართული, Mkhedruli script)",
    "de": "German",
}

MODEL = "claude-sonnet-4-6"
BATCH_SIZE = 40

SYSTEM_PROMPT = """You are a professional translator specializing in academic political science CVs.

Translate from English to {target}.

RULES:
1. Maintain formal academic register appropriate for a political science professor's CV at a research-intensive North American university.
2. Do NOT translate proper nouns: institution names (McGill University, SSHRC, FRQSC), journal titles (American Political Science Review, World Politics), person names, place names with established local forms (keep Montréal as Montréal, Tbilisi as Tbilisi). Program/acronym names like CAnD3 stay in English.
3. DO translate: role titles (Associate Professor, Visiting Professor), degree names (Ph.D., M.A.), section headers, narrative descriptions, UI labels, country names, and relationship words like "with".
4. For academic rank: use the closest conventional equivalent in the target language's academic system (e.g., "Associate Professor" → "Professeur agrégé" in French, "Außerordentlicher Professor" in German).
5. For the connector word "with" (used before coauthor names, as in "(with Brian Palmer-Rubin, ...)"), use the natural coauthor connector in the target language: "avec" (fr), "con" (es), "с" (ru), "з" (uk), "mit" (de), "-თან ერთად" (ka).
6. Keep punctuation, capitalization conventions, and any embedded symbols (em-dashes, en-dashes, parentheses) intact.

You will receive a JSON object where keys are identifiers and values are English strings. Return a JSON object with the SAME keys and translated values. No prose, no markdown fences, no commentary — only the raw JSON object."""


# ---------- helpers ----------

def load_api_key() -> str:
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env:
        return env.strip()
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    sys.exit(
        f"No API key found.\n"
        f"  Set ANTHROPIC_API_KEY in the environment, or\n"
        f"  save to {KEY_FILE} (mode 600)"
    )


def load_yaml_with_header(path: Path):
    """Split cv.yml into (header_text, data). Header = top comments+blanks."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    header, i = [], 0
    while i < len(lines) and (lines[i].lstrip().startswith("#") or lines[i].strip() == ""):
        header.append(lines[i])
        i += 1
    header_text = ("\n".join(header).rstrip() + "\n\n") if header else ""
    data = yaml.safe_load("\n".join(lines[i:]))
    return header_text, data


def dump_yaml_with_header(path: Path, header_text: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        if header_text:
            f.write(header_text)
        yaml.safe_dump(
            data, f,
            allow_unicode=True,
            sort_keys=False,
            width=100,
            default_flow_style=False,
        )


def content_hash(text: str, target_lang: str) -> str:
    return hashlib.sha256(f"{target_lang}:{text}".encode("utf-8")).hexdigest()[:16]


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache: dict):
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def is_lang_node(node) -> bool:
    """True if a dict's keys are all language codes."""
    if not isinstance(node, dict) or not node:
        return False
    return set(node.keys()).issubset(set(SUPPORTED))


def walk_lang_nodes(data, path=()):
    """Yield (path_tuple, lang_node_dict) for every language-keyed leaf."""
    if is_lang_node(data):
        yield path, data
        return
    if isinstance(data, dict):
        for k, v in data.items():
            yield from walk_lang_nodes(v, path + (k,))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            yield from walk_lang_nodes(v, path + (i,))


def collect_missing(data, target_langs: list[str], force: bool):
    """Return list of (path, lang, en_text) for strings needing translation."""
    missing = []
    for path, node in walk_lang_nodes(data):
        en = node.get("en")
        if not en or not isinstance(en, str):
            continue
        for lang in target_langs:
            if force or lang not in node or not node[lang]:
                missing.append((path, lang, en))
    return missing


def path_key(path: tuple) -> str:
    """Stable string identifier for a YAML path."""
    return ".".join(str(p) for p in path)


def apply_translation(data, path: tuple, lang: str, value: str):
    """Insert a translated value into the data tree at path[lang]."""
    node = data
    for p in path:
        node = node[p]
    node[lang] = value


def batch_iter(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def call_claude(client: Anthropic, target_lang: str, batch: dict) -> dict:
    lang_name = LANG_NAMES[target_lang]
    system = SYSTEM_PROMPT.format(target=lang_name)
    user_msg = json.dumps(batch, ensure_ascii=False, indent=2)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text").strip()
    # Strip possible code fences even though we asked for raw
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  ! JSON parse failed ({target_lang}): {e}", file=sys.stderr)
        print(f"    first 400 chars: {text[:400]}", file=sys.stderr)
        return {}


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", nargs="+", choices=NON_EN, default=NON_EN,
                    help="Target languages (default: all 6)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show counts only, no API calls or writes")
    ap.add_argument("--force", action="store_true",
                    help="Retranslate even cache-hit strings")
    ap.add_argument("--file", default=str(CV_YAML),
                    help=f"YAML file to translate (default: {CV_YAML})")
    args = ap.parse_args()

    target = Path(args.file)
    if not target.exists():
        sys.exit(f"File not found: {target}")
    header, data = load_yaml_with_header(target)
    cache = load_cache()

    missing = collect_missing(data, args.lang, args.force)
    if not missing:
        print("Nothing to translate — every string already has all requested languages.")
        return

    # Per-language breakdown
    by_lang: dict[str, list] = {}
    for path, lang, en in missing:
        by_lang.setdefault(lang, []).append((path, en))

    print(f"Languages: {', '.join(args.lang)}")
    for lang in args.lang:
        items = by_lang.get(lang, [])
        print(f"  {lang}: {len(items)} strings missing")

    if args.dry_run:
        print("\n(dry-run — not calling API)")
        return

    client = Anthropic(api_key=load_api_key())

    total_applied = 0
    total_cache_hits = 0
    total_api_calls = 0

    for lang in args.lang:
        items = by_lang.get(lang, [])
        if not items:
            continue
        print(f"\n=== {lang} ({LANG_NAMES[lang]}): {len(items)} strings ===")

        # Check cache first
        to_call = []
        cached_applied = 0
        for path, en in items:
            h = content_hash(en, lang)
            if not args.force and h in cache:
                apply_translation(data, path, lang, cache[h])
                cached_applied += 1
            else:
                to_call.append((path, en))
        if cached_applied:
            print(f"  {cached_applied} resolved from cache")
            total_cache_hits += cached_applied
            total_applied += cached_applied

        # Batch-call the rest
        if to_call:
            # Build batches as {stable_key: en_text}
            for batch_idx, chunk in enumerate(batch_iter(to_call, BATCH_SIZE), 1):
                payload = {path_key(p): en for p, en in chunk}
                print(f"  batch {batch_idx}: calling Claude for {len(payload)} strings…", file=sys.stderr)
                result = call_claude(client, lang, payload)
                total_api_calls += 1
                # Apply + cache
                applied_here = 0
                for p, en in chunk:
                    key = path_key(p)
                    translated = result.get(key)
                    if translated and isinstance(translated, str):
                        apply_translation(data, p, lang, translated)
                        cache[content_hash(en, lang)] = translated
                        applied_here += 1
                print(f"    applied {applied_here}/{len(payload)}")
                total_applied += applied_here
                save_cache(cache)  # save after each batch
                time.sleep(0.3)  # polite

    # Write back
    dump_yaml_with_header(target, header, data)
    print(f"\nWrote {target}")
    print(f"Totals: applied={total_applied}, cache_hits={total_cache_hits}, api_calls={total_api_calls}")


if __name__ == "__main__":
    main()
