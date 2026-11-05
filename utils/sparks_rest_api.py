# File: utils/sparks_rest_api.py
"""
Sparks Gateway REST API Client
Handles direct device configuration via local REST API
"""
import re
import time
import base64
import requests
from typing import Iterable, List, Optional
from .logger_main import log, redact
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_TIMEOUT = 60  # seconds for each HTTP request
# Clish output that means the command failed, e.g. "Could not set security-management: ..."
FAILURE_PATTERN = re.compile(r"\b(could not|failed|failure|error|invalid|rejected)\b", re.IGNORECASE)

class SparksGatewayAPI:
    """Client for configuring sparks gateways via their local API"""

    def __init__(self, ip_address: str, username: str, password: str, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = f"https://{ip_address}/web-api"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.sid = None
        self.session.verify = False  # For lab environments only

    def login(self):
        """Authenticate with the sparks gateway"""
        try:
            response = self.session.post(
                f"{self.base_url}/login",
                json={"user": self.username, "password": self.password},
                timeout=self.timeout
            )
            response.raise_for_status()
            self.sid = response.json()['sid']
            self.session.headers.update({'X-chkp-sid': self.sid})
            log.info("Sparks gateway login successful")
        except Exception as e:
            log.error(f"Sparks gateway login failed: {redact(str(e), [self.password])}")
            raise

    def execute_clish(self, commands: List[str], delay: int = 20,
                      secrets: Iterable[Optional[str]] = ()):
        """
        Execute CLISH commands on sparks gateway and return their outputs.
        Values in secrets are masked in all logs.
        """
        secrets = list(secrets)
        outputs: List[str] = []
        try:
            for cmd in commands:
                log.info(f"Running the command: {redact(cmd, secrets)}")

                encoded_cmd = base64.b64encode(cmd.encode()).decode()

                response = self.session.post(
                    f"{self.base_url}/run-clish-command",
                    json={"script": encoded_cmd},
                    timeout=self.timeout
                )

                response.raise_for_status()

                # Decode and log output
                output = base64.b64decode(response.json()['output']).decode()
                if output: # not all clish command return an output
                    log.debug(f"CLISH command response: {redact(output, secrets)}")
                # Clish reports most failures in the output with HTTP 200
                if FAILURE_PATTERN.search(output):
                    raise RuntimeError(f"Command '{redact(cmd, secrets)}' failed: "
                                       f"{redact(output.strip(), secrets)}")
                outputs.append(output)
                log.info(f"Waiting for {delay} seconds between commands")
                time.sleep(delay)
            return outputs

        except Exception as e:
            log.error(f"CLISH command failed: {redact(str(e), secrets)}")
            raise
