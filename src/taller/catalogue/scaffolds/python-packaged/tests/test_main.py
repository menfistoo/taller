import main


def test_it_runs_and_reports_its_version(capsys):
    assert main.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "%%name%% " + main.VERSION
