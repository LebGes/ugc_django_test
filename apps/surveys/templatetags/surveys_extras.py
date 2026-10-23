from datetime import timedelta

from django import template


register = template.Library()


@register.filter
def human_duration(value: timedelta | None) -> str:
    """
    Форматирует длительность в виде '3 мин 15 сек'.

    :param value: длительность
    :return: строка для отображения
    """
    
    if value is None:
        return 'нет данных'
    
    total_seconds = round(value.total_seconds())
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    
    parts = [
        f'{amount} {unit}'
        for amount, unit in ((hours, 'ч'), (minutes, 'мин'), (seconds, 'сек'))
        if amount
    ]
    
    return ' '.join(parts) or '0 сек'
