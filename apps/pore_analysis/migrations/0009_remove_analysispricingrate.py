from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("pore_analysis", "0008_seed_analysis_pricing_rates"),
    ]

    operations = [
        migrations.DeleteModel(
            name="AnalysisPricingRate",
        ),
    ]
