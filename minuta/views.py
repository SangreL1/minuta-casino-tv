import json
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
    return render(request, 'tv/index.html', {
        'cfg': cfg_gen,
        'servicios': servicios,
    })


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
    color_franja = serv_cfg.color_franja if serv_cfg else "#0B3FA8"
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

    # Horarios para Vista B
    servicios_list = []
    for s in ConfiguracionServicio.objects.all().order_by('orden'):
        es_activo = (s.codigo == s_cod)
        servicios_list.append({
            'codigo': s.codigo,
            'nombre': s.nombre,
            'desde': s.desde.strftime('%H:%M'),
            'hasta': s.hasta.strftime('%H:%M'),
            'color': s.color_franja,
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
        'pie_pagina': cfg_gen.pie_pagina,
        'recarga_minutos': cfg_gen.recarga_minutos,
        'logo_promet': logo_promet_url,
        'logo_coalfa': logo_coalfa_url,
    }
    return JsonResponse(data)


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
    return render(request, 'admin/login.html', {'error': error})


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
    servicios = ConfiguracionServicio.objects.all().order_by('orden')

    # Fecha seleccionada para editar
    fecha_str = request.GET.get('fecha')
    if fecha_str:
        try:
            fecha_sel = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            fecha_sel = date.today()
    else:
        fecha_sel = date.today()

    # Servicio seleccionado
    servicio_sel = request.GET.get('servicio', 'almuerzo')

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
            "HIPOCALÓRICO", "ENSALADAS", "POSTRES", "POSTRE", "PORRIDGE", "MEJORADO"
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
                    # Procesar hoja activa o con nombre 'Minuta'
                    ws = wb.active
                    data = procesar_excel_minuta(ws)
                else:
                    error_msg = "Formato no soportado. Suba archivo .xlsx o .json"
            elif json_texto:
                data = json.loads(json_texto)

            if data and 'dias' in data:
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
                                    columna = 2 if (cat.upper() in col2_categories or idx >= mitad) else 1

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
                error_msg = "El formato no contiene la clave 'dias'. Verifique la estructura JSON."

        except Exception as e:
            error_msg = f"Error al procesar la importación: {str(e)}"

        request.session['import_error'] = error_msg
        request.session['import_success'] = f"Se importaron exitosamente {dias_importados} días." if not error_msg else None
        return redirect('/panel/?tab=importar')

    return redirect('admin_panel')


def procesar_excel_minuta(ws):
    """Convierte filas de una planilla Excel en la estructura JSON requerida"""
    # Mapeo flexible de encabezados
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {'dias': {}}

    headers = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
    dias = {}

    for row in rows[1:]:
        if not any(row):
            continue
        row_dict = {headers[i]: row[i] for i in range(len(headers)) if i < len(row)}

        # Buscar fecha
        fecha_val = row_dict.get('fecha')
        if not fecha_val:
            continue
        if isinstance(fecha_val, datetime):
            f_str = fecha_val.strftime('%Y-%m-%d')
        elif isinstance(fecha_val, date):
            f_str = fecha_val.strftime('%Y-%m-%d')
        else:
            f_str = str(fecha_val).strip()

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
