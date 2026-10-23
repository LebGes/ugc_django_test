import os

from django.core.exceptions import ImproperlyConfigured


_TRUE_VALUES = frozenset({'1', 'true', 'yes', 'on'})
_FALSE_VALUES = frozenset({'0', 'false', 'no', 'off', ''})


def env_str(name: str, default: str | None = None) -> str:
    """
    Читает строковую переменную окружения.

    :param name: имя переменной окружения
    :param default: значение по умолчанию, если переменная не задана
    :return: значение переменной
    """
    value = os.environ.get(name, default)
    
    if value is None:
        raise ImproperlyConfigured(f'Не задана переменная окружения {name}')
    
    return value


def env_bool(name: str, default: bool = False) -> bool:
    """
    Читает логическую переменную окружения.

    :param name: имя переменной окружения
    :param default: значение по умолчанию, если переменная не задана
    :return: значение переменной
    """
    raw = os.environ.get(name)
    
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    
    raise ImproperlyConfigured(f'Переменная {name} должна быть логической, получено {raw!r}')


def env_int(name: str, default: int) -> int:
    """
    Читает целочисленную переменную окружения.

    :param name: имя переменной окружения
    :param default: значение по умолчанию, если переменная не задана
    :return: значение переменной
    """
    raw = os.environ.get(name)

    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f'Переменная {name} должна быть целым числом') from exc


def env_list(name: str, default: str = '') -> list[str]:
    """
    Читает переменную окружения со списком значений через запятую.

    :param name: имя переменной окружения
    :param default: значение по умолчанию, если переменная не задана
    :return: список непустых значений
    """

    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]
