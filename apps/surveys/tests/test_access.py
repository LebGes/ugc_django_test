from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.surveys.models import Option, Question, Survey, SurveyStatus
from apps.surveys.services.structure import get_survey_structure
from apps.surveys.tests.conftest import SurveyFactory
from apps.users.models import User

pytestmark = pytest.mark.django_db


def survey_url(name: str, survey: Survey) -> str:
    """
    Строит URL действия над опросом.

    :param name: имя маршрута без пространства имён
    :param survey: опрос
    :return: URL
    """
    return reverse(f'api:survey-{name}', kwargs={'pk': survey.pk})


def questions_url(survey: Survey, question: Question | None = None) -> str:
    """
    Строит URL списка вопросов или конкретного вопроса.

    :param survey: опрос
    :param question: вопрос или None для списка
    :return: URL
    """
    if question is None:
        return reverse('api:survey-question-list', kwargs={'survey_pk': survey.pk})
    return reverse('api:survey-question-detail', kwargs={'survey_pk': survey.pk, 'pk': question.pk})


def options_url(question: Question) -> str:
    """
    Строит URL списка вариантов ответа вопроса.

    :param question: вопрос
    :return: URL
    """
    return reverse(
        'api:survey-question-option-list',
        kwargs={'survey_pk': question.survey_id, 'question_pk': question.pk},
    )


def first_question(survey: Survey) -> Question:
    """
    Возвращает первый по порядку вопрос опроса.

    :param survey: опрос
    :return: вопрос
    """
    question = Question.objects.filter(survey=survey).order_by('position').first()
    assert question is not None
    return question


class TestAnonymousAccess:
    """
    Анонимный пользователь не имеет доступа к API.
    """

    @pytest.mark.parametrize(
        ('method', 'name'),
        [
            ('get', 'list'),
            ('post', 'list'),
            ('get', 'mine'),
        ],
    )
    def test_collection_endpoints(
        self, anonymous_client: APIClient, method: str, name: str
    ) -> None:
        """
        Списки опросов требуют аутентификации.

        :param anonymous_client: анонимный API-клиент
        :param method: HTTP-метод
        :param name: имя маршрута
        """
        response = getattr(anonymous_client, method)(reverse(f'api:survey-{name}'))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize(
        ('method', 'name'),
        [
            ('get', 'detail'),
            ('get', 'next-question'),
            ('post', 'answers'),
            ('get', 'stats'),
            ('post', 'publish'),
        ],
    )
    def test_survey_endpoints(
        self, anonymous_client: APIClient, published_survey: Survey, method: str, name: str
    ) -> None:
        """
        Действия с опросом требуют аутентификации.

        :param anonymous_client: анонимный API-клиент
        :param published_survey: опубликованный опрос
        :param method: HTTP-метод
        :param name: имя маршрута
        """
        response = getattr(anonymous_client, method)(survey_url(name, published_survey))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestSurveyVisibility:
    """
    Кто какие опросы видит.
    """

    def test_list_shows_only_published(
        self,
        respondent_client: APIClient,
        make_survey: SurveyFactory,
        author: User,
    ) -> None:
        """
        В общем списке только опубликованные опросы.

        :param respondent_client: API-клиент респондента
        :param make_survey: фабрика опросов
        :param author: автор опросов
        """
        published = make_survey(author, title='Опубликован')
        make_survey(author, title='Черновик', publish=False)

        response = respondent_client.get(reverse('api:survey-list'))

        assert response.status_code == status.HTTP_200_OK
        assert [item['id'] for item in response.data['results']] == [published.pk]

    def test_mine_shows_all_own_surveys(
        self,
        author_client: APIClient,
        make_survey: SurveyFactory,
        author: User,
        stranger: User,
    ) -> None:
        """
        В разделе 'мои опросы' есть все опросы автора и нет чужих.

        :param author_client: API-клиент автора
        :param make_survey: фабрика опросов
        :param author: автор опросов
        :param stranger: другой автор
        """
        draft = make_survey(author, title='Черновик', publish=False)
        published = make_survey(author, title='Опубликован')
        make_survey(stranger, title='Чужой')

        response = author_client.get(reverse('api:survey-mine'))

        assert [item['id'] for item in response.data['results']] == [published.pk, draft.pk]

    @pytest.mark.parametrize('name', ['detail', 'next-question', 'stats'])
    def test_foreign_draft_is_hidden(
        self, stranger_client: APIClient, draft_survey: Survey, name: str
    ) -> None:
        """
        Чужой черновик для постороннего пользователя не существует.

        :param stranger_client: API-клиент постороннего пользователя
        :param draft_survey: черновик опроса
        :param name: имя маршрута
        """
        response = stranger_client.get(survey_url(name, draft_survey))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_author_sees_structure(
        self, author_client: APIClient, published_survey: Survey
    ) -> None:
        """
        Автор получает опрос вместе с вопросами и вариантами в заданном порядке.

        :param author_client: API-клиент автора
        :param published_survey: опубликованный опрос
        """
        response = author_client.get(survey_url('detail', published_survey))

        assert response.status_code == status.HTTP_200_OK
        assert [q['position'] for q in response.data['questions']] == [1, 2, 3]
        assert [o['position'] for o in response.data['questions'][0]['options']] == [1, 2, 3]

    def test_respondent_does_not_see_structure(
        self, respondent_client: APIClient, published_survey: Survey
    ) -> None:
        """
        Респондент видит опрос без вопросов: вопросы выдаются по одному.

        :param respondent_client: API-клиент респондента
        :param published_survey: опубликованный опрос
        """
        response = respondent_client.get(survey_url('detail', published_survey))

        assert response.status_code == status.HTTP_200_OK
        assert 'questions' not in response.data


