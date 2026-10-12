def is_skippable(line: str) -> bool:
    """True, если строку requirements нужно пропустить:
    пустая (в том числе из пробелов) или комментарий"""
    stripped = line.strip()
    return stripped == "" or stripped.startswith("#")


def is_include(line: str) -> bool:
    """True, если строка подключает другой файл (начинается с -r)"""
    return line.strip().startswith("-r") or line.strip().startswith("--requirement")


def include_path(line: str) -> str:
    """Имя файла из строки подключения (-r file, -rfile, --requirement file)."""
    stripped = line.strip()
    if stripped.startswith("--requirement"):
        rest = stripped[len("--requirement") :]
    else:
        rest = stripped[2:]
    rest = rest.strip()
    if rest == "":
        raise ValueError(f"В строке подключения нет имени файла: {line!r}")
    return rest


def normalize_name(name: str) -> str:
    """Приводит имя пакета к единому виду: нижний регистр, "_" и "." заменяются на '-'"""
    while "." in name or "_" in name or "--" in name:
        name = name.replace("_", "-").replace(".", "-").replace("--", "-")
    return name.lower().strip()


def classify_line(line: str) -> str:
    """Итоговая классификация строки: "skip", "include" или "requirement"""
    if is_skippable(line):
        return "skip"
    if is_include(line):
        return "include"

    return "requirement"


if __name__ == "__main__":
    ...
