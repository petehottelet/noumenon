"""Noumenon runs from its own sources plus third-party packages only."""

import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"smythe", "benchmarks", "screensaver"}
SOURCE_DIRECTORIES = ("linux", "macos", "windows", "verification", "svg-preview", "tests")
MODULES = ["export_glyphs", "export_native_glyphs", "export_generated_sdf", "import_reference_glyphs",
           "svg_raster", "linux.smoke_linux", "verification.analyze_native_masks", "live.feedcheck"]


def _python_sources() -> list[Path]:
    paths = set(ROOT.glob("*.py"))
    for directory in SOURCE_DIRECTORIES:
        paths.update((ROOT / directory).glob("**/*.py"))
    return sorted(path for path in paths if "__pycache__" not in path.parts)


def test_no_source_imports_smythe_packages():
    offenders = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            offenders += [f"{path.relative_to(ROOT).as_posix()}: {name}" for name in names
                          if name.partition(".")[0] in FORBIDDEN]
    assert len(_python_sources()) >= 15
    assert not offenders


def test_every_module_imports_from_this_repository_without_smythe():
    # A fresh interpreter, which may have Smythe installed, loads only these files.
    code = (
        "import importlib, json, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        f"files = {{name: importlib.import_module(name).__file__ for name in {MODULES!r}}}\n"
        "print(json.dumps({'files': files, 'loaded': sorted({name.partition('.')[0] for name in sys.modules})}))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            cwd=ROOT, check=True, timeout=60)
    report = json.loads(result.stdout)
    assert not set(report["loaded"]) & FORBIDDEN
    for name, file in report["files"].items():
        assert Path(file).resolve().is_relative_to(ROOT), name


def _imports(path: Path, *, top_level_only: bool = False) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = tree.body if top_level_only else ast.walk(tree)
    names = []
    for node in nodes:
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names += [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
    return names


def test_only_the_optional_live_generator_uses_smythe_and_only_when_running():
    # The live generator runs on Smythe by design, but imports it inside the
    # functions that need it, so its grammar, gate and feed rules load without it.
    live = sorted((ROOT / "live").glob("*.py"))
    assert live
    for path in live:
        assert not [name for name in _imports(path, top_level_only=True)
                    if name.partition(".")[0] in FORBIDDEN], path.name
    assert not [name for name in _imports(ROOT / "live" / "feedcheck.py")
                if name.partition(".")[0] not in sys.stdlib_module_names], "feedcheck must stay standard-library only"


def test_the_core_uses_the_live_generator_only_for_the_native_feed_check():
    for path in _python_sources():
        if path.name.startswith("test_live") or path.name == "test_standalone.py":
            continue
        used = {name for name in _imports(path) if name.partition(".")[0] == "live"}
        assert used <= {"live", "live.feedcheck"}, f"{path.relative_to(ROOT).as_posix()}: {sorted(used)}"
