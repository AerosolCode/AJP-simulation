"""Load simple, Git-ignored AJP environment assignments without running a shell."""

import os
import re
import shlex
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_site_env(path=None):
    site_path = Path(path or os.environ.get("AJP_SITE_ENV", ROOT / "site.env")).expanduser()
    if not site_path.is_absolute():
        site_path = ROOT / site_path
    if site_path.is_file():
        for number, line in enumerate(site_path.read_text().splitlines(), 1):
            tokens = shlex.split(line, comments=True)
            if tokens[:1] == ["export"]:
                tokens = tokens[1:]
            if not tokens:
                continue
            if len(tokens) != 1 or "=" not in tokens[0]:
                raise ValueError("%s:%d: expected AJP_NAME=value" % (site_path, number))
            key, value = tokens[0].split("=", 1)
            if not re.fullmatch(r"AJP_[A-Z0-9_]+", key):
                raise ValueError("%s:%d: only AJP_* settings are allowed" % (site_path, number))
            if "$(" in value or "`" in value:
                raise ValueError("%s:%d: shell expressions are not supported" % (site_path, number))
            value = os.path.expandvars(os.path.expanduser(value))
            if re.search(r"\$[{A-Za-z_]", value):
                raise ValueError("%s:%d: unresolved variable" % (site_path, number))
            os.environ.setdefault(key, value)
    os.environ.setdefault("AJP_WORKER_ENV", "")
    return site_path
