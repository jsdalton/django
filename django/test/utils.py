from __future__ import with_statement

import types
import warnings
from django.conf import settings, UserSettingsHolder
from django.core import cache
from django.test.signals import template_rendered, setting_changed
from django.template import Template, loader, TemplateDoesNotExist
from django.template.loaders import cached
from django.utils.translation import deactivate
from django.utils.functional import wraps


__all__ = (
    'Approximate', 'ContextList',  'get_runner', 'override_settings',
    'setup_test_environment', 'teardown_test_environment',
)

RESTORE_LOADERS_ATTR = '_original_template_source_loaders'


class Approximate(object):
    def __init__(self, val, places=7):
        self.val = val
        self.places = places

    def __repr__(self):
        return repr(self.val)

    def __eq__(self, other):
        if self.val == other:
            return True
        return round(abs(self.val-other), self.places) == 0


class ContextList(list):
    """A wrapper that provides direct key access to context items contained
    in a list of context objects.
    """
    def __getitem__(self, key):
        if isinstance(key, basestring):
            for subcontext in self:
                if key in subcontext:
                    return subcontext[key]
            raise KeyError(key)
        else:
            return super(ContextList, self).__getitem__(key)

    def __contains__(self, key):
        try:
            value = self[key]
        except KeyError:
            return False
        return True


def instrumented_test_render(self, context):
    """
    An instrumented Template render method, providing a signal
    that can be intercepted by the test system Client
    """
    template_rendered.send(sender=self, template=self, context=context)
    return self.nodelist.render(context)


_caches_used_during_test = set()

def modified_get_cache(backend, **kwargs):
    """
    Modifies the original get_cache so that we can track any keys set during a cache run and reset
    them at the end.
    """
    requested_cache = cache.original_get_cache(backend, **kwargs)
    
    # Add '_test_' to key_prefix to ensure pre-existing cache values don't get touched
    requested_cache.original_key_prefix = requested_cache.key_prefix
    requested_cache.key_prefix = '_test_%s' % requested_cache.original_key_prefix
    
    # Keep track of which caches we use during a test
    global _caches_used_during_test
    _caches_used_during_test.add(requested_cache)
    
    requested_cache._keys_set_during_test = set()
    
    # Modify cache.set() to collect keys in _keys_set_during_test
    requested_cache.original_set = requested_cache.set
    def modified_set(self, key, value, timeout=None, version=None):
        requested_cache._keys_set_during_test.add(key)
        requested_cache.original_set(key, value, timeout, version)
    requested_cache.set = types.MethodType(modified_set, requested_cache)
    
    # Modify cache.add() to collect keys in _keys_set_during_test
    requested_cache.original_add = requested_cache.add
    def modified_add(self, key, value, timeout=None, version=None):
        requested_cache._keys_set_during_test.add(key)
        return requested_cache.original_add(key, value, timeout, version)
    requested_cache.add = types.MethodType(modified_add, requested_cache)
    
    # Modify cache.incr() to collect keys in _keys_set_during_test
    requested_cache.original_incr = requested_cache.incr
    def modified_incr(self, key, delta=1, version=None):
        requested_cache._keys_set_during_test.add(key)
        return requested_cache.original_incr(key, delta, version)
    requested_cache.incr = types.MethodType(modified_incr, requested_cache)
    
    # Modify cache.decr() to collect keys in _keys_set_during_test
    requested_cache.original_decr = requested_cache.decr
    def modified_decr(self, key, delta=1, version=None):
        requested_cache._keys_set_during_test.add(key)
        return requested_cache.original_decr(key, delta, version)
    requested_cache.decr = types.MethodType(modified_decr, requested_cache)
    
    # Modify cache.set_many() to collect keys in _keys_set_during_test
    requested_cache.original_set_many = requested_cache.set_many
    def modified_set_many(self, data, timeout=None, version=None):
        requested_cache._keys_set_during_test.update(data.keys())
        requested_cache.original_set_many(data, timeout, version)
    requested_cache.set_many = types.MethodType(modified_set_many, requested_cache)
    
    return requested_cache


def setup_test_environment():
    """Perform any global pre-test setup. This involves:

        - Installing the instrumented test renderer
        - Set the email backend to the locmem email backend.
        - Setting the active locale to match the LANGUAGE_CODE setting.
    """
    Template.original_render = Template._render
    Template._render = instrumented_test_render

    mail.original_email_backend = settings.EMAIL_BACKEND
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    mail.outbox = []
    
    cache.original_get_cache = cache.get_cache
    cache.get_cache = modified_get_cache
    
    # Make sure django.core.cache.cache also uses the modified cache
    cache.original_cache = cache.cache
    cache.cache = cache.get_cache(cache.DEFAULT_CACHE_ALIAS)

    deactivate()


