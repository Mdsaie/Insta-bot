#!/usr/bin/env python3
"""
Telegram Bot for Follower Sending Service
Integrates with takipcigir.com and takipcikrali.com
"""

import telebot
import threading
import time
import signal
import sys
from bot_handlers import BotHandlers
from config import BOT_TOKEN

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

# Initialize handlers
handlers = BotHandlers(bot)

# Register handlers
@bot.message_handler(commands=['start'])
def handle_start(message):
    handlers.handle_start(message)

@bot.message_handler(commands=['addaccount'])
def handle_addaccount(message):
    handlers.handle_addaccount_command(message)

@bot.message_handler(commands=['myaccounts'])
def handle_myaccounts(message):
    handlers.handle_myaccounts_command(message)

@bot.message_handler(commands=['schedule'])
def handle_schedule(message):
    handlers.handle_schedule_command(message)

@bot.message_handler(commands=['send-follower'])
def handle_send_follower(message):
    handlers.handle_send_follower_command(message)

@bot.message_handler(commands=['1service'])
def handle_1service(message):
    handlers.handle_1service_command(message)

@bot.message_handler(commands=['2service'])
def handle_2service(message):
    handlers.handle_2service_command(message)

@bot.message_handler(commands=['allservice'])
def handle_allservice(message):
    handlers.handle_allservice_command(message)

@bot.message_handler(commands=['premium'])
def handle_premium(message):
    handlers.handle_premium_command(message)

@bot.message_handler(commands=['premium_pro'])
def handle_premium_pro(message):
    handlers.handle_premium_pro_command(message)

@bot.message_handler(commands=['remove_user'])
def handle_remove_user(message):
    handlers.handle_remove_user_command(message)

@bot.message_handler(commands=['makeadmin'])
def handle_makeadmin(message):
    handlers.handle_makeadmin_command(message)

@bot.message_handler(commands=['view_users'])
def handle_view_users(message):
    handlers.handle_view_users_command(message)

@bot.message_handler(commands=['block'])
def handle_block(message):
    handlers.handle_block_command(message)

@bot.message_handler(commands=['unblock'])
def handle_unblock(message):
    handlers.handle_unblock_command(message)

@bot.message_handler(commands=['blocklist'])
def handle_blocklist(message):
    handlers.handle_blocklist_command(message)

@bot.message_handler(commands=['stop'])
def handle_stop(message):
    handlers.handle_stop_command(message)

@bot.message_handler(commands=['targets'])
def handle_targets(message):
    handlers.handle_targets_command(message)

@bot.message_handler(commands=['stats'])
def handle_stats(message):
    handlers.handle_stats_command(message)

@bot.message_handler(commands=['notice'])
def handle_notice(message):
    handlers.handle_notice_command(message)

@bot.message_handler(commands=['bot-on'])
def handle_bot_on(message):
    handlers.handle_bot_on_command(message)

@bot.message_handler(commands=['bot-stop'])
def handle_bot_stop(message):
    handlers.handle_bot_stop_command(message)



@bot.message_handler(func=lambda message: True)
def handle_message(message):
    handlers.handle_message(message)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    handlers.handle_callback(call)

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    print("\n🛑 Shutting down bot...")
    bot.stop_polling()
    sys.exit(0)

def main():
    """Main function"""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("🤖 Starting Telegram bot...")
    print(f"Bot token: {BOT_TOKEN[:20]}...")
    
    try:
        # Start bot polling
        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=60
        )
    except Exception as e:
        print(f"❌ Bot error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
