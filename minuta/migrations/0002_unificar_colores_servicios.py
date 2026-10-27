from django.db import migrations

def unificar_colores(apps, schema_editor):
    ConfiguracionServicio = apps.get_model('minuta', 'ConfiguracionServicio')
    # Unificar todos los servicios al color oficial azul claro de alta legibilidad
    ConfiguracionServicio.objects.all().update(color_franja='#0B3FA8')

class Migration(migrations.Migration):

    dependencies = [
        ('minuta', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(unificar_colores, reverse_code=migrations.RunPython.noop),
    ]
