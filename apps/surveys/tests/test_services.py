from collections.abc import Callable
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from pytest_django import DjangoAssertNumQueries

from apps.surveys.models import Answer, Option, Participation, Question, Survey, SurveyStatus
from apps.surveys.services import authoring, participation, stats
from apps.surveys.services.exceptions import (
    InvalidAnswerError,
    InvalidOrderError,
    ParticipationCompletedError,
    QuestionAlreadyAnsweredError,
    SurveyNotAvailableError,
    SurveyNotEditableError,
    SurveyNotPublishableError,
    SurveyStatusError,
    UnexpectedQuestionError,
)
from apps.surveys.services.structure import get_survey_structure
from apps.surveys.tests.conftest import SurveyFactory
from apps.users.models import User


pytestmark = pytest.mark.django_db

requires_postgres = pytest.mark.skipif(
    connection.vendor != 'postgresql',
    reason='Отложенные ограничения уникальности поддерживает только PostgreSQL',
)


def question_texts(survey: Survey) -> list[str]:
    """
    Возвращает тексты вопросов опроса в порядке показа.

    :param survey: опрос
    :return: тексты вопросов
    """
    
    return [question.text for question in get_survey_structure(survey).questions]


def answer_all(survey: Survey, user: User, option_index: int = 0) -> None:
    """
    Отвечает на все вопросы опроса, выбирая вариант с заданным номером.

    :param survey: опрос
    :param user: пользователь
    :param option_index: номер выбираемого варианта в каждом вопросе
    """
    current = participation.get_next_question(survey, user)
    
    while current.question is not None:
        current = participation.submit_answer(
            survey,
            user,
            question_id=current.question.id,
            option_id=current.question.options[option_index].id,
        )


