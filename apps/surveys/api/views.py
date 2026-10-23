from typing import Any, cast

from django.db.models import Prefetch, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from apps.surveys.api.mixins import SurveyNestedMixin
from apps.surveys.api.permissions import (
    IsParentSurveyAuthor,
    IsSurveyAuthor,
    IsSurveyAuthorOrReadOnly,
)
from apps.surveys.api.serializers import (
    AnswerSerializer,
    NextQuestionSerializer,
    OptionSerializer,
    QuestionSerializer,
    ReorderSerializer,
    SurveyDetailSerializer,
    SurveySerializer,
    SurveyStatsSerializer,
)
from apps.surveys.models import Option, Question, Survey
from apps.surveys.selectors import authored_surveys, published_surveys, visible_surveys
from apps.surveys.services import authoring, participation, stats
from apps.users.models import User


SURVEY_PK_PARAMETER = OpenApiParameter('survey_pk', int, OpenApiParameter.PATH)
QUESTION_PK_PARAMETER = OpenApiParameter('question_pk', int, OpenApiParameter.PATH)


def current_user(request: Request) -> User:
    """
    Возвращает аутентифицированного пользователя запроса.

    :param request: HTTP-запрос, прошедший проверку IsAuthenticated
    :return: пользователь
    """
    
    return cast(User, request.user)


def ordered_questions() -> QuerySet[Question]:
    """
    Возвращает вопросы в порядке показа с подгруженными вариантами.

    :return: набор вопросов
    """
    
    return Question.objects.order_by('position', 'id').prefetch_related(
        Prefetch('options', queryset=Option.objects.order_by('position', 'id')),
    )


