from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.surveys.forms import AnswerForm
from apps.surveys.selectors import authored_surveys, published_surveys, visible_surveys
from apps.surveys.services import participation, stats
from apps.surveys.services.exceptions import SurveyError
from apps.users.models import User

SURVEYS_PER_PAGE = 20


@require_http_methods(['GET'])
def survey_list(request: HttpRequest) -> HttpResponse:
    """
    Показывает опубликованные опросы от новых к старым и опросы текущего автора.

    Пагинация курсорная (параметр before), чтобы не считать COUNT по всей таблице.

    :param request: HTTP-запрос
    :return: страница со списком опросов
    """
    surveys = published_surveys()
    before = request.GET.get('before', '')
    if before.isdigit():
        surveys = surveys.filter(pk__lt=int(before))
    page = list(surveys.order_by('-id')[: SURVEYS_PER_PAGE + 1])
    has_next = len(page) > SURVEYS_PER_PAGE
    page = page[:SURVEYS_PER_PAGE]
    own_surveys = (
        list(authored_surveys(request.user.pk).order_by('-id')[:SURVEYS_PER_PAGE])
        if request.user.is_authenticated
        else []
    )
    return render(
        request,
        'surveys/survey_list.html',
        {
            'surveys': page,
            'own_surveys': own_surveys,
            'next_cursor': page[-1].pk if has_next else None,
        },
    )


@login_required
@require_http_methods(['GET', 'POST'])
def survey_take(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Страница прохождения опроса: показывает следующий вопрос и принимает ответ.

    :param request: HTTP-запрос
    :param pk: идентификатор опроса
    :return: страница с вопросом или редирект после ответа
    """
    survey = get_object_or_404(visible_surveys(request.user.pk), pk=pk)
    user = _current_user(request)
    try:
        current = participation.get_next_question(survey, user)
    except SurveyError as exc:
        messages.error(request, exc.message)
        return redirect('surveys:list')

    if current.question is None:
        return render(request, 'surveys/survey_done.html', {'survey': survey})

    form = AnswerForm(request.POST or None, question=current.question)
    if request.method == 'POST' and form.is_valid():
        try:
            participation.submit_answer(
                survey,
                user,
                question_id=form.cleaned_data['question'],
                option_id=form.cleaned_data['option'],
            )
        except SurveyError as exc:
            messages.error(request, exc.message)
        return redirect('surveys:take', pk=survey.pk)

    return render(
        request,
        'surveys/survey_take.html',
        {
            'survey': survey,
            'question': current.question,
            'progress': current.progress,
            'form': form,
        },
    )


@login_required
@require_http_methods(['GET'])
def survey_stats(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Страница статистики опроса для автора.

    :param request: HTTP-запрос
    :param pk: идентификатор опроса
    :return: страница со статистикой
    """
    survey = get_object_or_404(visible_surveys(request.user.pk), pk=pk)
    if survey.author_id != request.user.pk:
        raise PermissionDenied('Статистика доступна только автору опроса')
    return render(
        request,
        'surveys/survey_stats.html',
        {'survey': survey, 'stats': stats.get_survey_stats(survey)},
    )


def _current_user(request: HttpRequest) -> User:
    """
    Возвращает аутентифицированного пользователя запроса.

    :param request: HTTP-запрос, прошедший проверку login_required
    :return: пользователь
    """
    assert isinstance(request.user, User)
    return request.user