class TestAuthoring:
    """
    Создание и редактирование опросов.
    """

    def test_new_survey_is_draft(self, author: User) -> None:
        """
        Новый опрос создаётся черновиком без даты публикации.

        :param author: автор опроса
        """
        survey = authoring.create_survey(author=author, title='Новый')

        assert survey.status == SurveyStatus.DRAFT
        assert survey.published_at is None

    def test_questions_and_options_are_appended_in_order(self, draft_survey: Survey) -> None:
        """
        Вопросы и варианты получают позиции по порядку добавления.

        :param draft_survey: черновик опроса
        """
        questions = list(Question.objects.filter(survey=draft_survey).order_by('id'))
        options = list(Option.objects.filter(question=questions[0]).order_by('id'))

        assert [q.position for q in questions] == [1, 2, 3]
        assert [o.position for o in options] == [1, 2, 3]

    def test_reorder_questions(self, draft_survey: Survey) -> None:
        """
        Автор задаёт порядок вопросов, структура опроса его учитывает.

        :param draft_survey: черновик опроса
        """
        first, second, third = Question.objects.filter(survey=draft_survey).order_by('position')

        authoring.reorder_questions(draft_survey, [third.pk, first.pk, second.pk])

        assert question_texts(draft_survey) == [third.text, first.text, second.text]

    def test_reorder_options(self, draft_survey: Survey) -> None:
        """
        Автор задаёт порядок вариантов ответа.

        :param draft_survey: черновик опроса
        """
        question = Question.objects.filter(survey=draft_survey).order_by('position').first()
        
        assert question is not None
        
        first, second, third = Option.objects.filter(question=question).order_by('position')

        authoring.reorder_options(question, [second.pk, third.pk, first.pk])

        structure = get_survey_structure(draft_survey)
        
        assert [o.id for o in structure.questions[0].options] == [second.pk, third.pk, first.pk]

    @pytest.mark.parametrize(
        'make_ids',
        [
            pytest.param(lambda ids: ids[:-1], id='не все элементы'),
            pytest.param(lambda ids: [*ids, ids[0]], id='дубликат'),
            pytest.param(lambda ids: [*ids[:-1], 10**9], id='чужой элемент'),
        ],
    )
    def test_reorder_rejects_incomplete_list(
        self, draft_survey: Survey, make_ids: Callable[[list[int]], list[int]]
    ) -> None:
        """
        Порядок принимается только как полный список элементов без повторов.

        :param draft_survey: черновик опроса
        :param make_ids: функция, портящая список идентификаторов
        """
        ids = list(
            Question.objects.filter(survey=draft_survey)
            .order_by('position')
            .values_list('pk', flat=True)
        )

        with pytest.raises(InvalidOrderError):
            authoring.reorder_questions(draft_survey, make_ids(ids))

    @pytest.mark.django_db(transaction=True)
    def test_reorder_is_committed(self, draft_survey: Survey) -> None:
        """
        Перестановка фиксируется в базе. В PostgreSQL проверяется работа
        отложенного ограничения уникальности позиции при коммите.

        :param draft_survey: черновик опроса
        """
        ids = list(
            Question.objects.filter(survey=draft_survey)
            .order_by('position')
            .values_list('pk', flat=True)
        )

        authoring.reorder_questions(draft_survey, ids[::-1])

        positions = Question.objects.filter(survey=draft_survey).order_by('position')
        
        assert list(positions.values_list('pk', flat=True)) == ids[::-1]

    @requires_postgres
    @pytest.mark.django_db(transaction=True)
    def test_duplicate_position_rejected_on_commit(self, draft_survey: Survey) -> None:
        """
        Две одинаковые позиции в одном опросе не проходят проверку при коммите.

        :param draft_survey: черновик опроса
        """
        with pytest.raises(IntegrityError), transaction.atomic():
            Question.objects.create(survey=draft_survey, text='Дубль', position=1)

    def test_publish(self, draft_survey: Survey) -> None:
        """
        Публикация меняет статус и проставляет дату публикации.

        :param draft_survey: черновик опроса
        """
        survey = authoring.publish_survey(draft_survey)

        assert survey.status == SurveyStatus.PUBLISHED
        assert survey.published_at is not None

    def test_publish_requires_questions(self, author: User) -> None:
        """
        Пустой опрос нельзя опубликовать.

        :param author: автор опроса
        """
        survey = authoring.create_survey(author=author, title='Пустой')

        with pytest.raises(SurveyNotPublishableError):
            authoring.publish_survey(survey)

    def test_publish_requires_two_options(self, make_survey: SurveyFactory, author: User) -> None:
        """
        Вопрос с одним вариантом ответа не даёт опубликовать опрос.

        :param make_survey: фабрика опросов
        :param author: автор опроса
        """
        survey = make_survey(author, questions=[('Вопрос', ['Единственный'])], publish=False)

        with pytest.raises(SurveyNotPublishableError):
            authoring.publish_survey(survey)

    def test_publish_twice_is_rejected(self, published_survey: Survey) -> None:
        """
        Повторно опубликовать опрос нельзя.

        :param published_survey: опубликованный опрос
        """
        with pytest.raises(SurveyStatusError):
            authoring.publish_survey(published_survey)

    def test_close(self, published_survey: Survey) -> None:
        """
        Опубликованный опрос можно закрыть.

        :param published_survey: опубликованный опрос
        """
        
        assert authoring.close_survey(published_survey).status == SurveyStatus.CLOSED

    def test_close_draft_is_rejected(self, draft_survey: Survey) -> None:
        """
        Черновик закрыть нельзя.

        :param draft_survey: черновик опроса
        """
        with pytest.raises(SurveyStatusError):
            authoring.close_survey(draft_survey)

    def test_structure_is_frozen_after_publish(self, published_survey: Survey) -> None:
        """
        После публикации структуру опроса менять нельзя.

        :param published_survey: опубликованный опрос
        """
        question = Question.objects.filter(survey=published_survey).first()
        
        assert question is not None
        
        option = Option.objects.select_related('question').filter(question=question).first()
        
        assert option is not None

        operations: list[Callable[[], object]] = [
            lambda: authoring.add_question(published_survey, text='Новый'),
            lambda: authoring.update_question(question, text='Другой'),
            lambda: authoring.delete_question(question),
            lambda: authoring.reorder_questions(published_survey, [question.pk]),
            lambda: authoring.add_option(question, text='Новый'),
            lambda: authoring.update_option(option, text='Другой'),
            lambda: authoring.delete_option(option),
            lambda: authoring.reorder_options(question, [option.pk]),
        ]
        for operation in operations:
            with pytest.raises(SurveyNotEditableError):
                operation()

    def test_rename_published_survey(self, published_survey: Survey) -> None:
        """
        Название опубликованного опроса менять можно.

        :param published_survey: опубликованный опрос
        """
        authoring.rename_survey(published_survey, title='Фрукты')

        published_survey.refresh_from_db()
        
        assert published_survey.title == 'Фрукты'

    def test_delete_draft(self, draft_survey: Survey) -> None:
        """
        Черновик удаляется вместе с вопросами и вариантами.

        :param draft_survey: черновик опроса
        """
        authoring.delete_survey(draft_survey)

        assert not Survey.objects.filter(pk=draft_survey.pk).exists()
        assert not Question.objects.filter(survey_id=draft_survey.pk).exists()

    def test_delete_published_is_rejected(self, published_survey: Survey) -> None:
        """
        Опубликованный опрос удалить нельзя, его можно только закрыть.

        :param published_survey: опубликованный опрос
        """
        with pytest.raises(SurveyStatusError):
            authoring.delete_survey(published_survey)


