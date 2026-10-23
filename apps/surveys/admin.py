from typing import Any, cast

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest

from apps.surveys.models import Option, Question, Survey
from apps.surveys.services import authoring
from apps.surveys.services.exceptions import SurveyError
from apps.users.models import User


class DraftOnlyInlineMixin:
    """
    Делает вложенные элементы доступными для изменения только в черновике опроса.
    """

    def _is_editable(self, obj: Survey | Question | None) -> bool:
        """
        Проверяет, можно ли менять структуру родительского опроса.

        :param obj: родительский опрос или вопрос
        :return: True, если опрос ещё черновик или объект только создаётся
        """
        
        if obj is None:
            
            return True
        
        survey = obj if isinstance(obj, Survey) else obj.survey
        
        return survey.is_draft

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """
        Разрешает добавление только в черновике.

        :param request: HTTP-запрос
        :param obj: родительский объект
        :return: True, если добавление разрешено
        """
        
        return self._is_editable(obj)

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """
        Разрешает изменение только в черновике.

        :param request: HTTP-запрос
        :param obj: родительский объект
        :return: True, если изменение разрешено
        """
        
        return self._is_editable(obj)

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        """
        Разрешает удаление только в черновике.

        :param request: HTTP-запрос
        :param obj: родительский объект
        :return: True, если удаление разрешено
        """
        
        return self._is_editable(obj)


class QuestionInline(DraftOnlyInlineMixin, admin.TabularInline):
    """
    Вопросы на странице опроса.
    """

    model = Question
    fields = ['position', 'text']
    ordering = ['position', 'id']
    show_change_link = True
    extra = 0


class OptionInline(DraftOnlyInlineMixin, admin.TabularInline):
    """
    Варианты ответа на странице вопроса.
    """

    model = Option
    fields = ['position', 'text']
    ordering = ['position', 'id']
    extra = 0


@admin.register(Survey)
class SurveyAdmin(admin.ModelAdmin):
    """
    Редактор опросов. Автор видит только свои опросы.
    """

    list_display = ['id', 'title', 'author', 'status', 'created_at', 'published_at']
    list_filter = ['status']
    search_fields = ['title']
    readonly_fields = ['author', 'status', 'created_at', 'published_at']
    list_select_related = ['author']
    show_full_result_count = False
    inlines = [QuestionInline]
    actions = ['publish', 'close']

    def get_queryset(self, request: HttpRequest) -> QuerySet[Survey]:
        """
        Ограничивает список опросов авторством, если пользователь не суперпользователь.

        :param request: HTTP-запрос
        :return: набор опросов
        """
        
        queryset = super().get_queryset(request)
        
        if request.user.is_superuser:
            
            return queryset
        
        return queryset.filter(author_id=request.user.pk)

    def save_model(
        self, request: HttpRequest, obj: Survey, form: ModelForm, change: bool
    ) -> None:
        """
        Проставляет автора при создании опроса.

        :param request: HTTP-запрос
        :param obj: опрос
        :param form: форма опроса
        :param change: True, если опрос редактируется, а не создаётся
        """
        
        if not change:
            obj.author = cast(User, request.user)
        
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request: HttpRequest, obj: Survey | None = None) -> bool:
        """
        Разрешает удалять только черновики.

        :param request: HTTP-запрос
        :param obj: опрос
        :return: True, если удаление разрешено
        """
        
        if obj is not None and not obj.is_draft:
            
            return False
        
        return super().has_delete_permission(request, obj)

    @admin.action(description='Опубликовать выбранные опросы')
    def publish(self, request: HttpRequest, queryset: QuerySet[Survey]) -> None:
        """
        Публикует выбранные опросы.

        :param request: HTTP-запрос
        :param queryset: выбранные опросы
        """
        
        self._apply(request, queryset, authoring.publish_survey)

    @admin.action(description='Закрыть выбранные опросы')
    def close(self, request: HttpRequest, queryset: QuerySet[Survey]) -> None:
        """
        Закрывает выбранные опросы.

        :param request: HTTP-запрос
        :param queryset: выбранные опросы
        """
        
        self._apply(request, queryset, authoring.close_survey)

    def _apply(self, request: HttpRequest, queryset: QuerySet[Survey], operation: Any) -> None:
        """
        Применяет операцию к каждому опросу и сообщает о результате.

        :param request: HTTP-запрос
        :param queryset: выбранные опросы
        :param operation: функция сервисного слоя, принимающая опрос
        """
        
        for survey in queryset:
            try:
                operation(survey)
            except SurveyError as exc:
                self.message_user(request, f'{survey}: {exc.message}', messages.ERROR)
            else:
                self.message_user(request, f'{survey}: готово', messages.SUCCESS)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    """
    Редактор вопроса с вариантами ответа.
    """

    list_display = ['id', 'text', 'survey', 'position']
    list_select_related = ['survey']
    raw_id_fields = ['survey']
    show_full_result_count = False
    inlines = [OptionInline]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Question]:
        """
        Ограничивает список вопросов опросами текущего автора.

        :param request: HTTP-запрос
        :return: набор вопросов
        """
        
        queryset = super().get_queryset(request).select_related('survey')
        
        if request.user.is_superuser:
            
            return queryset
        
        return queryset.filter(survey__author_id=request.user.pk)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """
        Запрещает создавать вопрос отдельно от опроса, вопросы добавляются на странице опроса.

        :param request: HTTP-запрос
        :return: всегда False
        """
        
        return False

    def has_change_permission(self, request: HttpRequest, obj: Question | None = None) -> bool:
        """
        Разрешает менять вопрос только в черновике опроса.

        :param request: HTTP-запрос
        :param obj: вопрос
        :return: True, если изменение разрешено
        """
        
        if obj is not None and not obj.survey.is_draft:
            
            return False
        
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: Question | None = None) -> bool:
        """
        Разрешает удалять вопрос только в черновике опроса.

        :param request: HTTP-запрос
        :param obj: вопрос
        :return: True, если удаление разрешено
        """
        
        if obj is not None and not obj.survey.is_draft:
            
            return False
        
        return super().has_delete_permission(request, obj)
