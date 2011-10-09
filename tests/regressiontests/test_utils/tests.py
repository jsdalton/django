from __future__ import with_statement

from django.forms import EmailField
from django.test import SimpleTestCase, TestCase, skipUnlessDBFeature
from django.utils.unittest import skip, skipUnless
from django.conf import settings
from django.core import management
from django.core.cache import get_cache, DEFAULT_CACHE_ALIAS

from models import Person


class SkippingTestCase(TestCase):
    def test_skip_unless_db_feature(self):
        "A test that might be skipped is actually called."
        # Total hack, but it works, just want an attribute that's always true.
        @skipUnlessDBFeature("__class__")
        def test_func():
            raise ValueError

        self.assertRaises(ValueError, test_func)


class AssertNumQueriesTests(TestCase):
    urls = 'regressiontests.test_utils.urls'

    def test_assert_num_queries(self):
        def test_func():
            raise ValueError

        self.assertRaises(ValueError,
            self.assertNumQueries, 2, test_func
        )

    def test_assert_num_queries_with_client(self):
        person = Person.objects.create(name='test')

        self.assertNumQueries(
            1,
            self.client.get,
            "/test_utils/get_person/%s/" % person.pk
        )

        self.assertNumQueries(
            1,
            self.client.get,
            "/test_utils/get_person/%s/" % person.pk
        )

        def test_func():
            self.client.get("/test_utils/get_person/%s/" % person.pk)
            self.client.get("/test_utils/get_person/%s/" % person.pk)
        self.assertNumQueries(2, test_func)


class AssertNumQueriesContextManagerTests(TestCase):
    urls = 'regressiontests.test_utils.urls'

    def test_simple(self):
        with self.assertNumQueries(0):
            pass

        with self.assertNumQueries(1):
            Person.objects.count()

        with self.assertNumQueries(2):
            Person.objects.count()
            Person.objects.count()

    def test_failure(self):
        with self.assertRaises(AssertionError) as exc_info:
            with self.assertNumQueries(2):
                Person.objects.count()
        self.assertIn("1 queries executed, 2 expected", str(exc_info.exception))

        with self.assertRaises(TypeError):
            with self.assertNumQueries(4000):
                raise TypeError

    def test_with_client(self):
        person = Person.objects.create(name="test")

        with self.assertNumQueries(1):
            self.client.get("/test_utils/get_person/%s/" % person.pk)

        with self.assertNumQueries(1):
            self.client.get("/test_utils/get_person/%s/" % person.pk)

        with self.assertNumQueries(2):
            self.client.get("/test_utils/get_person/%s/" % person.pk)
            self.client.get("/test_utils/get_person/%s/" % person.pk)


class SaveRestoreWarningState(TestCase):
    def test_save_restore_warnings_state(self):
        """
        Ensure save_warnings_state/restore_warnings_state work correctly.
        """
        # In reality this test could be satisfied by many broken implementations
        # of save_warnings_state/restore_warnings_state (e.g. just
        # warnings.resetwarnings()) , but it is difficult to test more.
        import warnings
        self.save_warnings_state()

        class MyWarning(Warning):
            pass

        # Add a filter that causes an exception to be thrown, so we can catch it
        warnings.simplefilter("error", MyWarning)
        self.assertRaises(Warning, lambda: warnings.warn("warn", MyWarning))

        # Now restore.
        self.restore_warnings_state()
        # After restoring, we shouldn't get an exception. But we don't want a
        # warning printed either, so we have to silence the warning.
        warnings.simplefilter("ignore", MyWarning)
        warnings.warn("warn", MyWarning)

        # Remove the filter we just added.
        self.restore_warnings_state()


class SkippingExtraTests(TestCase):
    fixtures = ['should_not_be_loaded.json']

    # HACK: This depends on internals of our TestCase subclasses
    def __call__(self, result=None):
        # Detect fixture loading by counting SQL queries, should be zero
        with self.assertNumQueries(0):
            super(SkippingExtraTests, self).__call__(result)

    @skip("Fixture loading should not be performed for skipped tests.")
    def test_fixtures_are_skipped(self):
        pass


# We must set this via a function to confirm that cache set test has run
# before cache get test
_cache_set_test_has_run = False

def cache_set_test_run():
    global _cache_set_test_has_run
    _cache_set_test_has_run = True

def cache_get_test_finished():
    global _cache_set_test_has_run
    _cache_set_test_has_run = False


