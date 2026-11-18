# File: utils/sparks_rest_api.py
"""
Sparks Gateway REST API Client
Handles direct device configuration via local REST API
"""
import re
import time
import base64
from typing import Iterable, List, Optional
import requests
import urllib3
from .logger_main import log, redact
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_TIMEOUT = 60  # seconds for each HTTP request
# Clish output that means the command failed, e.g. "Could not set security-management: ..."
FAILURE_PATTERN = re.compile(r"\b(could not|failed|failure|error|invalid|rejected)\b", re.IGNORECASE)
REST_API_OFF = ("The REST API on this appliance is off. Enable it in Gaia Clish on the appliance "
                "with 'set rest-api mode true', then run the deployer again.")

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
            try:
                response = self.session.post(
                    f"{self.base_url}/login",
                    json={"user": self.username, "password": self.password},
                    timeout=self.timeout
                )
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                raise RuntimeError(
                    f"Cannot reach the appliance REST API at {self.base_url} from this machine. "
                    "Check the address and port in gateway_ip (the default port is 4434), and "
                    f"that the firewalls in between allow it. Details: {e}"
                ) from e
            # The appliance answers with "REST API on this appliance is off" until it is enabled
            if re.search(r"rest api.*\boff\b", response.text, re.IGNORECASE):
                raise RuntimeError(REST_API_OFF)
            if not response.ok:
                raise RuntimeError(f"Appliance login returned HTTP {response.status_code}: "
                                   f"{response.text.strip()[:300]}")
            try:
                self.sid = response.json()['sid']
            except (ValueError, KeyError) as e:
                raise RuntimeError("Appliance login did not return a session: "
                                   f"{response.text.strip()[:300]}") from e
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
