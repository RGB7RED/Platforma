from cli import main


def test_main_outputs_name(capsys):
    assert main(["--name", "Codex"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "Hello, Codex!"
