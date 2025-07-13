import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from config import DATABASE_URL

class Database:
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # User accounts table (for storing website accounts)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                website TEXT,
                username TEXT,
                password TEXT,
                credits INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Saved targets table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saved_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                target_username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Blacklist table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Admin table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Scheduler table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scheduler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                target_username TEXT,
                website TEXT,
                interval_minutes INTEGER,
                last_run TIMESTAMP,
                next_run TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Bot access control table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_access_control (
                id INTEGER PRIMARY KEY,
                is_active INTEGER DEFAULT 0,
                expiry_time TIMESTAMP,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Initialize bot access control with default OFF state
        cursor.execute('''
            INSERT OR IGNORE INTO bot_access_control (id, is_active) VALUES (1, 0)
        ''')
        
        conn.commit()
        conn.close()
    
    def get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)
    
    def add_user(self, user_id: int, username: str = None, first_name: str = None, role: str = 'user'):
        """Add or update user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, role, last_active)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, role, datetime.now()))
        
        conn.commit()
        conn.close()
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        
        conn.close()
        
        if row:
            return {
                'user_id': row[0],
                'username': row[1],
                'first_name': row[2],
                'role': row[3],
                'created_at': row[4],
                'last_active': row[5]
            }
        return None
    
    def update_user_role(self, user_id: int, role: str):
        """Update user role"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', (role, user_id))
        
        conn.commit()
        conn.close()
    
    def is_blacklisted(self, user_id: int) -> bool:
        """Check if user is blacklisted"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM blacklist WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
    
    def add_to_blacklist(self, user_id: int, reason: str = ""):
        """Add user to blacklist"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('INSERT OR REPLACE INTO blacklist (user_id, reason) VALUES (?, ?)', 
                      (user_id, reason))
        
        conn.commit()
        conn.close()
    
    def remove_from_blacklist(self, user_id: int):
        """Remove user from blacklist"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM blacklist WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        conn.close()
        return result is not None
    
    def add_admin(self, user_id: int, added_by: int):
        """Add admin"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('INSERT OR REPLACE INTO admins (user_id, added_by) VALUES (?, ?)', 
                      (user_id, added_by))
        
        conn.commit()
        conn.close()
    
    def remove_admin(self, user_id: int):
        """Remove admin"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
    
    def add_user_account(self, user_id: int, website: str, username: str, password: str):
        """Add user account for website"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO user_accounts (user_id, website, username, password)
            VALUES (?, ?, ?, ?)
        ''', (user_id, website, username, password))
        
        conn.commit()
        conn.close()
    
    def get_user_accounts(self, user_id: int, website: str = None) -> List[Dict]:
        """Get user accounts"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if website:
            cursor.execute('''
                SELECT id, website, username, password, credits, status, created_at
                FROM user_accounts WHERE user_id = ? AND website = ?
            ''', (user_id, website))
        else:
            cursor.execute('''
                SELECT id, website, username, password, credits, status, created_at
                FROM user_accounts WHERE user_id = ?
            ''', (user_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        accounts = []
        for row in rows:
            accounts.append({
                'id': row[0],
                'website': row[1],
                'username': row[2],
                'password': row[3],
                'credits': row[4],
                'status': row[5],
                'created_at': row[6]
            })
        
        return accounts
    
    def update_account_credits(self, account_id: int, credits: int):
        """Update account credits"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE user_accounts SET credits = ? WHERE id = ?', 
                      (credits, account_id))
        
        conn.commit()
        conn.close()
    
    def count_user_accounts(self, user_id: int) -> int:
        """Count user accounts"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM user_accounts WHERE user_id = ?', (user_id,))
        count = cursor.fetchone()[0]
        
        conn.close()
        return count
    
    def remove_user_account(self, account_id: int, user_id: int):
        """Remove user account"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM user_accounts WHERE id = ? AND user_id = ?', 
                      (account_id, user_id))
        
        conn.commit()
        conn.close()
    
    def add_saved_target(self, user_id: int, target_username: str):
        """Add saved target"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('INSERT INTO saved_targets (user_id, target_username) VALUES (?, ?)', 
                      (user_id, target_username))
        
        conn.commit()
        conn.close()
    
    def get_saved_targets(self, user_id: int) -> List[str]:
        """Get saved targets"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT target_username FROM saved_targets WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        
        conn.close()
        return [row[0] for row in rows]
    
    def remove_saved_target(self, user_id: int, target_username: str):
        """Remove saved target"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM saved_targets WHERE user_id = ? AND target_username = ?', 
                      (user_id, target_username))
        
        conn.commit()
        conn.close()
    
    def get_all_users(self) -> List[Dict]:
        """Get all users"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id, username, first_name, role FROM users')
        rows = cursor.fetchall()
        
        conn.close()
        
        users = []
        for row in rows:
            users.append({
                'user_id': row[0],
                'username': row[1],
                'first_name': row[2],
                'role': row[3]
            })
        
        return users
    
    def add_scheduler_task(self, user_id: int, target_username: str, website: str, interval_minutes: int):
        """Add scheduler task"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        next_run = datetime.now()
        
        cursor.execute('''
            INSERT INTO scheduler (user_id, target_username, website, interval_minutes, next_run)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, target_username, website, interval_minutes, next_run))
        
        conn.commit()
        conn.close()
    
    def get_scheduler_tasks(self, user_id: int) -> List[Dict]:
        """Get scheduler tasks for user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, target_username, website, interval_minutes, last_run, next_run, is_active
            FROM scheduler WHERE user_id = ?
        ''', (user_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        tasks = []
        for row in rows:
            tasks.append({
                'id': row[0],
                'target_username': row[1],
                'website': row[2],
                'interval_minutes': row[3],
                'last_run': row[4],
                'next_run': row[5],
                'is_active': row[6]
            })
        
        return tasks
    
    def get_all_scheduler_tasks(self) -> List[Dict]:
        """Get all active scheduler tasks"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, user_id, target_username, website, interval_minutes, last_run, next_run, is_active
            FROM scheduler WHERE is_active = 1
        ''', )
        
        rows = cursor.fetchall()
        conn.close()
        
        tasks = []
        for row in rows:
            tasks.append({
                'id': row[0],
                'user_id': row[1],
                'target_username': row[2],
                'website': row[3],
                'interval_minutes': row[4],
                'last_run': row[5],
                'next_run': row[6],
                'is_active': row[7]
            })
        
        return tasks
    
    def update_scheduler_task(self, task_id: int, last_run: datetime, next_run: datetime):
        """Update scheduler task run times"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE scheduler SET last_run = ?, next_run = ? WHERE id = ?
        ''', (last_run, next_run, task_id))
        
        conn.commit()
        conn.close()
    
    def remove_scheduler_task(self, task_id: int, user_id: int):
        """Remove scheduler task"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM scheduler WHERE id = ? AND user_id = ?', 
                      (task_id, user_id))
        
        conn.commit()
        conn.close()
    
    def set_bot_access_for_everyone(self, is_active: bool, expiry_time: datetime = None, created_by: int = None):
        """Set bot access for everyone"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE bot_access_control 
            SET is_active = ?, expiry_time = ?, created_by = ?, created_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (int(is_active), expiry_time, created_by))
        
        conn.commit()
        conn.close()
    
    def get_bot_access_status(self) -> Dict:
        """Get bot access status"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT is_active, expiry_time, created_by, created_at FROM bot_access_control WHERE id = 1')
        row = cursor.fetchone()
        
        conn.close()
        
        if row:
            return {
                'is_active': bool(row[0]),
                'expiry_time': row[1],
                'created_by': row[2],
                'created_at': row[3]
            }
        return {'is_active': False, 'expiry_time': None, 'created_by': None, 'created_at': None}
    
    def is_bot_access_active_for_everyone(self) -> bool:
        """Check if bot access is currently active for everyone"""
        status = self.get_bot_access_status()
        
        if not status['is_active']:
            return False
        
        if status['expiry_time']:
            try:
                expiry = datetime.fromisoformat(status['expiry_time'])
                if datetime.now() > expiry:
                    # Expired, update status
                    self.set_bot_access_for_everyone(False)
                    return False
            except:
                return False
        
        return True
    
    def get_free_users(self) -> List[Dict]:
        """Get all users with 'user' role (free users)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id, username, first_name FROM users WHERE role = ?', ('user',))
        rows = cursor.fetchall()
        
        conn.close()
        
        users = []
        for row in rows:
            users.append({
                'user_id': row[0],
                'username': row[1],
                'first_name': row[2]
            })
        
        return users
