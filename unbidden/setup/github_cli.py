"""Connect GitHub through the `gh` CLI, in the person's own terminal: install gh when it is missing (with the
machine's package manager, under the person's eyes and password), then `gh auth login --web`, which shows a code
and opens the browser. Unbidden then reads the session the way it already does (`gh auth token`, held in memory,
never copied): no OAuth App of Unbidden's own, nothing stored by Unbidden."""

from __future__ import annotations

import shutil
from collections.abc import Callable

from unbidden.setup.github_access import forget_gh_token, gh_token

Terminal = Callable[[list[str]], int]  # run argv in the person's terminal (the app suspends itself), exit code

LOGIN = ["gh", "auth", "login", "--web", "--git-protocol", "https", "--hostname", "github.com"]
SITE = "https://cli.github.com"

_MANAGERS: tuple[tuple[str, list[str]], ...] = (
    ("brew", ["brew", "install", "gh"]),
    ("apt-get", ["sudo", "apt-get", "install", "-y", "gh"]),
    ("dnf", ["sudo", "dnf", "install", "-y", "gh"]),
    ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "github-cli"]),
    ("zypper", ["sudo", "zypper", "install", "-y", "gh"]),
    ("winget", ["winget", "install", "--id", "GitHub.cli"]),
)


def installed() -> bool:
    return shutil.which("gh") is not None


def install_command() -> list[str] | None:
    """The command that installs gh here, by the first package manager found; None when none is."""
    for name, argv in _MANAGERS:
        if shutil.which(name):
            return argv
    return None


def sign_in(terminal: Terminal, say: Callable[[str], None], *, confirm_install: Callable[[list[str]], bool]) -> bool:
    """Install gh if needed (asking first), sign in, and confirm the session is readable. True when it is."""
    from unbidden.setup.text import t

    if not installed():
        command = install_command()
        if command is None:
            say(t("gh.install.none", site=SITE))
            return False
        if not confirm_install(command):
            say(t("gh.install.skipped", site=SITE))
            return False
        if terminal(command) != 0 or not installed():
            say(t("gh.install.failed", site=SITE))
            return False
    say(t("gh.login"))
    code = terminal(LOGIN)
    forget_gh_token()
    if code != 0 or not gh_token():
        say(t("gh.failed"))
        return False
    return True
