from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.surveys.api.mixins import SurveyNestedMixin
from apps.surveys.models import Survey


class IsSurveyAuthorOrReadOnly(BasePermission):
    """
    Читать опрос может любой, кому он виден, изменять только автор.
    """

    message = 'Изменять опрос может только его автор'

    def has_object_permission(self, request: Request, view: APIView, obj: Survey) -> bool:
        """
        Проверяет доступ к конкретному опросу.

        :param request: HTTP-запрос
        :param view: обработчик запроса
        :param obj: опрос
        :return: True, если доступ разрешён
        """
        
        return request.method in SAFE_METHODS or obj.author_id == request.user.pk


class IsSurveyAuthor(BasePermission):
    """
    Доступ только для автора опроса.
    """

    message = 'Действие доступно только автору опроса'

    def has_object_permission(self, request: Request, view: APIView, obj: Survey) -> bool:
        """
        Проверяет, что пользователь является автором опроса.

        :param request: HTTP-запрос
        :param view: обработчик запроса
        :param obj: опрос
        :return: True, если пользователь автор опроса
        """
        
        return obj.author_id == request.user.pk


class IsParentSurveyAuthor(BasePermission):
    """
    Управлять вопросами и вариантами может только автор опроса.
    """

    message = 'Управлять структурой опроса может только его автор'

    def has_permission(self, request: Request, view: APIView) -> bool:
        """
        Проверяет, что пользователь является автором опроса из URL.

        :param request: HTTP-запрос
        :param view: обработчик запроса
        :return: True, если пользователь автор опроса
        """
        
        if not isinstance(view, SurveyNestedMixin):
            return False
        
        return view.get_survey().author_id == request.user.pk
