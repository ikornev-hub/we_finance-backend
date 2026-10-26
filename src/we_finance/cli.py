"""Модуль запуска всего приложения."""

import argparse
import getpass

from we_finance import __version__
from we_finance.auth.password import hash_password
from we_finance.auth.users import UserStore
from we_finance.doctor.report import main as main_doctor
from we_finance.settings import get_database_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="we-finance")
    sub = parser.add_subparsers(dest="command")
    doctor = sub.add_parser("doctor", help="Проверить окружение по requirements")
    doctor.add_argument("--file", default="requirements-dev.txt")
    set_password_cmd = sub.add_parser("set-password", help="Задать пароль пользователю")
    set_password_cmd.add_argument("login")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Вывод версии приложения"""
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return main_doctor(args.file)

    if args.command == "set-password":
        return set_password(args.login)

    print(f"We finance version {__version__}!")
    return 0


def set_password(login: str) -> int:
    """Проверить логин, спросить пароль дважды, не показывая его, и записать хеш."""
    users = UserStore(get_database_url())
    if users.find(login) is None:
        print(f"Пользователя {login} нет")
        return 1
    password = getpass.getpass("Пароль: ")
    if len(password) < 8:
        print("Пароль короче 8 символов")
        return 1
    if getpass.getpass("Ещё раз: ") != password:
        print("Пароли не совпали")
        return 1
    users.set_password_hash(login, hash_password(password))
    print(f"Пароль для {login} задан")
    return 0
