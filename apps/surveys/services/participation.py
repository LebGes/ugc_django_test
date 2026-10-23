import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.surveys.models import Answer, Participation, Survey
from apps.surveys.services.exceptions import (
    InvalidAnswerError,
    ParticipationCompletedError,
    QuestionAlreadyAnsweredError,
    SurveyNotAvailableError,
    UnexpectedQuestionError,
)
from apps.surveys.services.structure import QuestionData, SurveyStructure, get_survey_structure
from apps.users.models import User


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Progress:
    """
    Прогресс пользователя по опросу.
    """

    answered: int
    total: int

    @property
    def is_completed(self) -> bool:
        """
        Проверяет, ответил ли пользователь на все вопросы.

        :return: True, если опрос пройден
        """
        
        return self.answered >= self.total


@dataclass(frozen=True, slots=True)
class NextQuestion:
    """
    Следующий вопрос для пользователя и его прогресс.
    """

    question: QuestionData | None
    progress: Progress


def get_next_question(survey: Survey, user: User) -> NextQuestion:
    """
    Возвращает вопрос, на который пользователь должен ответить следующим.

    Структура опроса берётся из кэша, поэтому в базу уходит один запрос
    за идентификаторами уже отвеченных вопросов.

    :param survey: опрос
    :param user: пользователь, проходящий опрос
    :return: следующий вопрос и прогресс, вопрос равен None, если опрос пройден
    """
    
    _ensure_accepts_answers(survey)
    structure = get_survey_structure(survey)
    answered_ids = set(
        Answer.objects.filter(
            participation__survey_id=survey.pk,
            participation__user_id=user.pk,
        ).values_list('question_id', flat=True)
    )
    
    return _build_next_question(structure, answered_ids)


@transaction.atomic
def submit_answer(survey: Survey, user: User, *, question_id: int, option_id: int) -> NextQuestion:
    """
    Сохраняет ответ пользователя и возвращает следующий вопрос.

    Отвечать можно только на следующий по порядку вопрос. Строка прохождения
    блокируется, поэтому параллельные запросы одного пользователя не создадут
    дублей и не нарушат порядок.

    :param survey: опрос
    :param user: пользователь, проходящий опрос
    :param question_id: идентификатор вопроса
    :param option_id: идентификатор выбранного варианта ответа
    :return: следующий вопрос и прогресс после сохранения ответа
    """
    
    _ensure_accepts_answers(survey)
    structure = get_survey_structure(survey)
    question = structure.get_question(question_id)
    
    if question is None or not question.has_option(option_id):
        raise InvalidAnswerError

    participation, _ = Participation.objects.select_for_update().get_or_create(
        survey_id=survey.pk,
        user_id=user.pk,
    )
    
    if participation.is_completed:
        raise ParticipationCompletedError

    answered_ids = set(participation.answers.values_list('question_id', flat=True))
    
    if question_id in answered_ids:
        raise QuestionAlreadyAnsweredError
    
    expected = structure.first_unanswered(answered_ids)
    
    if expected is None or expected.id != question_id:
        raise UnexpectedQuestionError

    Answer.objects.create(participation=participation, question_id=question_id, option_id=option_id)
    answered_ids.add(question_id)

    result = _build_next_question(structure, answered_ids)
    
    if result.progress.is_completed:
        participation.completed_at = timezone.now()
        participation.save(update_fields=['completed_at'])
        logger.info('Participation %s completed survey %s', participation.pk, survey.pk)
    
    return result


def _ensure_accepts_answers(survey: Survey) -> None:
    """
    Проверяет, что опрос можно проходить.

    :param survey: опрос
    """
    
    if not survey.is_published:
        raise SurveyNotAvailableError


def _build_next_question(structure: SurveyStructure, answered_ids: set[int]) -> NextQuestion:
    """
    Собирает следующий вопрос и прогресс по набору отвеченных вопросов.

    :param structure: структура опроса
    :param answered_ids: идентификаторы вопросов, на которые пользователь уже ответил
    :return: следующий вопрос и прогресс
    """
    
    return NextQuestion(
        question=structure.first_unanswered(answered_ids),
        progress=Progress(answered=len(answered_ids), total=structure.total),
    )
