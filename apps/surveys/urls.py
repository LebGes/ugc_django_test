from django.urls import path

from apps.surveys import views

app_name = 'surveys'

urlpatterns = [
    path('', views.survey_list, name='list'),
    path('surveys/<int:pk>/', views.survey_take, name='take'),
    path('surveys/<int:pk>/stats/', views.survey_stats, name='stats'),
]