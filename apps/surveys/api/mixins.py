from typing import Any

from django.shortcuts import get_object_or_404
from rest_framework.generics import GenericAPIView

from apps.surveys.models import Question, Survey
from apps.surveys.selectors import visible_surveys


class SurveyNestedMixin(GenericAPIView[Any]):
    """
    Доступ к родительскому опросу и вопросу во вложенных ресурсах.
    """

    def get_survey(self) -> Survey:
        """
        Возвращает опрос из URL, загружая его один раз за запрос.

        :return: опрос
        """
        
        if not hasattr(self, '_survey'):
            self._survey = get_object_or_404(
                visible_surveys(self.request.user.pk),
                pk=self.kwargs['survey_pk'],
            )
        
        return self._survey

    def get_question(self) -> Question:
        """
        Возвращает вопрос из URL, проверяя, что он относится к опросу.

        :return: вопрос
        """
        
        if not hasattr(self, '_question'):
            self._question = get_object_or_404(
                Question.objects.all(),
                pk=self.kwargs['question_pk'],
                survey_id=self.get_survey().pk,
            )
        
        return self._question
