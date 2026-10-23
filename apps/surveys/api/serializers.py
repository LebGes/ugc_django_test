from datetime import timedelta

from rest_framework import serializers

from apps.surveys.models import Option, Question, Survey
from apps.surveys.services.participation import NextQuestion
from apps.surveys.services.stats import SurveyStats


class OptionSerializer(serializers.ModelSerializer[Option]):
    """
    Вариант ответа для автора опроса.
    """

    class Meta:
        """
        Настройки сериализатора варианта ответа.
        """

        model = Option
        fields = ['id', 'text', 'position']
        read_only_fields = ['position']


class QuestionSerializer(serializers.ModelSerializer[Question]):
    """
    Вопрос с вариантами ответа для автора опроса.
    """

    options = OptionSerializer(many=True, read_only=True)

    class Meta:
        """
        Настройки сериализатора вопроса.
        """

        model = Question
        fields = ['id', 'text', 'position', 'options']
        read_only_fields = ['position']


class SurveySerializer(serializers.ModelSerializer[Survey]):
    """
    Краткое представление опроса.
    """

    author = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        """
        Настройки сериализатора опроса.
        """

        model = Survey
        fields = ['id', 'title', 'author', 'status', 'created_at', 'published_at']
        read_only_fields = ['status', 'created_at', 'published_at']


class SurveyDetailSerializer(SurveySerializer):
    """
    Опрос со всеми вопросами и вариантами, доступен только автору.
    """

    questions = QuestionSerializer(many=True, read_only=True)

    class Meta(SurveySerializer.Meta):
        """
        Настройки сериализатора опроса со структурой.
        """

        fields = [*SurveySerializer.Meta.fields, 'questions']


class ReorderSerializer(serializers.Serializer[None]):
    """
    Новый порядок элементов: полный список идентификаторов.
    """

    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=1000,
    )


class AnswerSerializer(serializers.Serializer[None]):
    """
    Ответ пользователя на вопрос.
    """

    question = serializers.IntegerField(min_value=1)
    option = serializers.IntegerField(min_value=1)


class PublicOptionSerializer(serializers.Serializer[None]):
    """
    Вариант ответа для респондента.
    """

    id = serializers.IntegerField()
    text = serializers.CharField()


class PublicQuestionSerializer(serializers.Serializer[None]):
    """
    Вопрос для респондента.
    """

    id = serializers.IntegerField()
    text = serializers.CharField()
    position = serializers.IntegerField()
    options = PublicOptionSerializer(many=True)


class ProgressSerializer(serializers.Serializer[None]):
    """
    Прогресс прохождения опроса.
    """

    answered = serializers.IntegerField()
    total = serializers.IntegerField()
    completed = serializers.BooleanField(source='is_completed')


class NextQuestionSerializer(serializers.Serializer[NextQuestion]):
    """
    Следующий вопрос и прогресс. Вопрос равен null, когда опрос пройден.
    """

    question = PublicQuestionSerializer(allow_null=True)
    progress = ProgressSerializer()


class OptionStatsSerializer(serializers.Serializer[None]):
    """
    Статистика по варианту ответа.
    """

    id = serializers.IntegerField()
    text = serializers.CharField()
    votes = serializers.IntegerField()
    percent = serializers.FloatField()


class QuestionStatsSerializer(serializers.Serializer[None]):
    """
    Статистика по вопросу.
    """

    id = serializers.IntegerField()
    text = serializers.CharField()
    position = serializers.IntegerField()
    answers = serializers.IntegerField()
    options = OptionStatsSerializer(many=True)
    top_option_ids = serializers.ListField(child=serializers.IntegerField())


class SurveyStatsSerializer(serializers.Serializer[SurveyStats]):
    """
    Сводная статистика по опросу.
    """

    survey_id = serializers.IntegerField()
    participants = serializers.IntegerField()
    completed = serializers.IntegerField()
    completion_rate = serializers.FloatField()
    average_duration_seconds = serializers.SerializerMethodField()
    questions = QuestionStatsSerializer(many=True)

    def get_average_duration_seconds(self, stats: SurveyStats) -> float | None:
        """
        Переводит среднее время прохождения в секунды.

        :param stats: статистика опроса
        :return: среднее время в секундах или None, если завершённых прохождений нет
        """
        
        duration: timedelta | None = stats.average_duration
        
        return round(duration.total_seconds(), 1) if duration is not None else None
