#!/usr/bin/env python3
"""TRANSLATION IS PERMANENTLY BANNED (user decision, 9 Oct 2026). Do not restore.

Content Engine is English only. This helper no longer translates or republishes.

Kept so older commands that call translate_and_publish.py exit cleanly instead
of generating a 46-language map or calling the Grok API. Publish English posts
with publish_contentengine.py.
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    ap = argparse.ArgumentParser(
        description="No-op. Content Engine posts are English only; translations were removed."
    )
    ap.add_argument("--project", default="")
    ap.add_argument("--slug", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-translate", action="store_true")
    ap.add_argument("--langs", default="")
    ap.add_argument("--report", default="")
    ap.parse_args()
    print(
        "Translation is permanently banned. Not translating, not writing post.translations, not publishing.",
        flush=True,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
