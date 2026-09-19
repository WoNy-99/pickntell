from django.urls import path
from stories import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('',                     views.home,              name='home'),
    path('create/',              views.generate_story,    name='generate_story'),
    path('create/branch/',       views.branch_story,      name='branch_story'),
    path('create/set_current/',  views.set_current_index, name='set_current_index'),
    path('create/<int:page_idx>/', views.show_page,       name='show_page'),  # ← 추가
    path('api/generate_bgm/',    views.generate_bgm,      name='generate_bgm'),
]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