class BaseCacheReset(TestCase):
    @classmethod
    def setUpClass(cls):
        # Setup everything here, because setupClass is guaranteed to run first
        cache = cls.original_cache()

        # Add a "pre-existing" value to cache to ensure it gets reset properly
        cache.set('salt', 'pepper') # We won't touch this one
        cache.set('sweet', 'sour') # We will touch a key with this name and check if it's restored at the end
        
        # Sanity checks
        assert cache.get('salt') == 'pepper'
        assert cache.get('sweet') == 'sour'

        # We manually prefix the test_ here because we are not trying to pretend these are part
        # of the original cache. We're just making sure the values exist so that we can call incr/decr
        # without using cache.set() first
        cache.orig_key_prefix = cache.key_prefix
        cache.key_prefix = '_test_%s' % cache.orig_key_prefix
        try:
            cache.set('going_up', 1)
            cache.set('going_down', 2)
        finally:
            cache.key_prefix = cache.orig_key_prefix

    def setUp(self):
        # Set up cache again at the instance level. This one will get reset
        self.cache = self.modified_cache()


class CacheResetTestsMixin(object):
    # Note test names start with a/b. This ensures test order is correct (which we're normally
    # not supposed to worry about)
    def test_a_set_cache_in_various_ways_in_one_test_method(self):
        """
        Set some cache stuff in this method, and then we'll sure it doesn't carry over to the next
        """
        sweet_result = self.cache.set('sweet', 'bitter')
        left_result = self.cache.set('left', 'right')
        loud_result = self.cache.add('loud', 'quiet')
        
        assert self.cache.get('going_up') == 1
        going_up_result = self.cache.incr('going_up')
        
        assert self.cache.get('going_down') == 2
        going_down_result = self.cache.decr('going_down')
        
        over_above_result = self.cache.set_many({'over': 'under', 'above': 'below'})

        # Sanity checks
        self.assertEqual(self.cache.get('sweet'), 'bitter')
        self.assertEqual(sweet_result, None)
        
        self.assertEqual(self.cache.get('left'), 'right')
        self.assertEqual(left_result, None)
        
        self.assertEqual(self.cache.get('loud'), 'quiet')
        self.assertEqual(loud_result, True)
        
        self.assertEqual(self.cache.get('going_up'), 2)
        self.assertEqual(going_up_result, 2)
        
        self.assertEqual(self.cache.get('going_down'), 1)
        self.assertEqual(going_down_result, 1)
        
        self.assertEqual(self.cache.get('over'), 'under')
        self.assertEqual(self.cache.get('above'), 'below')
        self.assertEqual(over_above_result, None)

        # Mark that set_cache tests have run
        cache_set_test_run()

    def test_b_get_cache_in_another_test_method(self):
        # Confirm that set tests has already run
        if not _cache_set_test_has_run:
            self.skipTest("set_cache test did not run first!")

        try:
            self.assertEqual(self.cache.get('left'), None)
            self.assertEqual(self.cache.get('loud'), None)
            self.assertEqual(self.cache.get('going_up'), None)
            self.assertEqual(self.cache.get('going_down'), None)
            self.assertEqual(self.cache.get('over'), None)
            self.assertEqual(self.cache.get('above'), None)

            # Make sure pre-existing values are still correct
            original_cache = self.__class__.original_cache()
            self.assertEqual(original_cache.get('sweet'), 'sour')
            self.assertEqual(original_cache.get('salt'), 'pepper')
        finally:
            # Mark get_cache tests finished
            cache_get_test_finished()


class LocMemCacheResetTests(BaseCacheReset, CacheResetTestsMixin):
    backend_name = 'django.core.cache.backends.locmem.LocMemCache'

    @classmethod
    def original_cache(cls):
        if not hasattr(cls, '_original_cache'):
            from django.core.cache import original_get_cache
            cls._original_cache = original_get_cache(cls.backend_name, LOCATION='test')
        return cls._original_cache

    def modified_cache(self):
        return get_cache(self.backend_name, LOCATION='test')


class FileBasedCacheResetTests(BaseCacheReset, CacheResetTestsMixin):
    backend_name = 'django.core.cache.backends.filebased.FileBasedCache'

    @classmethod
    def original_cache(cls):
        if not hasattr(cls, '_original_cache'):
            cls.cache_dirname = tempfile.mkdtemp()
            from django.core.cache import original_get_cache
            cls._original_cache = original_get_cache(cls.backend_name, LOCATION=cls.cache_dirname)
        return cls._original_cache

    def modified_cache(self):
        return get_cache(self.backend_name, LOCATION=self.cache_dirname)


class DBCacheResetTests(BaseCacheReset, CacheResetTestsMixin):
    backend_name = 'django.core.cache.backends.db.DatabaseCache'

    @classmethod
    def original_cache(cls):
        if not hasattr(cls, '_original_cache'):
            cls.cache_table_name = 'test_cache_table'
            management.call_command('createcachetable', cls.cache_table_name, verbosity=0, interactive=False)
            from django.core.cache import original_get_cache
            cls._original_cache = original_get_cache(cls.backend_name, LOCATION=cls.cache_table_name)
        return cls._original_cache

    def modified_cache(self):
        return get_cache(self.backend_name, LOCATION=self.cache_table_name)

    @classmethod
    def tearDownClass(cls):
        from django.db import connection
        cursor = connection.cursor()
        cursor.execute('DROP TABLE %s' % connection.ops.quote_name(cls.cache_table_name))


