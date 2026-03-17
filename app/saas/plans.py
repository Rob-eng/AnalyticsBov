# config/plans.py

# ==========================================
# SAAS SUBSCRIPTION TIERS AND STRIPE PRICES
# ==========================================

import os

# Stripe keys (The secret key should be in ENV, not hardcoded if possible, but for test is OK)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")

# WhatsApp Meta API 
META_WABA_ID = os.getenv("META_WABA_ID", "2090195198222305")
META_PHONE_ID = os.getenv("META_PHONE_ID", "954772111063161")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")

# The unified dictionary for bot behavior based on SaaS tier
PLANOS = {
    "FREE": {
        "max_properties": 1,
        "price_brl": 0,
        "stripe_price_id_monthly": None,
        "stripe_price_id_annual": None,
        "features": ["cotacao_manual", "clima", "ndvi_manual", "mdt_2d"]
    },
    "STARTER": {
        "max_properties": 10,
        "price_brl": 29.90,
        "stripe_price_id_monthly": "price_1T55Oq2M9WyBElyRth0qLD5M",
        "stripe_price_id_annual": "price_1T55Oq2M9WyBElyRU52SNG7e",
        "features": ["cotacao_manual", "clima", "ndvi_manual", "mdt_2d", "alertas_ndvi_auto", "cotacao_auto_semanal"]
    },
    "PRO": {
        "max_properties": 30,
        "price_brl": 79.90,
        "stripe_price_id_monthly": "price_1T55Q72M9WyBElyRlawYjcRD",
        "stripe_price_id_annual": "price_1T55Q72M9WyBElyReOxOLUEP",
        "features": ["cotacao_manual", "clima", "ndvi_manual", "mdt_2d", "alertas_ndvi_auto", "cotacao_auto_semanal", "mdt_3d_video"]
    },
    "ENTERPRISE": {
        "max_properties": 9999,
        "price_brl": None,
        "stripe_price_id_monthly": None,
        "stripe_price_id_annual": None,
        "features": ["todas"]
    }
}
