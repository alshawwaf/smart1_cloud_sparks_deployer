#!/usr/bin/env python3
"""
Smart-1 Cloud Gateway Deployment Orchestrator
.venv/Scripts/python.exe s1c_deploy_sparks_gw.py            deploy the gateways
.venv/Scripts/python.exe s1c_deploy_sparks_gw.py --delete   remove the gateways
see the readme file for more details
"""

import argparse, os, sys, time, json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from utils.logger_main import log, redact
from utils.load_config_file import read_config_file, AuthConfig, GatewayConfig, PolicyPackage
from utils.smart1_cloud_mgmt_api import ManagementAPI
from utils.sparks_rest_api import SparksGatewayAPI
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Cloud tokens of gateways without appliance credentials, for manual onboarding
TOKEN_DIR = Path("tokens")
MANUAL_ONBOARDING = "registered, token saved for manual onboarding"


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

    log.info("Registering gateways through the Management API (cloud token)")

    # Final state of each gateway, reported in the summary
    results: Dict[str, str] = {gateway.gw_name: "not started" for gateway in config_data}
    configured_gateways = []
    pending_physical_config = []

    # The values the tenant accepts for Spark gateways, and the management server address
    # that the appliances fetch their certificate from
    capabilities = mgmt_api.get_spark_capabilities()
    mgmt_ip = mgmt_api.get_management_ip()
    log.info(f"Smart-1 Cloud management server address: {mgmt_ip}")

    # Phase 1: Cloud Registration & Configuration
    for gateway in config_data:
        try:
            log.info(f"Starting processing for {gateway.gw_name}")
            hardware, hardware_subtype, version = spark_settings(gateway, capabilities)

            # 1. Cloud Registration
            registration = mgmt_api.register_gateway(gateway.gw_name, hardware, hardware_subtype, version)
            gateway.maas_token = registration['token']
            log.debug("Cloud registration response: %s",
                      redact(json.dumps(registration, indent=2), [gateway.maas_token]))

            # 2. Cloud Configuration
            log.info("Configuring Gateway Object settings")
            configure_gateway(mgmt_api, gateway)

            if all([gateway.gateway_ip, gateway.gateway_username, gateway.gateway_password]):
                # Track gateways needing physical config
                configured_gateways.append(gateway.gw_name)
                results[gateway.gw_name] = "configured, waiting for SIC"
                pending_physical_config.append(gateway)
                log.info("Queueing for physical configuration")
            else:
                # No appliance credentials: save the token for manual onboarding. These
                # gateways are not part of the SIC wait and policy installation.
                token_file = save_onboarding_file(gateway, registration.get('token_expiration'), mgmt_ip)
                results[gateway.gw_name] = MANUAL_ONBOARDING
                log.info(f"No appliance credentials for {gateway.gw_name}. Cloud token and onboarding "
                         f"steps saved to {token_file.as_posix()}")

            log.info("Waiting 15 seconds for stabilization")
            time.sleep(15)

        except Exception as e:
            log.error(f"Failed to process {gateway.gw_name}: {redact(str(e), [gateway.maas_token, gateway.sic_key])}")
            results[gateway.gw_name] = "failed: registration or object configuration"
            continue

    if not configured_gateways:
        if any(state == MANUAL_ONBOARDING for state in results.values()):
            log.info("No gateways to configure over the appliance REST API, skipping phases 2 and 3")
        else:
            log.error("No gateways were configured, skipping policy installation")
        log_summary(results)
        return all(state == MANUAL_ONBOARDING for state in results.values())

    # Phase 2: Physical Gateway Configuration
    # The appliance must connect to Smart-1 Cloud and establish SIC before
    # policy can be installed on it, so this runs before policy installation.
    for gateway in pending_physical_config:
        try:
            log.info(f"Configuring physical gateway {gateway.gw_name}")
            configure_sparks_gateway(gateway, mgmt_ip)

            log.info("Waiting 10s for physical gateway initialization")
            time.sleep(10)

        except Exception as e:
            log.error(f"Spark gateway configuration failed for {gateway.gw_name}: "
                      f"{redact(str(e), [gateway.maas_token, gateway.sic_key, gateway.gateway_password])}")
            continue

    # Phase 3: Policy Installation, only on gateways that established SIC
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
    return all(state in ("deployed", MANUAL_ONBOARDING) for state in results.values())


