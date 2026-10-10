"""Une archive conserve l'identité source sans présumer un arbre propre."""

from anonymisation.cli import predict


def test_exported_commit_used_without_git(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_git", lambda *_: None)
    commit = "a" * 40
    (tmp_path / ".git_archival.txt").write_text(f"commit: {commit}\ntree: {'b' * 40}\n")
    assert predict._git_commit(tmp_path) == commit
    # Un arbre déclaré mais divergent n'est jamais présumé propre.
    assert predict._git_dirty(tmp_path) is True


def test_unexpanded_or_malformed_marker_never_invents_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_git", lambda *_: None)
    marker = tmp_path / ".git_archival.txt"
    marker.write_text("commit: $Format:%H$\ntree: $Format:%T$\n")
    assert predict._git_commit(tmp_path) is None
    marker.write_text("commit: pretend-commit\ntree: bad\n")
    assert predict._git_commit(tmp_path) is None


def test_live_git_precedes_archive_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_git", lambda *_: "live-commit\n")
    (tmp_path / ".git_archival.txt").write_text(f"commit: {'a' * 40}\ntree: {'b' * 40}\n")
    assert predict._git_commit(tmp_path) == "live-commit"


def test_real_git_archive_checks_changes_and_ignored_outputs(tmp_path):
    import subprocess
    import tarfile

    from anonymisation.provenance import ARCHIVAL_TEMPLATE, archive_dirty, archive_identity

    source = tmp_path / "source"
    source.mkdir()

    def git(*args):
        return subprocess.check_output(("git", *args), cwd=source).decode().strip()

    git("init", "--quiet")
    (source / ".gitignore").write_text("runs/\n.venv/\n")
    (source / ".gitattributes").write_text(".git_archival.txt export-subst\n")
    (source / ".git_archival.txt").write_bytes(ARCHIVAL_TEMPLATE)
    (source / "code.py").write_text("value = 1\n")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    path = tmp_path / "source.tar"
    git("archive", "HEAD", "-o", str(path))
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(path) as archive:
        archive.extractall(extracted, filter="data")
    assert archive_identity(extracted) == (git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}"))
    assert archive_dirty(extracted) is False
    (extracted / "runs").mkdir()
    (extracted / "runs/result.json").write_text("{}")
    assert archive_dirty(extracted) is False
    (extracted / "code.py").write_text("value = 2\n")
    assert archive_dirty(extracted) is True
    (extracted / "code.py").write_text("value = 1\n")
    (extracted / "extra_code.py").write_text("value = 3\n")
    assert archive_dirty(extracted) is True
    (extracted / "extra_code.py").unlink()
    (extracted / "code.py").chmod(0o755)
    assert archive_dirty(extracted) is True
    (extracted / "code.py").unlink()
    assert archive_dirty(extracted) is True


def test_archive_without_git_tool_remains_unknown(tmp_path, monkeypatch):
    import subprocess

    from anonymisation.provenance import archive_dirty

    (tmp_path / ".git_archival.txt").write_text(f"commit: {'a' * 40}\ntree: {'b' * 40}\n")

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(subprocess, "run", unavailable)
    assert archive_dirty(tmp_path) is None
