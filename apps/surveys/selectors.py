from django.db.models import Q, QuerySet

from apps.surveys.models import Survey, SurveyStatus


def visible_surveys(user_id: int | None) -> QuerySet[Survey]:
    """
    Возвращает опросы, которые пользователь может видеть.

    Черновики видит только автор, опубликованные и закрытые опросы видят все.

    :param user_id: идентификатор пользователя
    :return: набор доступных опросов
    """
    
    return Survey.objects.select_related("author").filter(
        Q(author_id=user_id) | ~Q(status=SurveyStatus.DRAFT)
    )


def published_surveys() -> QuerySet[Survey]:
    """
    Возвращает опубликованные опросы.

    :return: набор опросов
    """

    return Survey.objects.select_related("author").filter(status=SurveyStatus.PUBLISHED)


def authored_surveys(user_id: int | None) -> QuerySet[Survey]:
    """
    Возвращает опросы автора во всех статусах.

    :param user_id: идентификатор автора
    :return: набор опросов
    """

    return Survey.objects.select_related("author").filter(author_id=user_id)
