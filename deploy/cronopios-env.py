#!/usr/bin/env python3
"""Cronopios: read or set keys in /opt/brightbean/.env without touching the rest.
  cronopios-env.py get KEY
  cronopios-env.py set KEY=VALUE [KEY=VALUE ...]
"""
import re
import sys

PATH = "/opt/brightbean/.env"


def read():
    try:
        return open(PATH).read()
    except FileNotFoundError:
        return ""


def get(text, key):
    m = re.search(r"^%s=(.*)$" % re.escape(key), text, flags=re.M)
    return m.group(1).strip() if m else ""


def main(argv):
    text = read()
    if len(argv) == 3 and argv[1] == "get":
        print(get(text, argv[2]))
        return 0
    if len(argv) >= 3 and argv[1] == "set":
        for pair in argv[2:]:
            key, _, value = pair.partition("=")
            line = "%s=%s" % (key, value)
            text, n = re.subn(r"^#?\s*%s=.*$" % re.escape(key), lambda m: line, text, count=1, flags=re.M)
            if not n:
                text = text.rstrip("\n") + "\n" + line + "\n"
        open(PATH, "w").write(text)
        return 0
    print(__doc__)
    return 2


sys.exit(main(sys.argv))