class TestNextQuestion:
    """
    Выбор следующего вопроса с учётом прогресса пользователя.
    """

    def test_first_question(self, published_survey: Survey, respondent: User) -> None:
        """
        Новому пользователю показывается первый вопрос.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        result = participation.get_next_question(published_survey, respondent)

        assert result.question is not None
        assert result.question.text == question_texts(published_survey)[0]
        assert (result.progress.answered, result.progress.total) == (0, 3)
        assert not Participation.objects.exists()

    def test_options_follow_author_order(self, make_survey: SurveyFactory, author: User) -> None:
        """
        Варианты ответа отдаются в порядке, заданном автором.

        :param make_survey: фабрика опросов
        :param author: автор опроса
        """
        survey = make_survey(author, questions=[('Вопрос', ['А', 'Б', 'В'])], publish=False)
        question = Question.objects.get(survey=survey)
        a, b, c = Option.objects.filter(question=question).order_by('position')
        authoring.reorder_options(question, [c.pk, a.pk, b.pk])
        survey = authoring.publish_survey(survey)

        result = participation.get_next_question(survey, author)

        assert result.question is not None
        assert [o.text for o in result.question.options] == ['В', 'А', 'Б']

    def test_respects_question_order(self, draft_survey: Survey, respondent: User) -> None:
        """
        Вопросы идут в порядке, заданном автором, а не в порядке создания.

        :param draft_survey: черновик опроса
        :param respondent: респондент
        """
        first, second, third = Question.objects.filter(survey=draft_survey).order_by('position')
        authoring.reorder_questions(draft_survey, [second.pk, third.pk, first.pk])
        survey = authoring.publish_survey(draft_survey)

        result = participation.get_next_question(survey, respondent)

        assert result.question is not None
        assert result.question.id == second.pk

    def test_progress_moves_forward(self, published_survey: Survey, respondent: User) -> None:
        """
        После ответа пользователь получает следующий по порядку вопрос.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        first = participation.get_next_question(published_survey, respondent).question
        
        assert first is not None
        
        participation.submit_answer(
            published_survey, respondent, question_id=first.id, option_id=first.options[0].id
        )

        result = participation.get_next_question(published_survey, respondent)

        assert result.question is not None
        assert result.question.text == question_texts(published_survey)[1]
        assert result.progress.answered == 1

    def test_completed_survey_has_no_next_question(
        self, published_survey: Survey, respondent: User
    ) -> None:
        """
        Когда все вопросы отвечены, следующего вопроса нет.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        answer_all(published_survey, respondent)

        result = participation.get_next_question(published_survey, respondent)

        assert result.question is None
        assert result.progress.is_completed

    def test_progress_is_per_user(
        self, published_survey: Survey, respondent: User, stranger: User
    ) -> None:
        """
        Прогресс одного пользователя не влияет на другого.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        :param stranger: другой пользователь
        """
        answer_all(published_survey, respondent)

        result = participation.get_next_question(published_survey, stranger)

        assert result.progress.answered == 0

    @pytest.mark.parametrize('survey_status', [SurveyStatus.DRAFT, SurveyStatus.CLOSED])
    def test_unavailable_survey(
        self, draft_survey: Survey, respondent: User, survey_status: SurveyStatus
    ) -> None:
        """
        Черновик и закрытый опрос проходить нельзя.

        :param draft_survey: черновик опроса
        :param respondent: респондент
        :param survey_status: статус опроса
        """
        draft_survey.status = survey_status

        with pytest.raises(SurveyNotAvailableError):
            participation.get_next_question(draft_survey, respondent)

    def test_single_query_with_warm_cache(
        self,
        published_survey: Survey,
        respondent: User,
        django_assert_num_queries: DjangoAssertNumQueries,
    ) -> None:
        """
        При прогретом кэше структуры следующий вопрос получается одним запросом.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        :param django_assert_num_queries: проверка количества запросов
        """
        get_survey_structure(published_survey)

        with django_assert_num_queries(1):
            participation.get_next_question(published_survey, respondent)


class TestSubmitAnswer:
    """
    Сохранение ответов и завершение прохождения.
    """

    def test_answer_is_saved(self, published_survey: Survey, respondent: User) -> None:
        """
        Первый ответ создаёт прохождение и сохраняет выбранный вариант.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        question = get_survey_structure(published_survey).questions[0]

        result = participation.submit_answer(
            published_survey, respondent, question_id=question.id, option_id=question.options[1].id
        )

        answer = Answer.objects.get()
        
        assert answer.participation.user == respondent
        assert answer.option_id == question.options[1].id
        assert result.progress.answered == 1

    def test_completion_is_recorded(self, published_survey: Survey, respondent: User) -> None:
        """
        Ответ на последний вопрос завершает прохождение.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        answer_all(published_survey, respondent)

        record = Participation.objects.get(survey=published_survey, user=respondent)
        
        assert record.completed_at is not None
        assert record.answers.count() == 3

    def test_option_from_other_question(self, published_survey: Survey, respondent: User) -> None:
        """
        Вариант от другого вопроса не принимается.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        first, second, _ = get_survey_structure(published_survey).questions

        with pytest.raises(InvalidAnswerError):
            participation.submit_answer(
                published_survey, respondent, question_id=first.id, option_id=second.options[0].id
            )

    def test_question_from_other_survey(
        self, published_survey: Survey, make_survey: SurveyFactory, author: User, respondent: User
    ) -> None:
        """
        Вопрос другого опроса не принимается.

        :param published_survey: опубликованный опрос
        :param make_survey: фабрика опросов
        :param author: автор опроса
        :param respondent: респондент
        """
        other = get_survey_structure(make_survey(author, title='Другой')).questions[0]

        with pytest.raises(InvalidAnswerError):
            participation.submit_answer(
                published_survey, respondent, question_id=other.id, option_id=other.options[0].id
            )

    def test_repeated_answer(self, published_survey: Survey, respondent: User) -> None:
        """
        Повторный ответ на тот же вопрос отклоняется, ответ не дублируется.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        question = get_survey_structure(published_survey).questions[0]
        kwargs = {'question_id': question.id, 'option_id': question.options[0].id}
        participation.submit_answer(published_survey, respondent, **kwargs)

        with pytest.raises(QuestionAlreadyAnsweredError):
            participation.submit_answer(published_survey, respondent, **kwargs)
        
        assert Answer.objects.count() == 1

    def test_skipping_question(self, published_survey: Survey, respondent: User) -> None:
        """
        Нельзя ответить на вопрос, пропустив предыдущие.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        last = get_survey_structure(published_survey).questions[-1]

        with pytest.raises(UnexpectedQuestionError):
            participation.submit_answer(
                published_survey, respondent, question_id=last.id, option_id=last.options[0].id
            )

    def test_answer_after_completion(self, published_survey: Survey, respondent: User) -> None:
        """
        После завершения опроса ответы больше не принимаются.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        answer_all(published_survey, respondent)
        question = get_survey_structure(published_survey).questions[0]

        with pytest.raises(ParticipationCompletedError):
            participation.submit_answer(
                published_survey,
                respondent,
                question_id=question.id,
                option_id=question.options[0].id,
            )

    def test_closed_survey(self, published_survey: Survey, respondent: User) -> None:
        """
        Закрытый опрос не принимает ответы.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        question = get_survey_structure(published_survey).questions[0]
        survey = authoring.close_survey(published_survey)

        with pytest.raises(SurveyNotAvailableError):
            participation.submit_answer(
                survey, respondent, question_id=question.id, option_id=question.options[0].id
            )


