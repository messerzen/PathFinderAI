import os
import requests
import urllib3
from dotenv import load_dotenv, set_key

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
ENV_FILE = ".env"

def get_strava_access_token():
    """
    Returns a valid Strava access token.
    If the current one is expired or empty, it uses the refresh_token to get a new one.
    """
    access_token = os.getenv("STRAVA_ACCESS_TOKEN")
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")

    if not CLIENT_SECRET or CLIENT_SECRET == 'COLE_SEU_SEGREDO_DO_CLIENTE_AQUI':
        print("Please configure STRAVA_CLIENT_SECRET in .env.")
        return None

    # Try to validate current token with a simple request
    if access_token:
        headers = {'Authorization': f"Bearer {access_token}"}
        test_req = requests.get('https://www.strava.com/api/v3/athlete', headers=headers, verify=False)
        if test_req.status_code == 200:
            return access_token

    # If test failed or no access token but we have refresh token
    if refresh_token:
        print("Refreshing Strava token...")
        payload = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }
        res = requests.post("https://www.strava.com/oauth/token", data=payload, verify=False)
        data = res.json()
        if 'access_token' in data:
            new_access = data['access_token']
            new_refresh = data['refresh_token']
            # update .env file
            set_key(ENV_FILE, "STRAVA_ACCESS_TOKEN", new_access)
            set_key(ENV_FILE, "STRAVA_REFRESH_TOKEN", new_refresh)
            # update runtime env
            os.environ["STRAVA_ACCESS_TOKEN"] = new_access
            os.environ["STRAVA_REFRESH_TOKEN"] = new_refresh
            return new_access
    
    # If we get here, we need full manual auth
    print("Full authentication required.")
    auth_url = f"https://www.strava.com/oauth/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=activity:read_all"
    print("1. Click this link and authorize:")
    print(auth_url)
    print("2. Copy the code from the localhost URL (e.g. code=...)")
    code = input("\nEnter code: ").strip()

    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code'
    }
    
    res = requests.post("https://www.strava.com/oauth/token", data=payload, verify=False)
    data = res.json()

    if 'access_token' in data:
        print("Successfully obtained tokens!")
        new_access = data['access_token']
        new_refresh = data['refresh_token']
        set_key(ENV_FILE, "STRAVA_ACCESS_TOKEN", new_access)
        set_key(ENV_FILE, "STRAVA_REFRESH_TOKEN", new_refresh)
        return new_access
    else:
        print("Error getting token:", data)
        return None

if __name__ == '__main__':
    token = get_strava_access_token()
    if token:
        print("Token is valid and active.")
