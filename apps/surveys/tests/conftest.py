from collections.abc import Callable, Iterator, Sequence

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.surveys.models import Survey
from apps.surveys.services import authoring
from apps.users.models import User


QuestionSpec = tuple[str, Sequence[str]]
SurveyFactory = Callable[..., Survey]

DEFAULT_QUESTIONS: tuple[QuestionSpec, ...] = (
    ('Ты любишь огурцы?', ('Да', 'Нет', 'Только в коктейлях')),
    ('Ты любишь помидоры?', ('Да', 'Нет', 'Только если гаспачо')),
    ('Ты любишь огуречный салат?', ('Да', 'Нет', 'Только с уксусом')),
)


@pytest.fixture(autouse=True)
def clear_cache() -> Iterator[None]:
    """
    Очищает кэш до и после каждого теста, чтобы тесты не влияли друг на друга.
    """
    cache.clear()
    
    yield
    
    cache.clear()


@pytest.fixture
def author(django_user_model: type[User]) -> User:
    """
    Автор опросов.

    :param django_user_model: модель пользователя
    :return: пользователь
    """
    
    return django_user_model.objects.create_user(username='author', password='pass-author-1')


@pytest.fixture
def respondent(django_user_model: type[User]) -> User:
    """
    Пользователь, который проходит опросы.

    :param django_user_model: модель пользователя
    :return: пользователь
    """
    
    return django_user_model.objects.create_user(username='respondent', password='pass-resp-1')


@pytest.fixture
def stranger(django_user_model: type[User]) -> User:
    """
    Посторонний пользователь, не связанный с опросом.

    :param django_user_model: модель пользователя
    :return: пользователь
    """
    
    return django_user_model.objects.create_user(username='stranger', password='pass-strange-1')


@pytest.fixture
def make_survey() -> SurveyFactory:
    """
    Фабрика опросов через сервисный слой.

    :return: функция, создающая опрос
    """

    def factory(
        author: User,
        *,
        title: str = 'Овощи',
        questions: Sequence[QuestionSpec] = DEFAULT_QUESTIONS,
        publish: bool = True,
    ) -> Survey:
        """
        Создаёт опрос с вопросами и вариантами ответа.

        :param author: автор опроса
        :param title: название опроса
        :param questions: вопросы с текстами вариантов
        :param publish: опубликовать ли опрос
        :return: опрос
        """
        
        survey = authoring.create_survey(author=author, title=title)
        
        for question_text, option_texts in questions:
            question = authoring.add_question(survey, text=question_text)
            for option_text in option_texts:
                authoring.add_option(question, text=option_text)
        
        if publish:
            survey = authoring.publish_survey(survey)
        
        return survey

    return factory


@pytest.fixture
def draft_survey(make_survey: SurveyFactory, author: User) -> Survey:
    """
    Черновик опроса из трёх вопросов.

    :param make_survey: фабрика опросов
    :param author: автор опроса
    :return: опрос
    """
    
    return make_survey(author, publish=False)


@pytest.fixture
def published_survey(make_survey: SurveyFactory, author: User) -> Survey:
    """
    Опубликованный опрос из трёх вопросов.

    :param make_survey: фабрика опросов
    :param author: автор опроса
    :return: опрос
    """
    
    return make_survey(author)


def _client_for(user: User | None) -> APIClient:
    """
    Создаёт API-клиент от имени пользователя.

    :param user: пользователь или None для анонимного клиента
    :return: API-клиент
    """
    client = APIClient()
    
    if user is not None:
        client.force_authenticate(user)
    
    return client


@pytest.fixture
def anonymous_client() -> APIClient:
    """
    API-клиент без аутентификации.

    :return: API-клиент
    """
    
    return _client_for(None)


@pytest.fixture
def author_client(author: User) -> APIClient:
    """
    API-клиент автора.

    :param author: автор опроса
    :return: API-клиент
    """
    
    return _client_for(author)


@pytest.fixture
def respondent_client(respondent: User) -> APIClient:
    """
    API-клиент респондента.

    :param respondent: респондент
    :return: API-клиент
    """
    
    return _client_for(respondent)


@pytest.fixture
def stranger_client(stranger: User) -> APIClient:
    """
    API-клиент постороннего пользователя.

    :param stranger: посторонний пользователь
    :return: API-клиент
    """
    
    return _client_for(stranger)
