from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

from we_finance.doctor.installed import check_all, find_extra, get_installed
from we_finance.doctor.lines import classify_line, include_path


def read_lines(path: Path) -> list[str]:
    """Прочитать файл в список строк (utf-8)."""
    if path.exists():
        text = path.read_text(encoding="UTF-8")
        lines = text.splitlines()
    else:
        raise FileNotFoundError(f"Нет файла по указанному пути {path}")

    return lines


def read_requirements(path: Path, seen: set[Path] | None = None) -> list[str]:
    """Все строки-требования файла, с рекурсивным раскрытием -r."""
    if seen is None:
        seen = set()
    path = path.resolve()
    if path in seen:
        raise ValueError(f"Циклическое подключение {path}")
    seen.add(path)

    lines = read_lines(path)
    result = []
    for line in lines:
        if classify_line(line) == "requirement":
            result.append(line.strip())
        elif classify_line(line) == "include":
            includes_p = Path(path.parent / include_path(line))
            result.extend(read_requirements(includes_p, seen))

    return result


def bad_lines(lines: list[str]) -> list[str]:
    """Строки, которые packaging не может разобрать как требование."""
    result = []
    for line in lines:
        try:
            Requirement(line)
        except InvalidRequirement:
            result.append(line)

    return result


def format_report(statuses: list[tuple[str, str]], extra: list[str]) -> str:
    """Текст отчёта: '<статус>: <имя>' на каждое требование, затем 'extra: <имя>'."""
    lines = []
    for name, status in statuses:
        lines.append(f"{status}: {name}")
    for name in extra:
        lines.append(f"extra: {name}")
    return "\n".join(lines)


def exit_code(statuses: list[tuple[str, str]]) -> int:
    """0 — все требования ok, 1 — есть missing/mismatch."""
    for _, status in statuses:
        if status != "ok":
            return 1

    return 0


def main(filename: str) -> int:
    """Проверить окружение по requirements-файлу, напечатать отчёт, вернуть код возврата."""
    my_libs = read_requirements(Path(filename))
    have_bad_lines = bad_lines(my_libs)
    if have_bad_lines:
        print("\n".join(have_bad_lines))
        return 2
    installed_now = get_installed()
    check = check_all(my_libs, installed_now)
    extra = find_extra(my_libs, installed_now)
    print(format_report(check, extra))
    return exit_code(check)
