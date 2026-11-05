#!/usr/bin/env python3
"""
Smart-1 Cloud Management API Operations

Handles Check Point Management Server operations including:
- Gateway configuration
- Policy installation
- Session management

API Documentation:
https://sc1.checkpoint.com/documents/latest/APIs/

R82.20 (Management API v2.1) notes:
- set-simple-gateway gained 'trust-method' / 'trust-settings'. When a one-time-password
  is set, SIC is initiated according to 'trust-settings.initiation-phase', which defaults
  to 'now' (push the certificate immediately) unless the object is already a Spark gateway.
  Spark gateways behind Smart-1 Cloud must pull the certificate themselves
  ('fetch certificate'), so SIC is now set only after the object is a Spark gateway and
  with 'initiation-phase': 'when_gateway_connects'.
"""

from typing import Dict, Optional, List
import requests
import json
import time
from .logger_main import log
from tqdm import tqdm

# Management API version that introduced 'trust-settings' (R82.20)
TRUST_SETTINGS_API_VERSION = (2, 1)
GATEWAY_OBJECT_TIMEOUT = 180  # seconds to wait for the Smart-1 Cloud gateway object
GATEWAY_OBJECT_POLL = 10  # seconds
SIC_POLL = 15  # seconds between SIC state checks
DEFAULT_TIMEOUT = 60  # seconds for each HTTP request
TASK_TIMEOUT = 1800  # seconds to wait for a publish or install-policy task


