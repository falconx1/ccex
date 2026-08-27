"""Give a new profile the non-account bits of your config: onboarding, theme, folder trust."""
import os, sys

from ccexlib import BASE, cfg_for, load, save, seed_into

d = sys.argv[1]
dst = os.path.join(d, ".claude.json")
a = load(cfg_for(BASE))
if not a:
    sys.exit(0)
b = load(dst)
n = seed_into(b, a)
save(dst, b)
print("ccex: seeded onboarding + trust for %d project dirs" % n, file=sys.stderr)
