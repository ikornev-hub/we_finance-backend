from importlib.metadata import distributions

from packaging.requirements import Requirement

from we_finance.doctor.lines import classify_line, normalize_name


def requirement_lines(lines) -> list[str]:
    """
    Из всех строк файла оставить только строки-требования, очищенные от пробелов.
    Пропуски и подключения (-r) — выбросить (подключения обработаем в py-3).
    """
    result = []
    for line in lines:
        if classify_line(line) == "requirement":
            result.append(line.strip())

    return result


def to_installed_dict(pairs) -> dict[str, str]:
    """Список пар (имя, версия) → словарь {нормализованное имя: версия}"""
    result = {}
    for key, value in pairs:
        if key and value:
            key = normalize_name(key)
            result[key] = value

    return result


def get_installed() -> dict[str, str]:
    """То же, но по-настоящему установленным пакетам (используй distributions() и функцию 2).
    ⚠️ Эти проверки зависят от твоего .venv — это уже не чистая функция."""
    pairs = []
    for dist in distributions():
        pairs.append((dist.metadata["Name"], dist.version))

    return to_installed_dict(pairs)


def check_one(line, installed) -> str:
    """Статус одного требования: "ok", "missing" или "mismatch\""""
    status = "missing"

    r = Requirement(line)
    name = normalize_name(r.name)
    if name in installed:
        if installed[name] in r.specifier:
            status = "ok"
        else:
            status = "mismatch"
    return status


def check_all(lines, installed) -> list[tuple[str, str]]:
    """Статусы всех требований: список пар (нормализованное имя, статус) в порядке строк"""
    result = []
    for line in lines:
        r = Requirement(line)
        result.append((normalize_name(r.name), check_one(line, installed)))
    return result


def find_extra(lines, installed) -> list[str]:
    """Установлено, но не упомянуто в требованиях. Отсортированный список имён."""
    lists = []
    for line in lines:
        r = Requirement(line)
        lists.append(normalize_name(r.name))
    result = []
    for inst in installed:
        if inst not in lists:
            result.append(inst)
    return sorted(result)


if __name__ == "__main__":
    installed_now = get_installed()
