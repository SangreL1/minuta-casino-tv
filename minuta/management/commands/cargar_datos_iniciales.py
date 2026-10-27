import json
from pathlib import Path
from datetime import datetime, time
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from minuta.models import (
    ConfiguracionServicio,
    ConfiguracionGeneral,
    MinutaDia,
    MinutaServicio,
    ItemMinuta,
    RegistroAuditoria
)

class Command(BaseCommand):
    help = "Carga la configuración inicial de servicios, usuario administrador y la minuta de Octubre 2026"

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Iniciando carga de datos iniciales..."))

        # 1. Crear o actualizar Servicios
        servicios_data = [
            {
                "codigo": "desayuno",
                "nombre": "DESAYUNO",
                "desde": time(5, 0),
                "hasta": time(10, 0),
                "color_franja": "#0B3FA8",
                "orden": 1
            },
            {
                "codigo": "almuerzo",
                "nombre": "ALMUERZO",
                "desde": time(12, 0),
                "hasta": time(14, 30),
                "color_franja": "#0B3FA8",
                "orden": 2
            },
            {
                "codigo": "cena",
                "nombre": "CENA",
                "desde": time(16, 30),
                "hasta": time(22, 0),
                "color_franja": "#0B3FA8",
                "orden": 3
            },
        ]

        for s in servicios_data:
            obj, created = ConfiguracionServicio.objects.update_or_create(
                codigo=s["codigo"],
                defaults={
                    "nombre": s["nombre"],
                    "desde": s["desde"],
                    "hasta": s["hasta"],
                    "color_franja": s["color_franja"],
                    "orden": s["orden"]
                }
            )
            accion = "creado" if created else "actualizado"
            self.stdout.write(f"Servicio {obj.nombre} {accion}.")

        # 2. Configuración General
        cfg = ConfiguracionGeneral.get_solo()
        cfg.intervalo_rotacion_segundos = 10
        cfg.zona_horaria = "America/Santiago"
        cfg.pie_pagina = "Hotelería Promet · Servicio de alimentación Coalfa"
        cfg.recarga_minutos = 30
        cfg.save()
        self.stdout.write("Configuración general establecida.")

        # 3. Superusuario administrador
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@coalfa.cl", "coalfa2026")
            self.stdout.write(self.style.SUCCESS("Usuario admin creado con clave: coalfa2026"))
        else:
            self.stdout.write("Usuario admin ya existe.")

        # 4. Cargar Minuta Octubre 2026
        json_path = Path(__file__).resolve().parent.parent.parent / "data" / "minuta_octubre_2026.json"
        if not json_path.exists():
            self.stdout.write(self.style.ERROR(f"No se encontró {json_path}"))
            return

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        dias = data.get("dias", {})
        dias_cargados = 0

        # Categorías típicas que van en la columna derecha
        col2_categories = {
            "HIPOCALÓRICO", "ENSALADAS", "POSTRES", "POSTRE", "PORRIDGE", "MEJORADO"
        }

        for fecha_str, serv_dict in dias.items():
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            colacion = serv_dict.get("colacion", "")

            minuta_dia, _ = MinutaDia.objects.update_or_create(
                fecha=fecha,
                defaults={"colacion": colacion}
            )

            for s_cod in ["desayuno", "almuerzo", "cena"]:
                if s_cod in serv_dict:
                    s_info = serv_dict[s_cod]
                    items = s_info.get("items", [])

                    minuta_serv, _ = MinutaServicio.objects.update_or_create(
                        dia=minuta_dia,
                        servicio_codigo=s_cod
                    )

                    # Borrar items previos para recarga limpia
                    minuta_serv.items.all().delete()

                    # Asignar items a columnas 1 y 2
                    total_items = len(items)
                    mitad = (total_items + 1) // 2

                    for idx, it in enumerate(items):
                        cat = it.get("categoria", "").strip()
                        txt = it.get("texto", "").strip()
                        cant = it.get("cantidad")

                        # Decidir columna: si es categoría típica de col2 o si estamos en la 2da mitad
                        columna = 1
                        if cat.upper() in col2_categories or idx >= mitad:
                            columna = 2

                        ItemMinuta.objects.create(
                            servicio=minuta_serv,
                            categoria=cat,
                            texto=txt,
                            cantidad=cant,
                            orden=idx,
                            columna=columna
                        )

            dias_cargados += 1

        # 5. Registro de auditoría
        RegistroAuditoria.objects.create(
            nombre_usuario="Sistema",
            accion="IMPORTACION",
            resumen="Carga inicial automática de minuta de Octubre 2026 (31 días)",
            detalles=f"Se cargaron exitosamente {dias_cargados} días con desayunos, almuerzos y cenas.",
            ip="127.0.0.1"
        )

        self.stdout.write(self.style.SUCCESS(f"¡Carga completada con éxito! {dias_cargados} días cargados en la base de datos."))
