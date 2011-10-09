from django.conf.urls import patterns, include

import admin

urlpatterns = patterns('',
    (r'^generic_inline_admin/admin/', include(admin.site.urls)),
)
