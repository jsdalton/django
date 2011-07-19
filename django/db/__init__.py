from django.conf import settings
from django.core import signals
from django.core.exceptions import ImproperlyConfigured
from django.db.utils import (ConnectionHandler, ConnectionRouter,
    load_backend, DEFAULT_DB_ALIAS, DatabaseError, IntegrityError)

__all__ = ('backend', 'connection', 'connections', 'router', 'DatabaseError',
    'IntegrityError', 'DEFAULT_DB_ALIAS')


if DEFAULT_DB_ALIAS not in settings.DATABASES:
    raise ImproperlyConfigured("You must define a '%s' database" % DEFAULT_DB_ALIAS)

connections = ConnectionHandler(settings.DATABASES)
connections._ignore_num_queries = False

router = ConnectionRouter(settings.DATABASE_ROUTERS)

# `connection`, `DatabaseError` and `IntegrityError` are convenient aliases
# for backend bits.

# DatabaseWrapper.__init__() takes a dictionary, not a settings module, so
# we manually create the dictionary from the settings, passing only the
# settings that the database backends care about. Note that TIME_ZONE is used
# by the PostgreSQL backends.
# we load all these up for backwards compatibility, you should use
# connections['default'] instead.
connection = connections[DEFAULT_DB_ALIAS]
backend = load_backend(connection.settings_dict['ENGINE'])

# Register an event that closes the database connection
# when a Django request is finished.
def close_connection(**kwargs):
    for conn in connections.all():
        conn.close()
signals.request_finished.connect(close_connection)

# Register an event that resets connection.queries
# when a Django request is started.
def reset_queries(**kwargs):
    for conn in connections.all():
        conn.queries = []
signals.request_started.connect(reset_queries)

# Register an event that rolls back the connections
# when a Django request has an exception.
def _rollback_on_exception(**kwargs):
    from django.db import transaction
    for conn in connections:
        try:
            transaction.rollback_unless_managed(using=conn)
        except DatabaseError:
            pass
signals.got_request_exception.connect(_rollback_on_exception)
