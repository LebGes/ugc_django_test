from typing import Any

from django import forms

from apps.surveys.services.structure import QuestionData


class AnswerForm(forms.Form):
    """
    Форма ответа на вопрос опроса.
    """

    question = forms.IntegerField(widget=forms.HiddenInput)
    option = forms.TypedChoiceField(
        label='Ваш ответ',
        coerce=int,
        widget=forms.RadioSelect,
        error_messages={'required': 'Выберите вариант ответа'},
    )

    def __init__(self, *args: Any, question: QuestionData, **kwargs: Any) -> None:
        """
        Создаёт форму для конкретного вопроса.

        :param args: позиционные аргументы формы
        :param question: вопрос, на который отвечает пользователь
        :param kwargs: именованные аргументы формы
        """
        super().__init__(*args, **kwargs)
        self.fields['question'].initial = question.id
        option_field = self.fields['option']
        assert isinstance(option_field, forms.TypedChoiceField)
        option_field.choices = [(option.id, option.text) for option in question.options]
