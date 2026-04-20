from decimal import Decimal

from django.db import migrations


def seed_pricing_rates(apps, schema_editor):
    AnalysisPricingRate = apps.get_model("pore_analysis", "AnalysisPricingRate")

    rates = [
        ("poresize", "default", Decimal("1.0000")),
        ("network_extraction", "cpu", Decimal("2.0000")),
        ("network_extraction", "parallel", Decimal("3.0000")),
        ("network_validation", "default", Decimal("1.5000")),
        ("permeability", "cpu", Decimal("1.0000")),
        ("permeability", "gpu", Decimal("2.0000")),
        ("permeability", "metal", Decimal("2.0000")),
        ("permeability", "cuda", Decimal("2.0000")),
        ("permeability", "opengl", Decimal("2.0000")),
        ("diffusivity", "cpu", Decimal("1.2500")),
        ("diffusivity", "gpu", Decimal("2.5000")),
    ]

    for analysis_type, backend, credits_per_million_voxels in rates:
        AnalysisPricingRate.objects.update_or_create(
            analysis_type=analysis_type,
            backend=backend,
            defaults={
                "credits_per_million_voxels": credits_per_million_voxels,
                "is_active": True,
            },
        )


def unseed_pricing_rates(apps, schema_editor):
    AnalysisPricingRate = apps.get_model("pore_analysis", "AnalysisPricingRate")

    seeded_keys = [
        ("poresize", "default"),
        ("network_extraction", "cpu"),
        ("network_extraction", "parallel"),
        ("network_validation", "default"),
        ("permeability", "cpu"),
        ("permeability", "gpu"),
        ("permeability", "metal"),
        ("permeability", "cuda"),
        ("permeability", "opengl"),
        ("diffusivity", "cpu"),
        ("diffusivity", "gpu"),
    ]

    for analysis_type, backend in seeded_keys:
        AnalysisPricingRate.objects.filter(analysis_type=analysis_type, backend=backend).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pore_analysis", "0007_alter_analysisjob_actual_cost_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_pricing_rates, unseed_pricing_rates),
    ]