class ManagementAPI:
    """Client for Check Point Gateway operations"""

    def __init__(self, instance: str, context: str, api_key: str, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = f"https://{instance}.maas.checkpoint.com/{context}/web_api"
        self.api_key = api_key
        self.timeout = timeout
        self.sid: Optional[str] = None
        self.api_version: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})


    def _login(self) -> None:
        """Authenticate with the management server"""
        try:
            response = self.session.post(
                f"{self.base_url}/login",
                json={"api-key": self.api_key},
                timeout=self.timeout
            )
            response.raise_for_status()
            login_data = response.json()
            self.sid = login_data['sid']
            self.api_version = login_data.get('api-server-version')
            self.session.headers.update({'X-chkp-sid': self.sid})
            log.info(f"Connected to Management API version {self.api_version}")

            # R82.20: Smart-1 Cloud may be running a background upgrade
            upgrade_message = login_data.get('background-upgrade-message')
            if upgrade_message:
                log.warning(f"Management server upgrade in progress: {upgrade_message}")

        except requests.exceptions.RequestException as e:
            log.error(f"Authentication failed: {str(e)}")
            raise

    def _logout(self) -> None:
        """Terminate management session"""
        try:
            # The API requires a JSON body, even an empty one
            response = self.session.post(f"{self.base_url}/logout", json={}, timeout=self.timeout)
            response.raise_for_status()
            log.debug("Successfully logged out")
        except requests.exceptions.RequestException as e:
            log.warning(f"Logout failed: {str(e)}")
        finally:
            self.sid = None
            self.session.headers.pop('X-chkp-sid', None)

    def _api_version_at_least(self, required: tuple) -> bool:
        """Compare the server API version (e.g. '2.1', '2.0.1') to a (major, minor) tuple"""
        try:
            parts = tuple(int(p) for p in str(self.api_version).split('.'))
            return parts >= required
        except ValueError:
            log.warning(f"Unknown API version '{self.api_version}', assuming legacy behavior")
            return False

    def _execute_api_call(self, endpoint: str, payload: Dict) -> Dict:
        """Generic API call handler with error checking"""
        try:
            response = self.session.post(
                f"{self.base_url}/{endpoint}",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            log.error(f"API call failed: {e.response.text}")
            raise
        except json.JSONDecodeError:
            log.error("Invalid JSON response from server")
            raise

    def _get_sms_organization(self) -> str:
        """Return the O= value of the Smart-1 Cloud management SIC name"""
        sms_info = self._execute_api_call(
            "show-checkpoint-host",
            {"name": "Management_Service"}
        )
        # e.g. "cn=cp_mgmt,o=<instance>.maas.checkpoint.com.<suffix>"
        sic_parts = dict(
            part.strip().split('=', 1) for part in sms_info['sic-name'].split(',') if '=' in part
        )
        sic_parts = {key.lower(): value for key, value in sic_parts.items()}
        if 'o' not in sic_parts:
            raise ValueError(f"Unexpected management SIC name: {sms_info['sic-name']}")
        return sic_parts['o']

    def _wait_for_gateway_object(self, gw_name: str) -> Dict:
        """Wait until Smart-1 Cloud has created the gateway object for a registered gateway"""
        deadline = time.time() + GATEWAY_OBJECT_TIMEOUT
        while True:
            response = self.session.post(
                f"{self.base_url}/show-simple-gateway",
                json={"name": gw_name},
                timeout=self.timeout
            )
            if response.status_code != 404 or time.time() > deadline:
                if not response.ok:
                    log.error(f"API call failed: {response.text}")
                response.raise_for_status()
                return response.json()
            log.info(f"Gateway object {gw_name} not created yet, retrying in {GATEWAY_OBJECT_POLL}s")
            time.sleep(GATEWAY_OBJECT_POLL)

    def configure_gateway(self, gw_name: str, version: str, net_type: str,
                         hardware: str, sic_key: str) -> None:
        """Full gateway configuration workflow"""
        try:
            self._login()
            # Get SMS certificate details
            sms_cn_name = self._get_sms_organization()

            # Get gateway UID
            gateway_info = self._wait_for_gateway_object(gw_name)
            gateway_uid = gateway_info.get('uid')

            # Set basic gateway properties
            self._execute_api_call(
                "set-simple-gateway",
                {
                    "name": gw_name,
                    "version": version,
                    "os-name": "Gaia Embedded"
                }
            )

            # Set advanced properties (turns the object into a Spark gateway)
            self._execute_api_call(
                "set-generic-object",
                {
                    "uid": gateway_uid,
                    "applianceType": "slim_fw",
                    "svnVersionName": version,
                    "slimFwType": net_type,
                    "slimFwHardwareType": hardware,
                    "securityBladesTopologyMode": "TOPOLOGY_TABLE",
                    "vpn1": True,
                    "hideInternalInterfaces": True
                }
            )

            # Set SIC only once the object is a Spark gateway. The gateway pulls the
            # certificate itself ('fetch certificate'), so the management must not try
            # to push it (R82.20 default for non-Spark objects is 'now').
            sic_payload = {
                "name": gw_name,
                "one-time-password": sic_key,
                "sic-name": f"CN={gw_name},O={sms_cn_name}"
            }
            if self._api_version_at_least(TRUST_SETTINGS_API_VERSION):
                sic_payload["trust-settings"] = {"initiation-phase": "when_gateway_connects"}
            self._execute_api_call("set-simple-gateway", sic_payload)

            # Publish changes
            response = self._execute_api_call("publish", {})
            task_id = response.get('task-id')
            log.info("Publishing the session")
            log.debug(f"Task ID: {task_id}")
            self._monitor_task(task_id)
            log.info("Configuration changes published successfully")

            # Install policy
            #self.install_policy(gw_name)

        finally:
            self._logout()


    def wait_for_sic(self, gw_names: List[str], timeout: int) -> List[str]:
        """Wait until gateways report SIC state 'communicating'. Returns the gateways that do."""
        pending = list(gw_names)
        communicating: List[str] = []
        deadline = time.time() + timeout
        try:
            self._login()
            while pending:
                for gw_name in list(pending):
                    try:
                        gateway_info = self._execute_api_call("show-simple-gateway", {"name": gw_name})
                    except requests.exceptions.RequestException as e:
                        log.warning(f"Could not read SIC state of {gw_name}: {str(e)}")
                        continue
                    sic_state = gateway_info.get('sic-state', 'unknown')
                    if sic_state == "communicating":
                        log.info(f"SIC established with {gw_name}")
                        pending.remove(gw_name)
                        communicating.append(gw_name)
                    else:
                        log.debug(f"{gw_name} SIC state: {sic_state}")
                if not pending or time.time() > deadline:
                    break
                log.info(f"Waiting for SIC with {', '.join(pending)}, retrying in {SIC_POLL}s")
                time.sleep(SIC_POLL)
        finally:
            self._logout()

        for gw_name in pending:
            log.error(f"SIC not established with {gw_name} within {timeout}s, skipping policy installation")
        return communicating

    def install_policy(self, policy_targets: List[str], policy_package: str) -> None:
        """Install security policy on gateways"""
        try:
            # configure_gateway() logs out when done, so this needs its own session
            self._login()
            log.info(f"Installing {policy_package} on {len(policy_targets)} gateways")
            response = self._execute_api_call(
                "install-policy",
                {
                    "policy-package": policy_package,
                    "access": True,
                    "threat-prevention": True,
                    "targets": policy_targets
                }
            )

            task_id = response.get('task-id')
            log.info(f"Policy installation started. Task ID: {task_id}")
            self._monitor_task(task_id)

        except Exception as e:
            log.error(f"Policy installation failed: {str(e)}")
            raise
        finally:
            self._logout()

    def _monitor_task(self, task_id: str, interval: int = 10, timeout: int = TASK_TIMEOUT) -> None:
        """Monitor async task completion with spinner"""
        deadline = time.time() + timeout
        try:
            with tqdm(
                total=1,  # Fake total for spinner
                bar_format="{desc}: {elapsed} {bar}",
                ncols=80
            ) as pbar:
                while True:
                    task_status = self._execute_api_call(
                        "show-task",
                        {"task-id": task_id}
                    )

                    task_data = task_status.get('tasks', [{}])[0]
                    status = task_data.get('status', 'unknown').upper()

                    # Update spinner description
                    pbar.set_description(status)

                    if status == "SUCCEEDED":
                        pbar.set_description("COMPLETED")
                        pbar.close()
                        return
                    if status in ("FAILED", "PARTIALLY SUCCEEDED"):
                        pbar.set_description(status)
                        pbar.close()
                        raise Exception(f"Task {status.lower()}: {task_data}")
                    if time.time() > deadline:
                        pbar.close()
                        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")

                    time.sleep(interval)

        except Exception as e:
            log.error(f"Task monitoring failed: {str(e)}")
            raise

if __name__ == '__main__':
    # Example usage
    api = ManagementAPI(
        instance="your-instance",
        context="your-context",
        api_key="your-api-key"
    )
    api.configure_gateway(
        gw_name="test-gw",
        version="R81.10",
        net_type="Wireless",
        hardware="1530/1550",
        sic_key="vpn123"
    )
