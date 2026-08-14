from django.apps import AppConfig


class FraudRulesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fraud_rules'
    verbose_name = 'Fraud Rules Engine'
