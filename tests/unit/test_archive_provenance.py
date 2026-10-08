"""Une archive conserve l'identité source sans présumer un arbre propre."""

from anonymisation.cli import predict


def test_exported_commit_used_without_git(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "_git", lambda *_: None)
    commit = "a" * 40
    (tmp_path / ".git_archival.txt").write_text(f"commit: {commit}\ntree: {'b' * 40}\n")
    assert predict._git_commit(tmp_path) == commit
    # L'identité exportée suffit au calcul diagnostic ; elle ne prouve pas
    # que l'archive n'a pas été modifiée depuis l'export.
    assert predict._git_dirty(tmp_path) is None


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
