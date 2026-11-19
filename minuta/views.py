import json
import re
import time as time_mod
import urllib.request
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction

from .models import (
    ConfiguracionServicio,
    ConfiguracionGeneral,
    MinutaDia,
    MinutaServicio,
    ItemMinuta,
    RegistroAuditoria
)

DIAS_SEMANA = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
MESES = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'
]

def formatear_fecha_espanol(d):
    """Devuelve fecha en formato: 'martes, 27 de octubre de 2026'"""
    dia_sem = DIAS_SEMANA[d.weekday()]
    mes = MESES[d.month - 1]
    return f"{dia_sem}, {d.day} de {mes} de {d.year}"

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')

def obtener_estado_servicio(fecha_actual=None, hora_actual=None):
    """
    Determina qué servicio mostrar según la hora en Chile.
    Reglas:
    - Desayuno: 05:00 a 10:00 (vigente)
    - 10:00 a 12:00: Almuerzo (próximo)
    - Almuerzo: 12:00 a 14:30 (vigente)
    - 14:30 a 16:30: Cena (próximo)
    - Cena: 16:30 a 22:00 (vigente)
    - 22:00 a 05:00: Desayuno del día siguiente (o de hoy si hora < 05:00) (próximo)
    """
    cfg_gen = ConfiguracionGeneral.get_solo()
    tz = ZoneInfo(cfg_gen.zona_horaria)

    if fecha_actual is None or hora_actual is None:
        ahora = datetime.now(tz)
        f_actual = ahora.date()
        h_actual = ahora.time()
    else:
        f_actual = fecha_actual
        h_actual = hora_actual

    servicios = list(ConfiguracionServicio.objects.all().order_by('orden'))
    # Mapear por código
    s_map = {s.codigo: s for s in servicios}
    desayuno = s_map.get('desayuno')
    almuerzo = s_map.get('almuerzo')
    cena = s_map.get('cena')

    d_inicio = desayuno.desde if desayuno else time(5, 0)
    d_fin = desayuno.hasta if desayuno else time(10, 0)
    a_inicio = almuerzo.desde if almuerzo else time(12, 0)
    a_fin = almuerzo.hasta if almuerzo else time(14, 30)
    c_inicio = cena.desde if cena else time(16, 30)
    c_fin = cena.hasta if cena else time(22, 0)

    servicio_codigo = 'almuerzo'
    fecha_servicio = f_actual
    es_proximo = False

    if d_inicio <= h_actual < d_fin:
        servicio_codigo = 'desayuno'
        fecha_servicio = f_actual
        es_proximo = False
    elif d_fin <= h_actual < a_inicio:
        servicio_codigo = 'almuerzo'
        fecha_servicio = f_actual
        es_proximo = True
    elif a_inicio <= h_actual < a_fin:
        servicio_codigo = 'almuerzo'
        fecha_servicio = f_actual
        es_proximo = False
    elif a_fin <= h_actual < c_inicio:
        servicio_codigo = 'cena'
        fecha_servicio = f_actual
        es_proximo = True
    elif c_inicio <= h_actual < c_fin:
        servicio_codigo = 'cena'
        fecha_servicio = f_actual
        es_proximo = False
    elif h_actual >= c_fin:
        servicio_codigo = 'desayuno'
        fecha_servicio = f_actual + timedelta(days=1)
        es_proximo = True
    else:  # h_actual < d_inicio (entre medianoche y 05:00)
        servicio_codigo = 'desayuno'
        fecha_servicio = f_actual
        es_proximo = True

    return {
        'servicio_codigo': servicio_codigo,
        'fecha_servicio': fecha_servicio,
        'es_proximo': es_proximo,
        'fecha_actual': f_actual,
        'hora_actual': h_actual.strftime('%H:%M:%S')
    }


def index_tv(request):
    """Vista principal para la pantalla TV en TV Bro / Google TV"""
    cfg_gen = ConfiguracionGeneral.get_solo()
    servicios = ConfiguracionServicio.objects.all().order_by('orden')
    clima = obtener_datos_clima_calama()
    return render(request, 'tv/index.html', {
        'cfg': cfg_gen,
        'servicios': servicios,
        'clima': clima,
    })


# ------------------ CLIMA CALAMA ------------------
_CLIMA_CACHE = {
    'timestamp': 0,
    'data': None
}

