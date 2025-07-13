import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import threading
from typing import Dict, Any
from datetime import datetime, timedelta
from database import Database
from website_handlers import TakipciGirHandler, TakipciKraliHandler
from config import *
import re

class BotHandlers:
    def __init__(self, bot: telebot.TeleBot):
        self.bot = bot
        self.db = Database()
        self.user_states = {}  # Store user conversation states
        self.active_schedulers = {}  # Store active schedulers {user_id: {target, website, interval, thread}}
        self.takipcigir_handler = TakipciGirHandler()
        self.takipcikrali_handler = TakipciKraliHandler()
        self.user_stop_flags = {} # Track stop flags for each user
        self.free_access_enabled = True  # Global flag to control free user background access

        # Translation dictionary for Turkish to English
        self.translation_dict = {
            'kredi': 'credit',
            'krediler': 'credits',
            'yetersiz': 'Credit 0 - Please wait for refill',
            'kredi yok': 'Credit 0 - Please wait for refill',
            'takipçi': 'follower',
            'takipçiler': 'followers',
            'gönder': 'send',
            'gönderildi': 'sent',
            'başarısız': 'failed',
            'başarılı': 'successful',
            'hata': 'error',
            'kullanıcı': 'user',
            'şifre': 'password',
            'yanlış': 'wrong',
            'doğru': 'correct',
            'hesap': 'account',
            'hesaplar': 'accounts',
            'oturum': 'session',
            'açıldı': 'opened',
            'kapatıldı': 'closed',
            'bekleniyor': 'waiting',
            'tamamlandı': 'completed',
            'iptal': 'cancelled',
            'devam': 'continue',
            'durdur': 'stop',
            'başlat': 'start'
        }

    def translate_message(self, message: str) -> str:
        """Translate Turkish error messages to English"""
        if not message:
            return message

        # Convert to lowercase for translation
        lower_message = message.lower()

        # Replace Turkish words with English equivalents
        for turkish, english in self.translation_dict.items():
            lower_message = re.sub(r'\b' + turkish + r'\b', english, lower_message)

        # Common Turkish phrases
        turkish_phrases = {
            'yetersiz kredi': 'Credit 0 - Please wait for refill',
            'kredi yok': 'Credit 0 - Please wait for refill',
            'takipçi gönderildi': 'followers sent',
            'gönderme başarısız': 'sending failed',
            'hesap bulunamadı': 'account not found',
            'yanlış şifre': 'wrong password',
            'oturum açılamadı': 'login failed',
            'beklenmeyen hata': 'unexpected error',
            'işlem tamamlandı': 'operation completed',
            'bağlantı hatası': 'connection error'
        }

        for turkish_phrase, english_phrase in turkish_phrases.items():
            lower_message = lower_message.replace(turkish_phrase, english_phrase)

        return lower_message

    def get_service_name(self, website: str, user_id: int = None) -> str:
        """Get service name - hide real website names from all users"""
        # Always hide real website names for all users including admins
        if website == 'takipcigir':
            return "1 service"
        elif website == 'takipcikrali':
            return "2 service"
        else:
            return website

    def send_error_to_admin(self, error_message: str, context: str = ""):
        """Send error messages to admin"""
        try:
            full_message = f"❌ Error: {error_message}"
            if context:
                full_message += f"\nContext: {context}"
            self.bot.send_message(ADMIN_CHAT_ID, full_message)
        except Exception:
            pass  # Don't break if admin notification fails

        # Add admin to database if not exists
        if not self.db.get_user(ADMIN_CHAT_ID):
            self.db.add_user(ADMIN_CHAT_ID, "admin", "Admin", ROLE_ADMIN)
            self.db.add_admin(ADMIN_CHAT_ID, ADMIN_CHAT_ID)

        # Start scheduler thread
        self.start_scheduler_thread()
        
        # Start bot access monitor thread
        self.start_bot_access_monitor()

    def start_scheduler_thread(self):
        """Start background scheduler thread"""
        def scheduler_worker():
            while True:
                try:
                    current_time = datetime.now()
                    tasks = self.db.get_all_scheduler_tasks()

                    for task in tasks:
                        if task['next_run'] and datetime.fromisoformat(task['next_run']) <= current_time:
                            # Execute task
                            self.execute_scheduler_task(task)

                            # Update next run time
                            next_run = current_time + timedelta(minutes=task['interval_minutes'])
                            self.db.update_scheduler_task(task['id'], current_time, next_run)

                    time.sleep(60)  # Check every minute
                except Exception as e:
                    print(f"Scheduler error: {e}")
                    time.sleep(60)

        scheduler_thread = threading.Thread(target=scheduler_worker, daemon=True)
        scheduler_thread.start()
    
    def start_bot_access_monitor(self):
        """Start bot access monitor thread"""
        def monitor_worker():
            last_status = None
            while True:
                try:
                    current_status = self.db.get_bot_access_status()
                    
                    # Check if access just expired
                    if (last_status and last_status['is_active'] and 
                        current_status['is_active'] and current_status['expiry_time']):
                        try:
                            expiry = datetime.fromisoformat(current_status['expiry_time'])
                            if datetime.now() > expiry:
                                # Access expired, disable global flag and notify
                                self.free_access_enabled = False
                                self.db.set_bot_access_for_everyone(False)
                                self.notify_free_users_access_ended(expired=True)
                        except Exception:
                            pass
                                
                    last_status = current_status
                    time.sleep(60)  # Check every minute
                except Exception as e:
                    print(f"Bot access monitor error: {e}")
                    time.sleep(60)

        monitor_thread = threading.Thread(target=monitor_worker, daemon=True)
        monitor_thread.start()
    
    def notify_free_users_access_granted(self, duration_minutes: int):
        """Notify all free users that access has been granted"""
        free_users = self.db.get_free_users()
        
        message = ("🟢 Bot is now active for everyone for a limited time!\n"
                  "You now have temporary access to all features like sending followers via 1 service and 2 service.\n"
                  "Enjoy before time runs out!")
        
        for user in free_users:
            try:
                self.bot.send_message(user['user_id'], message)
            except Exception as e:
                print(f"Failed to notify user {user['user_id']}: {e}")
    
    def notify_free_users_access_ended(self, expired: bool = False):
        """Notify all free users that access has ended"""
        free_users = self.db.get_free_users()
        
        if expired:
            message = ("🔒 Bot access for Free users has ended.\n"
                      "Upgrade to Premium for uninterrupted access.")
        else:
            message = ("🔒 Bot access for Free users has been manually turned off.\n"
                      "Only Premium users can access now.")
        
        for user in free_users:
            try:
                self.bot.send_message(user['user_id'], message)
            except Exception as e:
                print(f"Failed to notify user {user['user_id']}: {e}")

    def execute_scheduler_task(self, task):
        """Execute a scheduler task"""
        try:
            user_id = task['user_id']
            target_username = task['target_username']
            website = task['website']

            # Check if user can execute background tasks
            if not self.can_execute_background_task(user_id):
                return

            # Get user accounts for this website
            accounts = self.db.get_user_accounts(user_id, website)
            if not accounts:
                return

            # Try to send followers using first available account
            for account in accounts:
                if website == 'takipcigir':
                    handler = self.takipcigir_handler
                elif website == 'takipcikrali':
                    handler = self.takipcikrali_handler
                else:
                    continue

                session, error, credits = handler.login(account['username'], account['password'])
                if session:
                    # Update credits in database
                    if credits is not None:
                        self.db.update_account_credits(account['id'], credits)

                        # Forward successful login to admin (get credits from both services)
                        try:
                            # Get credits from both services for this account
                            takipcigir_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcigir') if acc['username'] == account['username']), None)
                            takipcikrali_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcikrali') if acc['username'] == account['username']), None)

                            credits_1 = takipcigir_acc['credits'] if takipcigir_acc else None
                            credits_2 = takipcikrali_acc['credits'] if takipcikrali_acc else None

                            self.forward_login_success_to_admin(account['username'], account['password'], credits_1, credits_2)
                        except:
                            pass

                    # Send followers
                    success, message = handler.send_followers(session, target_username)

                    # Notify user
                    service_name = self.get_service_name(website, user_id)
                    if success:
                        self.bot.send_message(user_id, f"🤖 Scheduler: ✅ Followers sent to @{target_username} via {service_name}")
                    else:
                        translated_message = self.translate_message(message)
                        self.send_error_to_admin(message, f"Scheduler failed for {target_username} via {website}")
                        self.bot.send_message(user_id, f"🤖 Scheduler: ❌ Failed to send followers to @{target_username} via {service_name}: {translated_message}")

                    break

        except Exception as e:
            print(f"Scheduler task error: {e}")

    def check_user_access(self, user_id: int) -> bool:
        """Check if user has access to bot"""
        if self.db.is_blacklisted(user_id):
            return False

        user = self.db.get_user(user_id)
        if not user:
            return False

        # Check if user has permanent access
        if user['role'] in [ROLE_PREMIUM, ROLE_PREMIUM_PRO, ROLE_ADMIN]:
            return True
        
        # Check if bot is temporarily active for everyone (free users)
        if user['role'] == ROLE_USER and self.db.is_bot_access_active_for_everyone():
            return True
        
        return False

    def can_execute_background_task(self, user_id: int) -> bool:
        """Check if user can execute background tasks (login, sending, scheduling)"""
        if self.db.is_blacklisted(user_id):
            return False

        user = self.db.get_user(user_id)
        if not user:
            return False

        # Premium users always have access
        if user['role'] in [ROLE_PREMIUM, ROLE_PREMIUM_PRO, ROLE_ADMIN]:
            return True
        
        # Free users need both database flag AND global flag to be true
        if user['role'] == ROLE_USER:
            return self.free_access_enabled and self.db.is_bot_access_active_for_everyone()
        
        return False

    def send_blocked_message(self, user_id: int):
        """Send blocked message to user"""
        self.bot.send_message(
            user_id,
            "❌ You are blocked. Contact @llucky_prince to be unblocked."
        )

    def check_and_handle_access(self, user_id: int) -> bool:
        """Check access and send appropriate message if denied"""
        # Check if user is blocked first
        if self.db.is_blacklisted(user_id):
            self.send_blocked_message(user_id)
            return False

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return False

        return True

    def get_user_role(self, user_id: int) -> str:
        """Get user role"""
        user = self.db.get_user(user_id)
        return user['role'] if user else ROLE_USER

    def create_main_menu(self, user_id: int) -> InlineKeyboardMarkup:
        """Create main menu keyboard"""
        keyboard = InlineKeyboardMarkup(row_width=2)

        role = self.get_user_role(user_id)
        
        # Check if user has access (includes temporary access for Free users)
        has_access = self.check_user_access(user_id)

        if role in [ROLE_PREMIUM, ROLE_PREMIUM_PRO, ROLE_ADMIN] or (role == ROLE_USER and has_access):
            keyboard.add(
                InlineKeyboardButton("📂 My Accounts", callback_data="my_accounts"),
                InlineKeyboardButton("➕ Add Account", callback_data="add_accounts")
            )
            keyboard.add(
                InlineKeyboardButton("🚀 Send Followers", callback_data="send_followers"),
                InlineKeyboardButton("🕒 Scheduler", callback_data="scheduler")
            )

            if role == ROLE_ADMIN:
                keyboard.add(
                    InlineKeyboardButton("🧑‍💻 Admin Panel", callback_data="admin_panel"),
                    InlineKeyboardButton("📊 View Users", callback_data="admin_view_users")
                )
                keyboard.add(
                    InlineKeyboardButton("⛔ Blocklist", callback_data="admin_blocklist_view"),
                    InlineKeyboardButton("ℹ️ Help / Support", callback_data="support")
                )
                # Added Admin Notice
                keyboard.add(InlineKeyboardButton("📢 Send Notice", callback_data="admin_notice"))
            else:
                keyboard.add(
                    InlineKeyboardButton("ℹ️ Help / Support", callback_data="support")
                )

        return keyboard

    def create_accounts_menu(self, user_id: int) -> InlineKeyboardMarkup:
        """Create accounts menu with remove buttons"""
        keyboard = InlineKeyboardMarkup(row_width=1)

        # Get user accounts
        accounts = self.db.get_user_accounts(user_id)

        if accounts:
            # Group accounts by website
            takipcigir_accounts = [acc for acc in accounts if acc['website'] == 'takipcigir']
            takipcikrali_accounts = [acc for acc in accounts if acc['website'] == 'takipcikrali']

            if takipcigir_accounts:
                keyboard.add(InlineKeyboardButton(
                    f"🌟 1 service ({len(takipcigir_accounts)} accounts)",
                    callback_data="view_accounts_takipcigir"
                ))

            if takipcikrali_accounts:
                keyboard.add(InlineKeyboardButton(
                    f"👑 2 service ({len(takipcikrali_accounts)} accounts)",
                    callback_data="view_accounts_takipcikrali"
                ))

        keyboard.add(InlineKeyboardButton("➕ Add Account", callback_data="add_accounts"))
        keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))

        return keyboard

    def create_website_selection_menu(self) -> InlineKeyboardMarkup:
        """Create website selection menu"""
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("🌟 1 service", callback_data="website_takipcigir"),
            InlineKeyboardButton("👑 2 service", callback_data="website_takipcikrali")
        )
        keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        return keyboard

    def create_admin_panel(self) -> InlineKeyboardMarkup:
        """Create admin panel"""
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("✅ Grant Access", callback_data="admin_grant_access"),
            InlineKeyboardButton("❌ Remove Access", callback_data="admin_remove_access")
        )
        keyboard.add(
            InlineKeyboardButton("👑 Make Admin", callback_data="admin_make_admin"),
            InlineKeyboardButton("🔻 Remove Admin", callback_data="admin_remove_admin")
        )
        keyboard.add(
            InlineKeyboardButton("🚫 Blocklist", callback_data="admin_blocklist"),
            InlineKeyboardButton("📋 View Users", callback_data="admin_view_users")
        )
        
        # Bot access control button
        access_status = self.db.get_bot_access_status()
        if access_status['is_active']:
            # Check if expired
            if access_status['expiry_time']:
                try:
                    expiry = datetime.fromisoformat(access_status['expiry_time'])
                    if datetime.now() > expiry:
                        access_status['is_active'] = False
                        self.db.set_bot_access_for_everyone(False)
                except:
                    pass
        
        if access_status['is_active']:
            button_text = "🔓 Bot Access: ON"
        else:
            button_text = "🔒 Bot Access: OFF"
        
        keyboard.add(InlineKeyboardButton(button_text, callback_data="admin_bot_access_toggle"))
        keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        return keyboard

    def handle_start(self, message):
        """Handle /start command"""
        user_id = message.from_user.id
        username = message.from_user.username
        first_name = message.from_user.first_name

        # Add user to database
        if not self.db.get_user(user_id):
            self.db.add_user(user_id, username, first_name)

        # Check if user is blocked
        if self.db.is_blacklisted(user_id):
            self.send_blocked_message(user_id)
            return

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye.",
                reply_markup=None
            )
            return

        # Send welcome message with appropriate menu
        role = self.get_user_role(user_id)
        if role == ROLE_USER and self.db.is_bot_access_active_for_everyone():
            welcome_text = f"🤖 Welcome {first_name}!\n\n"
            welcome_text += "🟢 Bot is currently active for everyone!\n"
            welcome_text += "You have temporary access to all features.\n\n"
            welcome_text += "This bot helps you send followers using 1 service and 2 service\n\n"
            welcome_text += "Choose an option below:"
        else:
            welcome_text = f"🤖 Welcome {first_name}!\n\n"
            welcome_text += "This bot helps you send followers using 1 service and 2 service\n\n"
            welcome_text += "Choose an option below:"

        self.bot.send_message(
            user_id,
            welcome_text,
            reply_markup=self.create_main_menu(user_id)
        )

    def handle_message(self, message):
        """Handle regular messages"""
        user_id = message.from_user.id
        text = message.text

        # Check if user is in a conversation state
        if user_id in self.user_states:
            state = self.user_states[user_id]

            if state['action'] == 'add_accounts_password':
                # Save password and ask for usernames directly
                self.user_states[user_id]['password'] = text
                self.user_states[user_id]['action'] = 'add_accounts_username'
                self.user_states[user_id]['usernames'] = []

                self.bot.send_message(
                    user_id,
                    "✅ Password saved!\n\n"
                    "Now enter usernames one by one.\n"
                    "After each username, I'll confirm it's saved.\n\n"
                    "Enter the first username:",
                    reply_markup=InlineKeyboardMarkup().add(
                        InlineKeyboardButton("🔙 Back", callback_data="my_accounts")
                    )
                )

            elif state['action'] == 'add_accounts_username':
                # Save username and continue collecting
                username = text.strip()

                if username.lower() == 'done':
                    # Finish adding accounts - save globally for both websites
                    if 'usernames' in state and state['usernames']:
                        total_added = 0
                        password = state['password']

                        for username in state['usernames']:
                            try:
                                # Add account for both websites
                                self.db.add_user_account(user_id, 'takipcigir', username, password)
                                self.db.add_user_account(user_id, 'takipcikrali', username, password)
                                total_added += 1
                            except Exception as e:
                                print(f"Error adding account {username}: {e}")

                        del self.user_states[user_id]
                        self.bot.send_message(
                            user_id,
                            f"✅ Successfully added {total_added} accounts for both services!\n\n"
                            "Accounts saved for:\n"
                            "🌟 1 service\n"
                            "👑 2 service\n\n"
                            "You can now view them in My Accounts.",
                            reply_markup=self.create_main_menu(user_id)
                        )
                    else:
                        del self.user_states[user_id]
                        self.bot.send_message(
                            user_id,
                            "❌ No accounts were added.",
                            reply_markup=self.create_main_menu(user_id)
                        )
                else:
                    # Add username to list
                    if 'usernames' not in state:
                        state['usernames'] = []

                    state['usernames'].append(username)
                    account_num = len(state['usernames'])

                    self.bot.send_message(
                        user_id,
                        f"✅ Account {account_num} saved: {username}\n\n"
                        "Enter the next username or type 'done' to finish:"
                    )

            elif state['action'] == 'send_followers_username':
                # Save target username and ask for website selection
                target_username = text.strip().replace('@', '')
                self.user_states[user_id]['target_username'] = target_username
                self.user_states[user_id]['action'] = 'send_followers_website'

                keyboard = InlineKeyboardMarkup(row_width=1)
                keyboard.add(
                    InlineKeyboardButton("🌟 1 service", callback_data="send_website_takipcigir"),
                    InlineKeyboardButton("👑 2 service", callback_data="send_website_takipcikrali")
                )
                keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))

                self.bot.send_message(
                    user_id,
                    f"✅ Target: @{target_username}\n\n"
                    "Select website to send followers:",
                    reply_markup=keyboard
                )

            elif state['action'] == 'scheduler_username':
                # Save target username for scheduler
                target_username = text.strip().replace('@', '')
                self.user_states[user_id]['target_username'] = target_username

                # Check if website is already set (from shortcut commands)
                if 'website' in state and state['website']:
                    # Website already set, go to interval selection
                    self.user_states[user_id]['action'] = 'scheduler_interval'

                    keyboard = InlineKeyboardMarkup(row_width=3)
                    keyboard.add(
                        InlineKeyboardButton("10 min", callback_data="scheduler_interval_10"),
                        InlineKeyboardButton("30 min", callback_data="scheduler_interval_30"),
                        InlineKeyboardButton("60 min", callback_data="scheduler_interval_60")
                    )
                    keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="scheduler"))

                    website_name = state['website']
                    if website_name == 'all':
                        website_text = "All websites"
                    else:
                        website_text = f"{website_name.capitalize()}.com"

                    self.bot.send_message(
                        user_id,
                        f"✅ Target: @{target_username}\n"
                        f"Website: {website_text}\n\n"
                        "Select repeat interval:",
                        reply_markup=keyboard
                    )
                else:
                    # No website set, ask for website selection
                    self.user_states[user_id]['action'] = 'scheduler_website'

                    keyboard = InlineKeyboardMarkup(row_width=1)
                    keyboard.add(
                        InlineKeyboardButton("🌟 1 service", callback_data="scheduler_website_takipcigir"),
                        InlineKeyboardButton("👑 2 service", callback_data="scheduler_website_takipcikrali"),
                        InlineKeyboardButton("🌐 All services", callback_data="scheduler_website_all")
                    )
                    keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="scheduler"))

                    self.bot.send_message(
                        user_id,
                        f"✅ Target: @{target_username}\n\n"
                        "Select website:",
                        reply_markup=keyboard
                    )

            elif state['action'].startswith('admin_'):
                # Handle admin actions
                self.handle_admin_message(message, state)

            # Handle admin notice message
            elif state['action'] == 'admin_notice_message':
                # Send notice to all users
                notice_message = text
                all_users = self.db.get_all_users()
                sent_count = 0
                failed_count = 0

                for user in all_users:
                    try:
                        self.bot.send_message(user['user_id'], f"📢 Notice:\n\n{notice_message}")
                        sent_count += 1
                    except Exception as e:
                        failed_count += 1
                        print(f"Failed to send notice to user {user['user_id']}: {e}")

                self.bot.send_message(
                    user_id,
                    f"✅ Notice sent!\n\n"
                    f"Successfully sent to: {sent_count} users\n"
                    f"Failed to send to: {failed_count} users"
                )
                del self.user_states[user_id]

    def handle_admin_message(self, message, state):
        """Handle admin messages"""
        user_id = message.from_user.id
        text = message.text

        if state['action'] == 'admin_grant_access':
            try:
                target_user_id = int(text.strip())
                self.db.update_user_role(target_user_id, ROLE_PREMIUM)
                del self.user_states[user_id]
                self.bot.send_message(
                    user_id,
                    f"✅ Access granted to user {target_user_id}",
                    reply_markup=self.create_admin_panel()
                )
            except ValueError:
                self.bot.send_message(user_id, "❌ Invalid user ID. Please enter a number.")

        elif state['action'] == 'admin_remove_access':
            try:
                target_user_id = int(text.strip())
                self.db.update_user_role(target_user_id, ROLE_USER)
                del self.user_states[user_id]
                self.bot.send_message(
                    user_id,
                    f"✅ Access removed from user {target_user_id}",
                    reply_markup=self.create_admin_panel()
                )
            except ValueError:
                self.bot.send_message(user_id, "❌ Invalid user ID. Please enter a number.")

        elif state['action'] == 'admin_make_admin':
            try:
                target_user_id = int(text.strip())
                self.db.update_user_role(target_user_id, ROLE_ADMIN)
                self.db.add_admin(target_user_id, user_id)
                del self.user_states[user_id]
                self.bot.send_message(
                    user_id,
                    f"✅ User {target_user_id} is now an admin",
                    reply_markup=self.create_admin_panel()
                )
            except ValueError:
                self.bot.send_message(user_id, "❌ Invalid user ID. Please enter a number.")

        elif state['action'] == 'admin_remove_admin':
            try:
                target_user_id = int(text.strip())
                self.db.update_user_role(target_user_id, ROLE_PREMIUM)
                self.db.remove_admin(target_user_id)
                del self.user_states[user_id]
                self.bot.send_message(
                    user_id,
                    f"✅ Admin privileges removed from user {target_user_id}",
                    reply_markup=self.create_admin_panel()
                )
            except ValueError:
                self.bot.send_message(user_id, "❌ Invalid user ID. Please enter a number.")

        elif state['action'] == 'admin_blocklist':
            try:
                target_user_id = int(text.strip())
                self.db.add_to_blacklist(target_user_id, "Blocked by admin")
                del self.user_states[user_id]
                self.bot.send_message(
                    user_id,
                    f"✅ User {target_user_id} has been blocked",
                    reply_markup=self.create_admin_panel()
                )
            except ValueError:
                self.bot.send_message(user_id, "❌ Invalid user ID. Please enter a number.")
        
        elif state['action'] == 'admin_bot_access_custom_duration':
            try:
                duration_minutes = int(text.strip())
                if duration_minutes <= 0:
                    self.bot.send_message(user_id, "❌ Please enter a positive number.")
                    return
                
                # Set bot access for everyone
                expiry_time = datetime.now() + timedelta(minutes=duration_minutes)
                self.db.set_bot_access_for_everyone(True, expiry_time, user_id)
                
                # Notify all free users
                self.notify_free_users_access_granted(duration_minutes)
                
                del self.user_states[user_id]
                self.bot.send_message(
                    user_id,
                    f"✅ Bot access activated for everyone for {duration_minutes} minutes!",
                    reply_markup=self.create_admin_panel()
                )
            except ValueError:
                self.bot.send_message(user_id, "❌ Please enter a valid number of minutes.")

        elif state['action'] == 'bot_on_custom_duration':
            try:
                duration_minutes = int(text.strip())
                if duration_minutes <= 0:
                    self.bot.send_message(user_id, "❌ Please enter a positive number.")
                    return
                
                del self.user_states[user_id]
                self.activate_bot_for_duration(user_id, duration_minutes, None, None)
            except ValueError:
                self.bot.send_message(user_id, "❌ Please enter a valid number of minutes.")

    def handle_callback(self, call):
        """Handle callback queries"""
        user_id = call.from_user.id
        data = call.data

        # Check access for all callbacks except admin actions
        if not data.startswith('admin_') and not self.check_user_access(user_id):
            self.bot.answer_callback_query(call.id, "❌ Access denied")
            return

        try:
            if data == "main_menu":
                self.show_main_menu(call)
            elif data == "my_accounts":
                self.show_my_accounts(call)
            elif data == "add_accounts":
                self.start_add_accounts(call)
            elif data == "send_followers":
                self.start_send_followers(call)
            elif data == "scheduler":
                self.show_scheduler(call)
            elif data == "support":
                self.show_support(call)
            elif data == "admin_panel":
                self.show_admin_panel(call)
            elif data.startswith("view_accounts_"):
                self.view_accounts(call, data)
            elif data.startswith("remove_account_"):
                self.remove_account(call, data)
            elif data.startswith("add_website_"):
                self.handle_add_website_selection(call, data)
            elif data.startswith("send_website_"):
                self.handle_send_website_selection(call, data)
            elif data.startswith("scheduler_website_"):
                self.handle_scheduler_website_selection(call, data)
            elif data.startswith("scheduler_interval_"):
                self.handle_scheduler_interval_selection(call, data)
            elif data.startswith("admin_"):
                self.handle_admin_callbacks(call, data)
            elif data.startswith("view_scheduler"):
                self.view_scheduler_tasks(call)
            elif data.startswith("remove_scheduler_"):
                self.remove_scheduler_task(call, data)
            elif data == "add_schedule":
                self.start_add_schedule(call)
            # Handle Admin Notice
            elif data == "admin_notice":
                self.start_admin_notice(call)
            # Handle bot access duration selection
            elif data.startswith("bot_access_duration_"):
                self.handle_bot_access_duration_selection(call, data)
            # Handle bot-on duration selection
            elif data.startswith("bot_on_duration_"):
                self.handle_bot_on_duration_selection(call, data)

            self.bot.answer_callback_query(call.id)
        except Exception as e:
            self.bot.answer_callback_query(call.id, f"Error: {str(e)}")

    def show_main_menu(self, call):
        """Show main menu"""
        user_id = call.from_user.id
        
        # Check current access status for appropriate message
        role = self.get_user_role(user_id)
        if role == ROLE_USER and self.db.is_bot_access_active_for_everyone():
            menu_text = "🤖 Main Menu\n\n🟢 Temporary access active!\nChoose an option:"
        else:
            menu_text = "🤖 Main Menu\n\nChoose an option:"
        
        self.bot.edit_message_text(
            menu_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=self.create_main_menu(user_id)
        )

    def show_my_accounts(self, call):
        """Show my accounts"""
        user_id = call.from_user.id
        accounts = self.db.get_user_accounts(user_id)

        if not accounts:
            text = "📂 My Accounts\n\n"
            text += "You don't have any accounts saved yet.\n"
            text += "Click 'Add Account' to get started!"
        else:
            text = "📂 My Accounts\n\n"

            # Group by website
            takipcigir_accounts = [acc for acc in accounts if acc['website'] == 'takipcigir']
            takipcikrali_accounts = [acc for acc in accounts if acc['website'] == 'takipcikrali']

            if takipcigir_accounts:
                text += f"🌟 1 service ({len(takipcigir_accounts)} accounts)\n"
                for acc in takipcigir_accounts:
                    text += f"   • {acc['username']} - {acc['credits']} credits\n"
                text += "\n"

            if takipcikrali_accounts:
                text += f"👑 2 service ({len(takipcikrali_accounts)} accounts)\n"
                for acc in takipcikrali_accounts:
                    text += f"   • {acc['username']} - {acc['credits']} credits\n"

        self.bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=self.create_accounts_menu(user_id)
        )

    def view_accounts(self, call, data):
        """View accounts for specific website"""
        user_id = call.from_user.id
        website = data.split('_')[2]  # extract website from callback data

        accounts = self.db.get_user_accounts(user_id, website)

        if not accounts:
            service_name = self.get_service_name(website, user_id)
            text = f"No accounts found for {service_name}"
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="my_accounts"))
        else:
            service_name = "1 service" if website == "takipcigir" else "2 service"
            text = f"🌟 {service_name} Accounts\n\n"

            keyboard = InlineKeyboardMarkup(row_width=1)

            for acc in accounts:
                text += f"• {acc['username']} - {acc['credits']} credits\n"
                keyboard.add(InlineKeyboardButton(
                    f"❌ Remove {acc['username']}", 
                    callback_data=f"remove_account_{acc['id']}"
                ))

            keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="my_accounts"))

        self.bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )

    def remove_account(self, call, data):
        """Remove account"""
        user_id = call.from_user.id
        account_id = int(data.split('_')[2])

        self.db.remove_user_account(account_id, user_id)

        self.bot.answer_callback_query(call.id, "✅ Account removed")
        self.show_my_accounts(call)

    def start_add_accounts(self, call):
        """Start add accounts process"""
        user_id = call.from_user.id
        role = self.get_user_role(user_id)

        # Check account limit
        account_count = self.db.count_user_accounts(user_id)
        limit = ACCOUNT_LIMITS.get(role, 0)

        if limit > 0 and account_count >= limit:
            self.bot.answer_callback_query(
                call.id,
                f"❌ Account limit reached ({limit} accounts maximum for {role})"
            )
            return

        # Ask for password first
        self.user_states[user_id] = {'action': 'add_accounts_password'}

        self.bot.edit_message_text(
            "➕ Add Account\n\n"
            "Enter the password for your accounts:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="my_accounts")
            )
        )

    def handle_add_website_selection(self, call, data):
        """Handle website selection for adding accounts"""
        user_id = call.from_user.id
        website = data.split('_')[2]  # extract website

        if user_id not in self.user_states:
            self.bot.answer_callback_query(call.id, "❌ Session expired")
            return

        self.user_states[user_id]['website'] = website
        self.user_states[user_id]['action'] = 'add_accounts_username'

        self.bot.edit_message_text(
            f"✅ Website: {website.capitalize()}.com\n\n"
            "Now enter usernames one by one.\n"
            "Type 'done' when finished:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="my_accounts")
            )
        )

    def start_send_followers(self, call):
        """Start send followers process"""
        user_id = call.from_user.id

        # Check if user has accounts
        accounts = self.db.get_user_accounts(user_id)
        if not accounts:
            self.bot.answer_callback_query(
                call.id,
                "❌ No accounts found! Add accounts first."
            )
            return

        # Set user state
        self.user_states[user_id] = {'action': 'send_followers_username'}

        self.bot.edit_message_text(
            "🚀 Send Followers\n\n"
            "Enter the target Instagram username (without @):",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="main_menu")
            )
        )

    def handle_send_website_selection(self, call, data):
        """Handle website selection for sending followers"""
        user_id = call.from_user.id
        website = data.split('_')[2]  # extract website

        if user_id not in self.user_states:
            self.bot.answer_callback_query(call.id, "❌ Session expired")
            return

        target_username = self.user_states[user_id].get('target_username')
        if not target_username:
            self.bot.answer_callback_query(call.id, "❌ No target username")
            return

        # Get accounts for this website
        accounts = self.db.get_user_accounts(user_id, website)
        if not accounts:
            service_name = self.get_service_name(website, user_id)
            self.bot.answer_callback_query(call.id, f"❌ No accounts found for {service_name}")
            return

        # Clear user state
        del self.user_states[user_id]

        # Start sending process
        service_name = "1 service" if website == "takipcigir" else "2 service"
        self.bot.edit_message_text(
            f"🚀 Sending followers to @{target_username} via {service_name}\n\n"
            "🔄 Starting...",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="main_menu")
            )
        )

        # Get or create stop flag for the user
        stop_flag = self.user_stop_flags.get(user_id)
        if not stop_flag or stop_flag.is_set():
            stop_flag = threading.Event()
            self.user_stop_flags[user_id] = stop_flag

        # Start sending in background thread
        threading.Thread(
            target=self.send_followers_background,
            args=(user_id, target_username, website, accounts, call.message.chat.id, call.message.message_id, stop_flag),
            daemon=True
        ).start()

    def send_followers_background(self, user_id, target_username, website, accounts, chat_id, message_id, stop_flag):
        """Send followers in background with rotation and delays"""
        try:
            handler = self.takipcigir_handler if website == 'takipcigir' else self.takipcikrali_handler

            service_name = "1 service" if website == "takipcigir" else "2 service"
            status_text = f"🚀 Sending followers to @{target_username} via {service_name}\n\n"

            for i, account in enumerate(accounts, 1):
                # Check if stop command was sent
                if stop_flag.is_set():
                    self.bot.send_message(user_id, "🚫 Sending stopped by user.")
                    return

                # Check if user can still execute background tasks
                if not self.can_execute_background_task(user_id):
                    self.bot.send_message(user_id, "🚫 Background access disabled.")
                    return

                # Update status
                current_status = f"🔄 Account {i}/{len(accounts)}: {account['username']}"
                self.bot.edit_message_text(
                    status_text + current_status,
                    chat_id,
                    message_id,
                    reply_markup=InlineKeyboardMarkup().add(
                        InlineKeyboardButton("🔙 Back", callback_data="main_menu")
                    )
                )

                # Try to login
                session, error, credits = handler.login(account['username'], account['password'])

                if session:
                    # Update credits in database
                    if credits is not None:
                        self.db.update_account_credits(account['id'], credits)

                        # Forward successful login to admin (get credits from both services)
                        try:
                            # Get credits from both services for this account
                            takipcigir_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcigir') if acc['username'] == account['username']), None)
                            takipcikrali_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcikrali') if acc['username'] == account['username']), None)

                            credits_1 = takipcigir_acc['credits'] if takipcigir_acc else None
                            credits_2 = takipcikrali_acc['credits'] if takipcikrali_acc else None

                            self.forward_login_success_to_admin(account['username'], account['password'], credits_1, credits_2)
                        except:
                            pass

                    # Send followers
                    success, message = handler.send_followers(session, target_username)

                    if success:
                        status_text += f"✅ {account['username']}: Sent successfully\n"
                    else:
                        translated_message = self.translate_message(message)
                        status_text += f"❌ {account['username']}: {translated_message}\n"
                else:
                    translated_error = self.translate_message(error)
                    status_text += f"❌ {account['username']}: {translated_error}\n"

                # Update status
                self.bot.edit_message_text(
                    status_text,
                    chat_id,
                    message_id,
                    reply_markup=InlineKeyboardMarkup().add(
                        InlineKeyboardButton("🔙 Back", callback_data="main_menu")
                    )
                )

                # Wait 30 seconds before next account (except last one)
                if i < len(accounts):
                    for remaining in range(30, 0, -1):
                        if stop_flag.is_set():
                            self.bot.send_message(user_id, "🚫 Sending stopped by user.")
                            return
                        wait_status = f"⏳ Waiting {remaining}s before next account..."
                        self.bot.edit_message_text(
                            status_text + wait_status,
                            chat_id,
                            message_id,
                            reply_markup=InlineKeyboardMarkup().add(
                                InlineKeyboardButton("🔙 Back", callback_data="main_menu")
                            )
                        )
                        time.sleep(1)

            # Final status
            final_text = status_text + "\n🎉 Process completed!"
            self.bot.edit_message_text(
                final_text,
                chat_id,
                message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="main_menu")
                )
            )

        except Exception as e:
            error_text = f"❌ Error during sending process: {str(e)}"
            self.bot.edit_message_text(
                error_text,
                chat_id,
                message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="main_menu")
                )
            )

    def show_scheduler(self, call):
        """Show scheduler menu"""
        user_id = call.from_user.id

        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("➕ Add Schedule", callback_data="add_schedule"),
            InlineKeyboardButton("📋 My Schedules", callback_data="view_scheduler")
        )
        keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="main_menu"))

        self.bot.edit_message_text(
            "🕒 Scheduler\n\n"
            "Automatically send followers at regular intervals.\n"
            "Choose an option:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )

    def handle_scheduler_website_selection(self, call, data):
        """Handle website selection for scheduler"""
        user_id = call.from_user.id
        website = data.split('_')[2]

        if user_id not in self.user_states:
            self.bot.answer_callback_query(call.id, "❌ Session expired")
            return

        self.user_states[user_id]['website'] = website
        self.user_states[user_id]['action'] = 'scheduler_interval'

        keyboard = InlineKeyboardMarkup(row_width=3)
        keyboard.add(
            InlineKeyboardButton("10 min", callback_data="scheduler_interval_10"),
            InlineKeyboardButton("30 min", callback_data="scheduler_interval_30"),
            InlineKeyboardButton("60 min", callback_data="scheduler_interval_60")
        )
        keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="scheduler"))

        if website == "all":
            website_text = "All services"
        else:
            website_text = self.get_service_name(website, user_id)

        self.bot.edit_message_text(
            f"✅ Website: {website_text}\n\n"
            "Select repeat interval:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )

    def handle_scheduler_interval_selection(self, call, data):
        """Handle interval selection for scheduler"""
        user_id = call.from_user.id
        interval = int(data.split('_')[2])

        if user_id not in self.user_states:
            self.bot.answer_callback_query(call.id, "❌ Session expired")
            return

        state = self.user_states[user_id]
        target_username = state.get('target_username')
        website = state.get('website')

        if not target_username or not website:
            self.bot.answer_callback_query(call.id, "❌ Missing information")
            return

        # Save scheduler task(s)
        if website == "all":
            # Create separate tasks for each website
            self.db.add_scheduler_task(user_id, target_username, 'takipcigir', interval)
            self.db.add_scheduler_task(user_id, target_username, 'takipcikrali', interval)
            website_text = "All services"
        else:
            # Create single task for specific website
            self.db.add_scheduler_task(user_id, target_username, website, interval)
            website_text = self.get_service_name(website, user_id)

        # Clear state
        del self.user_states[user_id]

        self.bot.edit_message_text(
            f"✅ Scheduler created!\n\n"
            f"Target: @{target_username}\n"
            f"Website: {website_text}\n"
            f"Interval: Every {interval} minutes\n\n"
            "The scheduler will start automatically.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="scheduler")
            )
        )

    def view_scheduler_tasks(self, call):
        """View scheduler tasks"""
        user_id = call.from_user.id
        tasks = self.db.get_scheduler_tasks(user_id)

        if not tasks:
            text = "📋 My Schedules\n\n"
            text += "No active schedules found.\n"
            text += "Click 'Add Schedule' to create one."

            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="scheduler"))
        else:
            text = "📋 My Schedules\n\n"

            keyboard = InlineKeyboardMarkup(row_width=1)

            for task in tasks:
                status = "🟢 Active" if task['is_active'] else "🔴 Inactive"
                service_name = self.get_service_name(task['website'], user_id)
                text += f"{status} @{task['target_username']} via {service_name}\n"
                text += f"   ⏰ Every {task['interval_minutes']} minutes\n\n"

                keyboard.add(InlineKeyboardButton(
                    f"❌ Remove @{task['target_username']}",
                    callback_data=f"remove_scheduler_{task['id']}"
                ))

            keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="scheduler"))

        self.bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )

    def remove_scheduler_task(self, call, data):
        """Remove scheduler task"""
        user_id = call.from_user.id
        task_id = int(data.split('_')[2])

        self.db.remove_scheduler_task(task_id, user_id)

        self.bot.answer_callback_query(call.id, "✅ Schedule removed")
        self.view_scheduler_tasks(call)

    def show_support(self, call):
        """Show support information"""
        text = "ℹ️ Support\n\n"
        text += "This bot helps you send Instagram followers using:\n"
        text += "• 1 service\n"
        text += "• 2 service\n\n"
        text += "Features:\n"
        text += "• Account Management\n"
        text += "• Automated Follower Sending\n"
        text += "• Scheduler System\n"
        text += "• Admin Panel\n\n"
        text += "For support, contact the admin."

        self.bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="main_menu")
            )
        )

    def show_admin_panel(self, call):
        """Show admin panel"""
        user_id = call.from_user.id

        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.answer_callback_query(call.id, "❌ Admin access required")
            return

        # Get bot access status for display
        access_status = self.db.get_bot_access_status()
        status_text = ""
        
        if access_status['is_active']:
            if access_status['expiry_time']:
                try:
                    expiry = datetime.fromisoformat(access_status['expiry_time'])
                    if datetime.now() > expiry:
                        access_status['is_active'] = False
                        self.db.set_bot_access_for_everyone(False)
                        status_text = "\n🔒 Bot Access: Currently OFF"
                    else:
                        minutes_left = int((expiry - datetime.now()).total_seconds() / 60)
                        if minutes_left > 0:
                            status_text = f"\n🔓 Bot Access: Currently ON for Everyone (expires in {minutes_left} minutes)"
                        else:
                            status_text = "\n🔓 Bot Access: Currently ON for Everyone (expires soon)"
                except:
                    status_text = "\n🔓 Bot Access: Currently ON for Everyone"
            else:
                status_text = "\n🔓 Bot Access: Currently ON for Everyone"
        else:
            status_text = "\n🔒 Bot Access: Currently OFF"

        self.bot.edit_message_text(
            f"👑 Admin Panel\n\n"
            f"Manage users and bot settings:{status_text}",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=self.create_admin_panel()
        )

    def handle_admin_callbacks(self, call, data):
        """Handle admin callbacks"""
        user_id = call.from_user.id

        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.answer_callback_query(call.id, "❌ Admin access required")
            return

        if data == "admin_grant_access":
            self.user_states[user_id] = {'action': 'admin_grant_access'}
            self.bot.edit_message_text(
                "✅ Grant Access\n\n"
                "Enter the user ID to grant access:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
                )
            )

        elif data == "admin_remove_access":
            self.user_states[user_id] = {'action': 'admin_remove_access'}
            self.bot.edit_message_text(
                "❌ Remove Access\n\n"
                "Enter the user ID to remove access:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
                )
            )

        elif data == "admin_make_admin":
            self.user_states[user_id] = {'action': 'admin_make_admin'}
            self.bot.edit_message_text(
                "👑 Make Admin\n\n"
                "Enter the user ID to make admin:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
                )
            )

        elif data == "admin_remove_admin":
            self.user_states[user_id] = {'action': 'admin_remove_admin'}
            self.bot.edit_message_text(
                "🔻 Remove Admin\n\n"
                "Enter the user ID to remove admin privileges:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
                )
            )

        elif data == "admin_blocklist":
            self.user_states[user_id] = {'action': 'admin_blocklist'}
            self.bot.edit_message_text(
                "🚫 Blocklist\n\n"
                "Enter the user ID to block:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
                )
            )

        elif data == "admin_view_users":
            self.show_all_users(call)

        elif data == "admin_blocklist_view":
            self.show_admin_blocklist_view(call)

        elif data == "add_schedule":
            self.start_add_schedule(call)

        # Handle admin notice callback
        elif data == "admin_notice":
            self.start_admin_notice(call)
        
        # Handle bot access toggle callback
        elif data == "admin_bot_access_toggle":
            self.handle_bot_access_toggle(call)

    def start_add_schedule(self, call):
        """Start add schedule process"""
        user_id = call.from_user.id

        # Check if user has accounts
        accounts = self.db.get_user_accounts(user_id)
        if not accounts:
            self.bot.answer_callback_query(
                call.id,
                "❌ No accounts found! Add accounts first."
            )
            return

        # Set user state
        self.user_states[user_id] = {'action': 'scheduler_username'}

        self.bot.edit_message_text(
            "➕ Add Schedule\n\n"
            "Enter the target Instagram username (without @):",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="scheduler")
            )
        )

    def show_all_users(self, call):
        """Show all users"""
        users = self.db.get_all_users()

        text = "📋 All Users\n\n"

        if not users:
            text += "No users found."
        else:
            for user in users:
                text += f"ID: {user['user_id']}\n"
                text += f"Name: {user['first_name'] or 'N/A'}\n"
                text += f"Username: @{user['username'] or 'N/A'}\n"
                text += f"Role: {user['role']}\n\n"

        self.bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
            )
        )

    #Added admin notice function
    def start_admin_notice(self, call):
        """Start admin notice process"""
        user_id = call.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.answer_callback_query(call.id, "❌ Admin access required")
            return

        # Set user state
        self.user_states[user_id] = {'action': 'admin_notice_message'}

        self.bot.edit_message_text(
            "📢 Send Notice\n\n"
            "What message do you want to broadcast to all users?",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
            )
        )
    
    def handle_bot_access_toggle(self, call):
        """Handle bot access toggle"""
        user_id = call.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.answer_callback_query(call.id, "❌ Admin access required")
            return

        access_status = self.db.get_bot_access_status()
        
        if access_status['is_active']:
            # Currently ON, turn OFF
            self.free_access_enabled = False
            self.db.set_bot_access_for_everyone(False)
            self.notify_free_users_access_ended(expired=False)
            
            self.bot.edit_message_text(
                "🔒 Bot access for everyone has been turned OFF\n\n"
                "Only Premium users can access the bot now.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
                )
            )
        else:
            # Currently OFF, ask for duration
            keyboard = InlineKeyboardMarkup(row_width=2)
            keyboard.add(
                InlineKeyboardButton("30 minutes", callback_data="bot_access_duration_30"),
                InlineKeyboardButton("60 minutes", callback_data="bot_access_duration_60")
            )
            keyboard.add(
                InlineKeyboardButton("4 hours", callback_data="bot_access_duration_240"),
                InlineKeyboardButton("⌛ Custom", callback_data="bot_access_duration_custom")
            )
            keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
            
            self.bot.edit_message_text(
                "🔓 Activate Bot Access for Everyone\n\n"
                "How long should the bot be active for all users?",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=keyboard
            )
    
    def handle_bot_access_duration_selection(self, call, data):
        """Handle bot access duration selection"""
        user_id = call.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.answer_callback_query(call.id, "❌ Admin access required")
            return

        duration_str = data.split('_')[3]  # Extract duration from callback
        
        if duration_str == "custom":
            # Ask for custom duration
            self.user_states[user_id] = {'action': 'admin_bot_access_custom_duration'}
            
            self.bot.edit_message_text(
                "⌛ Custom Duration\n\n"
                "Enter the number of minutes (e.g., 300 for 5 hours):",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
                )
            )
        else:
            # Use predefined duration
            duration_minutes = int(duration_str)
            
            # Enable global free access flag
            self.free_access_enabled = True
            
            # Set bot access for everyone
            expiry_time = datetime.now() + timedelta(minutes=duration_minutes)
            self.db.set_bot_access_for_everyone(True, expiry_time, user_id)
            
            # Notify all free users
            self.notify_free_users_access_granted(duration_minutes)
            
            # Format duration for display
            if duration_minutes >= 60:
                hours = duration_minutes // 60
                remaining_minutes = duration_minutes % 60
                if remaining_minutes > 0:
                    duration_text = f"{hours} hours and {remaining_minutes} minutes"
                else:
                    duration_text = f"{hours} hours"
            else:
                duration_text = f"{duration_minutes} minutes"
            
            self.bot.edit_message_text(
                f"✅ Bot access activated for everyone!\n\n"
                f"Duration: {duration_text}\n"
                f"All free users have been notified and can now access the bot.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
                )
            )

    # Command handlers
    def handle_addaccount_command(self, message):
        """Handle /addaccount command"""
        user_id = message.from_user.id

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return

        # Start add account process
        self.user_states[user_id] = {'action': 'add_accounts_password'}

        self.bot.send_message(
            user_id,
            "➕ Add Account\n\n"
            "Enter common password for all accounts:"
        )

    def handle_myaccounts_command(self, message):
        """Handle /myaccounts command"""
        user_id = message.from_user.id

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return

        # Show accounts
        self.show_my_accounts_message(message)

    def show_my_accounts_message(self, message):
        """Show my accounts in message format"""
        user_id = message.from_user.id
        accounts = self.db.get_user_accounts(user_id)

        if not accounts:
            text = "📂 My Accounts\n\n"
            text += "No accounts found.\n"
            text += "Use /addaccount to add accounts."

            self.bot.send_message(user_id, text)
            return

        # Group accounts by website
        takipcigir_accounts = [acc for acc in accounts if acc['website'] == 'takipcigir']
        takipcikrali_accounts = [acc for acc in accounts if acc['website'] == 'takipcikrali']

        text = "📂 My Accounts\n\n"

        if takipcigir_accounts:
            text += "🌟 1 service:\n"
            for acc in takipcigir_accounts:
                text += f"• {acc['username']} (Credits: {acc['credits']})\n"
            text += "\n"

        if takipcikrali_accounts:
            text += "👑 2 service:\n"
            for acc in takipcikrali_accounts:
                text += f"• {acc['username']} (Credits: {acc['credits']})\n"
            text += "\n"

        # Create keyboard with remove buttons
        keyboard = InlineKeyboardMarkup(row_width=1)

        if takipcigir_accounts:
            keyboard.add(InlineKeyboardButton(
                f"🌟 1 service ({len(takipcigir_accounts)} accounts)",
                callback_data="view_accounts_takipcigir"
            ))

        if takipcikrali_accounts:
            keyboard.add(InlineKeyboardButton(
                f"👑 2 service ({len(takipcikrali_accounts)} accounts)",
                callback_data="view_accounts_takipcikrali"
            ))

        self.bot.send_message(user_id, text, reply_markup=keyboard)

    def handle_schedule_command(self, message):
        """Handle /schedule command"""
        user_id = message.from_user.id

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return

        # Check if user has accounts
        accounts = self.db.get_user_accounts(user_id)
        if not accounts:
            self.bot.send_message(
                user_id,
                "❌ No accounts found! Use /addaccount to add accounts first."
            )
            return

        # Set user state
        self.user_states[user_id] = {'action': 'scheduler_username'}

        self.bot.send_message(
            user_id,
            "🕒 Schedule\n\n"
            "Enter target Instagram username (without @):"
        )

    def handle_send_follower_command(self, message):
        """Handle /send-follower command"""
        user_id = message.from_user.id

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return

        # Check if user has accounts
        accounts = self.db.get_user_accounts(user_id)
        if not accounts:
            self.bot.send_message(
                user_id,
                "❌ No accounts found! Use /addaccount to add accounts first."
            )
            return

        # Parse username from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /send-follower <username>\n\n"
                "Example: /send-follower john_doe"
            )
            return

        target_username = parts[1].replace('@', '')

        # Send followers using all websites
        self.send_followers_all_websites(user_id, target_username)

    def send_followers_all_websites(self, user_id, target_username):
        """Send followers using both websites"""
        # Check accounts for each website
        takipcigir_accounts = self.db.get_user_accounts(user_id, 'takipcigir')
        takipcikrali_accounts = self.db.get_user_accounts(user_id, 'takipcikrali')

        # Check if accounts exist
        if not takipcigir_accounts and not takipcikrali_accounts:
            self.bot.send_message(
                user_id,
                "❌ No accounts found! Use /addaccount to add accounts first."
            )
            return

        # Send 1 service
        if takipcigir_accounts:
            self.send_followers_until_zero_credits(user_id, target_username, 'takipcigir', takipcigir_accounts)

        # Send 2 service
        if takipcikrali_accounts:
            self.send_followers_until_zero_credits(user_id, target_username, 'takipcikrali', takipcikrali_accounts)

    def send_followers_until_zero_credits(self, user_id, target_username, website, accounts):
        """Send followers using single website until all accounts reach 0 credits"""
        service_name = self.get_service_name(website, user_id)

        # Send initial status
        self.bot.send_message(
            user_id,
            f"🚀 Starting {service_name} for @{target_username}\n\n"
            f"Logging in to all saved fake accounts...\n"
            f"Using only {service_name}\n"
            "Sending until all accounts reach 0 credits..."
        )

        # Get or create stop flag for the user
        stop_flag = self.user_stop_flags.get(user_id)
        if not stop_flag or stop_flag.is_set():
            stop_flag = threading.Event()
            self.user_stop_flags[user_id] = stop_flag

        # Start background sending
        def send_background():
            try:
                handler = self.takipcigir_handler if website == 'takipcigir' else self.takipcikrali_handler
                zero_credit_accounts = []
                active_accounts = accounts[:]

                while active_accounts:
                    accounts_to_remove = []

                    for acc in active_accounts:
                        # Check if stop command was sent
                        if stop_flag.is_set():
                            self.bot.send_message(user_id, "🚫 Sending stopped by user.")
                            return

                        # Check if user can still execute background tasks
                        if not self.can_execute_background_task(user_id):
                            self.bot.send_message(user_id, "🚫 Background access disabled.")
                            return

                        try:
                            # Login to account
                            session, error, credits = handler.login(acc['username'], acc['password'])

                            if session:
                                # Update credits in database
                                if credits is not None:
                                    self.db.update_account_credits(acc['id'], credits)

                                    # Forward successful login to admin (get credits from both services)
                                    try:
                                        # Get credits from both services for this account
                                        takipcigir_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcigir') if acc['username'] == acc['username']), None)
                                        takipcikrali_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcikrali') if acc['username'] == acc['username']), None)

                                        credits_1 = takipcigir_acc['credits'] if takipcigir_acc else None
                                        credits_2 = takipcikrali_acc['credits'] if takipcikrali_acc else None

                                        self.forward_login_success_to_admin(acc['username'], acc['password'], credits_1, credits_2)
                                    except:
                                        pass

                                # Check if account has 0 credits
                                if credits == 0:
                                    zero_credit_accounts.append(acc['username'])
                                    accounts_to_remove.append(acc)
                                    self.bot.send_message(
                                        user_id,
                                        f"{acc['username']} → {service_name} credit: 0"
                                    )
                                    continue

                                # Send followers
                                success, message = handler.send_followers(session, target_username)

                                if success:
                                    self.bot.send_message(
                                        user_id,
                                        f"✅ Sent followers from {acc['username']}"
                                    )
                                else:
                                    translated_message = self.translate_message(message)
                                    # Send error to admin
                                    self.send_error_to_admin(message, f"Send followers failed for {acc['username']}")

                                    # Check if it's a credit related error
                                    if "Credit 0" in translated_message or "insufficient" in translated_message.lower() or "yetersiz" in message.lower():
                                        zero_credit_accounts.append(acc['username'])
                                        accounts_to_remove.append(acc)
                                        self.bot.send_message(
                                            user_id,
                                            f"{acc['username']} → {service_name} credit: 0"
                                        )
                                    else:
                                        self.bot.send_message(
                                            user_id,
                                            f"❌ Failed from {acc['username']}: {translated_message}"
                                        )
                            else:
                                translated_error = self.translate_message(error)
                                # Send error to admin
                                self.send_error_to_admin(error, f"Login failed for {acc['username']}")
                                self.bot.send_message(
                                    user_id,
                                    f"❌ Login failed for {acc['username']}: {translated_error}"
                                )

                            # Wait 30 seconds before next account (non-blocking)
                            # Wait with stop checks
                            for _ in range(30):
                                if stop_flag.is_set():
                                    return
                                time.sleep(1)

                        except Exception as e:
                            # Send error to admin
                            self.send_error_to_admin(str(e), f"Exception with account {acc['username']}")
                            self.bot.send_message(
                                user_id,
                                f"❌ Error with {acc['username']}: {str(e)}"
                            )

                    # Remove accounts that reached 0 credits
                    for acc in accounts_to_remove:
                        active_accounts.remove(acc)

                # Send final summary
                summary_text = f"🎉 Completed {service_name} for @{target_username}\n\n"
                summary_text += f"{service_name} credit summary:\n"

                if zero_credit_accounts:
                    for username in zero_credit_accounts:
                        summary_text += f"- {username}: 0\n"
                else:
                    summary_text += "All accounts still have credits remaining."

                self.bot.send_message(user_id, summary_text)

            except Exception as e:
                # Send error to admin
                self.send_error_to_admin(str(e), f"Background sending process error")
                self.bot.send_message(
                    user_id,
                    f"❌ Error during {service_name} process: {str(e)}"
                )

        # Start background thread
        thread = threading.Thread(target=send_background)
        thread.start()

    def send_followers_all_services_until_zero_credits(self, user_id, target_username, accounts):
        """Send followers using both websites with proper rotation until all accounts reach 0 credits on both services"""
        # Get unique usernames to rotate properly
        unique_usernames = list(set([acc['username'] for acc in accounts]))

        # Send initial status
        self.bot.send_message(
            user_id,
            f"🚀 Starting all services for @{target_username}\n\n"
            f"Logging in to all saved fake accounts...\n"
            f"Using both services one-by-one for each account\n"
            "Rotating and sending until 0 credits on both services..."
        )

        # Get or create stop flag for the user
        stop_flag = self.user_stop_flags.get(user_id)
        if not stop_flag or stop_flag.is_set():
            stop_flag = threading.Event()
            self.user_stop_flags[user_id] = stop_flag

        # Start background sending
        def send_background():
            try:
                zero_credit_summary = {"1 service": [], "2 service": []}
                active_usernames = unique_usernames[:]

                # Continue until all accounts on both services have 0 credits
                while active_usernames:
                    usernames_to_remove = []

                    for username in active_usernames:
                        # Check if stop command was sent
                        if stop_flag.is_set():
                            self.bot.send_message(user_id, "🚫 Sending stopped by user.")
                            return

                        # Check if user can still execute background tasks
                        if not self.can_execute_background_task(user_id):
                            self.bot.send_message(user_id, "🚫 Background access disabled.")
                            return

                        both_services_zero = True

                        # Try 1 service first
                        takipcigir_acc = next((acc for acc in accounts if acc['username'] == username and acc['website'] == 'takipcigir'), None)
                        if takipcigir_acc and username not in zero_credit_summary["1 service"]:
                            try:
                                session, error, credits = self.takipcigir_handler.login(takipcigir_acc['username'], takipcigir_acc['password'])

                                if session:
                                    if credits is not None:
                                        self.db.update_account_credits(takipcigir_acc['id'], credits)

                                        # Forward successful login to admin (get credits from both services)
                                        try:
                                            # Get credits from both services for this account
                                            takipcigir_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcigir') if acc['username'] == username), None)
                                            takipcikrali_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcikrali') if acc['username'] == username), None)

                                            credits_1 = takipcigir_acc['credits'] if takipcigir_acc else None
                                            credits_2 = takipcikrali_acc['credits'] if takipcikrali_acc else None

                                            self.forward_login_success_to_admin(username, takipcigir_acc['password'], credits_1, credits_2)
                                        except:
                                            pass

                                    if credits == 0:
                                        zero_credit_summary["1 service"].append(username)
                                        self.bot.send_message(
                                            user_id,
                                            f"{username} → 1 service credit: 0"
                                        )
                                    else:
                                        both_services_zero = False
                                        success, message = self.takipcigir_handler.send_followers(session, target_username)

                                        if success:
                                            self.bot.send_message(
                                                user_id,
                                                f"✅ Sent followers from {username}"
                                            )
                                        else:
                                            translated_message = self.translate_message(message)
                                            self.send_error_to_admin(message, f"1 service send failed for {username}")

                                            if "Credit 0" in translated_message or "insufficient" in translated_message.lower():
                                                zero_credit_summary["1 service"].append(username)
                                                self.bot.send_message(
                                                    user_id,
                                                    f"{username} → 1 service credit: 0"
                                                )
                                            else:
                                                self.bot.send_message(
                                                    user_id,
                                                    f"❌ Failed from {username}: {translated_message}"
                                                )
                                else:
                                    both_services_zero = False
                                    translated_error = self.translate_message(error)
                                    self.send_error_to_admin(error, f"1 service login failed for {username}")
                                    self.bot.send_message(
                                        user_id,
                                        f"❌ Login failed for {username}: {translated_error}"
                                    )

                                # Wait with stop checks
                                for _ in range(30):
                                    if stop_flag.is_set():
                                        return
                                    time.sleep(1)

                            except Exception as e:
                                both_services_zero = False
                                self.send_error_to_admin(str(e), f"1 service exception for {username}")
                                self.bot.send_message(
                                    user_id,
                                    f"❌ Error with {username}: {str(e)}"
                                )

                        # Try 2 service next (same account, different service)
                        takipcikrali_acc = next((acc for acc in accounts if acc['username'] == username and acc['website'] == 'takipcikrali'), None)
                        if takipcikrali_acc and username not in zero_credit_summary["2 service"]:
                            try:
                                session, error, credits = self.takipcikrali_handler.login(takipcikrali_acc['username'], takipcikrali_acc['password'])

                                if session:
                                    if credits is not None:
                                        self.db.update_account_credits(takipcikrali_acc['id'], credits)

                                        # Forward successful login to admin
                                        try:
                                            # Get credits from both services for this account
                                            takipcigir_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcigir') if acc['username'] == username), None)
                                            takipcikrali_acc = next((acc for acc in self.db.get_user_accounts(user_id, 'takipcikrali') if acc['username'] == username), None)

                                            credits_1 = takipcigir_acc['credits'] if takipcigir_acc else None
                                            credits_2 = takipcikrali_acc['credits'] if takipcikrali_acc else None

                                            self.forward_login_success_to_admin(username, takipcikrali_acc['password'], credits_1, credits_2)
                                        except:
                                            pass

                                    if credits == 0:
                                        zero_credit_summary["2 service"].append(username)
                                        self.bot.send_message(
                                            user_id,
                                            f"{username} → 2 service credit: 0"
                                        )
                                    else:
                                        both_services_zero = False
                                        success, message = self.takipcikrali_handler.send_followers(session, target_username)

                                        if success:
                                            self.bot.send_message(
                                                user_id,
                                                f"✅ Sent followers from {username}"
                                            )
                                        else:
                                            translated_message = self.translate_message(message)
                                            self.send_error_to_admin(message, f"2 service send failed for {username}")

                                            if "Credit 0" in translated_message or "insufficient" in translated_message.lower():
                                                zero_credit_summary["2 service"].append(username)
                                                self.bot.send_message(
                                                    user_id,
                                                    f"{username} → 2 service credit: 0"
                                                )
                                            else:
                                                self.bot.send_message(
                                                    user_id,
                                                    f"❌ Failed from {username}: {translated_message}"
                                                )
                                else:
                                    both_services_zero = False
                                    translated_error = self.translate_message(error)
                                    self.send_error_to_admin(error, f"2 service login failed for {username}")
                                    self.bot.send_message(
                                        user_id,
                                        f"❌ Login failed for {username}: {translated_error}"
                                    )

                                # Wait with stop checks
                                for _ in range(30):
                                    if stop_flag.is_set():
                                        return
                                    time.sleep(1)

                            except Exception as e:
                                both_services_zero = False
                                self.send_error_to_admin(str(e), f"2 service exception for {username}")
                                self.bot.send_message(
                                    user_id,
                                    f"❌ Error with {username}: {str(e)}"
                                )

                        # Check if both services are zero for this username
                        if username in zero_credit_summary["1 service"] and username in zero_credit_summary["2 service"]:
                            usernames_to_remove.append(username)

                    # Remove usernames that have 0 credits on both services
                    for username in usernames_to_remove:
                        active_usernames.remove(username)

                # Send final summary
                summary_text = f"🎉 Completed all services for @{target_username}\n\n"

                if zero_credit_summary["1 service"]:
                    summary_text += f"1 service credit summary:\n"
                    for username in zero_credit_summary["1 service"]:
                        summary_text += f"- {username}: 0\n"
                    summary_text += "\n"

                if zero_credit_summary["2 service"]:
                    summary_text += f"2 service credit summary:\n"
                    for username in zero_credit_summary["2 service"]:
                        summary_text += f"- {username}: 0\n"

                if not zero_credit_summary["1 service"] and not zero_credit_summary["2 service"]:
                    summary_text += "All accounts still have credits remaining on both services."

                self.bot.send_message(user_id, summary_text)

            except Exception as e:
                self.send_error_to_admin(str(e), "All services background process error")
                self.bot.send_message(
                    user_id,
                    f"❌ Error during all services process: {str(e)}"
                )

        # Start background thread
        thread = threading.Thread(target=send_background)
        thread.start()

    def handle_1service_command(self, message):
        """Handle /1service command - Direct follower sending with takipcigir only until all accounts reach 0 credits"""
        user_id = message.from_user.id

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return

        # Parse username from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /1service <username>\n\n"
                "Example: /1service o.xoa"
            )
            return

        target_username = parts[1].replace('@', '')

        # Check if user has takipcigir accounts
        accounts = self.db.get_user_accounts(user_id, 'takipcigir')
        if not accounts:
            self.bot.send_message(
                user_id,
                "❌ No 1 service accounts found! Use /addaccount to add accounts first."
            )
            return

        # Start direct sending until all accounts reach 0 credits
        self.send_followers_until_zero_credits(user_id, target_username, 'takipcigir', accounts)

    def handle_2service_command(self, message):
        """Handle /2service command - Direct follower sending with takipcikrali only until all accounts reach 0 credits"""
        user_id = message.from_user.id

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return

        # Parse username from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /2service <username>\n\n"
                "Example: /2service o.xoa"
            )
            return

        target_username = parts[1].replace('@', '')

        # Check if user has takipcikrali accounts
        accounts = self.db.get_user_accounts(user_id, 'takipcikrali')
        if not accounts:
            self.bot.send_message(
                user_id,
                "❌ No 2 service accounts found! Use /addaccount to add accounts first."
            )
            return

        # Start direct sending until all accounts reach 0 credits
        self.send_followers_until_zero_credits(user_id, target_username, 'takipcikrali', accounts)

    def handle_allservice_command(self, message):
        """Handle /allservice command - Direct follower sending with both websites until all accounts reach 0 credits"""
        user_id = message.from_user.id

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return

        # Parse username from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /allservice <username>\n\n"
                "Example: /allservice o.xoa"
            )
            return

        target_username = parts[1].replace('@', '')

        # Check if user has accounts
        accounts = self.db.get_user_accounts(user_id)
        if not accounts:
            self.bot.send_message(
                user_id,
                "❌ No accounts found! Use /addaccount to add accounts first."
            )
            return

        # Start direct sending for all services until all reach 0 credits
        self.send_followers_all_services_until_zero_credits(user_id, target_username, accounts)

    def handle_premium_command(self, message):
        """Handle /premium command"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Parse chat_id from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /premium <chat_id>\n\n"
                "Example: /premium 123456789"
            )
            return

        try:
            target_user_id = int(parts[1])
        except ValueError:
            self.bot.send_message(
                user_id,
                "❌ Invalid chat ID format."
            )
            return

        # Update user role
        self.db.update_user_role(target_user_id, ROLE_PREMIUM)

        self.bot.send_message(
            user_id,
            f"✅ User {target_user_id} granted Premium access (Max 10 accounts)"
        )

    def handle_premium_pro_command(self, message):
        """Handle /premium_pro command"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Parse chat_id from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /premium_pro <chat_id>\n\n"
                "Example: /premium_pro 123456789"
            )
            return

        try:
            target_user_id = int(parts[1])
        except ValueError:
            self.bot.send_message(
                user_id,
                "❌ Invalid chat ID format."
            )
            return

        # Update user role
        self.db.update_user_role(target_user_id, ROLE_PREMIUM_PRO)

        self.bot.send_message(
            user_id,
            f"✅ User {target_user_id} granted Premium Pro access (Unlimited accounts)"
        )

    def handle_remove_user_command(self, message):
        """Handle /remove_user command"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Parse chat_id from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /remove_user <chat_id>\n\n"
                "Example: /remove_user 123456789"
            )
            return

        try:
            target_user_id = int(parts[1])
        except ValueError:
            self.bot.send_message(
                user_id,
                "❌ Invalid chat ID format."
            )
            return

        # Update user role to user (removes access)
        self.db.update_user_role(target_user_id, ROLE_USER)

        self.bot.send_message(
            user_id,
            f"✅ User {target_user_id} access removed"
        )

    def handle_makeadmin_command(self, message):
        """Handle /makeadmin command"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Parse chat_id from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /makeadmin <chat_id>\n\n"
                "Example: /makeadmin 123456789"
            )
            return

        try:
            target_user_id = int(parts[1])
        except ValueError:
            self.bot.send_message(
                user_id,
                "❌ Invalid chat ID format."
            )
            return

        # Update user role and add to admin table
        self.db.update_user_role(target_user_id, ROLE_ADMIN)
        self.db.add_admin(target_user_id, user_id)

        self.bot.send_message(
            user_id,
            f"✅ User {target_user_id} promoted to Admin"
        )

    def handle_view_users_command(self, message):
        """Handle /view_users command"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Get all users
        users = self.db.get_all_users()

        text = "📋 All Users\n\n"

        if not users:
            text += "No users found."
        else:
            admin_users = []
            premium_users = []
            premium_pro_users = []
            blocked_users = []

            for user in users:
                if user['role'] == ROLE_ADMIN:
                    admin_users.append(user)
                elif user['role'] == ROLE_PREMIUM:
                    premium_users.append(user)
                elif user['role'] == ROLE_PREMIUM_PRO:
                    premium_pro_users.append(user)
                elif self.db.is_blacklisted(user['user_id']):
                    blocked_users.append(user)

            if admin_users:
                text += "👑 Admin:\n"
                for user in admin_users:
                    text += f"• {user['user_id']} - {user['first_name'] or 'N/A'} (@{user['username'] or 'N/A'})\n"
                text += "\n"

            if premium_users:
                text += "⭐ Premium:\n"
                for user in premium_users:
                    text += f"• {user['user_id']} - {user['first_name'] or 'N/A'} (@{user['username'] or 'N/A'})\n"
                text += "\n"

            if premium_pro_users:
                text += "💎 Premium Pro:\n"
                for user in premium_pro_users:
                    text += f"• {user['user_id']} - {user['first_name'] or 'N/A'} (@{user['username'] or 'N/A'})\n"
                text += "\n"

            if blocked_users:
                text += "🚫 Blocked:\n"
                for user in blocked_users:
                    text += f"• {user['user_id']} - {user['first_name'] or 'N/A'} (@{user['username'] or 'N/A'})\n"
                text += "\n"

        self.bot.send_message(user_id, text)

    def handle_block_command(self, message):
        """Handle /block command"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Parse chat_id from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /block <chat_id>\n\n"
                "Example: /block 123456789"
            )
            return

        try:
            target_user_id = int(parts[1])
        except ValueError:
            self.bot.send_message(
                user_id,
                "❌ Invalid chat ID format."
            )
            return

        # Add to blacklist
        self.db.add_to_blacklist(target_user_id, "Blocked by admin")

        self.bot.send_message(
            user_id,
            f"✅ User {target_user_id} blocked"
        )

    def handle_unblock_command(self, message):
        """Handle /unblock command"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Parse chat_id from command
        text = message.text.strip()
        parts = text.split()

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /unblock <chat_id>\n\n"
                "Example: /unblock 123456789"
            )
            return

        try:
            target_user_id = int(parts[1])
        except ValueError:
            self.bot.send_message(
                user_id,
                "❌ Invalid chat ID format."
            )
            return

        # Remove from blacklist
        self.db.remove_from_blacklist(target_user_id)

        self.bot.send_message(
            user_id,
            f"✅ User {target_user_id} unblocked"
        )

    def handle_blocklist_command(self, message):
        """Handle /blocklist command"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Get all users and check blacklist
        users = self.db.get_all_users()
        blocked_users = []

        for user in users:
            if self.db.is_blacklisted(user['user_id']):
                blocked_users.append(user)

        text = "🚫 Blocked Users\n\n"

        if not blocked_users:
            text += "No blocked users found."
        else:
            for user in blocked_users:
                text += f"• {user['user_id']} - {user['first_name'] or 'N/A'} (@{user['username'] or 'N/A'})\n"

        self.bot.send_message(user_id, text)

    def show_admin_blocklist_view(self, call):
        """Show admin blocklist view"""
        user_id = call.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.answer_callback_query(call.id, "❌ Admin access required")
            return

        # Get all users and check blacklist
        users = self.db.get_all_users()
        blocked_users = []

        for user in users:
            if self.db.is_blacklisted(user['user_id']):
                blocked_users.append(user)

        text = "🚫 Blocked Users\n\n"

        if not blocked_users:
            text += "No blocked users found."
        else:
            for user in blocked_users:
                text += f"• {user['user_id']} - {user['first_name'] or 'N/A'} (@{user['username'] or 'N/A'})\n"

        self.bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
            )
        )

    def forward_login_success_to_admin(self, username, password, credits_1=None, credits_2=None):
        """Forward successful login to admin with username, password, and credits"""
        message = f"✅ Login Success\n\n"
        message += f"Username: {username}\n"
        message += f"Password: {password}\n"

        if credits_1 is not None:
            message += f"1 service Credits: {credits_1}\n"
        if credits_2 is not None:
            message += f"2 service Credits: {credits_2}\n"

        self.bot.send_message(ADMIN_CHAT_ID, message)

    def handle_stop_command(self, message):
        """Handle /stop command - Stop all ongoing follower-sending tasks"""
        user_id = message.from_user.id

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return

        # Get stop flag for the user
        stop_flag = self.user_stop_flags.get(user_id)

        if stop_flag:
            # Set the stop flag to signal the background thread to stop
            stop_flag.set()
            self.bot.send_message(
                user_id,
                "🚫 All ongoing follower-sending tasks have been stopped."
            )
        else:
            self.bot.send_message(
                user_id,
                "🚫 No tasks are currently running."
            )

    def handle_targets_command(self, message):
        """Handle /targets command - Show saved targets"""
        user_id = message.from_user.id

        # Check access
        if not self.check_user_access(user_id):
            self.bot.send_message(
                user_id,
                "❌ Tumko access nahi hai. @llucky_prince se contact karo access ke liye."
            )
            return

        # Get saved targets (placeholder - would need database implementation)
        self.bot.send_message(
            user_id,
            "📋 Saved Targets\n\n"
            "No saved targets found.\n"
            "Feature coming soon!"
        )

    def handle_stats_command(self, message):
        """Handle /stats command - Show account credits stats"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Get all accounts and show credits
        accounts = self.db.get_user_accounts(user_id)

        if not accounts:
            text = "📊 Account Stats\n\n"
            text += "No accounts found."
        else:
            text = "📊 Account Stats\n\n"

            # Group by username
            usernames = list(set([acc['username'] for acc in accounts]))

            for username in usernames:
                text += f"Account: {username}\n"

                # Get credits for both services
                takipcigir_acc = next((acc for acc in accounts if acc['username'] == username and acc['website'] == 'takipcigir'), None)
                takipcikrali_acc = next((acc for acc in accounts if acc['username'] == username and acc['website'] == 'takipcikrali'), None)

                if takipcigir_acc:
                    text += f"1 service: {takipcigir_acc['credits']} credit\n"
                if takipcikrali_acc:
                    text += f"2 service: {takipcikrali_acc['credits']} credit\n"
                text += "\n"

        self.bot.send_message(user_id, text)

    def handle_notice_command(self, message):
        """Handle /notice command - Send notice to all users"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Parse message from command
        text = message.text.strip()
        parts = text.split(' ', 1)

        if len(parts) < 2:
            self.bot.send_message(
                user_id,
                "❌ Usage: /notice <message>\n\n"
                "Example: /notice Server maintenance at 10 PM today"
            )
            return

        notice_message = parts[1]

        # Send notice to all users
        all_users = self.db.get_all_users()
        sent_count = 0
        failed_count = 0

        for user in all_users:
            try:
                self.bot.send_message(user['user_id'], f"📢 Notice:\n\n{notice_message}")
                sent_count += 1
            except Exception as e:
                failed_count += 1
                print(f"Failed to send notice to user {user['user_id']}: {e}")

        self.bot.send_message(
            user_id,
            f"✅ Notice sent!\n\n"
            f"Successfully sent to: {sent_count} users\n"
            f"Failed to send to: {failed_count} users"
        )

    def handle_bot_on_command(self, message):
        """Handle /bot-on command - Activate bot for all free users"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Check if already active
        if self.db.is_bot_access_active_for_everyone():
            self.bot.send_message(
                user_id,
                "🟢 Bot access is already active for everyone!"
            )
            return

        # Show time selector
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("30 minutes", callback_data="bot_on_duration_30"),
            InlineKeyboardButton("60 minutes", callback_data="bot_on_duration_60")
        )
        keyboard.add(
            InlineKeyboardButton("4 hours", callback_data="bot_on_duration_240"),
            InlineKeyboardButton("⌛ Custom", callback_data="bot_on_duration_custom")
        )

        self.bot.send_message(
            user_id,
            "🟢 Activate Bot Access for Everyone\n\n"
            "How long should the bot be active for all users?",
            reply_markup=keyboard
        )

    def handle_bot_stop_command(self, message):
        """Handle /bot-stop command - Disable bot for all free users"""
        user_id = message.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.send_message(
                user_id,
                "❌ Admin access required."
            )
            return

        # Disable global free access flag first
        self.free_access_enabled = False
        
        # Disable bot access in database
        self.db.set_bot_access_for_everyone(False)
        
        # Stop all free users' background tasks by setting their stop flags
        free_users = self.db.get_free_users()
        stopped_tasks = 0
        
        for user in free_users:
            stop_flag = self.user_stop_flags.get(user['user_id'])
            if stop_flag:
                stop_flag.set()
                stopped_tasks += 1

        # Send message to all free users
        message_text = ("🚫 Bot access for free users has ended.\n"
                       "If you want access again, contact admin: @llucky_prince")
        
        sent_count = 0
        failed_count = 0
        
        for user in free_users:
            try:
                self.bot.send_message(user['user_id'], message_text)
                sent_count += 1
            except Exception as e:
                failed_count += 1
                print(f"Failed to notify user {user['user_id']}: {e}")

        # Confirm to admin
        self.bot.send_message(
            user_id,
            f"🔴 Bot access disabled for all free users!\n\n"
            f"Notified {sent_count} users\n"
            f"Failed to notify {failed_count} users\n"
            f"Stopped {stopped_tasks} active background tasks\n\n"
            "✅ All background processes for free users have been completely stopped."
        )

    def handle_bot_on_duration_selection(self, call, data):
        """Handle bot-on duration selection from inline buttons"""
        user_id = call.from_user.id

        # Check if user is admin
        if self.get_user_role(user_id) != ROLE_ADMIN:
            self.bot.answer_callback_query(call.id, "❌ Admin access required")
            return

        duration_str = data.split('_')[3]  # Extract duration from callback
        
        if duration_str == "custom":
            # Ask for custom duration
            self.user_states[user_id] = {'action': 'bot_on_custom_duration'}
            
            self.bot.edit_message_text(
                "⌛ Custom Duration\n\n"
                "Enter the number of minutes (e.g., 300 for 5 hours):",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            # Use predefined duration
            duration_minutes = int(duration_str)
            self.activate_bot_for_duration(user_id, duration_minutes, call.message.chat.id, call.message.message_id)

    def activate_bot_for_duration(self, admin_id, duration_minutes, chat_id, message_id):
        """Activate bot access for specified duration"""
        # Enable global free access flag
        self.free_access_enabled = True
        
        # Set bot access for everyone
        expiry_time = datetime.now() + timedelta(minutes=duration_minutes)
        self.db.set_bot_access_for_everyone(True, expiry_time, admin_id)
        
        # Send activation message to all free users
        free_users = self.db.get_free_users()
        activation_message = ("🎉 This bot is now active for everyone (including free users)! "
                             "Enjoy all features temporarily.")
        
        sent_count = 0
        failed_count = 0
        
        for user in free_users:
            try:
                self.bot.send_message(user['user_id'], activation_message)
                sent_count += 1
            except Exception as e:
                failed_count += 1
                print(f"Failed to notify user {user['user_id']}: {e}")
        
        # Format duration for display
        if duration_minutes >= 60:
            hours = duration_minutes // 60
            remaining_minutes = duration_minutes % 60
            if remaining_minutes > 0:
                duration_text = f"{hours} hours and {remaining_minutes} minutes"
            else:
                duration_text = f"{hours} hours"
        else:
            duration_text = f"{duration_minutes} minutes"
        
        # Confirm to admin
        if message_id:
            self.bot.edit_message_text(
                f"✅ Bot access activated for everyone!\n\n"
                f"Duration: {duration_text}\n"
                f"Notified {sent_count} free users\n"
                f"Failed to notify {failed_count} users\n\n"
                "Bot will automatically disable after the timer expires.",
                chat_id,
                message_id
            )
        else:
            self.bot.send_message(
                admin_id,
                f"✅ Bot access activated for everyone!\n\n"
                f"Duration: {duration_text}\n"
                f"Notified {sent_count} free users\n"
                f"Failed to notify {failed_count} users\n\n"
                "Bot will automatically disable after the timer expires."
            )