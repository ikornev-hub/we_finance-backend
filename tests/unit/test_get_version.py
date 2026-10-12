"""Тесты метаданных приложения."""

from we_finance import __version__
from we_finance.cli import main


def test_get_version(capsys):
    """Отображение версии приложения"""
    main([])
    out, _ = capsys.readouterr()
    assert out.strip() != ""
    assert out.strip() == f"We finance version {__version__}!"