def obtener_datos_clima_calama():
    """
    Consulta la API gratuita de Open-Meteo para Calama, Chile (-22.4544, -68.9294)
    con caché de 15 minutos (900 seg) y fallback inteligente según la hora en Chile.
    """
    now_ts = time_mod.time()
    if _CLIMA_CACHE['data'] and (now_ts - _CLIMA_CACHE['timestamp'] < 900):
        return _CLIMA_CACHE['data']

    cfg_gen = ConfiguracionGeneral.get_solo()
    tz = ZoneInfo(cfg_gen.zona_horaria)
    ahora = datetime.now(tz)
    hora = ahora.hour
    minuto = ahora.minute

    # Coordenadas oficiales de Calama, Región de Antofagasta, Chile
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        "latitude=-22.4544&longitude=-68.9294&"
        "current=temperature_2m,is_day,weather_code&"
        "timezone=America%2FSantiago"
    )

    temp = None
    is_day = None
    weather_code = 0

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MinutaCasinoCoalfa/1.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            payload = json.loads(response.read().decode('utf-8'))
            curr = payload.get('current', {})
            temp = curr.get('temperature_2m')
            is_day = curr.get('is_day')
            weather_code = curr.get('weather_code', 0)
    except Exception:
        pass

    # Si is_day no vino de la API, inferir según hora local en Calama
    if is_day is None:
        is_day = 1 if (6 <= hora < 20 or (hora == 20 and minuto < 15)) else 0

    # Estimación de temperatura si la API externa no respondió
    if temp is None:
        if 12 <= hora < 17:
            temp = 25.0
        elif 17 <= hora < 20:
            temp = 20.5
        elif 20 <= hora or hora < 7:
            temp = 12.0
        else:
            temp = 17.0

    # Determinar si es momento de 'tarde' / 'atardecer' (luz dorada del desierto, 17:30 a 20:15)
    es_tarde = (is_day == 1 and (hora == 17 and minuto >= 30 or 18 <= hora < 20 or (hora == 20 and minuto <= 15)))

    # Interpretar código meteorológico WMO (World Meteorological Organization)
    if is_day == 0:
        momento = 'noche'
        if weather_code in [0, 1]:
            icono = '🌙'
            descripcion = 'Noche despejada'
            tipo = 'noche_despejada'
        elif weather_code == 2:
            icono = '☁️'
            descripcion = 'Noche con nubes'
            tipo = 'noche_parcial'
        elif weather_code == 3:
            icono = '☁️'
            descripcion = 'Nublado'
            tipo = 'nublado'
        elif weather_code in [45, 48]:
            icono = '🌫️'
            descripcion = 'Neblina nocturna'
            tipo = 'neblina'
        elif weather_code >= 51:
            icono = '🌧️'
            descripcion = 'Lluvia'
            tipo = 'lluvia'
        else:
            icono = '🌙'
            descripcion = 'Noche despejada'
            tipo = 'noche_despejada'
    elif es_tarde:
        momento = 'tarde'
        if weather_code in [0, 1]:
            icono = '🌇'
            descripcion = 'Atardecer despejado'
            tipo = 'tarde_sol'
        elif weather_code == 2:
            icono = '⛅'
            descripcion = 'Tarde parcialmente nublada'
            tipo = 'tarde_parcial'
        elif weather_code == 3:
            icono = '☁️'
            descripcion = 'Tarde nublada'
            tipo = 'nublado'
        elif weather_code in [45, 48]:
            icono = '🌫️'
            descripcion = 'Neblina'
            tipo = 'neblina'
        elif weather_code >= 51:
            icono = '🌧️'
            descripcion = 'Lluvia'
            tipo = 'lluvia'
        else:
            icono = '🌇'
            descripcion = 'Atardecer'
            tipo = 'tarde_sol'
    else:
        momento = 'dia'
        if weather_code == 0:
            icono = '☀️'
            descripcion = 'Soleado'
            tipo = 'sol'
        elif weather_code in [1, 2]:
            icono = '🌤️'
            descripcion = 'Parcialmente nublado'
            tipo = 'sol_nubes'
        elif weather_code == 3:
            icono = '☁️'
            descripcion = 'Nublado'
            tipo = 'nublado'
        elif weather_code in [45, 48]:
            icono = '🌫️'
            descripcion = 'Neblina'
            tipo = 'neblina'
        elif weather_code >= 51:
            icono = '🌧️'
            descripcion = 'Lluvia'
            tipo = 'lluvia'
        else:
            icono = '☀️'
            descripcion = 'Soleado'
            tipo = 'sol'

    temp_round = int(temp + 0.5) if temp is not None else 25
    data_clima = {
        'status': 'ok',
        'ciudad': 'Calama',
        'temperatura': round(temp, 1),
        'temperatura_int': temp_round,
        'temperatura_texto': f"{temp_round}°C",
        'is_day': is_day,
        'momento': momento,
        'tipo': tipo,
        'icono': icono,
        'descripcion': descripcion,
        'hora': ahora.strftime('%H:%M')
    }

    _CLIMA_CACHE['timestamp'] = now_ts
    _CLIMA_CACHE['data'] = data_clima
    return data_clima


