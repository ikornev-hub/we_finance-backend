"""Модуль запуска всего приложения."""

import argparse

from we_finance import __version__
from we_finance.doctor.report import main as main_doctor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="we-finance")
    sub = parser.add_subparsers(dest="command")
    doctor = sub.add_parser("doctor", help="Проверить окружение по requirements")
    doctor.add_argument("--file", default="requirements-dev.txt")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Вывод версии приложения"""
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return main_doctor(args.file)

    print(f"We finance version {__version__}!")
    return 0
