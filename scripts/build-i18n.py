#!/usr/bin/env python3
"""
build-i18n.py — Merge all i18n YAML sources into a single HTML partial.

Reads:
  _data/cv.yml          (CV-specific i18n keys)
  _data/site-i18n.yml   (navbar, index, lab page i18n keys)

Writes:
  _generated/i18n-toggle.html   (JSON blob + toggle JS, included site-wide)

The partial is referenced from _quarto.yml's include-after-body.
Every page gets the toggle dropdown and all 7 languages for every key.
Individual .qmd pages just use <span data-i18n="key">English</span>.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")

REPO = Path(__file__).resolve().parents[1]
SOURCES = [
    REPO / "_data" / "cv.yml",
    REPO / "_data" / "site-i18n.yml",
]
INSTITUTIONS_PATH = REPO / "_data" / "institution-names.yml"
OUTPUT = REPO / "_generated" / "i18n-toggle.html"
SUPPORTED = ("en", "fr", "es", "ru", "uk", "ka", "de")


def institution_slug(name: str) -> str:
    """Generate a stable i18n key slug from an institution's English name."""
    import re
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:60]


def load_institution_overrides() -> dict:
    """Load _data/institution-names.yml and return {slug: {lang: value}}.

    Two keys per entry:
      institutions.<slug>          — full name only ("Centre pour l'étude...")
      institutions.<slug>.combined — full name with parenthesized abbr
                                      ("Centre pour l'étude... (CÉCD)")

    The combined form matches how orgs are written in cv.yml. Renderers
    wrap the org string in a <span data-i18n="institutions.<slug>.combined">
    so the toggle swaps to the local form."""
    if not INSTITUTIONS_PATH.exists():
        return {}
    data = yaml.safe_load(INSTITUTIONS_PATH.read_text(encoding="utf-8")) or {}
    entries = data.get("institutions") or []
    result = {}
    for e in entries:
        en = e.get("en")
        if not en:
            continue
        slug = institution_slug(en)

        # Full-name-only values per language (falls back to EN)
        name_values = {}
        if e.get("all"):
            for lang in SUPPORTED:
                name_values[lang] = e["all"]
        else:
            for lang in SUPPORTED:
                if lang in e:
                    name_values[lang] = e[lang]
            name_values.setdefault("en", en)
            # Fill missing languages with English so the toggle doesn't
            # fall back to the English full form when another language
            # wasn't explicitly set
            for lang in SUPPORTED:
                name_values.setdefault(lang, name_values["en"])
        result[f"institutions.{slug}"] = name_values

        # Combined "Name (Abbr)" form per language
        if e.get("abbr_en"):
            combined = {}
            for lang in SUPPORTED:
                name = name_values.get(lang, en)
                abbr = e.get(f"abbr_{lang}") or e.get("abbr_en")
                combined[lang] = f"{name} ({abbr})"
            result[f"institutions.{slug}.combined"] = combined

        # Abbreviation-only values (e.g., for inline "per CSDC guidelines" text)
        if e.get("abbr_en"):
            abbr_values = {}
            for lang in SUPPORTED:
                abbr_values[lang] = e.get(f"abbr_{lang}") or e["abbr_en"]
            result[f"institutions.{slug}.abbr"] = abbr_values
    return result


def is_lang_node(node) -> bool:
    if not isinstance(node, dict) or not node:
        return False
    return set(node.keys()).issubset(set(SUPPORTED))


def collect(node, prefix="") -> dict:
    result = {}
    if is_lang_node(node):
        result[prefix] = {k: node[k] for k in node if k in SUPPORTED}
        return result
    if isinstance(node, dict):
        for k, v in node.items():
            child = f"{prefix}.{k}" if prefix else k
            result.update(collect(v, child))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            result.update(collect(v, f"{prefix}.{i}"))
    return result