def api_clima(request):
    """Endpoint JSON público para el clima de Calama"""
    data = obtener_datos_clima_calama()
    res = JsonResponse(data)
    res['Access-Control-Allow-Origin'] = '*'
    res['Cache-Control'] = 'public, max-age=600'
    return res


def api_tv_data(request):
    """Endpoint JSON consumido por la TV periódicamente y para renderizado dinámico"""
    cfg_gen = ConfiguracionGeneral.get_solo()
    tz = ZoneInfo(cfg_gen.zona_horaria)

    # Permitir simulación vía query param ?sim=2026-10-27T12:30
    sim_str = request.GET.get('sim')
    fecha_sim = None
    hora_sim = None
    if sim_str:
        try:
            dt_sim = datetime.fromisoformat(sim_str)
            fecha_sim = dt_sim.date()
            hora_sim = dt_sim.time()
        except ValueError:
            pass

    info_est = obtener_estado_servicio(fecha_sim, hora_sim)
    s_cod = info_est['servicio_codigo']
    fecha_serv = info_est['fecha_servicio']
    es_proximo = info_est['es_proximo']

    serv_cfg = ConfiguracionServicio.objects.filter(codigo=s_cod).first()
    nombre_servicio = serv_cfg.nombre if serv_cfg else s_cod.upper()
    # Forzar la paleta oficial de Almuerzo (#0B3FA8) para todos los servicios
    color_franja = "#0B3FA8"
    horario_texto = f"{serv_cfg.desde.strftime('%H:%M')} a {serv_cfg.hasta.strftime('%H:%M')} hrs" if serv_cfg else ""

    # Buscar minuta para la fecha
    minuta_dia = MinutaDia.objects.filter(fecha=fecha_serv).first()
    items_col1 = []
    items_col2 = []
    hay_minuta = False
    colacion = ""

    if minuta_dia:
        colacion = minuta_dia.colacion
        min_serv = minuta_dia.servicios.filter(servicio_codigo=s_cod).first()
        if min_serv:
            items_qs = min_serv.items.all().order_by('columna', 'orden', 'id')
            if items_qs.exists():
                hay_minuta = True
                for it in items_qs:
                    item_dict = {
                        'categoria': it.categoria,
                        'texto': it.texto,
                        'cantidad': it.cantidad
                    }
                    if it.columna == 1:
                        items_col1.append(item_dict)
                    else:
                        items_col2.append(item_dict)

    # Si por alguna razón una columna quedó vacía y hay ítems, balancear
    total_items = items_col1 + items_col2
    if hay_minuta and (not items_col1 or not items_col2) and len(total_items) > 1:
        mitad = (len(total_items) + 1) // 2
        items_col1 = total_items[:mitad]
        items_col2 = total_items[mitad:]

    # Horarios para Vista B: todos usan la paleta de Almuerzo (#0B3FA8)
    servicios_list = []
    for s in ConfiguracionServicio.objects.all().order_by('orden'):
        es_activo = (s.codigo == s_cod)
        servicios_list.append({
            'codigo': s.codigo,
            'nombre': s.nombre,
            'desde': s.desde.strftime('%H:%M'),
            'hasta': s.hasta.strftime('%H:%M'),
            'color': '#0B3FA8',
            'es_activo': es_activo
        })

    # Logos
    logo_promet_url = cfg_gen.logo_promet.url if cfg_gen.logo_promet else "/static/img/logo_promet.svg"
    logo_coalfa_url = cfg_gen.logo_coalfa.url if cfg_gen.logo_coalfa else "/static/img/logo_coalfa.svg"

    data = {
        'status': 'ok',
        'hora_actual': info_est['hora_actual'],
        'fecha_actual': info_est['fecha_actual'].isoformat(),
        'fecha_servicio': fecha_serv.isoformat(),
        'fecha_texto': formatear_fecha_espanol(fecha_serv),
        'servicio_codigo': s_cod,
        'nombre_servicio': nombre_servicio,
        'es_proximo': es_proximo,
        'color_franja': color_franja,
        'horario_texto': horario_texto,
        'hay_minuta': hay_minuta,
        'colacion': colacion,
        'items_col1': items_col1,
        'items_col2': items_col2,
        'horarios_servicios': servicios_list,
        'intervalo_rotacion': cfg_gen.intervalo_rotacion_segundos,
        'tiempo_minuta': getattr(cfg_gen, 'tiempo_minuta_segundos', 25),
        'tiempo_horarios': getattr(cfg_gen, 'tiempo_horarios_segundos', 8),
        'tiempo_qr': getattr(cfg_gen, 'tiempo_qr_segundos', 8),
        'pie_pagina': cfg_gen.pie_pagina,
        'recarga_minutos': cfg_gen.recarga_minutos,
        'logo_promet': logo_promet_url,
        'logo_coalfa': logo_coalfa_url,
        'clima': obtener_datos_clima_calama(),
    }
    response = JsonResponse(data)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response


