import requests
from bs4 import BeautifulSoup
import time
import json
from fake_useragent import UserAgent
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Tuple, Optional

class WebsiteHandler:
    def __init__(self):
        self.ua = UserAgent()
        self.headers = {
            "User-Agent": self.ua.chrome,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "X-Requested-With": "XMLHttpRequest"
        }
        
    def create_session(self):
        """Create session with retries"""
        session = requests.Session()
        session.headers.update(self.headers)
        
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retries))
        
        return session

class TakipciGirHandler(WebsiteHandler):
    def __init__(self):
        super().__init__()
        self.base_url = "https://takipcigir.com"
    
    def login(self, username: str, password: str) -> Tuple[Optional[requests.Session], Optional[str], Optional[int]]:
        """Login to takipcigir.com using the exact logic from working script"""
        session = self.create_session()
        login_url = f"{self.base_url}/login"
        
        try:
            # Get login page
            login_page = session.get(login_url, headers=self.headers, timeout=30)
            if login_page.status_code != 200:
                return None, f"Login page failed: {login_page.status_code}", None
            
            soup = BeautifulSoup(login_page.text, "html.parser")
            form = soup.find("form")
            if not form:
                return None, "Login form not found", None
            
            # Prepare login data
            login_data = {
                "username": username,
                "password": password,
            }
            
            # Add hidden fields (CSRF tokens etc.)
            for input_field in form.find_all("input"):
                if input_field.get("name") and input_field.get("type") == "hidden":
                    login_data[input_field.get("name")] = input_field.get("value")
            
            # Submit login
            form_action = form.get("action") or login_url
            if not form_action.startswith("http"):
                form_action = self.base_url + form_action
            
            login_post = session.post(form_action, data=login_data, headers=self.headers, timeout=30, allow_redirects=True)
            
            # Check response
            try:
                login_response = json.loads(login_post.text)
                if "Güvenliksiz giriş tespit edildi" in login_response.get("error", "") or "Unsecured login detected" in login_response.get("error", ""):
                    return None, "Unsecured login detected - manual approval required", None
                elif login_response.get("status") == "success":
                    redirect_url = login_response.get("returnUrl")
                    if redirect_url:
                        redirected_page = session.get(self.base_url + redirect_url, headers=self.headers, timeout=30)
                        soup = BeautifulSoup(redirected_page.text, "html.parser")
                        if (
                            "Hoşgeldiniz" in redirected_page.text
                            or "panel" in redirected_page.url.lower()
                            or soup.find("a", href=True, string=lambda t: t and "Çıkış" in t)
                        ):
                            # Login successful, get credits
                            credits = self.fetch_credits(session)
                            return session, None, credits
                        else:
                            return None, "Login failed after redirect", None
                    else:
                        return None, "Redirect URL not found", None
                else:
                    return None, f"Login failed: {login_response.get('message', 'Unknown error')}", None
            except json.JSONDecodeError:
                if "Kullanıcı adı veya şifre hatalı" in login_post.text:
                    return None, "Username or password incorrect", None
                elif "Hesabınız askıya alınmıştır" in login_post.text:
                    return None, "Account suspended", None
                elif "Güvenlik kodu" in login_post.text or "captcha" in login_post.text.lower():
                    return None, "Captcha required", None
                else:
                    return None, "Login failed - unknown error", None
                    
        except Exception as e:
            return None, f"Login error: {str(e)}", None
    
    def fetch_credits(self, session: requests.Session) -> Optional[int]:
        """Fetch account credits using exact logic from working script"""
        try:
            response = session.get(f"{self.base_url}/tools", headers=self.headers, timeout=30)
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            credits_element = soup.find("span", {"id": "takipKrediCount"})
            if credits_element:
                return int(credits_element.text)
            return None
        except Exception:
            return None
    
    def send_followers(self, session: requests.Session, target_username: str) -> Tuple[bool, str]:
        """Send followers to target"""
        try:
            follower_send_url = f"{self.base_url}/tools/send-follower"
            
            # Get follower page
            response = session.get(follower_send_url, timeout=30)
            if response.status_code != 200:
                return False, f"Follower page failed: {response.status_code}"
            
            soup = BeautifulSoup(response.text, "html.parser")
            form = soup.find("form", {"method": "post", "action": "?formType=findUserID"})
            if not form:
                return False, "User form not found"
            
            # Find user ID
            find_user_data = {"username": target_username}
            response = session.post(follower_send_url + "?formType=findUserID", 
                                  data=find_user_data, timeout=30, allow_redirects=True)
            
            if response.status_code != 200:
                return False, "User not found"
            
            user_id = response.url.split("/")[-1]
            if not user_id.isdigit():
                return False, "UserID extraction failed"
            
            # Get final send page
            final_send_url = f"{self.base_url}/tools/send-follower/{user_id}"
            response = session.get(final_send_url, timeout=30)
            if response.status_code != 200:
                return False, "Final page failed"
            
            soup = BeautifulSoup(response.text, "html.parser")
            form = soup.find("form", {"id": "formTakip"})
            if not form:
                return False, "Final form not found"
            
            # Send followers
            send_data = {
                "adet": "50",
                "userID": user_id,
                "userName": target_username,
            }
            
            headers = self.headers.copy()
            headers["Accept"] = "application/json"
            
            response = session.post(final_send_url + "?formType=send", 
                                  data=send_data, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return False, "Send request failed"
            
            try:
                response_json = json.loads(response.text)
                if response_json.get("status") == "success":
                    return True, "Followers sent successfully"
                else:
                    return False, response_json.get("message", "Unknown error")
            except json.JSONDecodeError:
                return False, "Invalid response format"
                
        except Exception as e:
            return False, f"Send error: {str(e)}"

class TakipciKraliHandler(WebsiteHandler):
    def __init__(self):
        super().__init__()
        self.base_url = "https://takipcikrali.com"
    
    def login(self, username: str, password: str) -> Tuple[Optional[requests.Session], Optional[str], Optional[int]]:
        """Login to takipcikrali.com"""
        session = self.create_session()
        login_url = f"{self.base_url}/login"
        
        try:
            # Get login page
            login_page = session.get(login_url, timeout=30)
            if login_page.status_code != 200:
                return None, f"Login page failed: {login_page.status_code}", None
            
            soup = BeautifulSoup(login_page.text, "html.parser")
            form = soup.find("form")
            if not form:
                return None, "Login form not found", None
            
            # Prepare login data
            login_data = {
                "username": username,
                "password": password,
            }
            
            # Add hidden fields
            for input_field in form.find_all("input"):
                if input_field.get("name") and input_field.get("type") == "hidden":
                    login_data[input_field.get("name")] = input_field.get("value")
            
            # Submit login
            form_action = form.get("action") or login_url
            if not form_action.startswith("http"):
                form_action = self.base_url + form_action
            
            login_post = session.post(form_action, data=login_data, timeout=30, allow_redirects=True)
            
            # Check response
            try:
                login_response = json.loads(login_post.text)
                if "Güvenliksiz giriş tespit edildi" in login_response.get("error", "") or "Unsecured login detected" in login_response.get("error", ""):
                    return None, "Unsecured login detected - manual approval required", None
                elif login_response.get("status") == "success":
                    redirect_url = login_response.get("returnUrl")
                    if redirect_url:
                        redirected_page = session.get(self.base_url + redirect_url, timeout=30)
                        soup = BeautifulSoup(redirected_page.text, "html.parser")
                        if (
                            "Hoşgeldiniz" in redirected_page.text
                            or "panel" in redirected_page.url.lower()
                            or soup.find("a", href=True, string=lambda t: t and "Çıkış" in t)
                        ):
                            # Login successful, get credits
                            credits = self.fetch_credits(session)
                            return session, None, credits
                        else:
                            return None, "Login failed after redirect", None
                    else:
                        return None, "Redirect URL not found", None
                else:
                    return None, f"Login failed: {login_response.get('message', 'Unknown error')}", None
            except json.JSONDecodeError:
                if "Kullanıcı adı veya şifre hatalı" in login_post.text:
                    return None, "Username or password incorrect", None
                elif "Hesabınız askıya alınmıştır" in login_post.text:
                    return None, "Account suspended", None
                elif "Güvenlik kodu" in login_post.text or "captcha" in login_post.text.lower():
                    return None, "Captcha required", None
                else:
                    return None, "Login failed - unknown error", None
                    
        except Exception as e:
            return None, f"Login error: {str(e)}", None
    
    def fetch_credits(self, session: requests.Session) -> Optional[int]:
        """Fetch account credits"""
        try:
            response = session.get(f"{self.base_url}/tools", timeout=30)
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, "html.parser")
            credits_element = soup.find("span", {"id": "takipKrediCount"})
            if credits_element:
                return int(credits_element.text)
            return None
        except Exception:
            return None
    
    def send_followers(self, session: requests.Session, target_username: str) -> Tuple[bool, str]:
        """Send followers to target"""
        try:
            follower_send_url = f"{self.base_url}/tools/send-follower"
            
            # Get follower page
            response = session.get(follower_send_url, timeout=30)
            if response.status_code != 200:
                return False, f"Follower page failed: {response.status_code}"
            
            soup = BeautifulSoup(response.text, "html.parser")
            form = soup.find("form", {"method": "post", "action": "?formType=findUserID"})
            if not form:
                return False, "User form not found"
            
            # Find user ID
            find_user_data = {"username": target_username}
            response = session.post(follower_send_url + "?formType=findUserID", 
                                  data=find_user_data, timeout=30, allow_redirects=True)
            
            if response.status_code != 200:
                return False, "User not found"
            
            user_id = response.url.split("/")[-1]
            if not user_id.isdigit():
                return False, "UserID extraction failed"
            
            # Get final send page
            final_send_url = f"{self.base_url}/tools/send-follower/{user_id}"
            response = session.get(final_send_url, timeout=30)
            if response.status_code != 200:
                return False, "Final page failed"
            
            soup = BeautifulSoup(response.text, "html.parser")
            form = soup.find("form", {"id": "formTakip"})
            if not form:
                return False, "Final form not found"
            
            # Send followers
            send_data = {
                "adet": "50",
                "userID": user_id,
                "userName": target_username,
            }
            
            headers = self.headers.copy()
            headers["Accept"] = "application/json"
            
            response = session.post(final_send_url + "?formType=send", 
                                  data=send_data, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return False, "Send request failed"
            
            try:
                response_json = json.loads(response.text)
                if response_json.get("status") == "success":
                    return True, "Followers sent successfully"
                else:
                    return False, response_json.get("message", "Unknown error")
            except json.JSONDecodeError:
                return False, "Invalid response format"
                
        except Exception as e:
            return False, f"Send error: {str(e)}"
