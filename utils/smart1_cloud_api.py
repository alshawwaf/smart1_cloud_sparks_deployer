#!/usr/bin/env python3
"""
Smart-1 Cloud Gateway Object Management Client

Provides a robust interface for managing gateways in Check Point Smart-1 Cloud,
including registration, deletion, and listing operations.

Features:
- Secure authentication with token management
- Full error handling and retry logic
- Type hints and detailed documentation
- Configurable timeouts and retries
- Comprehensive logging

API Documentation:
https://app.swaggerhub.com/apis-docs/Check-Point/smart-1_cloud_api/1.0.0
"""

import requests
import json
import time
from typing import Dict, List, Optional
from requests.exceptions import RequestException
from .logger_main import log

# API Constants
AUTH_ENDPOINT = "/auth/external"
GATEWAYS_ENDPOINT = "/app/maas/api/v1/gateways"
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5 # seconds

class Smart1CloudAPI:
    """Client for Smart-1 Cloud Gateway Management API"""
    
    def __init__(
        self,
        client_id: str,
        access_key: str,
        portal_url: str,
        timeout: int = DEFAULT_TIMEOUT
    ):
        """
        Initialize API client
        
        Args:
            client_id: API client ID from Smart-1 Cloud
            access_key: API access key from Smart-1 Cloud
            portal_url: Base URL of Smart-1 Cloud portal
            timeout: Request timeout in seconds
        """
        self.client_id = client_id
        self.access_key = access_key
        self.base_url = portal_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        self._auth_token: Optional[str] = None
        self._token_expiry: Optional[float] = None

    def _authenticate(self) -> None:
        """Obtain and manage authentication token"""
        try:
            if self._token_valid():
                return

            log.debug("Acquiring new authentication token")
            auth_url = f"{self.base_url}{AUTH_ENDPOINT}"
            payload = json.dumps({
                "clientId": self.client_id,
                "accessKey": self.access_key
            })

            response = self._execute_request(
                "POST", auth_url, payload=payload, auth_required=False
            )
            
            self._auth_token = response['data']['token']
            self._token_expiry = time.time() + 3600  # 1 hour expiration
            self.session.headers.update({'Authorization': f"Bearer {self._auth_token}"})

        except Exception as e:
            log.error(f"Authentication failed: {str(e)}")
            raise

    def _token_valid(self) -> bool:
        """Check if current token is still valid"""
        return self._auth_token and self._token_expiry and time.time() < self._token_expiry

    def _execute_request(
        self,
        method: str,
        url: str,
        payload: Optional[str] = None,
        auth_required: bool = True,
        retries: int = MAX_RETRIES
    ) -> Dict:
        """
        Execute API request with retry logic
        
        Args:
            method: HTTP method (GET/POST/DELETE)
            url: Full API endpoint URL
            payload: Request payload
            auth_required: Whether authentication is required
            retries: Number of remaining retry attempts
            
        Returns:
            dict: Parsed JSON response
            
        Raises:
            RequestException: On permanent failure
        """
        try:
            if auth_required:
                self._authenticate()

            log.debug(f"Executing {method} request to {url}")
            response = self.session.request(
                method=method,
                url=url,
                data=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        except RequestException as e:
            if retries > 0:
                log.warning(f"Request failed, retrying... ({retries} left)")
                time.sleep(RETRY_DELAY)
                return self._execute_request(
                    method, url, payload, auth_required, retries-1
                )
            log.error(f"Permanent request failure: {str(e)}")
            raise
        except json.JSONDecodeError:
            log.error("Failed to parse JSON response")
            raise

    def register_gateway(self, gw_name: str) -> Dict:
        """
        Register a new gateway in Smart-1 Cloud
        """
        try:
            log.info(f"Registering gateway: {gw_name}")
            url = f"{self.base_url}{GATEWAYS_ENDPOINT}"
            payload = json.dumps({
                "name": gw_name,
                "description": "Automatically registered via Python API"
            })

            response = self._execute_request("POST", url, payload)
            
            if not response.get('success'):
                error_msg = response.get('message', 'Unknown registration error')
                raise ValueError(f"Registration failed: {error_msg}")

            # Extract token from nested data structure
            token = response['data']['token']
            log.info(f"Registered gateway: {gw_name} successfully. Token: {token[:8]}...")
            
            return {
                'token': token,
                'gateway_id': response['data']['id'],
                'details': response['data']
            }

        except Exception as e:
            log.error(f"Gateway registration error: {str(e)}")
            raise
    
    def delete_gateway(self, gw_name: str) -> None:
        """
        Delete an existing gateway
        
        Args:
            gw_name: Name of gateway to delete
            
        Raises:
            ValueError: If deletion fails
        """
        try:
            log.info(f"Deleting gateway: {gw_name}")
            url = f"{self.base_url}{GATEWAYS_ENDPOINT}/{gw_name}"
            params = {'deleteObjectFromConfiguration': 'true'}
            
            response = self._execute_request("DELETE", url, params=params)
            
            if response.get('success'):
                log.info(f"Deleted the gateway {gw_name} Successfully")
            else:
                raise ValueError(response.get('message', 'Unknown deletion error'))

        except Exception as e:
            log.error(f"Gateway deletion error: {str(e)}")
            raise

    def list_gateways(self) -> List[Dict]:
        """
        Retrieve list of all configured gateways
        
        Returns:
            list: Gateway objects with status information
        """
        try:
            log.debug("Fetching gateway list")
            response = self._execute_request("GET", f"{self.base_url}{GATEWAYS_ENDPOINT}")
            return response.get('data', {}).get('objects', [])
            
        except Exception as e:
            log.error(f"Failed to list gateways: {str(e)}")
            raise

    def get_gateway_status(self, gw_name: str) -> Dict:
        """
        Get detailed status of a specific gateway
        
        Args:
            gw_name: Name of target gateway
            
        Returns:
            dict: Detailed status information
        """
        try:
            log.debug(f"Fetching status for gateway: {gw_name}")
            url = f"{self.base_url}{GATEWAYS_ENDPOINT}/{gw_name}/status"
            response = self._execute_request("GET", url)
            return response.get('data', {})
            
        except Exception as e:
            log.error(f"Failed to get gateway status: {str(e)}")
            raise

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Smart-1 Cloud Gateway Management CLI"
    )
    parser.add_argument('-i', '--client-id', required=True, help='API Client ID')
    parser.add_argument('-k', '--access-key', required=True, help='API Access Key')
    parser.add_argument('-p', '--portal-url', required=True, help='Portal URL')
    parser.add_argument('-n', '--gw-name', help='Gateway name')
    parser.add_argument('command', choices=['register', 'delete', 'list', 'status'],
                        help='Operation to perform')
    
    args = parser.parse_args()
    
    try:
        api = Smart1CloudAPI(
            client_id=args.client_id,
            access_key=args.access_key,
            portal_url=args.portal_url
        )
        
        if args.command == 'register':
            if not args.gw_name:
                raise ValueError("Gateway name required for registration")
            result = api.register_gateway(args.gw_name)
            print(f"Registration Token: {result['token']}")
            
        elif args.command == 'delete':
            if not args.gw_name:
                raise ValueError("Gateway name required for deletion")
            api.delete_gateway(args.gw_name)
            
        elif args.command == 'list':
            gateways = api.list_gateways()
            print("Configured Gateways:")
            for gw in gateways:
                print(f" - {gw['name']}: {gw['statusDetails']}")
                
        elif args.command == 'status':
            if not args.gw_name:
                raise ValueError("Gateway name required for status check")
            status = api.get_gateway_status(args.gw_name)
            print(json.dumps(status, indent=2))
            
    except Exception as e:
        log.error(f"Operation failed: {str(e)}")
        exit(1)