@skipUnless(settings.CACHES[DEFAULT_CACHE_ALIAS]['BACKEND'].startswith('django.core.cache.backends.memcached.'), "memcached not available")
class MemcachedCacheResetTests(BaseCacheReset, CacheResetTestsMixin):
    backend_name = 'django.core.cache.backends.memcached.MemcachedCache'

    @classmethod
    def original_cache(cls):
        if not hasattr(cls, '_original_cache'):
            cls.memcached_location = settings.CACHES[DEFAULT_CACHE_ALIAS]['LOCATION']
            from django.core.cache import original_get_cache
            cls._original_cache = original_get_cache(cls.backend_name, LOCATION=cls.memcached_location)
        return cls._original_cache

    def modified_cache(self):
        return get_cache(self.backend_name, LOCATION=self.memcached_location)


class AssertRaisesMsgTest(SimpleTestCase):

    def test_special_re_chars(self):
        """assertRaisesMessage shouldn't interpret RE special chars."""
        def func1():
            raise ValueError("[.*x+]y?")
        self.assertRaisesMessage(ValueError, "[.*x+]y?", func1)


class AssertFieldOutputTests(SimpleTestCase):

    def test_assert_field_output(self):
        error_invalid = [u'Enter a valid e-mail address.']
        self.assertFieldOutput(EmailField, {'a@a.com': 'a@a.com'}, {'aaa': error_invalid})
        self.assertRaises(AssertionError, self.assertFieldOutput, EmailField, {'a@a.com': 'a@a.com'}, {'aaa': error_invalid + [u'Another error']})
        self.assertRaises(AssertionError, self.assertFieldOutput, EmailField, {'a@a.com': 'Wrong output'}, {'aaa': error_invalid})
        self.assertRaises(AssertionError, self.assertFieldOutput, EmailField, {'a@a.com': 'a@a.com'}, {'aaa': [u'Come on, gimme some well formatted data, dude.']})


__test__ = {"API_TEST": r"""
# Some checks of the doctest output normalizer.
# Standard doctests do fairly
>>> from django.utils import simplejson
>>> from django.utils.xmlutils import SimplerXMLGenerator
>>> from StringIO import StringIO

>>> def produce_long():
...     return 42L

>>> def produce_int():
...     return 42

>>> def produce_json():
...     return simplejson.dumps(['foo', {'bar': ('baz', None, 1.0, 2), 'whiz': 42}])

>>> def produce_xml():
...     stream = StringIO()
...     xml = SimplerXMLGenerator(stream, encoding='utf-8')
...     xml.startDocument()
...     xml.startElement("foo", {"aaa" : "1.0", "bbb": "2.0"})
...     xml.startElement("bar", {"ccc" : "3.0"})
...     xml.characters("Hello")
...     xml.endElement("bar")
...     xml.startElement("whiz", {})
...     xml.characters("Goodbye")
...     xml.endElement("whiz")
...     xml.endElement("foo")
...     xml.endDocument()
...     return stream.getvalue()

>>> def produce_xml_fragment():
...     stream = StringIO()
...     xml = SimplerXMLGenerator(stream, encoding='utf-8')
...     xml.startElement("foo", {"aaa": "1.0", "bbb": "2.0"})
...     xml.characters("Hello")
...     xml.endElement("foo")
...     xml.startElement("bar", {"ccc": "3.0", "ddd": "4.0"})
...     xml.endElement("bar")
...     return stream.getvalue()

# Long values are normalized and are comparable to normal integers ...
>>> produce_long()
42

# ... and vice versa
>>> produce_int()
42L

# JSON output is normalized for field order, so it doesn't matter
# which order json dictionary attributes are listed in output
>>> produce_json()
'["foo", {"bar": ["baz", null, 1.0, 2], "whiz": 42}]'

>>> produce_json()
'["foo", {"whiz": 42, "bar": ["baz", null, 1.0, 2]}]'

# XML output is normalized for attribute order, so it doesn't matter
# which order XML element attributes are listed in output
>>> produce_xml()
'<?xml version="1.0" encoding="UTF-8"?>\n<foo aaa="1.0" bbb="2.0"><bar ccc="3.0">Hello</bar><whiz>Goodbye</whiz></foo>'

>>> produce_xml()
'<?xml version="1.0" encoding="UTF-8"?>\n<foo bbb="2.0" aaa="1.0"><bar ccc="3.0">Hello</bar><whiz>Goodbye</whiz></foo>'

>>> produce_xml_fragment()
'<foo aaa="1.0" bbb="2.0">Hello</foo><bar ccc="3.0" ddd="4.0"></bar>'

>>> produce_xml_fragment()
'<foo bbb="2.0" aaa="1.0">Hello</foo><bar ddd="4.0" ccc="3.0"></bar>'

"""}
