from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, F, Q

from apps.surveys.models import Answer, Participation, Survey
from apps.surveys.services.structure import QuestionData, get_survey_structure


@dataclass(frozen=True, slots=True)
class OptionStats:
    """
    Статистика по варианту ответа.
    """

    id: int
    text: str
    votes: int
    percent: float


@dataclass(frozen=True, slots=True)
class QuestionStats:
    """
    Статистика по вопросу.

    Количество ответов на вопросы по порядку показывает, на каком вопросе
    пользователи бросают опрос.
    """

    id: int
    text: str
    position: int
    answers: int
    options: tuple[OptionStats, ...]
    top_option_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SurveyStats:
    """
    Сводная статистика по опросу.
    """

    survey_id: int
    participants: int
    completed: int
    completion_rate: float
    average_duration: timedelta | None
    questions: tuple[QuestionStats, ...]


def stats_cache_key(survey_id: int) -> str:
    """
    Формирует ключ кэша для статистики опроса.

    :param survey_id: идентификатор опроса
    :return: ключ кэша
    """
    
    return f'surveys:stats:{survey_id}'


def get_survey_stats(survey: Survey) -> SurveyStats:
    """
    Возвращает статистику опроса с коротким кэшированием.

    Для популярных опросов автор может часто обновлять страницу статистики,
    поэтому результат кэшируется на SURVEY_STATS_CACHE_TIMEOUT секунд.

    :param survey: опрос
    :return: статистика опроса
    """
    
    key = stats_cache_key(survey.pk)
    stats: SurveyStats | None = cache.get(key)
    
    if stats is None:
        stats = calculate_survey_stats(survey)
        cache.set(key, stats, settings.SURVEY_STATS_CACHE_TIMEOUT)
    
    return stats


def calculate_survey_stats(survey: Survey) -> SurveyStats:
    """
    Считает статистику опроса по данным из базы.

    :param survey: опрос
    :return: статистика опроса
    """
    
    structure = get_survey_structure(survey)
    finished = Q(completed_at__isnull=False)
    
    totals = Participation.objects.filter(survey_id=survey.pk).aggregate(
        participants=Count('pk'),
        completed=Count('pk', filter=finished),
        average_duration=Avg(F('completed_at') - F('started_at'), filter=finished),
    )
    
    votes_by_option: dict[int, int] = dict(
        Answer.objects.filter(question_id__in=structure.question_ids)
        .values('option_id')
        .annotate(votes=Count('option_id'))
        .values_list('option_id', 'votes')
    )

    participants: int = totals['participants']
    completed: int = totals['completed']
    
    return SurveyStats(
        survey_id=survey.pk,
        participants=participants,
        completed=completed,
        completion_rate=_percent(completed, participants),
        average_duration=totals['average_duration'],
        questions=tuple(
            _question_stats(question, votes_by_option) for question in structure.questions
        ),
    )


def _question_stats(question: QuestionData, votes_by_option: dict[int, int]) -> QuestionStats:
    """
    Собирает статистику по одному вопросу.

    :param question: вопрос из структуры опроса
    :param votes_by_option: количество голосов по идентификатору варианта
    :return: статистика по вопросу
    """
    
    votes = [votes_by_option.get(option.id, 0) for option in question.options]
    answers = sum(votes)
    max_votes = max(votes, default=0)
    
    return QuestionStats(
        id=question.id,
        text=question.text,
        position=question.position,
        answers=answers,
        options=tuple(
            OptionStats(
                id=option.id,
                text=option.text,
                votes=option_votes,
                percent=_percent(option_votes, answers),
            )
            for option, option_votes in zip(question.options, votes, strict=True)
        ),
        top_option_ids=tuple(
            option.id
            for option, option_votes in zip(question.options, votes, strict=True)
            if max_votes and option_votes == max_votes
        ),
    )


def _percent(part: int, whole: int) -> float:
    """
    Считает долю в процентах с округлением до десятых.

    :param part: часть
    :param whole: целое
    :return: процент или 0, если целое равно нулю
    """
    
    return 0.0 if not whole else round(part * 100 / whole, 1)
