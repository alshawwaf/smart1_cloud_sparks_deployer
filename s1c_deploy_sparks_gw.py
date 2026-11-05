#!/usr/bin/env python3
"""
Smart-1 Cloud Gateway Deployment Orchestrator
.venv/Scripts/python.exe s1c_deploy_sparks_gw.py            deploy the gateways
.venv/Scripts/python.exe s1c_deploy_sparks_gw.py --delete   remove the gateways
see the readme file for more details
"""

import argparse, sys, time, json
from typing import Dict, List
from utils.logger_main import log, redact
from utils.load_config_file import read_config_file, AuthConfig, GatewayConfig, PolicyPackage
from utils.smart1_cloud_api import Smart1CloudAPI
from utils.smart1_cloud_mgmt_api import ManagementAPI
from utils.sparks_rest_api import SparksGatewayAPI
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def deploy_s1c_sparks_gw(delete: bool = False) -> None:
    """Main deployment workflow executor"""
    try:
        # Load configurations
        auth_config: AuthConfig = read_config_file('./config/auth_data.json')
        config_data: List[GatewayConfig] = read_config_file('./config/config_data.json')

        if delete:
            log.info("Starting gateway removal process")
            succeeded = remove_gateways(auth_config, config_data)
        else:
            policy_config: PolicyPackage = read_config_file('./config/policy_package_data.json')
            log.info("Starting gateway deployment process")
            succeeded = process_gateways(auth_config, config_data, policy_config)

    except Exception as e:
        log.error(f"Critical deployment error: {str(e)}")
        raise

    if not succeeded:
        sys.exit(1)


def process_gateways(auth_config: AuthConfig, config_data: List[GatewayConfig], policy_config: PolicyPackage) -> bool:
    """Process each gateway configuration with proper sequencing. Returns True if all gateways succeeded."""
    # Initialize API clients
    mgmt_api = ManagementAPI(
        instance=auth_config.instance,
        context=auth_config.context,
        api_key=auth_config.api_key
    )

    # Gateways are registered through the Infinity Portal API when its credentials are
    # configured, otherwise through the Management API (cloud token)
    if auth_config.use_portal_registration:
        log.info("Registering gateways through the Infinity Portal API")
        registrar = Smart1CloudAPI(
            client_id=auth_config.client_id,
            access_key=auth_config.access_key,
            portal_url=auth_config.portal_url
        )
    else:
        log.info("Registering gateways through the Management API (cloud token)")
        registrar = mgmt_api

    # Final state of each gateway, reported in the summary
    results: Dict[str, str] = {gateway.gw_name: "not started" for gateway in config_data}
    configured_gateways = []
    pending_physical_config = []

    # Phase 1: Cloud Registration & Configuration
    for gateway in config_data:
        try:
            log.info(f"Starting processing for {gateway.gw_name}")

            # 1. Cloud Registration
            registration = registrar.register_gateway(gateway.gw_name)
            gateway.maas_token = registration['token']
            log.debug("Cloud registration response: %s",
                      redact(json.dumps(registration, indent=2), [gateway.maas_token]))
            time.sleep(25)

            # 2. Cloud Configuration
            log.info("Configuring Gateway Object settings")
            configure_gateway(mgmt_api, gateway)
            configured_gateways.append(gateway.gw_name)
            results[gateway.gw_name] = "configured, waiting for SIC"

            # Track gateways needing physical config
            if all([gateway.gateway_ip, gateway.gateway_username, gateway.gateway_password]):
                pending_physical_config.append(gateway)
                log.info("Queueing for physical configuration")

            log.info("Waiting 15 seconds for stabilization")
            time.sleep(15)

        except Exception as e:
            log.error(f"Failed to process {gateway.gw_name}: {redact(str(e), [gateway.maas_token, gateway.sic_key])}")
            results[gateway.gw_name] = "failed: registration or object configuration"
            continue

    if not configured_gateways:
        log.error("No gateways were configured, skipping policy installation")
        log_summary(results)
        return False

    # Phase 2: Physical Gateway Configuration
    # The appliance must connect to Smart-1 Cloud and establish SIC before
    # policy can be installed on it, so this runs before policy installation.
    for gateway in pending_physical_config:
        try:
            log.info(f"Configuring physical gateway {gateway.gw_name}")
            configure_sparks_gateway(gateway)

            log.info("Waiting 10s for physical gateway initialization")
            time.sleep(10)

        except Exception as e:
            log.error(f"Spark gateway configuration failed for {gateway.gw_name}: "
                      f"{redact(str(e), [gateway.maas_token, gateway.sic_key, gateway.gateway_password])}")
            continue

    # Phase 3: Policy Installation, only on gateways that established SIC.
    # Zero Touch appliances connect on their own and are included once they communicate.
    log.info(f"Waiting up to {policy_config.sic_timeout}s for gateways to establish SIC")
    ready_gateways = mgmt_api.wait_for_sic(configured_gateways, timeout=policy_config.sic_timeout)
    for gw_name in configured_gateways:
        if gw_name not in ready_gateways:
            results[gw_name] = "failed: SIC not established"

    if ready_gateways:
        try:
            log.info(f"Installing policy package '{policy_config.policy_package}'")
            mgmt_api.install_policy(
                policy_targets=ready_gateways,
                policy_package=policy_config.policy_package
            )
            for gw_name in ready_gateways:
                results[gw_name] = "deployed"

        except Exception as e:
            log.error(f"Policy installation failed: {str(e)}")
            for gw_name in ready_gateways:
                results[gw_name] = "failed: policy installation"
    else:
        log.error("No gateway established SIC, skipping policy installation")

    log_summary(results)
    return all(state == "deployed" for state in results.values())