def save_onboarding_file(gateway: GatewayConfig, token_expiration: Optional[str], mgmt_ip: str) -> Path:
    """
    Write the cloud token and the onboarding steps for an appliance that the deployer does not
    configure. The steps follow the Smart-1 Cloud Administration Guide (Connecting a Spark
    Firewall Appliance). The SIC one-time password is not written to the file.
    """
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    token_file = TOKEN_DIR / f"{gateway.gw_name}.txt"
    content = f"""Smart-1 Cloud onboarding for gateway {gateway.gw_name}
Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Token expires: {token_expiration or 'not reported'}

This file contains a credential. Delete it after the appliance is connected.

Cloud token:
{gateway.maas_token}

The gateway object already exists in Smart-1 Cloud, with the SIC one-time password set to the
sic_key value of {gateway.gw_name} in config_data.json.

Option 1 - Spark WebUI
  1. Go to Home > Security Management and click Setup.
  2. Select "Use Security Management service" and click Next.
  3. Paste the cloud token above and click Connect.
  4. Wait for "Connected successfully to the Security Management Server", then click Next.
  5. Enter the one-time password (sic_key) and click Next.
     Do not select "Initiate trusted communication without authentication".
  6. Select "Connect to the Security Management Server now" and click Connect, then Finish.
     The message "unable to fetch the Security Policy" is expected at this point.

Option 2 - Gaia Clish
  connect maas auth-token <cloud token above>
  set security-management mode centrally-managed
  set sic_init password <sic_key>
  fetch certificate mgmt-ipv4-address {mgmt_ip} gateway-name {gateway.gw_name}

Then install the policy on {gateway.gw_name} from SmartConsole.
"""
    token_file.write_text(content, encoding='utf-8')
    try:
        os.chmod(token_file, 0o600)  # owner read/write only, where the OS supports it
    except OSError:
        pass
    return token_file


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
            log.info("No appliance credentials, skipping appliance reset. Reset the appliance manually.")
        try:
            mgmt_api.delete_gateway(gateway.gw_name)
            results[gateway.gw_name] = "removed" if appliance_ok else "deleted, failed: appliance reset"
            # The cloud token is no longer valid once the object is deleted
            token_file = TOKEN_DIR / f"{gateway.gw_name}.txt"
            if token_file.exists():
                token_file.unlink()
                log.info(f"Deleted {token_file.as_posix()}")
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
        if state in ("deployed", MANUAL_ONBOARDING):
            log.info(f"  {gw_name}: {state}")
        else:
            log.error(f"  {gw_name}: {state}")
    deployed = sum(1 for state in results.values() if state == "deployed")
    manual = sum(1 for state in results.values() if state == MANUAL_ONBOARDING)
    log.info(f"{deployed} of {len(results)} gateways deployed")
    if manual:
        log.info(f"{manual} of {len(results)} gateways registered for manual onboarding "
                 f"(see {TOKEN_DIR.as_posix()}/)")


def spark_settings(gateway: GatewayConfig, capabilities: Dict[str, List[str]]) -> Tuple[str, str, str]:
    """
    Map the gateway configuration to the values the Management API expects, and check them
    against show-gateway-capabilities. Returns (hardware, hardware_subtype, version).
    """
    # "1800" is accepted as shorthand for "1800 Appliances"
    hardware = gateway.hardware
    if hardware not in capabilities['hardware'] and f"{hardware} Appliances" in capabilities['hardware']:
        hardware = f"{hardware} Appliances"
    if hardware not in capabilities['hardware']:
        raise ValueError(f"hardware '{gateway.hardware}' is not supported. "
                         f"Supported: {', '.join(capabilities['hardware'])}")

    subtypes = {subtype.lower(): subtype for subtype in capabilities['subtypes']}
    if gateway.net_type.lower() not in subtypes:
        raise ValueError(f"net_type '{gateway.net_type}' is not supported. "
                         f"Supported: {', '.join(capabilities['subtypes'])}")

    if gateway.version not in capabilities['versions']:
        raise ValueError(f"version '{gateway.version}' is not supported. "
                         f"Supported: {', '.join(capabilities['versions'])}")

    # The API expects the hardware subtype in lowercase, for example 'wired'
    return hardware, gateway.net_type.lower(), gateway.version


def configure_gateway(mgmt_api: ManagementAPI, gateway: GatewayConfig) -> None:
    """Configure the SIC one-time password and blades of the gateway object"""
    log.debug("Starting gateway configuration")
    try:
        mgmt_api.configure_gateway(
            gw_name=gateway.gw_name,
            sic_key=gateway.sic_key,
            application_control=gateway.application_control,
            url_filtering=gateway.url_filtering
        )
        log.info(f"Configured {gateway.gw_name} successfully")


    except Exception as e:
        log.error(f"Configuration failed for {gateway.gw_name}: {redact(str(e), [gateway.sic_key])}")
        raise


def configure_sparks_gateway(gateway: GatewayConfig, mgmt_ip: str) -> None:
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

        # Execute physical configuration commands (Spark CLI Reference Guide). The appliance
        # joins Smart-1 Cloud with the cloud token and pulls its SIC certificate from the
        # management server. Policy is installed from the management afterwards, so no
        # 'fw fetch' is needed here. 'connect security-management' is not used: after
        # 'fetch certificate' it fails with "You must reinitialize trusted communications"
        # (verified on R81.10.17).
        commands = [
            # "add interface-loopback ipv4-address 10.0.0.1 mask-length 32",
            # "cplic put #your_license_string",
            f"connect maas auth-token {gateway.maas_token}",
            "set security-management mode centrally-managed",
            f"set sic_init password {gateway.sic_key}",
            f"fetch certificate mgmt-ipv4-address {mgmt_ip} gateway-name {gateway.gw_name}"
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
        "set maas mode disable",
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