# ------------------ PRÓXIMOS DÍAS ------------------

def proximos_dias(request):
    """Página pública con la minuta de los próximos 7 días — accesible por QR."""
    return render(request, 'tv/proximos_dias.html', {
        'clima': obtener_datos_clima_calama(),
    })


def api_proximos_dias(request):
    """API JSON que devuelve los menús de los próximos 7 días a partir de hoy."""
    cfg_gen = ConfiguracionGeneral.get_solo()
    tz = ZoneInfo(cfg_gen.zona_horaria)
    hoy = datetime.now(tz).date()

    dias_data = []
    for offset in range(0, 8):
        fecha = hoy + timedelta(days=offset)
        minuta_dia = MinutaDia.objects.filter(fecha=fecha).first()
        servicios_dia = []

        for s_cfg in ConfiguracionServicio.objects.all().order_by('orden'):
            if minuta_dia:
                min_serv = minuta_dia.servicios.filter(servicio_codigo=s_cfg.codigo).first()
                items = []
                if min_serv:
                    for it in min_serv.items.all().order_by('columna', 'orden', 'id'):
                        items.append({
                            'categoria': it.categoria,
                            'texto': it.texto,
                        })
            else:
                items = []

            servicios_dia.append({
                'codigo': s_cfg.codigo,
                'nombre': s_cfg.nombre,
                'desde': s_cfg.desde.strftime('%H:%M'),
                'hasta': s_cfg.hasta.strftime('%H:%M'),
                'items': items,
                'hay_minuta': len(items) > 0,
            })

        dias_data.append({
            'fecha': fecha.isoformat(),
            'fecha_texto': formatear_fecha_espanol(fecha),
            'dia_semana': DIAS_SEMANA[fecha.weekday()].capitalize(),
            'dia_num': fecha.day,
            'mes': MESES[fecha.month - 1].capitalize(),
            'es_hoy': offset == 0,
            'colacion': minuta_dia.colacion if minuta_dia else '',
            'servicios': servicios_dia,
        })

    data = {
        'status': 'ok',
        'dias': dias_data,
        'generado_a': datetime.now(tz).strftime('%H:%M'),
        'pie_pagina': cfg_gen.pie_pagina,
        'clima': obtener_datos_clima_calama(),
    }
    response = JsonResponse(data)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    return response


# ------------------ PANEL DE ADMINISTRACIÓN ------------------

def login_view(request):
    if request.user.is_authenticated:
        return redirect('admin_panel')
    error = None
    if request.method == 'POST':
        u = request.POST.get('username', '').strip()
        p = request.POST.get('password', '').strip()
        user = authenticate(request, username=u, password=p)
        if user is not None:
            login(request, user)
            RegistroAuditoria.objects.create(
                usuario=user,
                nombre_usuario=user.username,
                accion='CONFIGURACION',
                resumen=f"Inicio de sesión exitoso de {user.username}",
                ip=get_client_ip(request)
            )
            return redirect('admin_panel')
        else:
            error = "Usuario o contraseña incorrectos."

    return render(request, 'admin/login.html', {
        'error': error,
        'clima': obtener_datos_clima_calama(),
    })