def remove_gateways(auth_config: AuthConfig, config_data: List[GatewayConfig]) -> bool:
    """Reset each appliance to local management and delete its gateway object. Returns True on success."""
    mgmt_api = ManagementAPI(
        instance=auth_config.instance,
        context=auth_config.context,
        api_key=auth_config.api_key
    )
    results: Dict[str, str] = {}
    for gateway in config_data:
        log.info(f"Removing {gateway.gw_name}")
        appliance_ok = True
        if all([gateway.gateway_ip, gateway.gateway_username, gateway.gateway_password]):
            try:
                reset_sparks_gateway(gateway)
            except Exception as e:
                appliance_ok = False
                log.error(f"Appliance reset failed for {gateway.gw_name}: "
                          f"{redact(str(e), [gateway.gateway_password])}")
        else:
            log.info("No appliance credentials, skipping appliance reset")
        try:
            mgmt_api.delete_gateway(gateway.gw_name)
            results[gateway.gw_name] = "removed" if appliance_ok else "deleted, failed: appliance reset"
        except Exception as e:
            log.error(f"Failed to delete {gateway.gw_name}: {str(e)}")
            results[gateway.gw_name] = "failed: object deletion"

    log.info("Removal summary:")
    for gw_name, state in results.items():
        (log.info if state == "removed" else log.error)(f"  {gw_name}: {state}")
    return all(state == "removed" for state in results.values())


def log_summary(results: Dict[str, str]) -> None:
    """Log the final state of each gateway"""
    log.info("Deployment summary:")
    for gw_name, state in results.items():
        if state == "deployed":
            log.info(f"  {gw_name}: {state}")
        else:
            log.error(f"  {gw_name}: {state}")
    deployed = sum(1 for state in results.values() if state == "deployed")
    log.info(f"{deployed} of {len(results)} gateways deployed")


def configure_gateway(mgmt_api: ManagementAPI, gateway: GatewayConfig) -> None:
    """Configure gateway settings and install policy"""
    log.debug("Starting gateway configuration")
    try:
        mgmt_api.configure_gateway(
            gw_name=gateway.gw_name,
            version=gateway.version,
            net_type=gateway.net_type,
            hardware=gateway.hardware,
            sic_key=gateway.sic_key,
            application_control=gateway.application_control,
            url_filtering=gateway.url_filtering
        )
        log.info(f"Configured {gateway.gw_name} successfully")


    except Exception as e:
        log.error(f"Configuration failed for {gateway.gw_name}: {redact(str(e), [gateway.sic_key])}")
        raise


def configure_sparks_gateway(gateway: GatewayConfig) -> None:
    """Configure physical gateway using dedicated API client"""
    if not all([gateway.gateway_ip, gateway.gateway_username, gateway.gateway_password]):
        log.info("Skipping physical config - incomplete credentials")
        return

    secrets = [gateway.maas_token, gateway.sic_key, gateway.gateway_password]
    try:
        # Initialize PHYSICAL gateway client
        sparks_gw = SparksGatewayAPI(
            ip_address=gateway.gateway_ip,
            username=gateway.gateway_username,
            password=gateway.gateway_password
        )

        sparks_gw.login()

        # Execute physical configuration commands. The appliance joins Smart-1 Cloud with the
        # MaaS token and pulls its SIC certificate. Policy is installed from the management
        # afterwards, so no 'fw fetch' is needed here. 'connect security-management' is not
        # used: after 'fetch certificate' it fails with "You must reinitialize trusted
        # communications" (verified on R81.10.17).
        commands = [
            # "add interface-loopback ipv4-address 10.0.0.1 mask-length 32",
            # "cplic put #your_license_string",
            f"connect maas auth-token {gateway.maas_token}",
            "set security-management mode centrally-managed",
            f"set sic_init password {gateway.sic_key}",
            f"fetch certificate mgmt-ipv4-address 100.64.0.52 gateway-name {gateway.gw_name}"
        ]

        sparks_gw.execute_clish(commands, secrets=secrets)
        log.info(f"Sparks gateway {gateway.gw_name} configured successfully")
        #sparks_gw.logout()

    except Exception as e:
        log.error(f"Sparks configuration failed: {redact(str(e), secrets)}")
        raise


def reset_sparks_gateway(gateway: GatewayConfig) -> None:
    """Return an appliance to local management: stop Smart-1 Cloud, reset SIC"""
    sparks_gw = SparksGatewayAPI(
        ip_address=gateway.gateway_ip,
        username=gateway.gateway_username,
        password=gateway.gateway_password
    )
    sparks_gw.login()
    log.info(f"Resetting appliance {gateway.gw_name} to local management")
    # The local management mode must be set after 'fw sic_reset', which otherwise
    # switches the appliance back to central management (verified on R81.10.17)
    outputs = sparks_gw.execute_clish([
        "set maas mode stop-using",
        "fw sic_reset",
        "set security-management mode locally-managed",
        "show security-management"
    ], delay=5)
    if "locally-managed" not in outputs[-1]:
        raise RuntimeError(f"Appliance is not locally managed after the reset: {outputs[-1].strip()}")
    log.info(f"Appliance {gateway.gw_name} reset to local management")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Deploy Quantum Spark gateways to Smart-1 Cloud")
    parser.add_argument('--delete', action='store_true',
                        help="Reset the appliances to local management and delete their gateway objects")
    deploy_s1c_sparks_gw(delete=parser.parse_args().delete)
