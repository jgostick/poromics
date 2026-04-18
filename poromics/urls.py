"""Poromics URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/stable/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import RedirectView
from django.views.i18n import JavaScriptCatalog
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.teams.urls import team_urlpatterns as single_team_urls
from apps.web.sitemaps import StaticViewSitemap
from apps.web.urls import team_urlpatterns as web_team_urls
from apps.pore_analysis.urls import urlpatterns as pore_analysis_urls, team_urlpatterns as pore_analysis_team_urls

sitemaps = {
    "static": StaticViewSitemap(),
}

# urls that are unique to using a team should go here
team_urlpatterns = [
    path("", include(web_team_urls)),
    path("team/", include(single_team_urls)),
    path("pore-analysis/", include(pore_analysis_team_urls)),
]

urlpatterns = [
    # redirect Django admin login to main login page
    path("admin/login/", RedirectView.as_view(pattern_name="account_login")),
    path("admin/", admin.site.urls),
    path("dashboard/", include("apps.dashboard.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"),
    path("a/<slug:team_slug>/", include(team_urlpatterns)),
    path("pore-analysis/", include(pore_analysis_urls)),  # Global pore analysis URLs
    path("accounts/", include("allauth.urls")),
    path("users/", include("apps.users.urls")),
    path("teams/", include("apps.teams.urls")),
    path("", include("apps.web.urls")),
    path("pegasus/", include("pegasus.apps.examples.urls")),
    path("pegasus/employees/", include("pegasus.apps.employees.urls")),
    path("support/", include("apps.support.urls")),
    path("celery-progress/", include("celery_progress.urls")),
    # API docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # Optional UI - you may wish to remove one of these depending on your preference
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # hijack urls for impersonation
    path("hijack/", include("hijack.urls", namespace="hijack")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Add browser reload URL if the middleware is enabled (matches middleware check in settings.py)
if "django_browser_reload.middleware.BrowserReloadMiddleware" in settings.MIDDLEWARE:
    urlpatterns.insert(0, path("__reload__/", include("django_browser_reload.urls")))

if settings.ENABLE_DEBUG_TOOLBAR:
    urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))