JS_TOGGLE = r"""
(function () {
  var STORAGE_KEY = "site_lang";
  var DEFAULT_LANG = "en";
  var SUPPORTED = ["en", "fr", "es", "ru", "uk", "ka", "de"];
  var LANG_NAMES = {
    en: "English", fr: "Français", es: "Español",
    ru: "Русский", uk: "Українська", ka: "ქართული", de: "Deutsch"
  };

  document.documentElement.classList.add("cv-i18n-pending");

  function getLang() {
    try {
      var url = new URL(window.location.href);
      var fromUrl = url.searchParams.get("lang");
      if (fromUrl && SUPPORTED.indexOf(fromUrl) !== -1) return fromUrl;
      var stored = localStorage.getItem(STORAGE_KEY);
      if (stored && SUPPORTED.indexOf(stored) !== -1) return stored;
    } catch (e) {}
    return DEFAULT_LANG;
  }

  function applyTranslations(lang) {
    var blob = document.getElementById("site-i18n");
    if (!blob) return;
    var i18n;
    try { i18n = JSON.parse(blob.textContent); }
    catch (e) { return; }
    // Text-only (textContent — safe, strips HTML)
    var nodes = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var key = el.getAttribute("data-i18n");
      var entry = i18n[key];
      if (!entry) continue;
      var text = entry[lang] || entry.en || "";
      if (text) el.textContent = text;
    }
    // HTML variant (innerHTML — allows <em>, <strong>, etc. from trusted YAML)
    var htmlNodes = document.querySelectorAll("[data-i18n-html]");
    for (var j = 0; j < htmlNodes.length; j++) {
      var hEl = htmlNodes[j];
      var hKey = hEl.getAttribute("data-i18n-html");
      var hEntry = i18n[hKey];
      if (!hEntry) continue;
      var hHtml = hEntry[lang] || hEntry.en || "";
      if (hHtml) hEl.innerHTML = hHtml;
    }
    document.documentElement.lang = lang;
    document.documentElement.classList.remove("cv-i18n-pending");
    document.documentElement.classList.add("cv-i18n-ready");
  }

  function setLang(lang) {
    if (SUPPORTED.indexOf(lang) === -1) return;
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) {}
    applyTranslations(lang);
    try {
      var url = new URL(window.location.href);
      url.searchParams.set("lang", lang);
      history.replaceState(null, "", url.toString());
    } catch (e) {}
    var sel = document.getElementById("site-lang-select");
    if (sel) sel.value = lang;
  }

  function buildToggle() {
    if (document.getElementById("site-lang-toggle")) return;
    if (document.querySelectorAll("[data-i18n]").length === 0) return;
    var wrapper = document.createElement("div");
    wrapper.id = "site-lang-toggle";
    wrapper.style.cssText = "position:fixed;top:0.6em;right:0.8em;z-index:1100;background:#fff;border:1px solid #ccc;border-radius:4px;padding:0.25em 0.5em;font-size:0.82em;box-shadow:0 1px 4px rgba(0,0,0,0.08);font-family:var(--body-font,monospace)";
    var label = document.createElement("label");
    label.setAttribute("for", "site-lang-select");
    label.textContent = "\uD83C\uDF10 ";
    var sel = document.createElement("select");
    sel.id = "site-lang-select";
    sel.style.cssText = "border:0;background:transparent;font-size:inherit;cursor:pointer;font-family:inherit";
    for (var i = 0; i < SUPPORTED.length; i++) {
      var opt = document.createElement("option");
      opt.value = SUPPORTED[i];
      opt.textContent = LANG_NAMES[SUPPORTED[i]];
      sel.appendChild(opt);
    }
    sel.addEventListener("change", function () { setLang(sel.value); });
    wrapper.appendChild(label);
    wrapper.appendChild(sel);
    document.body.appendChild(wrapper);
  }

  function init() {
    buildToggle();
    setLang(getLang());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
"""


def main():
    all_i18n = {}
    for src in SOURCES:
        if not src.exists():
            print(f"  skip (not found): {src}", file=sys.stderr)
            continue
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        keys = collect(data)
        print(f"  {src.name}: {len(keys)} keys", file=sys.stderr)
        all_i18n.update(keys)

    # Merge institution overrides
    inst = load_institution_overrides()
    if inst:
        print(f"  institution-names.yml: {len(inst)} overrides", file=sys.stderr)
        all_i18n.update(inst)

    blob = json.dumps(all_i18n, ensure_ascii=False, separators=(",", ":"))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(f'<script id="site-i18n" type="application/json">{blob}</script>\n')
        f.write(f"<script>{JS_TOGGLE}</script>\n")

    print(f"  Wrote {OUTPUT} ({len(all_i18n)} keys, {len(blob)} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
