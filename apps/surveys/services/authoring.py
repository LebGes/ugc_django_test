import logging
from collections.abc import Sequence

from django.db import transaction
from django.db.models import Count, Max, QuerySet
from django.utils import timezone

from apps.surveys.models import Option, Question, Survey, SurveyStatus
from apps.surveys.services.exceptions import (
    InvalidOrderError,
    SurveyNotEditableError,
    SurveyNotPublishableError,
    SurveyStatusError,
)
from apps.users.models import User


logger = logging.getLogger(__name__)

MIN_OPTIONS_PER_QUESTION = 2


def create_survey(*, author: User, title: str) -> Survey:
    """
    Создаёт опрос в статусе черновика.

    :param author: автор опроса
    :param title: название опроса
    :return: созданный опрос
    """
    
    return Survey.objects.create(author=author, title=title)


def rename_survey(survey: Survey, *, title: str) -> Survey:
    """
    Меняет название опроса. Название можно менять в любом статусе.

    :param survey: опрос
    :param title: новое название
    :return: обновлённый опрос
    """
    
    survey.title = title
    survey.save(update_fields=['title', 'updated_at'])
    
    return survey


@transaction.atomic
def delete_survey(survey: Survey) -> None:
    """
    Удаляет черновик опроса вместе с вопросами и вариантами.

    :param survey: опрос
    """
    
    locked = _lock_survey(survey.pk)
    
    if not locked.is_draft:
        raise SurveyStatusError('Удалить можно только черновик, опубликованный опрос можно закрыть')
    
    locked.delete()


@transaction.atomic
def publish_survey(survey: Survey) -> Survey:
    """
    Публикует опрос. После публикации структура опроса замораживается.

    :param survey: опрос
    :return: опубликованный опрос
    """
    
    locked = _lock_survey(survey.pk)
    
    if not locked.is_draft:
        raise SurveyStatusError('Опубликовать можно только черновик')

    options_count = list(
        Question.objects.filter(survey_id=locked.pk)
        .annotate(options_count=Count('options'))
        .values_list('options_count', flat=True)
    )
    
    if not options_count:
        raise SurveyNotPublishableError('В опросе должен быть хотя бы один вопрос')
    
    if min(options_count) < MIN_OPTIONS_PER_QUESTION:
        raise SurveyNotPublishableError(
            f'У каждого вопроса должно быть не меньше {MIN_OPTIONS_PER_QUESTION} вариантов ответа'
        )

    locked.status = SurveyStatus.PUBLISHED
    locked.published_at = timezone.now()
    locked.save(update_fields=['status', 'published_at', 'updated_at'])
    logger.info('Survey %s published', locked.pk)
    
    return locked


@transaction.atomic
def close_survey(survey: Survey) -> Survey:
    """
    Закрывает опрос. Закрытый опрос больше не принимает ответы.

    :param survey: опрос
    :return: закрытый опрос
    """
    
    locked = _lock_survey(survey.pk)
    
    if not locked.is_published:
        raise SurveyStatusError('Закрыть можно только опубликованный опрос')
    
    locked.status = SurveyStatus.CLOSED
    locked.save(update_fields=['status', 'updated_at'])
    logger.info('Survey %s closed', locked.pk)
    
    return locked


@transaction.atomic
def add_question(survey: Survey, *, text: str) -> Question:
    """
    Добавляет вопрос в конец опроса.

    :param survey: опрос
    :param text: текст вопроса
    :return: созданный вопрос
    """
    
    locked = _lock_editable_survey(survey.pk)
    position = _next_position(Question.objects.filter(survey_id=locked.pk))
    
    return Question.objects.create(survey=locked, text=text, position=position)


@transaction.atomic
def update_question(question: Question, *, text: str) -> Question:
    """
    Меняет текст вопроса.

    :param question: вопрос
    :param text: новый текст
    :return: обновлённый вопрос
    """
    
    _lock_editable_survey(question.survey_id)
    question.text = text
    question.save(update_fields=['text'])
    
    return question


