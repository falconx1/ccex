"""Give a new profile the non-account bits of your config: onboarding, theme, folder trust."""
import os, sys

from ccexlib import load, save

d = sys.argv[1]
src = os.path.expanduser("~/.claude.json")
dst = os.path.join(d, ".claude.json")
KEEP = ("hasCompletedOnboarding", "lastOnboardingVersion", "lastReleaseNotesSeen", "theme",
        "installMethod", "autoUpdates", "respectGitignore", "tipsHistory", "hasSeenTasksHint",
        "showExpandedTodos", "copyOnSelect", "migrationVersion", "hasIdeOnboardingBeenShown")
a = load(src)
if not a:
    sys.exit(0)
b = load(dst)
for k in KEEP:
    if k in a and k not in b:
        b[k] = a[k]
proj = b.setdefault("projects", {})
for k, v in (a.get("projects") or {}).items():
    proj.setdefault(k, v)
save(dst, b)
print("ccex: seeded onboarding + trust for %d project dirs" % len(proj), file=sys.stderr)
