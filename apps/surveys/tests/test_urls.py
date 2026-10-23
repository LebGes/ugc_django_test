from typing import Any

import pytest
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from apps.surveys import views
from apps.surveys.api.views import OptionViewSet, QuestionViewSet, SurveyViewSet


API_ROUTES = [
    ('api:survey-list', {}, '/api/v1/surveys/', SurveyViewSet, {'get': 'list', 'post': 'create'}),
    ('api:survey-mine', {}, '/api/v1/surveys/mine/', SurveyViewSet, {'get': 'mine'}),
    (
        'api:survey-detail',
        {'pk': 7},
        '/api/v1/surveys/7/',
        SurveyViewSet,
        {
            'get': 'retrieve',
            'put': 'update',
            'patch': 'partial_update',
            'delete': 'destroy',
        },
    ),
    (
        'api:survey-publish',
        {'pk': 7},
        '/api/v1/surveys/7/publish/',
        SurveyViewSet,
        {'post': 'publish'},
    ),
    ('api:survey-close', {'pk': 7}, '/api/v1/surveys/7/close/', SurveyViewSet, {'post': 'close'}),
    (
        'api:survey-stats',
        {'pk': 7},
        '/api/v1/surveys/7/stats/',
        SurveyViewSet,
        {'get': 'statistics'},
    ),
    (
        'api:survey-next-question',
        {'pk': 7},
        '/api/v1/surveys/7/next-question/',
        SurveyViewSet,
        {'get': 'next_question'},
    ),
    (
        'api:survey-answers',
        {'pk': 7},
        '/api/v1/surveys/7/answers/',
        SurveyViewSet,
        {'post': 'answers'},
    ),
    (
        'api:survey-question-list',
        {'survey_pk': 7},
        '/api/v1/surveys/7/questions/',
        QuestionViewSet,
        {'get': 'list', 'post': 'create'},
    ),
    (
        'api:survey-question-detail',
        {'survey_pk': 7, 'pk': 3},
        '/api/v1/surveys/7/questions/3/',
        QuestionViewSet,
        {'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'},
    ),
    (
        'api:survey-question-reorder',
        {'survey_pk': 7},
        '/api/v1/surveys/7/questions/reorder/',
        QuestionViewSet,
        {'post': 'reorder'},
    ),
    (
        'api:survey-question-option-list',
        {'survey_pk': 7, 'question_pk': 3},
        '/api/v1/surveys/7/questions/3/options/',
        OptionViewSet,
        {'get': 'list', 'post': 'create'},
    ),
    (
        'api:survey-question-option-detail',
        {'survey_pk': 7, 'question_pk': 3, 'pk': 5},
        '/api/v1/surveys/7/questions/3/options/5/',
        OptionViewSet,
        {'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'},
    ),
    (
        'api:survey-question-option-reorder',
        {'survey_pk': 7, 'question_pk': 3},
        '/api/v1/surveys/7/questions/3/options/reorder/',
        OptionViewSet,
        {'post': 'reorder'},
    ),
]

PAGE_ROUTES = [
    ('surveys:list', {}, '/', views.survey_list),
    ('surveys:take', {'pk': 7}, '/surveys/7/', views.survey_take),
    ('surveys:stats', {'pk': 7}, '/surveys/7/stats/', views.survey_stats),
]


@pytest.mark.parametrize(('name', 'kwargs', 'path', 'viewset', 'actions'), API_ROUTES)
def test_api_route(
    name: str, kwargs: dict[str, Any], path: str, viewset: type, actions: dict[str, str]
) -> None:
    """
    Маршрут API разворачивается в ожидаемый путь, а путь попадает в нужный viewset и действие.
    Метод HEAD DRF добавляет сам при первом запросе, поэтому он не сравнивается.

    :param name: имя маршрута
    :param kwargs: параметры маршрута
    :param path: ожидаемый путь
    :param viewset: ожидаемый обработчик
    :param actions: ожидаемое соответствие HTTP-методов и действий
    """
    assert reverse(name, kwargs=kwargs) == path

    match = resolve(path)
    
    assert match.view_name == name
    assert match.func.cls is viewset  # type: ignore[attr-defined]
    
    routed_actions = {
        method: handler
        for method, handler in match.func.actions.items()  # type: ignore[attr-defined]
        if method != 'head'
    }
    
    assert routed_actions == actions
    assert {key: int(value) for key, value in match.kwargs.items()} == kwargs


@pytest.mark.parametrize(('name', 'kwargs', 'path', 'view'), PAGE_ROUTES)
def test_page_route(name: str, kwargs: dict[str, Any], path: str, view: Any) -> None:
    """
    Маршруты страниц разворачиваются в пути и попадают в нужные обработчики.

    :param name: имя маршрута
    :param kwargs: параметры маршрута
    :param path: ожидаемый путь
    :param view: ожидаемый обработчик
    """
    
    assert reverse(name, kwargs=kwargs) == path
    assert resolve(path).func is view


@pytest.mark.parametrize(
    'path',
    [
        '/api/v1/surveys/abc/',
        '/api/v1/surveys/7/questions/x/',
        '/api/v1/surveys/7/questions/3/options/y/',
        '/surveys/abc/',
    ],
)
def test_non_numeric_ids_are_not_routed(path: str) -> None:
    """
    Нечисловые идентификаторы не попадают в обработчики.

    :param path: путь с некорректным идентификатором
    """
    with pytest.raises(Resolver404):
        resolve(path)


def test_reverse_requires_survey_id() -> None:
    """
    Маршрут прохождения нельзя построить без идентификатора опроса.
    """
    with pytest.raises(NoReverseMatch):
        reverse('surveys:take')


@pytest.mark.parametrize(
    ('name', 'path'),
    [
        ('login', '/accounts/login/'),
        ('logout', '/accounts/logout/'),
        ('api-schema', '/api/schema/'),
        ('api-docs', '/api/docs/'),
    ],
)
def test_service_routes(name: str, path: str) -> None:
    """
    Служебные маршруты (вход, выход, документация API) доступны по ожидаемым путям.

    :param name: имя маршрута
    :param path: ожидаемый путь
    """
    
    assert reverse(name) == path