class TestAuthorPermissions:
    """
    Управлять опросом может только его автор.
    """

    @pytest.mark.parametrize(
        ('method', 'name', 'payload'),
        [
            ('patch', 'detail', {'title': 'Взлом'}),
            ('delete', 'detail', None),
            ('post', 'publish', None),
            ('post', 'close', None),
            ('get', 'stats', None),
        ],
    )
    def test_stranger_is_forbidden(
        self,
        stranger_client: APIClient,
        published_survey: Survey,
        method: str,
        name: str,
        payload: dict[str, Any] | None,
    ) -> None:
        """
        Посторонний пользователь не может менять опрос и смотреть его статистику.

        :param stranger_client: API-клиент постороннего пользователя
        :param published_survey: опубликованный опрос
        :param method: HTTP-метод
        :param name: имя маршрута
        :param payload: тело запроса
        """
        response = getattr(stranger_client, method)(survey_url(name, published_survey), payload)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_stranger_cannot_manage_questions(
        self, stranger_client: APIClient, published_survey: Survey
    ) -> None:
        """
        Посторонний пользователь не видит и не меняет вопросы чужого опроса.

        :param stranger_client: API-клиент постороннего пользователя
        :param published_survey: опубликованный опрос
        """
        question = first_question(published_survey)

        responses = [
            stranger_client.get(questions_url(published_survey)),
            stranger_client.post(questions_url(published_survey), {'text': 'Новый'}),
            stranger_client.delete(questions_url(published_survey, question)),
            stranger_client.get(options_url(question)),
        ]

        assert {r.status_code for r in responses} == {status.HTTP_403_FORBIDDEN}

    def test_question_of_other_survey_is_not_found(
        self,
        author_client: APIClient,
        draft_survey: Survey,
        make_survey: SurveyFactory,
        author: User,
    ) -> None:
        """
        Вопрос другого опроса недоступен через URL этого опроса.

        :param author_client: API-клиент автора
        :param draft_survey: черновик опроса
        :param make_survey: фабрика опросов
        :param author: автор опросов
        """
        foreign_question = first_question(make_survey(author, title='Другой', publish=False))

        responses = [
            author_client.get(questions_url(draft_survey, foreign_question)),
            author_client.get(
                reverse(
                    'api:survey-question-option-list',
                    kwargs={'survey_pk': draft_survey.pk, 'question_pk': foreign_question.pk},
                )
            ),
        ]

        assert {r.status_code for r in responses} == {status.HTTP_404_NOT_FOUND}