class TestStructureCache:
    """
    Кэширование структуры опроса.
    """

    def test_published_structure_is_cached(
        self, published_survey: Survey, django_assert_num_queries: DjangoAssertNumQueries
    ) -> None:
        """
        Структура опубликованного опроса после первого чтения берётся из кэша.

        :param published_survey: опубликованный опрос
        :param django_assert_num_queries: проверка количества запросов
        """
        get_survey_structure(published_survey)

        with django_assert_num_queries(0):
            get_survey_structure(published_survey)

    def test_draft_structure_is_not_cached(self, draft_survey: Survey) -> None:
        """
        Изменения черновика сразу видны в структуре.

        :param draft_survey: черновик опроса
        """
        get_survey_structure(draft_survey)
        authoring.add_question(draft_survey, text='Новый вопрос')

        assert question_texts(draft_survey)[-1] == 'Новый вопрос'


class TestStats:
    """
    Статистика по опросу.
    """

    def test_empty_survey(self, published_survey: Survey) -> None:
        """
        Статистика опроса без прохождений содержит нули.

        :param published_survey: опубликованный опрос
        """
        result = stats.calculate_survey_stats(published_survey)

        assert (result.participants, result.completed, result.completion_rate) == (0, 0, 0.0)
        assert result.average_duration is None
        assert all(q.answers == 0 and q.top_option_ids == () for q in result.questions)

    def test_counts_and_popular_answers(
        self, published_survey: Survey, respondent: User, stranger: User, author: User
    ) -> None:
        """
        Считаются прохождения, голоса, проценты и самые популярные варианты.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        :param stranger: второй респондент
        :param author: третий респондент, бросивший опрос после первого вопроса
        """
        answer_all(published_survey, respondent, option_index=0)
        answer_all(published_survey, stranger, option_index=0)
        first = get_survey_structure(published_survey).questions[0]
        participation.submit_answer(
            published_survey, author, question_id=first.id, option_id=first.options[1].id
        )

        result = stats.calculate_survey_stats(published_survey)

        assert (result.participants, result.completed) == (3, 2)
        assert result.completion_rate == 66.7
        first_stats, second_stats, _ = result.questions
        assert first_stats.answers == 3
        assert [o.votes for o in first_stats.options] == [2, 1, 0]
        assert [o.percent for o in first_stats.options] == [66.7, 33.3, 0.0]
        assert first_stats.top_option_ids == (first.options[0].id,)
        assert second_stats.answers == 2

    def test_top_options_with_tie(
        self, published_survey: Survey, respondent: User, stranger: User
    ) -> None:
        """
        При равенстве голосов популярными считаются все лидирующие варианты.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        :param stranger: второй респондент
        """
        answer_all(published_survey, respondent, option_index=0)
        answer_all(published_survey, stranger, option_index=2)

        first = stats.calculate_survey_stats(published_survey).questions[0]

        assert first.top_option_ids == (first.options[0].id, first.options[2].id)

    def test_average_duration(
        self, published_survey: Survey, respondent: User, stranger: User, author: User
    ) -> None:
        """
        Среднее время считается только по завершённым прохождениям.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        :param stranger: второй респондент
        :param author: респондент с незавершённым прохождением
        """
        answer_all(published_survey, respondent)
        answer_all(published_survey, stranger)
        first = get_survey_structure(published_survey).questions[0]
        participation.submit_answer(
            published_survey, author, question_id=first.id, option_id=first.options[0].id
        )
        started = timezone.now() - timedelta(hours=1)
        records = Participation.objects.filter(survey=published_survey)
        records.update(started_at=started)
        records.filter(user=respondent).update(completed_at=started + timedelta(seconds=60))
        records.filter(user=stranger).update(completed_at=started + timedelta(seconds=180))

        result = stats.calculate_survey_stats(published_survey)

        assert result.average_duration == timedelta(seconds=120)

    def test_stats_are_cached(self, published_survey: Survey, respondent: User) -> None:
        """
        Статистика кэшируется на короткое время.

        :param published_survey: опубликованный опрос
        :param respondent: респондент
        """
        stats.get_survey_stats(published_survey)
        answer_all(published_survey, respondent)

        assert stats.get_survey_stats(published_survey).participants == 0
        assert stats.calculate_survey_stats(published_survey).participants == 1
