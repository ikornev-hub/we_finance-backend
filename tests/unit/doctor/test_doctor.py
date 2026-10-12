import pytest

from we_finance.doctor.installed import (
    check_all,
    check_one,
    find_extra,
    get_installed,
    requirement_lines,
    to_installed_dict,
)
from we_finance.doctor.lines import (
    classify_line,
    include_path,
    is_include,
    is_skippable,
    normalize_name,
)
from we_finance.doctor.report import (
    bad_lines,
    exit_code,
    format_report,
    read_lines,
    read_requirements,
)


@pytest.mark.parametrize(
    ("requirements", "expected"),
    [
        (
            ["-r requirements.txt", "", "# comment", "pytest==9.1.1", "  ruff==0.16.9  "],
            ["pytest==9.1.1", "ruff==0.16.9"],
        ),
        ([], []),
        (["", "# only comments"], []),
        (["requests", "pydantic>=2.9,<3"], ["requests", "pydantic>=2.9,<3"]),
    ],
    ids=["filter comments", "empty lists", "without packets", "version in ranges"],
)
def test_filter_get_requirements_lines(requirements, expected):
    assert requirement_lines(requirements) == expected


@pytest.mark.parametrize(
    ("tuples", "expected"),
    [
        (
            [("Pre_Commit", "4.6.2"), ("fastapi", "0.142.2")],
            {"pre-commit": "4.6.2", "fastapi": "0.142.2"},
        ),
        ([], {}),
    ],
    ids=["valid structure", "empty lists"],
)
def test_installed_to_dict(tuples, expected):
    assert to_installed_dict(tuples) == expected


@pytest.mark.parametrize(
    ("requirements_list", "expected"),
    [
        (["fastapi==0.142.2", "uvicorn==0.54.0"], [("fastapi", "ok"), ("uvicorn", "missing")]),
        ([], []),
    ],
    ids=["valid structure", "empty_list"],
)
def test_return_status(requirements_list, expected, requirements_installed):
    assert check_all(requirements_list, requirements_installed) == expected


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("fastapi==0.142.2", "ok"),
        ("fastapi", "ok"),
        ("fastapi==0.125.0", "mismatch"),
        ("pydantic>=2.9,<3", "ok"),
        ("pydantic<2", "mismatch"),
        ("uvicorn==0.54.0", "missing"),
        ("Pre_Commit==4.6.2", "ok"),
        ("requests", "missing"),
    ],
)
def test_check_one_requirement(requirement, requirements_installed, expected):
    assert check_one(requirement, requirements_installed) == expected


@pytest.mark.parametrize(
    ("requirements_list", "expected"),
    [
        (["fastapi==0.142.2"], ["pre-commit", "pydantic"]),
        (["fastapi", "pydantic", "pre-commit"], []),
    ],
)
def test_find_extra_requirements(requirements_list, requirements_installed, expected):
    assert find_extra(requirements_list, requirements_installed) == expected


@pytest.mark.parametrize("check_installed", ["fastapi", "pre-commit"])
def test_get_installed(check_installed):
    installed_now = get_installed()
    assert check_installed in installed_now
    assert installed_now["pydantic"].startswith("2.")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("-r requirements.txt", "requirements.txt"),
        ("-rrequirements.txt", "requirements.txt"),
        ("--requirement base.txt", "base.txt"),
        ("  -r   base.txt ", "base.txt"),
    ],
)
def test_check_include_path(line, expected):
    assert include_path(line) == expected


@pytest.mark.parametrize("line", ["-r", "--requirement   "])
def test_get_raise_without_file(line):
    with pytest.raises(ValueError):
        include_path(line)


@pytest.mark.parametrize(
    ("filename", "expected"), [("base.txt", ["# prod", "fastapi==0.142.2", "pydantic>=2.9,<3"])]
)
def test_read_lines(path_to_requirements, filename, expected):
    assert read_lines(path_to_requirements / filename) == expected


