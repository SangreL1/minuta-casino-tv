from django.urls import path
from . import views

urlpatterns = [
    path('', views.index_tv, name='tv_index'),
    path('api/minuta-tv/', views.api_tv_data, name='api_tv_data'),
    path('proximos-dias/', views.proximos_dias, name='proximos_dias'),
    path('api/proximos-dias/', views.api_proximos_dias, name='api_proximos_dias'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('panel/', views.admin_panel, name='admin_panel'),
    path('panel/guardar-item/', views.guardar_item, name='guardar_item'),
    path('panel/eliminar-item/<int:item_id>/', views.eliminar_item, name='eliminar_item'),
    path('panel/guardar-colacion/', views.guardar_colacion, name='guardar_colacion'),
    path('panel/actualizar-config/', views.actualizar_configuracion, name='actualizar_config'),
    path('panel/importar-masiva/', views.importar_minuta_masiva, name='importar_masiva'),
]
