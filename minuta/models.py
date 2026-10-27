from django.db import models
from django.contrib.auth.models import User
import json

class ConfiguracionServicio(models.Model):
    CODIGOS_VALIDOS = [
        ('desayuno', 'Desayuno'),
        ('almuerzo', 'Almuerzo'),
        ('cena', 'Cena'),
    ]
    codigo = models.CharField(max_length=20, choices=CODIGOS_VALIDOS, unique=True)
    nombre = models.CharField(max_length=50, help_text="Nombre mostrado (ej. DESAYUNO)")
    desde = models.TimeField(help_text="Hora de inicio (ej. 05:00)")
    hasta = models.TimeField(help_text="Hora de fin (ej. 10:00)")
    color_franja = models.CharField(max_length=30, default="#0B3FA8", help_text="Color hex de la franja (ej. #0B3FA8)")
    orden = models.PositiveSmallIntegerField(default=1)

    class Meta:
        verbose_name = "Configuración de Servicio"
        verbose_name_plural = "Configuraciones de Servicios"
        ordering = ['orden', 'desde']

    def __str__(self):
        return f"{self.nombre} ({self.desde.strftime('%H:%M')} a {self.hasta.strftime('%H:%M')})"


class ConfiguracionGeneral(models.Model):
    intervalo_rotacion_segundos = models.PositiveSmallIntegerField(default=10, help_text="Segundos entre Vista A y Vista B")
    zona_horaria = models.CharField(max_length=50, default="America/Santiago")
    logo_promet = models.ImageField(upload_to="logos/", blank=True, null=True, help_text="Subir logo PROMET personalizado (opcional)")
    logo_coalfa = models.ImageField(upload_to="logos/", blank=True, null=True, help_text="Subir logo COALFA personalizado (opcional)")
    pie_pagina = models.CharField(max_length=255, default="Hotelería Promet · Servicio de alimentación Coalfa")
    recarga_minutos = models.PositiveSmallIntegerField(default=30, help_text="Intervalo de recarga completa de la TV")

    class Meta:
        verbose_name = "Configuración General"
        verbose_name_plural = "Configuración General"

    def __str__(self):
        return "Configuración del Sistema"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class MinutaDia(models.Model):
    fecha = models.DateField(unique=True, db_index=True)
    colacion = models.CharField(max_length=255, blank=True, default="", help_text="Colación del día")
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Minuta Diaria"
        verbose_name_plural = "Minutas Diarias"
        ordering = ['fecha']

    def __str__(self):
        return f"Minuta {self.fecha.strftime('%d/%m/%Y')}"


class MinutaServicio(models.Model):
    dia = models.ForeignKey(MinutaDia, related_name="servicios", on_delete=models.CASCADE)
    servicio_codigo = models.CharField(max_length=20)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Servicio de Minuta"
        verbose_name_plural = "Servicios de Minutas"
        unique_together = ('dia', 'servicio_codigo')

    def __str__(self):
        return f"{self.dia.fecha} - {self.servicio_codigo.upper()}"


class ItemMinuta(models.Model):
    servicio = models.ForeignKey(MinutaServicio, related_name="items", on_delete=models.CASCADE)
    categoria = models.CharField(max_length=100, help_text="Ej. ENTRADA CALIENTE · SOPA, FONDO NORMAL")
    texto = models.TextField(help_text="Descripción del plato o alimento")
    cantidad = models.PositiveIntegerField(null=True, blank=True, help_text="Raciones / cantidad planificada (opcional)")
    orden = models.PositiveSmallIntegerField(default=0)
    columna = models.PositiveSmallIntegerField(default=1, choices=[(1, 'Columna Izquierda'), (2, 'Columna Derecha')])

    class Meta:
        verbose_name = "Ítem de Minuta"
        verbose_name_plural = "Ítems de Minuta"
        ordering = ['columna', 'orden', 'id']

    def __str__(self):
        return f"{self.categoria}: {self.texto[:30]}"


class RegistroAuditoria(models.Model):
    ACCIONES = [
        ('CREACION', 'Creación'),
        ('MODIFICACION', 'Modificación'),
        ('ELIMINACION', 'Eliminación'),
        ('IMPORTACION', 'Importación Masiva'),
        ('CONFIGURACION', 'Cambio Configuración'),
    ]
    usuario = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="auditorias")
    nombre_usuario = models.CharField(max_length=150, default="Sistema")
    fecha_hora = models.DateTimeField(auto_now_add=True, db_index=True)
    accion = models.CharField(max_length=30, choices=ACCIONES)
    resumen = models.CharField(max_length=255)
    detalles = models.TextField(blank=True, default="")
    ip = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        verbose_name = "Registro de Auditoría"
        verbose_name_plural = "Registros de Auditoría"
        ordering = ['-fecha_hora']

    def __str__(self):
        return f"[{self.fecha_hora.strftime('%d/%m/%Y %H:%M')}] {self.nombre_usuario}: {self.resumen}"
