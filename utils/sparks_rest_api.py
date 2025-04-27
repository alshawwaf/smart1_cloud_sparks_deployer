# File: utils/sparks_rest_api.py
"""
Sparks Gateway REST API Client
Handles direct device configuration via local REST API
"""
import time
import base64
import requests
from typing import List
from .logger_main import log
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class SparksGatewayAPI:
    """Client for configuring sparks gateways via their local API"""
    
    def __init__(self, ip_address: str, username: str, password: str):
        self.base_url = f"https://{ip_address}/web-api"
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.sid = None
        self.session.verify = False  # For lab environments only

    def login(self):
        """Authenticate with the sparks gateway"""
        try:
            response = self.session.post(
                f"{self.base_url}/login",
                json={"user": self.username, "password": self.password}
            )
            response.raise_for_status()
            self.sid = response.json()['sid']
            self.session.headers.update({'X-chkp-sid': self.sid})
            log.info("Sparks gateway login successful")
        except Exception as e:
            log.error(f"Sparks gateway login failed: {str(e)}")
            raise

    def execute_clish(self, commands: List[str], delay: int = 20):
        """Execute CLISH commands on sparks gateway"""
        try:
            for cmd in commands:
                log.info(f"Running the command: {cmd}")
                
                encoded_cmd = base64.b64encode(cmd.encode()).decode()
                
                response = self.session.post(
                    f"{self.base_url}/run-clish-command",
                    json={"script": encoded_cmd}
                )
                
                response.raise_for_status()
                
                # Decode and log output
                output = base64.b64decode(response.json()['output']).decode()
                if output: # not all clish command return an output
                    log.debug(f"CLISH command response: {output}")
                log.info(f"🕒 Waiting for {delay} seconds between commands")
                time.sleep(delay)
                
        except Exception as e:
            log.error(f"CLISH command failed: {str(e)}")
            raise