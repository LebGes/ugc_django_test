class SurveyError(Exception):
    """
    Базовая ошибка предметной области опросов.
    """

    code = 'survey_error'
    default_message = 'Ошибка при работе с опросом'

    def __init__(self, message: str | None = None) -> None:
        """
        Создаёт ошибку с сообщением для пользователя.

        :param message: текст ошибки, если не задан, берётся сообщение по умолчанию
        """
        self.message = message or self.default_message
        super().__init__(self.message)


class SurveyNotEditableError(SurveyError):
    """
    Попытка изменить структуру опубликованного или закрытого опроса.
    """

    code = 'survey_not_editable'
    default_message = 'Структуру опроса можно менять только в черновике'


class SurveyStatusError(SurveyError):
    """
    Действие недоступно в текущем статусе опроса.
    """

    code = 'invalid_survey_status'
    default_message = 'Действие недоступно в текущем статусе опроса'


class SurveyNotPublishableError(SurveyError):
    """
    Опрос не готов к публикации.
    """

    code = 'survey_not_publishable'
    default_message = 'Опрос не готов к публикации'


class SurveyNotAvailableError(SurveyError):
    """
    Опрос не принимает ответы.
    """

    code = 'survey_not_available'
    default_message = 'Опрос сейчас не принимает ответы'


class InvalidAnswerError(SurveyError):
    """
    Вопрос или вариант ответа не относится к опросу.
    """

    code = 'invalid_answer'
    default_message = 'Вопрос или вариант ответа не относится к этому опросу'


class QuestionAlreadyAnsweredError(SurveyError):
    """
    Пользователь уже ответил на этот вопрос.
    """

    code = 'question_already_answered'
    default_message = 'Вы уже ответили на этот вопрос'


class UnexpectedQuestionError(SurveyError):
    """
    Пользователь отвечает не на тот вопрос, который идёт следующим.
    """

    code = 'unexpected_question'
    default_message = 'Сначала нужно ответить на предыдущие вопросы'


class ParticipationCompletedError(SurveyError):
    """
    Пользователь уже прошёл опрос до конца.
    """

    code = 'participation_completed'
    default_message = 'Вы уже прошли этот опрос'


class InvalidOrderError(SurveyError):
    """
    Новый порядок не совпадает с текущим набором элементов.
    """

    code = 'invalid_order'
    default_message = 'Нужно передать все элементы ровно по одному разу'