@transaction.atomic
def delete_question(question: Question) -> None:
    """
    Удаляет вопрос вместе с вариантами ответа.

    :param question: вопрос
    """
    
    _lock_editable_survey(question.survey_id)
    question.delete()


@transaction.atomic
def reorder_questions(survey: Survey, ordered_ids: Sequence[int]) -> list[Question]:
    """
    Задаёт новый порядок вопросов опроса.

    :param survey: опрос
    :param ordered_ids: идентификаторы всех вопросов опроса в нужном порядке
    :return: вопросы в новом порядке
    """
    
    locked = _lock_editable_survey(survey.pk)
    
    return _reorder(Question.objects.filter(survey_id=locked.pk), ordered_ids)


@transaction.atomic
def add_option(question: Question, *, text: str) -> Option:
    """
    Добавляет вариант ответа в конец списка вариантов вопроса.

    :param question: вопрос
    :param text: текст варианта
    :return: созданный вариант
    """
    
    _lock_editable_survey(question.survey_id)
    position = _next_position(Option.objects.filter(question_id=question.pk))
    
    return Option.objects.create(question=question, text=text, position=position)


@transaction.atomic
def update_option(option: Option, *, text: str) -> Option:
    """
    Меняет текст варианта ответа.

    :param option: вариант ответа
    :param text: новый текст
    :return: обновлённый вариант
    """
    
    _lock_editable_survey(option.question.survey_id)
    option.text = text
    option.save(update_fields=['text'])
    
    return option


@transaction.atomic
def delete_option(option: Option) -> None:
    """
    Удаляет вариант ответа.

    :param option: вариант ответа
    """
    
    _lock_editable_survey(option.question.survey_id)
    option.delete()


@transaction.atomic
def reorder_options(question: Question, ordered_ids: Sequence[int]) -> list[Option]:
    """
    Задаёт новый порядок вариантов ответа вопроса.

    :param question: вопрос
    :param ordered_ids: идентификаторы всех вариантов вопроса в нужном порядке
    :return: варианты в новом порядке
    """
    
    _lock_editable_survey(question.survey_id)
    
    return _reorder(Option.objects.filter(question_id=question.pk), ordered_ids)


def _lock_survey(survey_id: int) -> Survey:
    """
    Блокирует строку опроса до конца транзакции.

    Все изменения структуры опроса идут через эту блокировку, поэтому расчёт
    позиций и смена статуса не конфликтуют между параллельными запросами.

    :param survey_id: идентификатор опроса
    :return: заблокированный опрос
    """
    
    return Survey.objects.select_for_update().get(pk=survey_id)


def _lock_editable_survey(survey_id: int) -> Survey:
    """
    Блокирует опрос и проверяет, что его структуру можно менять.

    :param survey_id: идентификатор опроса
    :return: заблокированный опрос
    """
    
    survey = _lock_survey(survey_id)

    if not survey.is_draft:
        raise SurveyNotEditableError
    
    return survey


def _next_position[T: (Question, Option)](queryset: QuerySet[T]) -> int:
    """
    Вычисляет позицию для нового элемента в конце списка.

    :param queryset: элементы, среди которых ищется последняя позиция
    :return: следующая свободная позиция
    """
    
    last_position = queryset.aggregate(last=Max('position'))['last']
    
    return (last_position or 0) + 1


def _reorder[T: (Question, Option)](queryset: QuerySet[T], ordered_ids: Sequence[int]) -> list[T]:
    """
    Переписывает позиции элементов в соответствии с переданным порядком.

    Ограничение уникальности позиции отложенное (DEFERRABLE INITIALLY DEFERRED),
    поэтому временные совпадения позиций внутри транзакции допустимы.

    :param queryset: все элементы, которые нужно упорядочить
    :param ordered_ids: идентификаторы элементов в нужном порядке
    :return: элементы в новом порядке
    """
    
    items = {item.pk: item for item in queryset}
    
    if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != items.keys():
        raise InvalidOrderError

    ordered = [items[item_id] for item_id in ordered_ids]

    for position, item in enumerate(ordered, start=1):
        item.position = position
    queryset.model.objects.bulk_update(ordered, ['position'])

    return ordered
