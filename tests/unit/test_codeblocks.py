from __future__ import annotations

import pytest

from unbidden.brain.codeblocks import CodeBlockError, parse_files

pytestmark = pytest.mark.unit


def test_headers_inside_and_above_fences() -> None:
    text = (
        "Here is the fix.\n"
        "```python\n# file: app/a.py\ndef f():\n    return 1\n```\n\n"
        "# file: web/b.ts\n```ts\nexport const b = 2;\n\n\n```\n"
    )
    assert parse_files(text) == {"app/a.py": "def f():\n    return 1\n", "web/b.ts": "export const b = 2;\n"}


def test_unfenced_answer() -> None:
    assert parse_files("# file: a.py\nx = 1\n") == {"a.py": "x = 1\n"}


@pytest.mark.parametrize("path", ["/etc/passwd", "../x.py"])
def test_unsafe_paths(path: str) -> None:
    with pytest.raises(CodeBlockError):
        parse_files(f"# file: {path}\nx\n")


def test_no_header() -> None:
    with pytest.raises(CodeBlockError):
        parse_files("```python\nx = 1\n```")


def test_header_on_the_fence_line() -> None:
    assert parse_files("```# file: tests/test_a.py\nimport x\n```") == {"tests/test_a.py": "import x\n"}