class SurveyViewSet(viewsets.ModelViewSet[Survey]):
    """
    Опросы: создание и редактирование автором, прохождение и статистика.
    """

    serializer_class = SurveySerializer
    permission_classes = [IsAuthenticated, IsSurveyAuthorOrReadOnly]
    lookup_value_regex = r'\d+'

    def get_queryset(self) -> QuerySet[Survey]:
        """
        Возвращает опросы, доступные в рамках текущего действия.

        :return: набор опросов
        """
        
        user_id = self.request.user.pk
        
        if self.action == 'list':
            return published_surveys()
        
        if self.action == 'mine':
            return authored_surveys(user_id)
        
        return visible_surveys(user_id)

    @extend_schema(responses=SurveyDetailSerializer)
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Возвращает опрос. Автор получает его вместе со структурой.

        :param request: HTTP-запрос
        :param args: позиционные аргументы маршрута
        :param kwargs: именованные аргументы маршрута
        :return: HTTP-ответ с опросом
        """
        
        survey = self.get_object()
        
        if survey.author_id != request.user.pk:
            return Response(SurveySerializer(survey).data)
        
        return Response(self._detail_data(survey))

    def perform_create(self, serializer: BaseSerializer[Survey]) -> None:
        """
        Создаёт опрос от имени текущего пользователя.

        :param serializer: провалидированный сериализатор
        """
        
        serializer.instance = authoring.create_survey(
            author=current_user(self.request),
            title=serializer.validated_data['title'],
        )

    def perform_update(self, serializer: BaseSerializer[Survey]) -> None:
        """
        Переименовывает опрос.

        :param serializer: провалидированный сериализатор
        """
        
        survey = cast(Survey, serializer.instance)
        serializer.instance = authoring.rename_survey(
            survey,
            title=serializer.validated_data.get('title', survey.title),
        )

    def perform_destroy(self, instance: Survey) -> None:
        """
        Удаляет черновик опроса.

        :param instance: опрос
        """
        
        authoring.delete_survey(instance)

    @action(detail=False, methods=['get'])
    def mine(self, request: Request) -> Response:
        """
        Возвращает опросы текущего пользователя во всех статусах.

        :param request: HTTP-запрос
        :return: HTTP-ответ со страницей опросов
        """
        
        page = self.paginate_queryset(self.get_queryset())
        
        return self.get_paginated_response(SurveySerializer(page, many=True).data)

    @extend_schema(request=None, responses=SurveySerializer)
    @action(detail=True, methods=['post'])
    def publish(self, request: Request, pk: str) -> Response:
        """
        Публикует опрос.

        :param request: HTTP-запрос
        :param pk: идентификатор опроса
        :return: HTTP-ответ с опубликованным опросом
        """
        
        survey = authoring.publish_survey(self.get_object())
        
        return Response(SurveySerializer(survey).data)

    @extend_schema(request=None, responses=SurveySerializer)
    @action(detail=True, methods=['post'])
    def close(self, request: Request, pk: str) -> Response:
        """
        Закрывает опрос для новых ответов.

        :param request: HTTP-запрос
        :param pk: идентификатор опроса
        :return: HTTP-ответ с закрытым опросом
        """
        
        survey = authoring.close_survey(self.get_object())
        
        return Response(SurveySerializer(survey).data)

    @extend_schema(responses=SurveyStatsSerializer)
    @action(
        detail=True,
        methods=['get'],
        url_path='stats',
        url_name='stats',
        permission_classes=[IsAuthenticated, IsSurveyAuthor],
    )
    def statistics(self, request: Request, pk: str) -> Response:
        """
        Возвращает статистику опроса.

        :param request: HTTP-запрос
        :param pk: идентификатор опроса
        :return: HTTP-ответ со статистикой
        """
        
        survey_stats = stats.get_survey_stats(self.get_object())
        
        return Response(SurveyStatsSerializer(survey_stats).data)

    @extend_schema(responses=NextQuestionSerializer)
    @action(
        detail=True,
        methods=['get'],
        url_path='next-question',
        permission_classes=[IsAuthenticated],
    )
    def next_question(self, request: Request, pk: str) -> Response:
        """
        Возвращает вопрос, на который пользователь должен ответить следующим.

        :param request: HTTP-запрос
        :param pk: идентификатор опроса
        :return: HTTP-ответ со следующим вопросом и прогрессом
        """
        
        result = participation.get_next_question(self.get_object(), current_user(request))
        
        return Response(NextQuestionSerializer(result).data)

    @extend_schema(request=AnswerSerializer, responses={201: NextQuestionSerializer})
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def answers(self, request: Request, pk: str) -> Response:
        """
        Принимает ответ на текущий вопрос и возвращает следующий.

        :param request: HTTP-запрос
        :param pk: идентификатор опроса
        :return: HTTP-ответ со следующим вопросом и прогрессом
        """
        
        serializer = AnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        result = participation.submit_answer(
            self.get_object(),
            current_user(request),
            question_id=serializer.validated_data['question'],
            option_id=serializer.validated_data['option'],
        )
        
        return Response(NextQuestionSerializer(result).data, status=status.HTTP_201_CREATED)

    def _detail_data(self, survey: Survey) -> Any:
        """
        Сериализует опрос вместе с упорядоченной структурой.

        :param survey: опрос
        :return: данные для ответа
        """
        
        survey = (
            Survey.objects.select_related('author')
            .prefetch_related(Prefetch('questions', queryset=ordered_questions()))
            .get(pk=survey.pk)
        )
        
        return SurveyDetailSerializer(survey).data


@extend_schema_view(
    list=extend_schema(parameters=[SURVEY_PK_PARAMETER]),
    create=extend_schema(parameters=[SURVEY_PK_PARAMETER]),
    retrieve=extend_schema(parameters=[SURVEY_PK_PARAMETER]),
    update=extend_schema(parameters=[SURVEY_PK_PARAMETER]),
    partial_update=extend_schema(parameters=[SURVEY_PK_PARAMETER]),
    destroy=extend_schema(parameters=[SURVEY_PK_PARAMETER]),
)
class QuestionViewSet(SurveyNestedMixin, viewsets.ModelViewSet[Question]):
    """
    Вопросы опроса. Доступны только автору опроса.
    """

    serializer_class = QuestionSerializer
    permission_classes = [IsAuthenticated, IsParentSurveyAuthor]
    pagination_class = None
    lookup_value_regex = r'\d+'

    def get_queryset(self) -> QuerySet[Question]:
        """
        Возвращает вопросы опроса из URL в порядке показа.

        :return: набор вопросов
        """
        
        if getattr(self, 'swagger_fake_view', False):
            return Question.objects.none()
        
        return ordered_questions().filter(survey_id=self.get_survey().pk)

    def perform_create(self, serializer: BaseSerializer[Question]) -> None:
        """
        Добавляет вопрос в конец опроса.

        :param serializer: провалидированный сериализатор
        """
        
        serializer.instance = authoring.add_question(
            self.get_survey(),
            text=serializer.validated_data['text'],
        )

    def perform_update(self, serializer: BaseSerializer[Question]) -> None:
        """
        Меняет текст вопроса.

        :param serializer: провалидированный сериализатор
        """
        
        question = cast(Question, serializer.instance)
        serializer.instance = authoring.update_question(
            question,
            text=serializer.validated_data.get('text', question.text),
        )

    def perform_destroy(self, instance: Question) -> None:
        """
        Удаляет вопрос.

        :param instance: вопрос
        """
        
        authoring.delete_question(instance)

    @extend_schema(
        parameters=[SURVEY_PK_PARAMETER],
        request=ReorderSerializer,
        responses=QuestionSerializer(many=True),
    )
    @action(detail=False, methods=['post'])
    def reorder(self, request: Request, survey_pk: str) -> Response:
        """
        Задаёт новый порядок вопросов.

        :param request: HTTP-запрос
        :param survey_pk: идентификатор опроса
        :return: HTTP-ответ с вопросами в новом порядке
        """
        
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        authoring.reorder_questions(self.get_survey(), serializer.validated_data['ids'])
        
        return Response(QuestionSerializer(self.get_queryset(), many=True).data)


@extend_schema_view(
    list=extend_schema(parameters=[SURVEY_PK_PARAMETER, QUESTION_PK_PARAMETER]),
    create=extend_schema(parameters=[SURVEY_PK_PARAMETER, QUESTION_PK_PARAMETER]),
    retrieve=extend_schema(parameters=[SURVEY_PK_PARAMETER, QUESTION_PK_PARAMETER]),
    update=extend_schema(parameters=[SURVEY_PK_PARAMETER, QUESTION_PK_PARAMETER]),
    partial_update=extend_schema(parameters=[SURVEY_PK_PARAMETER, QUESTION_PK_PARAMETER]),
    destroy=extend_schema(parameters=[SURVEY_PK_PARAMETER, QUESTION_PK_PARAMETER]),
)
class OptionViewSet(SurveyNestedMixin, viewsets.ModelViewSet[Option]):
    """
    Варианты ответа на вопрос. Доступны только автору опроса.
    """

    serializer_class = OptionSerializer
    permission_classes = [IsAuthenticated, IsParentSurveyAuthor]
    pagination_class = None
    lookup_value_regex = r'\d+'

    def get_queryset(self) -> QuerySet[Option]:
        """
        Возвращает варианты вопроса из URL в порядке показа.

        :return: набор вариантов
        """
        
        if getattr(self, 'swagger_fake_view', False):
            return Option.objects.none()
        
        return (
            Option.objects.select_related('question')
            .filter(question_id=self.get_question().pk)
            .order_by('position', 'id')
        )

    def perform_create(self, serializer: BaseSerializer[Option]) -> None:
        """
        Добавляет вариант в конец списка вариантов.

        :param serializer: провалидированный сериализатор
        """
        
        serializer.instance = authoring.add_option(
            self.get_question(),
            text=serializer.validated_data['text'],
        )

    def perform_update(self, serializer: BaseSerializer[Option]) -> None:
        """
        Меняет текст варианта.

        :param serializer: провалидированный сериализатор
        """
        
        option = cast(Option, serializer.instance)
        serializer.instance = authoring.update_option(
            option,
            text=serializer.validated_data.get('text', option.text),
        )

    def perform_destroy(self, instance: Option) -> None:
        """
        Удаляет вариант ответа.

        :param instance: вариант ответа
        """
        
        authoring.delete_option(instance)

    @extend_schema(
        parameters=[SURVEY_PK_PARAMETER, QUESTION_PK_PARAMETER],
        request=ReorderSerializer,
        responses=OptionSerializer(many=True),
    )
    @action(detail=False, methods=['post'])
    def reorder(self, request: Request, survey_pk: str, question_pk: str) -> Response:
        """
        Задаёт новый порядок вариантов ответа.

        :param request: HTTP-запрос
        :param survey_pk: идентификатор опроса
        :param question_pk: идентификатор вопроса
        :return: HTTP-ответ с вариантами в новом порядке
        """
        
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        authoring.reorder_options(self.get_question(), serializer.validated_data['ids'])
        
        return Response(OptionSerializer(self.get_queryset(), many=True).data)
