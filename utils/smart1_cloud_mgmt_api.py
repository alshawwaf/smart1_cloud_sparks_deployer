#!/usr/bin/env python3
"""
Smart-1 Cloud Management API Operations

Handles Check Point Management Server operations including:
- Gateway configuration
- Policy installation
- Session management

API Documentation:
https://sc1.checkpoint.com/documents/latest/APIs/
"""

from typing import Dict, Optional, List
import requests
import json
import time
from .logger_main import log
from tqdm import tqdm

class ManagementAPI:
    """Client for Check Point Gateway operations"""
    
    def __init__(self, instance: str, context: str, api_key: str):
        self.base_url = f"https://{instance}.maas.checkpoint.com/{context}/web_api"
        self.api_key = api_key
        self.sid: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})


    def _login(self) -> None:
        """Authenticate with the management server"""
        try:
            response = self.session.post(
                f"{self.base_url}/login",
                json={"api-key": self.api_key}
            )
            response.raise_for_status()
            self.sid = response.json()['sid']
            self.session.headers.update({'X-chkp-sid': self.sid})
            log.debug("Successfully authenticated with management API")
            
        except requests.exceptions.RequestException as e:
            log.error(f"Authentication failed: {str(e)}")
            raise

    def _logout(self) -> None:
        """Terminate management session"""
        try:
            self.session.post(f"{self.base_url}/logout")
            log.debug("Successfully logged out")
        except requests.exceptions.RequestException as e:
            log.warning(f"Logout failed: {str(e)}")

    def _execute_api_call(self, endpoint: str, payload: Dict) -> Dict:
        """Generic API call handler with error checking"""
        try:
            response = self.session.post(
                f"{self.base_url}/{endpoint}",
                json=payload
            )
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            log.error(f"API call failed: {e.response.text}")
            raise
        except json.JSONDecodeError:
            log.error("Invalid JSON response from server")
            raise

    def configure_gateway(self, gw_name: str, version: str, net_type: str,
                         hardware: str, sic_key: str) -> None:
        """Full gateway configuration workflow"""
        try:
            self._login()
            # Get SMS certificate details
            sms_info = self._execute_api_call(
            "show-checkpoint-host",
            {"name": "Management_Service"}
            )
            sms_cn = sms_info['sic-name'].split(',')[1]
            
            # Get gateway UID
            gateway_info = self._execute_api_call(
                "show-simple-gateway",
                {"name": gw_name}
            )
            gateway_uid = gateway_info.get('uid')

            # Set basic gateway properties
            self._execute_api_call(
                "set-simple-gateway",
                {
                    "name": gw_name,
                    "one-time-password": sic_key,
                    "sic-name": f"CN={gw_name},{sms_cn}",
                    "version": version,
                    "os-name": "Gaia Embedded"
                }
            )

            # Set advanced properties
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


    def install_policy(self, policy_targets: List[str], policy_package: str) -> None:
        """Install security policy on gateways"""
        try:
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

    def _monitor_task(self, task_id: str, interval: int = 10) -> None:
        """Monitor async task completion with spinner"""
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
                    pbar.set_description(f"🔄 {status}")
                    
                    if status == "SUCCEEDED":
                        pbar.set_description("✅ COMPLETED")
                        pbar.close()
                        return
                    if status == "FAILED":
                        pbar.set_description("❌ FAILED")
                        pbar.close()
                        raise Exception(f"Task failed: {task_data}")

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
