from pathlib import Path

from qoder_proxy.cli.main import main


def test_account_add_pat_and_list_cli(tmp_path: Path, capsys, monkeypatch) -> None:
    storage_path = tmp_path / "accounts.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "qoder-proxy",
            "account",
            "add-pat",
            "--storage",
            str(storage_path),
            "--name",
            "main",
            "--pat-env",
            "QODER_PAT",
        ],
    )

    main()

    assert "Added account" in capsys.readouterr().out

    monkeypatch.setattr(
        "sys.argv",
        ["qoder-proxy", "account", "list", "--storage", str(storage_path)],
    )
    main()

    out = capsys.readouterr().out
    assert "main" in out
    assert "pat" in out


def test_account_remove_cli(tmp_path: Path, capsys, monkeypatch) -> None:
    storage_path = tmp_path / "accounts.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "qoder-proxy",
            "account",
            "add-pat",
            "--storage",
            str(storage_path),
            "--name",
            "main",
            "--pat-env",
            "QODER_PAT",
        ],
    )
    main()
    account_id = capsys.readouterr().out.split("(")[1].split(")")[0]

    monkeypatch.setattr(
        "sys.argv",
        ["qoder-proxy", "account", "remove", account_id, "--storage", str(storage_path)],
    )
    main()

    assert "Removed account" in capsys.readouterr().out


def test_account_login_reports_unsupported(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["qoder-proxy", "account", "login"])

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 1

    assert "Browser login is not implemented" in capsys.readouterr().out
