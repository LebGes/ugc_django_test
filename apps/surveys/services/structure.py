from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.db.models import Prefetch

from apps.surveys.models import Option, Question, Survey


@dataclass(frozen=True, slots=True)
class OptionData:
    """
    Вариант ответа в структуре опроса.
    """

    id: int
    text: str
    position: int


@dataclass(frozen=True, slots=True)
class QuestionData:
    """
    Вопрос с вариантами ответа в структуре опроса.
    """

    id: int
    text: str
    position: int
    options: tuple[OptionData, ...]

    def has_option(self, option_id: int) -> bool:
        """
        Проверяет, что вариант ответа относится к вопросу.

        :param option_id: идентификатор варианта ответа
        :return: True, если вариант принадлежит вопросу
        """
        
        return any(option.id == option_id for option in self.options)


@dataclass(frozen=True, slots=True)
class SurveyStructure:
    """
    Упорядоченные вопросы и варианты ответа опроса.
    """

    survey_id: int
    questions: tuple[QuestionData, ...]

    @property
    def total(self) -> int:
        """
        Возвращает количество вопросов в опросе.

        :return: количество вопросов
        """
        
        return len(self.questions)

    @property
    def question_ids(self) -> list[int]:
        """
        Возвращает идентификаторы вопросов в порядке показа.

        :return: список идентификаторов
        """
        
        return [question.id for question in self.questions]

    def get_question(self, question_id: int) -> QuestionData | None:
        """
        Ищет вопрос по идентификатору.

        :param question_id: идентификатор вопроса
        :return: вопрос или None, если он не относится к опросу
        """
        
        return next((q for q in self.questions if q.id == question_id), None)

    def first_unanswered(self, answered_ids: set[int]) -> QuestionData | None:
        """
        Находит первый по порядку вопрос, на который ещё нет ответа.

        :param answered_ids: идентификаторы вопросов, на которые пользователь уже ответил
        :return: вопрос или None, если отвечены все вопросы
        """
        
        return next((q for q in self.questions if q.id not in answered_ids), None)


def structure_cache_key(survey_id: int) -> str:
    """
    Формирует ключ кэша для структуры опроса.

    :param survey_id: идентификатор опроса
    :return: ключ кэша
    """
    
    return f'surveys:structure:{survey_id}'


def load_survey_structure(survey_id: int) -> SurveyStructure:
    """
    Загружает структуру опроса из базы данных.

    :param survey_id: идентификатор опроса
    :return: структура опроса
    """
    
    questions = (
        Question.objects.filter(survey_id=survey_id)
        .order_by('position', 'id')
        .prefetch_related(
            Prefetch('options', queryset=Option.objects.order_by('position', 'id')),
        )
    )
    
    return SurveyStructure(
        survey_id=survey_id,
        questions=tuple(
            QuestionData(
                id=question.pk,
                text=question.text,
                position=question.position,
                options=tuple(
                    OptionData(id=option.pk, text=option.text, position=option.position)
                    for option in question.options.all()
                ),
            )
            for question in questions
        ),
    )


def get_survey_structure(survey: Survey) -> SurveyStructure:
    """
    Возвращает структуру опроса, для опубликованных опросов через кэш.

    Структура опубликованного опроса заморожена, поэтому кэш не нужно инвалидировать.
    Черновик всегда читается из базы, так как автор может менять его в любой момент.

    :param survey: опрос
    :return: структура опроса
    """
    
    if survey.is_draft:
        return load_survey_structure(survey.pk)

    key = structure_cache_key(survey.pk)
    structure: SurveyStructure | None = cache.get(key)
    
    if structure is None:
        structure = load_survey_structure(survey.pk)
        cache.set(key, structure, settings.SURVEY_STRUCTURE_CACHE_TIMEOUT)
    
    return structure
