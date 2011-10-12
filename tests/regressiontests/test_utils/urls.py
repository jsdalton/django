from django.conf.urls import patterns

import views


urlpatterns = patterns('',
    (r'^test_utils/get_person/(\d+)/$', views.get_person),
    (r'^test_utils/simple_view/$', views.simple_view),
)
