from rest_framework.pagination import CursorPagination


class SurveyCursorPagination(CursorPagination):
    """
    Курсорная пагинация по убыванию id.

    На миллионе опросов OFFSET-пагинация деградирует на дальних страницах,
    а курсор всегда опирается на индекс (status, -id) или (author, -id).
    """

    ordering = '-id'
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