@csrf_exempt
def api_actualizar_tiempos(request):
    """
    Endpoint AJAX para actualizar los tiempos de rotación desde el login o panel.
    Requiere que el usuario esté logueado o provea la clave de administrador.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'mensaje': 'Método no permitido'}, status=405)

    if request.content_type == 'application/json':
        try:
            body = json.loads(request.body.decode('utf-8'))
        except Exception:
            body = {}
    else:
        body = request.POST

    password = body.get('password', '').strip()
    user_auth = request.user.is_authenticated

    if not user_auth:
        u = authenticate(request, username='admin', password=password)
        if not u:
            uname = body.get('username', 'admin').strip()
            u = authenticate(request, username=uname, password=password)
        if not u:
            return JsonResponse({'status': 'error', 'mensaje': 'Contraseña de administrador incorrecta'}, status=403)
        user_obj = u
    else:
        user_obj = request.user

    cfg_gen = ConfiguracionGeneral.get_solo()
    t_minuta = body.get('tiempo_minuta')
    t_horarios = body.get('tiempo_horarios')
    t_qr = body.get('tiempo_qr')

    if t_minuta:
        cfg_gen.tiempo_minuta_segundos = max(5, int(t_minuta))
    if t_horarios:
        cfg_gen.tiempo_horarios_segundos = max(3, int(t_horarios))
    if t_qr:
        cfg_gen.tiempo_qr_segundos = max(3, int(t_qr))

    cfg_gen.save()

    RegistroAuditoria.objects.create(
        usuario=user_obj,
        nombre_usuario=user_obj.username,
        accion='CONFIGURACION',
        resumen="Actualizó tiempos de visualización de la TV vía API",
        detalles=f"Minuta: {cfg_gen.tiempo_minuta_segundos}s | Horarios: {cfg_gen.tiempo_horarios_segundos}s | QR: {cfg_gen.tiempo_qr_segundos}s",
        ip=get_client_ip(request)
    )

    return JsonResponse({
        'status': 'ok',
        'mensaje': 'Tiempos de TV actualizados exitosamente',
        'tiempo_minuta': cfg_gen.tiempo_minuta_segundos,
        'tiempo_horarios': cfg_gen.tiempo_horarios_segundos,
        'tiempo_qr': cfg_gen.tiempo_qr_segundos,
    })


def logout_view(request):
    if request.user.is_authenticated:
        RegistroAuditoria.objects.create(
            usuario=request.user,
            nombre_usuario=request.user.username,
            accion='CONFIGURACION',
            resumen=f"Cierre de sesión de {request.user.username}",
            ip=get_client_ip(request)
        )
    logout(request)
    return redirect('login')


@login_required
def admin_panel(request):
    """Panel central de control y gestión de minuta"""
    cfg_gen = ConfiguracionGeneral.get_solo()
    tz = ZoneInfo(cfg_gen.zona_horaria)
    ahora_chile = datetime.now(tz)
    servicios = ConfiguracionServicio.objects.all().order_by('orden')

    # Fecha seleccionada para editar (por defecto fecha actual en Chile)
    fecha_str = request.GET.get('fecha')
    if fecha_str:
        try:
            fecha_sel = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            fecha_sel = ahora_chile.date()
    else:
        fecha_sel = ahora_chile.date()

    # Servicio seleccionado: por defecto el que esté activo en este momento según la hora
    info_actual = obtener_estado_servicio()
    servicio_sel = request.GET.get('servicio', info_actual['servicio_codigo'])

    # Minuta para el día y servicio
    minuta_dia, _ = MinutaDia.objects.get_or_create(fecha=fecha_sel)
    minuta_serv, _ = MinutaServicio.objects.get_or_create(dia=minuta_dia, servicio_codigo=servicio_sel)
    items = minuta_serv.items.all().order_by('columna', 'orden', 'id')

    # Últimos registros de auditoría
    auditorias = RegistroAuditoria.objects.all()[:50]

    return render(request, 'admin/panel.html', {
        'cfg': cfg_gen,
        'servicios': servicios,
        'fecha_sel': fecha_sel.isoformat(),
        'fecha_sel_texto': formatear_fecha_espanol(fecha_sel),
        'servicio_sel': servicio_sel,
        'minuta_dia': minuta_dia,
        'items': items,
        'auditorias': auditorias,
        'total_dias_cargados': MinutaDia.objects.count(),
        'clima': obtener_datos_clima_calama(),
    })


@login_required
def guardar_item(request):
    """Crear o editar un ítem de minuta"""
    if request.method == 'POST':
        fecha_str = request.POST.get('fecha')
        servicio_codigo = request.POST.get('servicio')
        item_id = request.POST.get('item_id')
        categoria = request.POST.get('categoria', '').strip()
        texto = request.POST.get('texto', '').strip()
        columna = int(request.POST.get('columna', 1))
        orden = int(request.POST.get('orden', 0))
        cantidad_str = request.POST.get('cantidad', '').strip()
        cantidad = int(cantidad_str) if cantidad_str.isdigit() else None

        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        minuta_dia, _ = MinutaDia.objects.get_or_create(fecha=fecha)
        minuta_serv, _ = MinutaServicio.objects.get_or_create(dia=minuta_dia, servicio_codigo=servicio_codigo)

        if item_id:
            item = get_object_or_404(ItemMinuta, id=item_id, servicio=minuta_serv)
            item.categoria = categoria
            item.texto = texto
            item.columna = columna
            item.orden = orden
            item.cantidad = cantidad
            item.save()
            accion_tipo = 'MODIFICACION'
            resumen = f"Editó ítem '{categoria}' en {servicio_codigo.upper()} del {fecha_str}"
        else:
            item = ItemMinuta.objects.create(
                servicio=minuta_serv,
                categoria=categoria,
                texto=texto,
                columna=columna,
                orden=orden,
                cantidad=cantidad
            )
            accion_tipo = 'CREACION'
            resumen = f"Agregó ítem '{categoria}' a {servicio_codigo.upper()} del {fecha_str}"

        RegistroAuditoria.objects.create(
            usuario=request.user,
            nombre_usuario=request.user.username,
            accion=accion_tipo,
            resumen=resumen,
            detalles=f"Plato: {texto} | Columna: {columna} | Cantidad: {cantidad}",
            ip=get_client_ip(request)
        )

        return redirect(f"/panel/?fecha={fecha_str}&servicio={servicio_codigo}")
    return redirect('admin_panel')


@login_required
def eliminar_item(request, item_id):
    """Eliminar un ítem de minuta"""
    item = get_object_or_404(ItemMinuta, id=item_id)
    fecha_str = item.servicio.dia.fecha.isoformat()
    servicio_codigo = item.servicio.servicio_codigo
    cat = item.categoria
    txt = item.texto

    item.delete()

    RegistroAuditoria.objects.create(
        usuario=request.user,
        nombre_usuario=request.user.username,
        accion='ELIMINACION',
        resumen=f"Eliminó ítem '{cat}' de {servicio_codigo.upper()} del {fecha_str}",
        detalles=f"Plato eliminado: {txt}",
        ip=get_client_ip(request)
    )

    return redirect(f"/panel/?fecha={fecha_str}&servicio={servicio_codigo}")


@login_required
def guardar_colacion(request):
    """Actualiza la colación del día"""
    if request.method == 'POST':
        fecha_str = request.POST.get('fecha')
        colacion = request.POST.get('colacion', '').strip()
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        minuta_dia, _ = MinutaDia.objects.get_or_create(fecha=fecha)
        minuta_dia.colacion = colacion
        minuta_dia.save()

        RegistroAuditoria.objects.create(
            usuario=request.user,
            nombre_usuario=request.user.username,
            accion='MODIFICACION',
            resumen=f"Actualizó colación del {fecha_str}",
            detalles=f"Colación: {colacion}",
            ip=get_client_ip(request)
        )
        return redirect(f"/panel/?fecha={fecha_str}")
    return redirect('admin_panel')


@login_required
def actualizar_configuracion(request):
    """Actualiza horarios de servicios, colores, logos y pie de página"""
    if request.method == 'POST':
        cfg_gen = ConfiguracionGeneral.get_solo()
        cfg_gen.pie_pagina = request.POST.get('pie_pagina', cfg_gen.pie_pagina).strip()
        cfg_gen.intervalo_rotacion_segundos = int(request.POST.get('intervalo_rotacion', 10))
        cfg_gen.recarga_minutos = int(request.POST.get('recarga_minutos', 30))
        if request.POST.get('tiempo_minuta'):
            cfg_gen.tiempo_minuta_segundos = max(5, int(request.POST.get('tiempo_minuta')))
        if request.POST.get('tiempo_horarios'):
            cfg_gen.tiempo_horarios_segundos = max(3, int(request.POST.get('tiempo_horarios')))
        if request.POST.get('tiempo_qr'):
            cfg_gen.tiempo_qr_segundos = max(3, int(request.POST.get('tiempo_qr')))

        if 'logo_promet' in request.FILES:
            cfg_gen.logo_promet = request.FILES['logo_promet']
        if 'logo_coalfa' in request.FILES:
            cfg_gen.logo_coalfa = request.FILES['logo_coalfa']

        cfg_gen.save()

        # Actualizar cada servicio
        cambios_servicios = []
        for s in ConfiguracionServicio.objects.all():
            desde_str = request.POST.get(f"desde_{s.codigo}")
            hasta_str = request.POST.get(f"hasta_{s.codigo}")
            color = request.POST.get(f"color_{s.codigo}")

            if desde_str:
                s.desde = datetime.strptime(desde_str, "%H:%M").time()
            if hasta_str:
                s.hasta = datetime.strptime(hasta_str, "%H:%M").time()
            if color:
                s.color_franja = color
            s.save()
            cambios_servicios.append(f"{s.nombre}: {s.desde.strftime('%H:%M')}-{s.hasta.strftime('%H:%M')} ({s.color_franja})")

        RegistroAuditoria.objects.create(
            usuario=request.user,
            nombre_usuario=request.user.username,
            accion='CONFIGURACION',
            resumen="Modificó configuración general y horarios de servicios",
            detalles=", ".join(cambios_servicios),
            ip=get_client_ip(request)
        )

        return redirect('/panel/?tab=config')
    return redirect('admin_panel')


@login_required
def importar_minuta_masiva(request):
    """Permite pegar JSON o subir Excel/CSV con la minuta del mes completo"""
    if request.method == 'POST':
        json_texto = request.POST.get('json_data', '').strip()
        archivo = request.FILES.get('archivo_minuta')
        dias_importados = 0
        error_msg = None

        col2_categories = {
            "HIPOCALÓRICO", "HIPOCALORICO", "ENSALADAS", "ENSALADA", "POSTRES", "POSTRE", "PORRIDGE", "MEJORADO"
        }

        try:
            data = None
            if archivo:
                nombre_arch = archivo.name.lower()
                if nombre_arch.endswith('.json'):
                    data = json.load(archivo)
                elif nombre_arch.endswith(('.xlsx', '.xls')):
                    import openpyxl
                    wb = openpyxl.load_workbook(archivo, data_only=True)
                    data = procesar_excel_minuta(wb)
                else:
                    error_msg = "Formato no soportado. Suba archivo .xlsx o .json"
            elif json_texto:
                data = json.loads(json_texto)

            if data and 'dias' in data and data['dias']:
                with transaction.atomic():
                    for fecha_str, serv_dict in data['dias'].items():
                        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
                        colacion = serv_dict.get('colacion', '')
                        minuta_dia, _ = MinutaDia.objects.update_or_create(
                            fecha=fecha,
                            defaults={'colacion': colacion}
                        )

                        for s_cod in ['desayuno', 'almuerzo', 'cena']:
                            if s_cod in serv_dict:
                                s_info = serv_dict[s_cod]
                                items = s_info.get('items', [])
                                minuta_serv, _ = MinutaServicio.objects.update_or_create(
                                    dia=minuta_dia,
                                    servicio_codigo=s_cod
                                )
                                minuta_serv.items.all().delete()

                                mitad = (len(items) + 1) // 2
                                for idx, it in enumerate(items):
                                    cat = it.get('categoria', '').strip()
                                    txt = it.get('texto', '').strip()
                                    cant = it.get('cantidad')
                                    columna = 2 if (cat.upper().strip() in col2_categories or idx >= mitad) else 1

                                    ItemMinuta.objects.create(
                                        servicio=minuta_serv,
                                        categoria=cat,
                                        texto=txt,
                                        cantidad=cant,
                                        orden=idx,
                                        columna=columna
                                    )
                        dias_importados += 1

                RegistroAuditoria.objects.create(
                    usuario=request.user,
                    nombre_usuario=request.user.username,
                    accion='IMPORTACION',
                    resumen=f"Importación masiva exitosa: {dias_importados} días",
                    detalles=f"Fuente: {'Archivo ' + archivo.name if archivo else 'Texto JSON'}",
                    ip=get_client_ip(request)
                )
            elif not error_msg:
                error_msg = "No se detectaron días válidos en el archivo o texto. Verifique que las hojas o fechas sean correctas."

        except Exception as e:
            error_msg = f"Error al procesar la importación: {str(e)}"

        request.session['import_error'] = error_msg
        request.session['import_success'] = f"Se importaron exitosamente {dias_importados} días." if not error_msg else None
        return redirect('/panel/?tab=importar')

    return redirect('admin_panel')


def extraer_fecha_celda(val):
    """Extrae una fecha en formato YYYY-MM-DD desde un valor datetime, date o string de celda."""
    if not val:
        return None
    if isinstance(val, (datetime, date)):
        return val.strftime('%Y-%m-%d')
    s = str(val).strip()
    m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', s)
    if m:
        return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    m = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})', s)
    if m:
        y = int(m.group(3))
        if y < 100:
            y += 2000
        return f'{y:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
    return None


def limpiar_texto_celda(val):
    """Limpia textos vacíos, guiones o None de celdas."""
    if val is None:
        return ''
    s = str(val).strip()
    if s.startswith('---') or s == '-' or s.lower() == 'none':
        return ''
    return s


def procesar_excel_minuta(wb_or_ws):
    """
    Convierte un archivo Excel en la estructura JSON requerida.
    Soporta:
    1. Formato oficial con pestañas SEMANA, Desayuno Mej., Colaciones.
    2. Formato tabular plano (hoja con columnas fecha, servicio, categoria, plato, etc.)
    """
    # Si es un workbook con hojas
    if hasattr(wb_or_ws, 'sheetnames'):
        sheet_names = wb_or_ws.sheetnames
        # Si tiene hojas SEMANA, procesar con lógica multi-hoja de casino
        has_semana = any('SEMANA' in s.upper() for s in sheet_names)
        if has_semana:
            dias = {}

            def get_dia(f_str):
                if f_str not in dias:
                    dias[f_str] = {
                        'colacion': '',
                        'desayuno': {'items': []},
                        'almuerzo': {'items': []},
                        'cena': {'items': []}
                    }
                return dias[f_str]

            for sname in sheet_names:
                if 'SEMANA' in sname.upper():
                    ws = wb_or_ws[sname]
                    servicio_actual = None
                    date_cols = {}

                    for r in range(1, ws.max_row + 1):
                        c1_val = str(ws.cell(r, 1).value or '').strip()
                        row_str = ' '.join([str(ws.cell(r, c).value or '') for c in range(1, ws.max_column + 1)]).upper()

                        if 'DESAYUNO' in row_str and ('HOSTAL' in row_str or 'CALAMA' in row_str or r <= 3):
                            servicio_actual = 'desayuno'
                            date_cols = {}
                            continue
                        elif 'ALMUERZO' in row_str and ('HOSTAL' in row_str or 'CALAMA' in row_str or (10 <= r <= 15)):
                            servicio_actual = 'almuerzo'
                            date_cols = {}
                            continue
                        elif 'CENA' in row_str and ('HOSTAL' in row_str or 'CALAMA' in row_str or (25 <= r <= 32)):
                            servicio_actual = 'cena'
                            date_cols = {}
                            continue

                        fechas_en_fila = {}
                        for c in range(2, ws.max_column + 1):
                            f = extraer_fecha_celda(ws.cell(r, c).value)
                            if f:
                                fechas_en_fila[c] = f

                        if fechas_en_fila:
                            date_cols = fechas_en_fila
                            continue

                        if servicio_actual and date_cols and c1_val:
                            cat = c1_val
                            for col_idx, f_str in date_cols.items():
                                dia_obj = get_dia(f_str)
                                plato = limpiar_texto_celda(ws.cell(r, col_idx).value)
                                if not plato:
                                    continue

                                cant = None
                                if (col_idx + 1) not in date_cols:
                                    cant_val = ws.cell(r, col_idx + 1).value
                                    if cant_val is not None:
                                        try:
                                            cant = int(float(str(cant_val).strip()))
                                        except (ValueError, TypeError):
                                            cant = None

                                it = {'categoria': cat, 'texto': plato}
                                if cant is not None:
                                    it['cantidad'] = cant
                                dia_obj[servicio_actual]['items'].append(it)

            # Desayuno Mejorado
            for sname in sheet_names:
                if 'MEJ' in sname.upper():
                    ws = wb_or_ws[sname]
                    for r in range(1, ws.max_row):
                        for c in range(1, ws.max_column + 1):
                            f = extraer_fecha_celda(ws.cell(r, c).value)
                            if f:
                                next_val = limpiar_texto_celda(ws.cell(r + 1, c).value)
                                if next_val and not extraer_fecha_celda(next_val):
                                    dia_obj = get_dia(f)
                                    dia_obj['desayuno']['items'].append({
                                        'categoria': 'MEJORADO',
                                        'texto': next_val
                                    })

            # Colaciones
            for sname in sheet_names:
                if 'COLACION' in sname.upper():
                    ws = wb_or_ws[sname]
                    for r in range(1, ws.max_row):
                        for c in range(1, ws.max_column + 1):
                            f = extraer_fecha_celda(ws.cell(r, c).value)
                            if f:
                                next_val = limpiar_texto_celda(ws.cell(r + 1, c).value)
                                if next_val and not extraer_fecha_celda(next_val):
                                    dia_obj = get_dia(f)
                                    dia_obj['colacion'] = next_val

            if dias:
                return {'dias': dias}

        ws = wb_or_ws.active
    else:
        ws = wb_or_ws

    # Fallback: Procesar formato tabular plano
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {'dias': {}}

    headers = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
    dias = {}

    for row in rows[1:]:
        if not any(row):
            continue
        row_dict = {headers[i]: row[i] for i in range(len(headers)) if i < len(row)}

        fecha_val = row_dict.get('fecha')
        if not fecha_val:
            continue
        f_str = extraer_fecha_celda(fecha_val)
        if not f_str:
            continue

        servicio = str(row_dict.get('servicio', 'almuerzo')).strip().lower()
        categoria = str(row_dict.get('categoria', '')).strip()
        plato = str(row_dict.get('plato', row_dict.get('texto', ''))).strip()
        cantidad = row_dict.get('cantidad')

        if f_str not in dias:
            dias[f_str] = {'colacion': ''}
        if servicio not in dias[f_str]:
            dias[f_str][servicio] = {'items': []}

        if categoria and plato:
            item_obj = {'categoria': categoria, 'texto': plato}
            if cantidad and str(cantidad).isdigit():
                item_obj['cantidad'] = int(cantidad)
            dias[f_str][servicio]['items'].append(item_obj)

    return {'dias': dias}