@pytest.mark.parametrize("filename", ["nope.txt"])
def test_get_raise_not_found(path_to_requirements, filename):
    with pytest.raises(FileNotFoundError):
        read_lines(path_to_requirements / filename)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("base.txt", ["fastapi==0.142.2", "pydantic>=2.9,<3"]),
        ("dev.txt", ["fastapi==0.142.2", "pydantic>=2.9,<3", "pytest==9.1.1"]),
        ("sub/inner.txt", ["fastapi==0.142.2", "pydantic>=2.9,<3", "ruff==0.16.9"]),
    ],
)
def test_read_requirements(path_to_requirements, filename, expected):
    assert read_requirements(path_to_requirements / filename) == expected


@pytest.mark.parametrize("filename", ["missing_include.txt"])
def test_get_raise_read_requirements_without_file(path_to_requirements, filename):
    with pytest.raises(FileNotFoundError):
        read_requirements(path_to_requirements / filename)


@pytest.mark.parametrize("filename", ["loop_a.txt"])
def test_get_raise_read_requirements_value_error(path_to_requirements, filename):
    with pytest.raises(ValueError):
        read_requirements(path_to_requirements / filename)


@pytest.mark.parametrize(
    ("requirements_lines", "expected"),
    [
        (["fastapi==0.142.2", "fastapi=1", "!!!"], ["fastapi=1", "!!!"]),
        (["fastapi", "pydantic>=2"], []),
    ],
)
def test_get_bad_lines(requirements_lines, expected):
    assert bad_lines(requirements_lines) == expected


@pytest.mark.parametrize(
    ("requirements_tuples", "extra", "expected"),
    [
        (
            [("fastapi", "ok"), ("uvicorn", "missing")],
            ["pywin32"],
            "ok: fastapi\nmissing: uvicorn\nextra: pywin32",
        ),
        ([], [], ""),
    ],
)
def test_format_report(requirements_tuples, extra, expected):
    assert format_report(requirements_tuples, extra) == expected


@pytest.mark.parametrize(
    ("requirements_tuples", "expected"),
    [
        ([("fastapi", "ok")], 0),
        ([("fastapi", "ok"), ("uvicorn", "missing")], 1),
        ([], 0),
        ([("ruff", "mismatch")], 1),
    ],
)
def test_exit_code(requirements_tuples, expected):
    assert exit_code(requirements_tuples) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("", True),
        ("   ", True),
        ("# dev tools", True),
        ("   # отступ перед комментарием", True),
        ("fastapi==0.142.2", False),
        ("-r requirements.txt", False),
        ("requests", False),
        ("fastapi>=0.140", False),
        ("# TODO: добавить -r base.txt", True),
        ("--requirement base.txt", False),
    ],
)
def test_is_skippable(line, expected):
    assert is_skippable(line) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("-r requirements.txt", True),
        ("  -r requirements.txt  ", True),
        ("fastapi==0.142.2", False),
        ("# dev tools", False),
        ("", False),
        ("-rrequirement base.txt", True),
        ("fastapi>=0.140", False),
        ("  ", False),
        ("--requirement base.txt", True),
    ],
)
def test_is_include(line, expected):
    assert is_include(line) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("-r requirements.txt", "requirements.txt"),
        ("  -r   base.txt ", "base.txt"),
        ("-r dev-requirements.txt", "dev-requirements.txt"),
    ],
)
def test_get_filename_include_path(line, expected):
    assert include_path(line) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("pre_commit", "pre-commit"),
        ("Pre-Commit", "pre-commit"),
        ("typing_extensions", "typing-extensions"),
        ("zope.interface", "zope-interface"),
        ("fastapi", "fastapi"),
        ("pre__commit", "pre-commit"),
        ("Zope..Interface", "zope-interface"),
        ("a-_.b", "a-b"),
        (" uvicorN", "uvicorn"),
    ],
)
def test_normalize_name(name, expected):
    assert normalize_name(name) == expected


@pytest.mark.parametrize(
    ("line", "expected_status"),
    [
        ("", "skip"),
        ("# comment", "skip"),
        ("-r requirements.txt", "include"),
        ("fastapi==0.142.2", "requirement"),
        ("fastapi>=0.140", "requirement"),
        ("requests", "requirement"),
    ],
)
def test_classify_line(line, expected_status):
    assert classify_line(line) == expected_status
