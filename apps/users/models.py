from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    Пользователь сервиса. Может быть и автором опросов, и респондентом.
    """

    class Meta(AbstractUser.Meta):
        """
        Настройки модели пользователя.
        """

        swappable = 'AUTH_USER_MODEL'
        verbose_name = 'пользователь'
        verbose_name_plural = 'пользователи'