def teardown_test_environment():
    """Perform any global post-test teardown. This involves:

        - Restoring the original test renderer
        - Restoring the email sending functions

    """
    Template._render = Template.original_render
    del Template.original_render

    settings.EMAIL_BACKEND = mail.original_email_backend
    del mail.original_email_backend
    del mail.outbox
    
    cache.cache = cache.original_cache
    del cache.original_cache
    cache.get_cache = cache.original_get_cache
    del cache.original_get_cache


def get_warnings_state():
    """
    Returns an object containing the state of the warnings module
    """
    # There is no public interface for doing this, but this implementation of
    # get_warnings_state and restore_warnings_state appears to work on Python
    # 2.4 to 2.7.
    return warnings.filters[:]


def restore_warnings_state(state):
    """
    Restores the state of the warnings module when passed an object that was
    returned by get_warnings_state()
    """
    warnings.filters = state[:]


def get_runner(settings, test_runner_class=None):
    if not test_runner_class:
        test_runner_class = settings.TEST_RUNNER

    test_path = test_runner_class.split('.')
    # Allow for Python 2.5 relative paths
    if len(test_path) > 1:
        test_module_name = '.'.join(test_path[:-1])
    else:
        test_module_name = '.'
    test_module = __import__(test_module_name, {}, {}, test_path[-1])
    test_runner = getattr(test_module, test_path[-1])
    return test_runner


def setup_test_template_loader(templates_dict, use_cached_loader=False):
    """
    Changes Django to only find templates from within a dictionary (where each
    key is the template name and each value is the corresponding template
    content to return).

    Use meth:`restore_template_loaders` to restore the original loaders.
    """
    if hasattr(loader, RESTORE_LOADERS_ATTR):
        raise Exception("loader.%s already exists" % RESTORE_LOADERS_ATTR)

    def test_template_loader(template_name, template_dirs=None):
        "A custom template loader that loads templates from a dictionary."
        try:
            return (templates_dict[template_name], "test:%s" % template_name)
        except KeyError:
            raise TemplateDoesNotExist(template_name)

    if use_cached_loader:
        template_loader = cached.Loader(('test_template_loader',))
        template_loader._cached_loaders = (test_template_loader,)
    else:
        template_loader = test_template_loader

    setattr(loader, RESTORE_LOADERS_ATTR, loader.template_source_loaders)
    loader.template_source_loaders = (template_loader,)
    return template_loader


def restore_template_loaders():
    """
    Restores the original template loaders after
    :meth:`setup_test_template_loader` has been run.
    """
    loader.template_source_loaders = getattr(loader, RESTORE_LOADERS_ATTR)
    delattr(loader, RESTORE_LOADERS_ATTR)


class OverrideSettingsHolder(UserSettingsHolder):
    """
    A custom setting holder that sends a signal upon change.
    """
    def __setattr__(self, name, value):
        UserSettingsHolder.__setattr__(self, name, value)
        setting_changed.send(sender=self.__class__, setting=name, value=value)


class override_settings(object):
    """
    Acts as either a decorator, or a context manager. If it's a decorator it
    takes a function and returns a wrapped function. If it's a contextmanager
    it's used with the ``with`` statement. In either event entering/exiting
    are called before and after, respectively, the function/block is executed.
    """
    def __init__(self, **kwargs):
        self.options = kwargs
        self.wrapped = settings._wrapped

    def __enter__(self):
        self.enable()

    def __exit__(self, exc_type, exc_value, traceback):
        self.disable()

    def __call__(self, test_func):
        from django.test import TransactionTestCase
        if isinstance(test_func, type) and issubclass(test_func, TransactionTestCase):
            original_pre_setup = test_func._pre_setup
            original_post_teardown = test_func._post_teardown
            def _pre_setup(innerself):
                self.enable()
                original_pre_setup(innerself)
            def _post_teardown(innerself):
                original_post_teardown(innerself)
                self.disable()
            test_func._pre_setup = _pre_setup
            test_func._post_teardown = _post_teardown
            return test_func
        else:
            @wraps(test_func)
            def inner(*args, **kwargs):
                with self:
                    return test_func(*args, **kwargs)
        return inner

    def enable(self):
        override = OverrideSettingsHolder(settings._wrapped)
        for key, new_value in self.options.items():
            setattr(override, key, new_value)
        settings._wrapped = override

    def disable(self):
        settings._wrapped = self.wrapped
