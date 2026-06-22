#!/usr/bin/env python3
"""List swagger apps as a JSON matrix for GitHub Actions.

For each swagger/*.yaml, derives the same slug onboard.py would use, plus
the SECRET_KEY form (slug, uppercased, dashes -> underscores) used to look
up per-app GitHub Secrets like DBX_HOST_<SECRET_KEY>.

Usage:
  python scripts/list_apps.py
"""
import glob
import json
import re

import yaml


def slugify(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def main():
    apps = []
    for path in sorted(glob.glob("swagger/*.yaml")):
        with open(path) as f:
            spec = yaml.safe_load(f)
        slug = slugify(spec["info"]["title"])
        apps.append(
            {
                "file": path,
                "slug": slug,
                "secret_key": slug.upper().replace("-", "_"),
            }
        )
    print(json.dumps({"include": apps}))


if __name__ == "__main__":
    main()
