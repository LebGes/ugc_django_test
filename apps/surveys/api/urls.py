from rest_framework.routers import SimpleRouter

from apps.surveys.api.views import OptionViewSet, QuestionViewSet, SurveyViewSet

app_name = 'api'

router = SimpleRouter()
router.register('surveys', SurveyViewSet, basename='survey')
router.register(
    r'surveys/(?P<survey_pk>\d+)/questions',
    QuestionViewSet,
    basename='survey-question',
)
router.register(
    r'surveys/(?P<survey_pk>\d+)/questions/(?P<question_pk>\d+)/options',
    OptionViewSet,
    basename='survey-question-option',
)

urlpatterns = router.urls
