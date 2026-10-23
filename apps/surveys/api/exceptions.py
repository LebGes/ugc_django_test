from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.surveys.services.exceptions import (
    InvalidAnswerError,
    InvalidOrderError,
    SurveyError,
    SurveyNotPublishableError,
)


_BAD_REQUEST_ERRORS = (InvalidAnswerError, InvalidOrderError, SurveyNotPublishableError)


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """
    Превращает доменные ошибки опросов в HTTP-ответы.

    Ошибки во входных данных отдаются как 400, ошибки состояния
    (опрос закрыт, вопрос уже отвечен и т.п.) как 409.

    :param exc: исключение, возникшее при обработке запроса
    :param context: контекст обработки запроса DRF
    :return: HTTP-ответ или None, если исключение не обработано
    """
    
    if isinstance(exc, SurveyError):
        http_status = (
            status.HTTP_400_BAD_REQUEST
            if isinstance(exc, _BAD_REQUEST_ERRORS)
            else status.HTTP_409_CONFLICT
        )
        
        return Response({'detail': exc.message, 'code': exc.code}, status=http_status)
    
    return drf_exception_handler(exc, context)
