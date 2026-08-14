"""
URL routing for Django REST Framework internal control plane API.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AlertReadOnlyViewSet,
    AuditLogReadOnlyViewSet,
    FraudRuleReadOnlyViewSet,
    RiskProfileReadOnlyViewSet,
    TransactionReadOnlyViewSet,
    UserReadOnlyViewSet,
)

router = DefaultRouter()
router.register(r'fraud-rules', FraudRuleReadOnlyViewSet, basename='fraud-rules')
router.register(r'audit-logs', AuditLogReadOnlyViewSet, basename='audit-logs')
router.register(r'users', UserReadOnlyViewSet, basename='users')
router.register(r'alerts', AlertReadOnlyViewSet, basename='alerts')
router.register(r'transactions', TransactionReadOnlyViewSet, basename='transactions')
router.register(r'risk-profiles', RiskProfileReadOnlyViewSet, basename='risk-profiles')

urlpatterns = [
    path('', include(router.urls)),
]
