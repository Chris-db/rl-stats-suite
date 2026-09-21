"""Find Rocket League and turn on its Stats API.

Non-technical users shouldn't have to edit ``DefaultStatsAPI.ini`` by hand. This
locates every Rocket League install (Epic + Steam libraries) and sets
``PacketSendRate`` so the socket starts streaming.

Note: the config usually lives under Program Files, so writing it may need
administrator rights — :func:`enable_stats_api` reports that clearly instead of
crashing.
"""

from __future__ import annotations

import os
import re

DEFAULT_RATE = 10
CONFIG_REL = os.path.join("rocketleague", "TAGame", "Config", "DefaultStatsAPI.ini")


def _fixed_drives() -> list[str]:
    return [f"{d}:\\" for d in "CDEFGH" if os.path.exists(f"{d}:\\")]


def _steam_roots() -> list[str]:
    """Steam install dirs + extra library folders from libraryfolders.vdf."""
    roots: list[str] = []
    for drive in _fixed_drives():
        for sub in ("Program Files (x86)\\Steam", "Steam", "SteamLibrary",
                    "Games\\Steam", "SteamGames"):
            path = os.path.join(drive, sub)
            if os.path.isdir(path):
                roots.append(path)

    libraries = list(roots)
    for root in roots:
        for vdf in (os.path.join(root, "steamapps", "libraryfolders.vdf"),
                    os.path.join(root, "config", "libraryfolders.vdf")):
            if os.path.isfile(vdf):
                try:
                    text = open(vdf, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                for match in re.findall(r'"path"\s*"([^"]+)"', text):
                    libraries.append(match.replace("\\\\", "\\"))
    return libraries


def find_configs() -> list[str]:
    """Return paths to every DefaultStatsAPI.ini we can find."""
    found: set[str] = set()

    # Epic Games
    for drive in _fixed_drives():
        for pf in ("Program Files", "Program Files (x86)"):
            p = os.path.join(drive, pf, "Epic Games", "rocketleague",
                             "TAGame", "Config", "DefaultStatsAPI.ini")
            if os.path.isfile(p):
                found.add(p)

    # Steam libraries
    for root in _steam_roots():
        p = os.path.join(root, "steamapps", "common", CONFIG_REL)
        if os.path.isfile(p):
            found.add(p)

    return sorted(found)


def read_rate(path: str) -> int | None:
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    m = re.search(r"(?im)^\s*PacketSendRate\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def enable_stats_api(path: str, rate: int = DEFAULT_RATE) -> str:
    """Set PacketSendRate in one config file.

    Returns one of: ``"already"`` (no change needed), ``"updated"``,
    ``"denied"`` (needs admin), ``"error"``.
    """
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return "error"

    if re.search(r"(?im)^\s*PacketSendRate\s*=", text):
        new = re.sub(r"(?im)^(\s*PacketSendRate\s*=).*$", rf"\g<1>{rate}", text)
    else:
        new = text.rstrip() + f"\nPacketSendRate={rate}\n"

    if new == text:
        return "already"
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
        return "updated"
    except PermissionError:
        return "denied"
    except OSError:
        return "error"


def ensure_enabled(rate: int = DEFAULT_RATE) -> list[tuple[str, str]]:
    """Enable the Stats API in every install found. Returns [(path, status)]."""
    results = []
    for path in find_configs():
        # Skip the write entirely if it's already on (avoids needing admin).
        if read_rate(path) == rate:
            results.append((path, "already"))
        else:
            results.append((path, enable_stats_api(path, rate)))
    return results


_MESSAGES = {
    "already": "already enabled",
    "updated": "ENABLED",
    "denied": "needs admin — right-click and 'Run as administrator' once",
    "error": "could not read/write the file",
}


def main(argv=None) -> None:
    import argparse
    p = argparse.ArgumentParser(description="Enable Rocket League's Stats API.")
    p.add_argument("--rate", type=int, default=DEFAULT_RATE,
                   help="updates per second (0 disables).")
    args = p.parse_args(argv)

    results = ensure_enabled(args.rate)
    if not results:
        print("No Rocket League install found.")
        print("If it's installed somewhere unusual, set PacketSendRate=10 manually in")
        print(r"  ...\rocketleague\TAGame\Config\DefaultStatsAPI.ini")
        return
    for path, status in results:
        print(f"[{_MESSAGES.get(status, status)}]  {path}")
    if any(s == "updated" for _, s in results):
        print("\nRestart Rocket League so it picks up the change.")
    if any(s == "denied" for _, s in results):
        print("\nSome files need admin rights. Re-run this as administrator.")


if __name__ == "__main__":
    main()
