"""Тесты командной строки we-finance."""

from we_finance.cli import main


def test_doctor_bad_file_exits_2(capsys, path_to_requirements):
    """Мусор в requirements — код 2 и список плохих строк."""
    code = main(["doctor", "--file", str(path_to_requirements / "bad.txt")])
    out, _ = capsys.readouterr()
    assert code == 2
    assert "fastapi=1" in out


def test_doctor_all_ok_exits_0(capsys, monkeypatch, path_to_requirements, requirements_installed):
    """Всё установлено как требуется — код 0."""
    monkeypatch.setattr("we_finance.doctor.report.get_installed", lambda: requirements_installed)
    code = main(["doctor", "--file", str(path_to_requirements / "base.txt")])
    out, _ = capsys.readouterr()
    assert code == 0
    assert "ok: fastapi" in out


def test_doctor_drift_exits_1(capsys, monkeypatch, path_to_requirements):
    """Установлена не та версия пакета — код 1 и mismatch в отчёте."""
    drifted = {"fastapi": "0.125.0", "pydantic": "2.13.5"}
    monkeypatch.setattr("we_finance.doctor.report.get_installed", lambda: drifted)
    code = main(["doctor", "--file", str(path_to_requirements / "base.txt")])
    out, _ = capsys.readouterr()
    assert code == 1
    assert "mismatch: fastapi" in out
