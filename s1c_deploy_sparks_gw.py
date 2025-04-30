#!/usr/bin/env python3
"""
Smart-1 Cloud Gateway Deployment Orchestrator
.venv/Scripts/python.exe s1c_deploy_sparks_gw.py
see the readme file for more details
"""

import time, json
from typing import List
from utils.logger_main import log
from utils.load_config_file import read_config_file, AuthConfig, GatewayConfig, PolicyPackage
from utils.smart1_cloud_api import Smart1CloudAPI
from utils.smart1_cloud_mgmt_api import ManagementAPI
from utils.sparks_rest_api import SparksGatewayAPI
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def deploy_s1c_sparks_gw() -> None:
    """Main deployment workflow executor"""
    try:
        # Load configurations
        auth_config: AuthConfig = read_config_file('./config/auth_data.json')
        policy_config: PolicyPackage = read_config_file('./config/policy_package_data.json')
        config_data: List[GatewayConfig] = read_config_file('./config/config_data.json')
        
        log.info("Starting gateway deployment process")
        process_gateways(auth_config, config_data, policy_config)  
        
    except Exception as e:
        log.error(f"Critical deployment error: {str(e)}")
        raise
    

def process_gateways(auth_config: AuthConfig, config_data: List[GatewayConfig], policy_config: PolicyPackage) -> None:
    """Process each gateway configuration with proper sequencing"""
    # Initialize API clients
    s1c_cloud = Smart1CloudAPI(
        client_id=auth_config.client_id,
        access_key=auth_config.access_key,
        portal_url=auth_config.portal_url
    )
    
    mgmt_api = ManagementAPI(
        instance=auth_config.instance,
        context=auth_config.context,
        api_key=auth_config.api_key
    )

    configured_gateways = []
    pending_physical_config = []

    # Phase 1: Cloud Registration & Configuration
    for gateway in config_data:
        try:
            log.info(f"🚀  Starting processing for {gateway.gw_name}")
            
            # 1. Cloud Registration
            registration = s1c_cloud.register_gateway(gateway.gw_name)
            gateway.maas_token = registration['token']
            log.debug("Cloud registration response: %s", json.dumps(registration, indent=2))
            time.sleep(25)
            
            # 2. Cloud Configuration
            log.info("⚙️  Configuring Gateway Object settings")
            configure_gateway(mgmt_api, gateway)
            configured_gateways.append(gateway.gw_name)
            
            # Track gateways needing physical config
            if all([gateway.gateway_ip, gateway.gateway_username, gateway.gateway_password]):
                pending_physical_config.append(gateway)
                log.info("⏳  Queueing for physical configuration")
            
            log.info("🕒  Waiting 15 seconds for stabilization")
            time.sleep(15)
            
        except Exception as e:
            log.error(f"❌  Failed to process {gateway.gw_name}: {str(e)}")
            continue

    # Phase 2: Policy Installation
    try:
        log.info(f"🛡️  Installing policy package '{policy_config.policy_package}'")
        mgmt_api.install_policy(
            policy_targets=configured_gateways,
            policy_package=policy_config.policy_package
        )
        
        # Use configured delay
        #delay = policy_config.install_delay
        #log.info(f"🕒 Waiting {delay}s for policy activation")
        #time.sleep(delay)
        
    except Exception as e:
        log.error(f"❌  Policy installation failed: {str(e)}")
        raise

    # Phase 3: Physical Gateway Configuration
    for gateway in pending_physical_config:
        try:
            log.info(f"🔧 Configuring physical gateway {gateway.gw_name}")
            configure_sparks_gateway(gateway)
            
            log.info(f"🕒  Waiting 10s for physical gateway initialization")
            time.sleep(10)
            
        except Exception as e:
            log.error(f"❌  Sparks Gateway config failed for {gateway.gw_name}: {str(e)}")
            continue

    log.info("✅ All gateway processing completed")
    
      
def configure_gateway(mgmt_api: ManagementAPI, gateway: GatewayConfig) -> None:
    """Configure gateway settings and install policy"""
    log.debug("Starting gateway configuration")
    try:
        mgmt_api.configure_gateway(
            gw_name=gateway.gw_name,
            version=gateway.version,
            net_type=gateway.net_type,
            hardware=gateway.hardware,
            sic_key=gateway.sic_key
        )
        log.info(f"Configured {gateway.gw_name} successfully")
        
        
    except Exception as e:
        log.error(f"Configuration failed for {gateway.gw_name}: {str(e)}")
        raise


def configure_sparks_gateway(gateway: GatewayConfig) -> None:
    """Configure physical gateway using dedicated API client"""
    if not all([gateway.gateway_ip, gateway.gateway_username, gateway.gateway_password]):
        log.info("Skipping physical config - incomplete credentials")
        return

    try:
        # Initialize PHYSICAL gateway client
        sparks_gw = SparksGatewayAPI(
            ip_address=gateway.gateway_ip,
            username=gateway.gateway_username,
            password=gateway.gateway_password
        )
        
        sparks_gw.login()
        
        # Execute physical configuration commands
        commands = [
            # "add interface-loopback ipv4-address 10.0.0.1 mask-length 32",
            # "cplic put #your_license_string",
            f"connect maas auth-token {gateway.maas_token}",
            "set security-management mode centrally-managed",
            f"set sic_init password {gateway.sic_key}",
            f"fetch certificate mgmt-ipv4-address 100.64.0.52 gateway-name {gateway.gw_name}",
            "connect security-management mgmt-addr 100.64.0.52 use-one-time-password true local-override-mgmt-addr true send-logs-to local-override-mgmt-addr",
            "fw fetch 100.64.0.52"
        ]
        
        sparks_gw.execute_clish(commands)
        log.info(f"Sparks gateway {gateway.gw_name} configured successfully")
        #sparks_gw.logout()
        
    except Exception as e:
        log.error(f"Sparks configuration failed: {str(e)}")
        raise
    

if __name__ == '__main__':
    deploy_s1c_sparks_gw()
