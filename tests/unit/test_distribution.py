"""`unbidden update` / `unbidden uninstall` and the shipped installer: no network, no uv call that changes anything."""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from unbidden import __version__, distribution
from unbidden.distribution import (
    INSTALL_SH,
    cmd_uninstall,
    cmd_update,
    data_paths,
    installed_version,
    register,
    run_installer,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _args(**kw: object) -> argparse.Namespace:
    return argparse.Namespace(**kw)


# --- the installer file itself -------------------------------------------------------------------------------------


def test_the_packaged_installer_is_the_root_installer() -> None:
    """One source of truth: install.sh at the root and the copy shipped with the package are byte for byte equal."""
    assert INSTALL_SH.is_file()
    assert INSTALL_SH.read_bytes() == (ROOT / "install.sh").read_bytes()


def test_the_installer_parses_as_posix_sh_and_bash() -> None:
    subprocess.run(["sh", "-n", str(INSTALL_SH)], check=True)
    subprocess.run(["bash", "-n", str(INSTALL_SH)], check=True)


def test_the_installer_refuses_a_version_with_a_custom_base_unset(tmp_path: Path) -> None:
    """With UNBIDDEN_INSTALL_BASE set and no --version, the script must not guess: exit 2 with the reason."""
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "UNBIDDEN_INSTALL_BASE": "http://127.0.0.1:1",
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(["sh", str(INSTALL_SH)], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert result.returncode == 2
    assert "--version X.Y.Z" in result.stderr


def test_the_installer_refuses_a_plain_http_base_that_is_not_loopback(tmp_path: Path) -> None:
    env = {**os.environ, "HOME": str(tmp_path), "UNBIDDEN_INSTALL_BASE": "http://example.com/releases"}
    result = subprocess.run(
        ["sh", str(INSTALL_SH), "--version", "0.9.0"], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    assert result.returncode == 2
    assert "refusing a plain http://" in result.stderr


def test_the_installer_rejects_an_unknown_option() -> None:
    result = subprocess.run(
        ["sh", str(INSTALL_SH), "--bogus"], capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    assert result.returncode == 2
    assert "unknown option" in result.stderr


def test_help_prints_the_header_and_exits_zero() -> None:
    result = subprocess.run(["sh", str(INSTALL_SH), "--help"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert result.returncode == 0
    assert "UNBIDDEN_INSTALL_BASE" in result.stdout


# --- the checksum gate, with a local file server and a fake uv ----------------------------------------------------


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """A release-shaped directory on loopback: the wheel and SHA256SUMS."""
    site = tmp_path / "site"
    site.mkdir()
    wheel = site / "unbidden_ai-0.9.0-py3-none-any.whl"
    wheel.write_bytes(b"PK\x05\x06" + b"\0" * 18)  # an empty zip: never installed by these tests
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (site / "SHA256SUMS").write_text(f"{digest}  {wheel.name}\n")
    handler = type("H", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **k: handler(*a, directory=str(site), **k))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", site
    finally:
        server.shutdown()


@pytest.fixture
def fake_uv(tmp_path: Path) -> Path:
    """A `uv` that records what it was asked and answers `tool dir --bin`; `tool install` only logs."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    log = tmp_path / "uv.log"
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'case "$*" in\n'
        f'  "tool dir --bin") echo "{bin_dir}" ;;\n'
        f'  "tool dir") echo "{tmp_path}/tools" ;;\n'
        '  "--version") echo "uv 0.0-fake" ;;\n'
        "esac\n"
        "exit 0\n"
    )
    uv.chmod(0o755)
    return bin_dir


def _run_installer(base: str, fake_uv: Path, home: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        "HOME": str(home),
        "PATH": f"{fake_uv}:{os.environ['PATH']}",
        "UNBIDDEN_INSTALL_BASE": base,
        "TMPDIR": str(home),
    }
    return subprocess.run(
        ["sh", str(INSTALL_SH), "--yes", "--version", "0.9.0", *extra],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def test_a_tampered_wheel_is_refused_before_uv_is_asked_to_install(
    served: tuple[str, Path], fake_uv: Path, tmp_path: Path
) -> None:
    base, site = served
    (site / "SHA256SUMS").write_text("0" * 64 + "  unbidden_ai-0.9.0-py3-none-any.whl\n")
    result = _run_installer(base, fake_uv, tmp_path)
    assert result.returncode == 8, result.stderr
    assert "checksum mismatch" in result.stderr
    assert "Nothing was installed" in result.stderr
    assert "tool install" not in (tmp_path / "uv.log").read_text()


def test_a_sums_file_without_the_wheel_is_refused(served: tuple[str, Path], fake_uv: Path, tmp_path: Path) -> None:
    base, site = served
    (site / "SHA256SUMS").write_text("0" * 64 + "  something-else.whl\n")
    result = _run_installer(base, fake_uv, tmp_path)
    assert result.returncode == 7
    assert "does not list" in result.stderr


def test_a_good_checksum_reaches_uv_tool_install_with_python_312(
    served: tuple[str, Path], fake_uv: Path, tmp_path: Path
) -> None:
    """The gate passes; the fake uv installs nothing, so the version check after it fails with exit 9 and says so."""
    base, _ = served
    result = _run_installer(base, fake_uv, tmp_path)
    assert "sha256 verified" in result.stderr
    asked = (tmp_path / "uv.log").read_text()
    assert "tool install --python 3.12 --reinstall" in asked
    assert "unbidden_ai-0.9.0-py3-none-any.whl" in asked
    assert result.returncode == 9  # the fake installed nothing: 'reports ... instead of 0.9.0'


# --- cmd_update ----------------------------------------------------------------------------------------------------


def test_installed_version_reads_the_installer_report() -> None:
    assert installed_version("x\nunbidden-ai 0.9.1 installed: /h/.local/bin/unbidden\n  next: cd ...\n") == "0.9.1"
    assert installed_version("nothing here") is None


def test_run_installer_passes_version_and_base(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def runner(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        seen["env"] = kw["env"]
        return subprocess.CompletedProcess(argv, 0, "", "unbidden-ai 0.8.0 installed: /x/unbidden\n")

    monkeypatch.delenv("UNBIDDEN_INSTALL_BASE", raising=False)
    result = run_installer("0.8.0", base="http://127.0.0.1:1", runner=runner)
    assert seen["argv"] == ["sh", str(INSTALL_SH), "--yes", "--version", "0.8.0"]
    assert seen["env"]["UNBIDDEN_INSTALL_BASE"] == "http://127.0.0.1:1"  # type: ignore[index]
    assert installed_version(result.stderr) == "0.8.0"


def test_update_json_reports_the_installer_outcome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(distribution, "find_uv", lambda: "/fake/uv")
    monkeypatch.setattr(
        distribution,
        "run_installer",
        lambda version, base=None: subprocess.CompletedProcess(
            [], 0, "", f"sha256 verified: abc\nunbidden-ai {version} installed: /h/bin/unbidden\n"
        ),
    )
    assert cmd_update(_args(json=True, version="0.9.1", base=None)) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["from"] == __version__
    assert data["requested"] == "0.9.1"
    assert data["installed"] == "0.9.1"


def test_update_failure_is_exit_one_and_nothing_hides_the_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(distribution, "find_uv", lambda: "/fake/uv")
    monkeypatch.setattr(
        distribution,
        "run_installer",
        lambda version, base=None: subprocess.CompletedProcess([], 8, "", "unbidden install: checksum mismatch\n"),
    )
    assert cmd_update(_args(json=False, version=None, base=None)) == 1
    captured = capsys.readouterr()
    assert "checksum mismatch" in captured.err
    assert "nothing changed" in captured.err


def test_update_without_uv_is_exit_two(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(distribution, "find_uv", lambda: None)
    assert cmd_update(_args(json=True, version=None, base=None)) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


# --- cmd_uninstall -------------------------------------------------------------------------------------------------


def test_uninstall_without_yes_only_shows_the_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], spend_home: Path
) -> None:
    monkeypatch.setattr(distribution, "find_uv", lambda: "/fake/uv")
    calls: list[list[str]] = []
    monkeypatch.setattr(distribution.subprocess, "run", lambda argv, **kw: calls.append(argv))
    assert cmd_uninstall(_args(json=True, yes=False, purge=False)) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["command"] == ["/fake/uv", "tool", "uninstall", "unbidden-ai"]
    assert plan["done"] is False
    assert str(spend_home) in plan["keeps"]
    assert calls == []


def test_uninstall_with_yes_runs_uv_and_keeps_data(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], spend_home: Path
) -> None:
    monkeypatch.setattr(distribution, "find_uv", lambda: "/fake/uv")
    marker = spend_home / "marker"
    marker.write_text("keep me")
    calls: list[list[str]] = []

    def run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "Uninstalled 1 executable: unbidden\n")

    monkeypatch.setattr(distribution.subprocess, "run", run)
    assert cmd_uninstall(_args(json=True, yes=True, purge=False)) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["done"] is True
    assert calls == [["/fake/uv", "tool", "uninstall", "unbidden-ai"]]
    assert marker.read_text() == "keep me"


def test_purge_requires_yes_and_lists_the_paths_first(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], spend_home: Path
) -> None:
    monkeypatch.setattr(distribution, "find_uv", lambda: "/fake/uv")
    (spend_home / "marker").write_text("still here")
    monkeypatch.setattr(distribution.subprocess, "run", lambda *a, **k: pytest.fail("must not run anything"))
    assert cmd_uninstall(_args(json=False, yes=False, purge=True)) == 2
    err = capsys.readouterr().err
    assert str(spend_home) in err
    assert "add --yes" in err
    assert (spend_home / "marker").exists()


def test_purge_with_yes_deletes_the_listed_paths_after_uv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], spend_home: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(distribution, "find_uv", lambda: "/fake/uv")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".unbidden").mkdir()
    (spend_home / "marker").write_text("gone")
    monkeypatch.setattr(distribution.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", ""))
    assert cmd_uninstall(_args(json=True, yes=True, purge=True)) == 0
    plan = json.loads(capsys.readouterr().out)
    assert set(plan["removes_data"]) == {str(spend_home), str(tmp_path / ".unbidden")}
    assert not spend_home.exists()
    assert not (tmp_path / ".unbidden").exists()


def test_data_paths_lists_home_and_this_repository(spend_home: Path, tmp_path: Path) -> None:
    assert data_paths(tmp_path) == [spend_home]
    (tmp_path / ".unbidden").mkdir()
    assert data_paths(tmp_path) == [spend_home, tmp_path / ".unbidden"]


# --- register ----------------------------------------------------------------------------------------------------


def test_register_wires_update_and_uninstall_like_build_parser_does() -> None:
    parser = argparse.ArgumentParser(prog="unbidden")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name: str, handler: object, help_text: str, *, json_out: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(handler=handler)
        if json_out:
            p.add_argument("--json", action="store_true")
        return p

    register(command)
    args = parser.parse_args(["update", "--version", "0.8.0", "--json"])
    assert args.handler is cmd_update and args.version == "0.8.0" and args.json
    args = parser.parse_args(["uninstall", "--purge", "--yes"])
    assert args.handler is cmd_uninstall and args.purge and args.yes