class TestAuthoringApi:
    """
    Создание и редактирование опроса через API.
    """

    def test_build_and_publish_survey(self, author_client: APIClient, author: User) -> None:
        """
        Автор создаёт опрос, добавляет вопросы и варианты и публикует его.

        :param author_client: API-клиент автора
        :param author: автор опроса
        """
        response = author_client.post(reverse('api:survey-list'), {'title': 'Фрукты'})
        assert response.status_code == status.HTTP_201_CREATED
        survey = Survey.objects.get(pk=response.data['id'])
        assert survey.author == author

        response = author_client.post(questions_url(survey), {'text': 'Любишь яблоки?'})
        assert response.status_code == status.HTTP_201_CREATED
        question = Question.objects.get(pk=response.data['id'])
        for text in ('Да', 'Нет'):
            response = author_client.post(options_url(question), {'text': text})
            assert response.status_code == status.HTTP_201_CREATED

        response = author_client.post(survey_url('publish', survey))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['status'] == SurveyStatus.PUBLISHED

    def test_position_is_read_only(self, author_client: APIClient, draft_survey: Survey) -> None:
        """
        Позицию нельзя задать при создании, новый вопрос встаёт в конец.

        :param author_client: API-клиент автора
        :param draft_survey: черновик опроса
        """
        response = author_client.post(questions_url(draft_survey), {'text': 'Новый', 'position': 1})

        assert response.data['position'] == 4

    def test_reorder_questions(self, author_client: APIClient, draft_survey: Survey) -> None:
        """
        Автор меняет порядок вопросов и получает их в новом порядке.

        :param author_client: API-клиент автора
        :param draft_survey: черновик опроса
        """
        ids = [q.id for q in get_survey_structure(draft_survey).questions][::-1]

        response = author_client.post(
            reverse('api:survey-question-reorder', kwargs={'survey_pk': draft_survey.pk}),
            {'ids': ids},
        )

        assert response.status_code == status.HTTP_200_OK
        assert [q['id'] for q in response.data] == ids
        assert [q['position'] for q in response.data] == [1, 2, 3]

    def test_reorder_options(self, author_client: APIClient, draft_survey: Survey) -> None:
        """
        Автор меняет порядок вариантов ответа.

        :param author_client: API-клиент автора
        :param draft_survey: черновик опроса
        """
        question = first_question(draft_survey)
        ids = list(
            Option.objects.filter(question=question)
            .order_by('-position')
            .values_list('pk', flat=True)
        )

        response = author_client.post(
            reverse(
                'api:survey-question-option-reorder',
                kwargs={'survey_pk': draft_survey.pk, 'question_pk': question.pk},
            ),
            {'ids': ids},
        )

        assert response.status_code == status.HTTP_200_OK
        assert [o['id'] for o in response.data] == ids

    def test_invalid_reorder(self, author_client: APIClient, draft_survey: Survey) -> None:
        """
        Неполный список при смене порядка отклоняется с понятной ошибкой.

        :param author_client: API-клиент автора
        :param draft_survey: черновик опроса
        """
        response = author_client.post(
            reverse('api:survey-question-reorder', kwargs={'survey_pk': draft_survey.pk}),
            {'ids': [first_question(draft_survey).pk]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['code'] == 'invalid_order'

    def test_published_structure_is_locked(
        self, author_client: APIClient, published_survey: Survey
    ) -> None:
        """
        Структуру опубликованного опроса через API изменить нельзя.

        :param author_client: API-клиент автора
        :param published_survey: опубликованный опрос
        """
        question = first_question(published_survey)

        responses = [
            author_client.post(questions_url(published_survey), {'text': 'Новый'}),
            author_client.patch(questions_url(published_survey, question), {'text': 'Другой'}),
            author_client.delete(questions_url(published_survey, question)),
            author_client.post(options_url(question), {'text': 'Новый'}),
        ]

        assert {r.status_code for r in responses} == {status.HTTP_409_CONFLICT}
        assert {r.data['code'] for r in responses} == {'survey_not_editable'}

    def test_publish_empty_survey(self, author_client: APIClient) -> None:
        """
        Пустой опрос не публикуется, ответ объясняет причину.

        :param author_client: API-клиент автора
        """
        survey_id = author_client.post(reverse('api:survey-list'), {'title': 'Пусто'}).data['id']

        response = author_client.post(reverse('api:survey-publish', kwargs={'pk': survey_id}))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data['code'] == 'survey_not_publishable'

    def test_delete_published_survey(
        self, author_client: APIClient, published_survey: Survey
    ) -> None:
        """
        Опубликованный опрос через API не удаляется.

        :param author_client: API-клиент автора
        :param published_survey: опубликованный опрос
        """
        response = author_client.delete(survey_url('detail', published_survey))

        assert response.status_code == status.HTTP_409_CONFLICT
        assert Survey.objects.filter(pk=published_survey.pk).exists()


class TestTakingSurveyApi:
    """
    Прохождение опроса через API.
    """

    def test_full_flow(self, respondent_client: APIClient, published_survey: Survey) -> None:
        """
        Пользователь получает вопросы по одному и проходит опрос до конца.

        :param respondent_client: API-клиент респондента
        :param published_survey: опубликованный опрос
        """
        response = respondent_client.get(survey_url('next-question', published_survey))
        assert response.status_code == status.HTTP_200_OK
        assert response.data['progress'] == {'answered': 0, 'total': 3, 'completed': False}

        for answered in range(1, 4):
            question = response.data['question']
            response = respondent_client.post(
                survey_url('answers', published_survey),
                {'question': question['id'], 'option': question['options'][0]['id']},
            )
            assert response.status_code == status.HTTP_201_CREATED
            assert response.data['progress']['answered'] == answered

        assert response.data['question'] is None
        assert response.data['progress']['completed'] is True

    def test_question_payload(self, respondent_client: APIClient, published_survey: Survey) -> None:
        """
        Вопрос для респондента содержит текст и варианты без служебных полей.

        :param respondent_client: API-клиент респондента
        :param published_survey: опубликованный опрос
        """
        response = respondent_client.get(survey_url('next-question', published_survey))

        question = response.data['question']
        assert set(question) == {'id', 'text', 'position', 'options'}
        assert [o['text'] for o in question['options']] == ['Да', 'Нет', 'Только в коктейлях']

    @pytest.mark.parametrize(
        ('payload', 'expected_status'),
        [
            pytest.param({}, status.HTTP_400_BAD_REQUEST, id='пустой запрос'),
            pytest.param(
                {'question': 'x', 'option': 1}, status.HTTP_400_BAD_REQUEST, id='не число'
            ),
            pytest.param({'question': 0, 'option': 1}, status.HTTP_400_BAD_REQUEST, id='ноль'),
        ],
    )
    def test_invalid_payload(
        self,
        respondent_client: APIClient,
        published_survey: Survey,
        payload: dict[str, Any],
        expected_status: int,
    ) -> None:
        """
        Некорректное тело запроса отклоняется валидацией.

        :param respondent_client: API-клиент респондента
        :param published_survey: опубликованный опрос
        :param payload: тело запроса
        :param expected_status: ожидаемый код ответа
        """
        response = respondent_client.post(survey_url('answers', published_survey), payload)

        assert response.status_code == expected_status

    def test_domain_errors(self, respondent_client: APIClient, published_survey: Survey) -> None:
        """
        Ошибки прохождения возвращаются с кодом и сообщением на русском.

        :param respondent_client: API-клиент респондента
        :param published_survey: опубликованный опрос
        """
        first, second, _ = get_survey_structure(published_survey).questions
        url = survey_url('answers', published_survey)

        wrong_option = respondent_client.post(
            url, {'question': first.id, 'option': second.options[0].id}
        )
        skipped = respondent_client.post(
            url, {'question': second.id, 'option': second.options[0].id}
        )
        respondent_client.post(url, {'question': first.id, 'option': first.options[0].id})
        repeated = respondent_client.post(
            url, {'question': first.id, 'option': first.options[0].id}
        )

        assert (wrong_option.status_code, wrong_option.data['code']) == (400, 'invalid_answer')
        assert (skipped.status_code, skipped.data['code']) == (409, 'unexpected_question')
        assert (repeated.status_code, repeated.data['code']) == (409, 'question_already_answered')
        assert repeated.data['detail'] == 'Вы уже ответили на этот вопрос'

    def test_draft_cannot_be_taken_by_author(
        self, author_client: APIClient, draft_survey: Survey
    ) -> None:
        """
        Даже автор не может проходить неопубликованный опрос.

        :param author_client: API-клиент автора
        :param draft_survey: черновик опроса
        """
        response = author_client.get(survey_url('next-question', draft_survey))

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.data['code'] == 'survey_not_available'

    def test_author_sees_stats(
        self, author_client: APIClient, respondent_client: APIClient, published_survey: Survey
    ) -> None:
        """
        Автор получает статистику с учётом ответов.

        :param author_client: API-клиент автора
        :param respondent_client: API-клиент респондента
        :param published_survey: опубликованный опрос
        """
        question = get_survey_structure(published_survey).questions[0]
        respondent_client.post(
            survey_url('answers', published_survey),
            {'question': question.id, 'option': question.options[0].id},
        )

        response = author_client.get(survey_url('stats', published_survey))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['participants'] == 1
        assert response.data['completed'] == 0
        assert response.data['average_duration_seconds'] is None
        assert response.data['questions'][0]['options'][0]['votes'] == 1


class TestPages:
    """
    Доступность HTML-страниц.
    """

    def test_list_is_public(self, client: Client, published_survey: Survey) -> None:
        """
        Список опросов открыт без входа.

        :param client: тестовый HTTP-клиент
        :param published_survey: опубликованный опрос
        """
        response = client.get(reverse('surveys:list'))

        assert response.status_code == status.HTTP_200_OK
        assert published_survey.title in response.content.decode()

    @pytest.mark.parametrize('name', ['surveys:take', 'surveys:stats'])
    def test_login_required(self, client: Client, published_survey: Survey, name: str) -> None:
        """
        Прохождение и статистика требуют входа.

        :param client: тестовый HTTP-клиент
        :param published_survey: опубликованный опрос
        :param name: имя маршрута
        """
        response = client.get(reverse(name, kwargs={'pk': published_survey.pk}))

        assert response.status_code == status.HTTP_302_FOUND
        assert response['Location'].startswith(reverse('login'))

    def test_take_survey(self, client: Client, respondent: User, published_survey: Survey) -> None:
        """
        Пользователь проходит опрос на страницах до сообщения о завершении.

        :param client: тестовый HTTP-клиент
        :param respondent: респондент
        :param published_survey: опубликованный опрос
        """
        client.force_login(respondent)
        url = reverse('surveys:take', kwargs={'pk': published_survey.pk})

        for question in get_survey_structure(published_survey).questions:
            page = client.get(url)
            assert question.text in page.content.decode()
            response = client.post(url, {'question': question.id, 'option': question.options[0].id})
            assert response.status_code == status.HTTP_302_FOUND

        assert 'Спасибо' in client.get(url).content.decode()

    def test_take_without_choice(
        self, client: Client, respondent: User, published_survey: Survey
    ) -> None:
        """
        Форма без выбранного варианта показывает ошибку и не сохраняет ответ.

        :param client: тестовый HTTP-клиент
        :param respondent: респондент
        :param published_survey: опубликованный опрос
        """
        client.force_login(respondent)
        question = get_survey_structure(published_survey).questions[0]

        response = client.post(
            reverse('surveys:take', kwargs={'pk': published_survey.pk}), {'question': question.id}
        )

        assert response.status_code == status.HTTP_200_OK
        assert 'Выберите вариант ответа' in response.content.decode()

    def test_stats_page(
        self, client: Client, author: User, stranger: User, published_survey: Survey
    ) -> None:
        """
        Страница статистики открыта автору и закрыта для остальных.

        :param client: тестовый HTTP-клиент
        :param author: автор опроса
        :param stranger: посторонний пользователь
        :param published_survey: опубликованный опрос
        """
        url = reverse('surveys:stats', kwargs={'pk': published_survey.pk})

        client.force_login(author)
        assert client.get(url).status_code == status.HTTP_200_OK
        client.force_login(stranger)
        assert client.get(url).status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.parametrize('name', ['login', 'api-schema', 'api-docs'])
    def test_service_pages(self, client: Client, name: str) -> None:
        """
        Страница входа и документация API открываются.

        :param client: тестовый HTTP-клиент
        :param name: имя маршрута
        """
        assert client.get(reverse(name)).status_code == status.HTTP_200_OK
