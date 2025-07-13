import os

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "1718154161"))

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")

# Website URLs
TAKIPCIGIR_URL = "https://takipcigir.com"
TAKIPCIKRALI_URL = "https://takipcikrali.com"

# User roles
ROLE_USER = "user"
ROLE_PREMIUM = "premium"
ROLE_PREMIUM_PRO = "premium_pro"
ROLE_ADMIN = "admin"

# Account limits
ACCOUNT_LIMITS = {
    ROLE_USER: 0,
    ROLE_PREMIUM: 10,
    ROLE_PREMIUM_PRO: -1,  # Unlimited
    ROLE_ADMIN: -1  # Unlimited
}

# Delays
SEND_DELAY = 30  # seconds between follower sends
