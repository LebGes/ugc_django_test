from django.conf import settings
from django.db import models


class SurveyStatus(models.TextChoices):
    """
    Жизненный цикл опроса.
    """

    DRAFT = 'draft', 'Черновик'
    PUBLISHED = 'published', 'Опубликован'
    CLOSED = 'closed', 'Закрыт'


class Survey(models.Model):
    """
    Опрос. Структуру можно менять только в черновике, после публикации она заморожена.
    """

    title = models.CharField('название', max_length=255)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='автор',
        on_delete=models.PROTECT,
        related_name='surveys',
        db_index=False,
    )
    status = models.CharField(
        'статус',
        max_length=16,
        choices=SurveyStatus.choices,
        default=SurveyStatus.DRAFT,
    )
    created_at = models.DateTimeField('дата создания', auto_now_add=True)
    updated_at = models.DateTimeField('дата изменения', auto_now=True)
    published_at = models.DateTimeField('дата публикации', null=True, blank=True)

    class Meta:
        """
        Настройки модели опроса.
        """

        verbose_name = 'опрос'
        verbose_name_plural = 'опросы'
        indexes = [
            models.Index(fields=['status', '-id'], name='survey_status_id_idx'),
            models.Index(fields=['author', '-id'], name='survey_author_id_idx'),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление опроса.

        :return: название опроса
        """

        return self.title

    @property
    def is_draft(self) -> bool:
        """
        Проверяет, что опрос находится в черновике.

        :return: True, если структуру опроса можно редактировать
        """

        return self.status == SurveyStatus.DRAFT

    @property
    def is_published(self) -> bool:
        """
        Проверяет, что опрос опубликован и принимает ответы.

        :return: True, если опрос можно проходить
        """

        return self.status == SurveyStatus.PUBLISHED


class Question(models.Model):
    """
    Вопрос опроса. Порядок вопросов задаётся полем position.
    """

    survey = models.ForeignKey(
        Survey,
        verbose_name='опрос',
        on_delete=models.CASCADE,
        related_name='questions',
        db_index=False,
    )
    text = models.CharField('текст', max_length=1000)
    position = models.PositiveIntegerField('позиция')

    class Meta:
        """
        Настройки модели вопроса.
        """

        verbose_name = 'вопрос'
        verbose_name_plural = 'вопросы'
        constraints = [
            models.UniqueConstraint(
                fields=['survey', 'position'],
                name='question_unique_position',
                deferrable=models.Deferrable.DEFERRED,
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление вопроса.

        :return: текст вопроса
        """

        return self.text


class Option(models.Model):
    """
    Вариант ответа на вопрос. Порядок вариантов задаётся полем position.
    """

    question = models.ForeignKey(
        Question,
        verbose_name='вопрос',
        on_delete=models.CASCADE,
        related_name='options',
        db_index=False,
    )
    text = models.CharField('текст', max_length=500)
    position = models.PositiveIntegerField('позиция')

    class Meta:
        """
        Настройки модели варианта ответа.
        """

        verbose_name = 'вариант ответа'
        verbose_name_plural = 'варианты ответа'
        constraints = [
            models.UniqueConstraint(
                fields=['question', 'position'],
                name='option_unique_position',
                deferrable=models.Deferrable.DEFERRED,
            ),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление варианта ответа.

        :return: текст варианта
        """

        return self.text


class Participation(models.Model):
    """
    Прохождение опроса пользователем. Каждый пользователь проходит опрос один раз.
    """

    survey = models.ForeignKey(
        Survey,
        verbose_name='опрос',
        on_delete=models.CASCADE,
        related_name='participations',
        db_index=False,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='пользователь',
        on_delete=models.CASCADE,
        related_name='participations',
        db_index=False,
    )
    started_at = models.DateTimeField('начало прохождения', auto_now_add=True)
    completed_at = models.DateTimeField('окончание прохождения', null=True, blank=True)

    class Meta:
        """
        Настройки модели прохождения.
        """

        verbose_name = 'прохождение'
        verbose_name_plural = 'прохождения'
        constraints = [
            models.UniqueConstraint(
                fields=['survey', 'user'],
                name='participation_unique_user',
            ),
        ]
        indexes = [
            models.Index(fields=['user', '-id'], name='participation_user_id_idx'),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление прохождения.

        :return: описание прохождения
        """

        return f'Прохождение {self.pk} опроса {self.survey_id}'

    @property
    def is_completed(self) -> bool:
        """
        Проверяет, завершено ли прохождение.

        :return: True, если пользователь ответил на все вопросы
        """

        return self.completed_at is not None


class Answer(models.Model):
    """
    Ответ пользователя на вопрос в рамках прохождения.

    Первичный ключ составной (participation, question): это самая большая таблица,
    и суррогатный ключ только раздул бы её и индексы. Подробности в docs/performance.md.
    """

    pk = models.CompositePrimaryKey('participation_id', 'question_id')
    participation = models.ForeignKey(
        Participation,
        verbose_name='прохождение',
        on_delete=models.CASCADE,
        related_name='answers',
        db_index=False,
    )
    question = models.ForeignKey(
        Question,
        verbose_name='вопрос',
        on_delete=models.PROTECT,
        related_name='answers',
        db_index=False,
    )
    option = models.ForeignKey(
        Option,
        verbose_name='вариант ответа',
        on_delete=models.PROTECT,
        related_name='answers',
    )
    created_at = models.DateTimeField('дата ответа', auto_now_add=True)

    class Meta:
        """
        Настройки модели ответа.
        """

        verbose_name = 'ответ'
        verbose_name_plural = 'ответы'
        indexes = [
            models.Index(fields=['question', 'option'], name='answer_question_option_idx'),
        ]

    def __str__(self) -> str:
        """
        Возвращает строковое представление ответа.

        :return: описание ответа
        """
        
        return f'Ответ на вопрос {self.question_id} в прохождении {self.participation_id}'
