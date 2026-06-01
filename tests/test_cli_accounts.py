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
