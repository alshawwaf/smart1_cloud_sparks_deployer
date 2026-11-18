#!/usr/bin/env python3
"""
Smart-1 Cloud Gateway Deployment Orchestrator
.venv/Scripts/python.exe s1c_deploy_sparks_gw.py            deploy the gateways
.venv/Scripts/python.exe s1c_deploy_sparks_gw.py --delete   remove the gateways
see the readme file for more details
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests
import urllib3
from utils.logger_main import log, redact
from utils.load_config_file import read_config_file, AuthConfig, GatewayConfig, PolicyPackage
from utils.smart1_cloud_mgmt_api import ManagementAPI
from utils.sparks_rest_api import SparksGatewayAPI
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Cloud tokens of gateways without appliance credentials, for manual onboarding
TOKEN_DIR = Path("tokens")
MANUAL_ONBOARDING = "registered, token saved for manual onboarding"
APPLIANCE_FAILED = "failed: appliance configuration, token saved for manual onboarding"
THREAT_PREVENTION_FAILED = ("failed: Threat Prevention policy installation "
                            "(Access Control policy is installed)")
THREAT_PREVENTION_RETRY = 60  # seconds before the second Threat Prevention attempt
RELOGIN_ATTEMPTS = 5  # appliance logins to try after 'fw sic_reset' drops the connection
# Shown at the start of every run, to tell which version of the deployer produced a log
__version__ = "2026.11.17"


def deploy_s1c_sparks_gw(delete: bool = False) -> None:
    """Main deployment workflow executor"""
    try:
        log.info(f"Smart-1 Cloud Spark Gateway Deployer version {__version__}")
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
    token_expirations: Dict[str, Optional[str]] = {}

    # Say up front which gateways the deployer connects itself and which are left for
    # manual onboarding, so a run never waits for SIC unexpectedly
    automatic = [gw.gw_name for gw in config_data if gw.has_appliance_credentials()]
    manual = [gw.gw_name for gw in config_data if not gw.has_appliance_credentials()]
    log.info(f"{len(automatic)} gateways with appliance credentials, connected by the deployer: "
             f"{', '.join(automatic) or 'none'}")
    log.info(f"{len(manual)} gateways without appliance credentials, for manual onboarding: "
             f"{', '.join(manual) or 'none'}")
    for gateway in config_data:
        if gateway.has_partial_appliance_credentials():
            log.warning(f"{gateway.gw_name}: gateway_ip, gateway_username and gateway_password "
                        "are not all set, so the appliance is left for manual onboarding")

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
            token_expirations[gateway.gw_name] = registration.get('token_expiration')
            log.debug("Cloud registration response: %s",
                      redact(json.dumps(registration, indent=2), [gateway.maas_token]))

            # 2. Cloud Configuration
            log.info("Configuring Gateway Object settings")
            configure_gateway(mgmt_api, gateway)

            if gateway.has_appliance_credentials():
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
            # The gateway object and its cloud token are still valid. Save them, so the
            # appliance can be connected manually, and do not wait for SIC with this gateway.
            configured_gateways.remove(gateway.gw_name)
            token_file = save_onboarding_file(gateway, token_expirations.get(gateway.gw_name), mgmt_ip)
            results[gateway.gw_name] = APPLIANCE_FAILED
            log.error(f"{gateway.gw_name} is registered in Smart-1 Cloud but the appliance was not "
                      f"connected. Fix the cause and run again after --delete, or connect it "
                      f"manually with the steps in {token_file.as_posix()}")
            continue

    if not configured_gateways:
        log.error("No appliance was connected, skipping the SIC wait and policy installation")
        log_summary(results)
        return False

    # Phase 3: Policy Installation, only on gateways that established SIC
    log.info(f"Waiting up to {policy_config.sic_timeout}s for gateways to establish SIC")
    ready_gateways = mgmt_api.wait_for_sic(configured_gateways, timeout=policy_config.sic_timeout)
    for gw_name in configured_gateways:
        if gw_name not in ready_gateways:
            results[gw_name] = "failed: SIC not established"

    if ready_gateways:
        try:
            log.info(f"Installing policy package '{policy_config.policy_package}'")
            # Access Control first. A newly connected gateway rejects the Threat Prevention
            # policy when both are sent in one request (verified on R81.10.17).
            mgmt_api.install_policy(
                policy_targets=ready_gateways,
                policy_package=policy_config.policy_package,
                access=True, threat_prevention=False
            )
            for gw_name in ready_gateways:
                results[gw_name] = "deployed"

        except Exception as e:
            log.error(f"Policy installation failed: {str(e)}")
            for gw_name in ready_gateways:
                results[gw_name] = "failed: policy installation"
            ready_gateways = []

        # Threat Prevention second, only on gateways with IPS, Anti-Bot or Anti-Virus enabled
        threat_prevention_gateways = [gw.gw_name for gw in config_data
                                      if gw.gw_name in ready_gateways and gw.has_threat_prevention()]
        if threat_prevention_gateways:
            install_threat_prevention(mgmt_api, threat_prevention_gateways,
                                      policy_config.policy_package, results)
    else:
        log.error("No gateway established SIC, skipping policy installation")

    log_summary(results)
    return all(state in ("deployed", MANUAL_ONBOARDING) for state in results.values())


def install_threat_prevention(mgmt_api: ManagementAPI, gw_names: List[str], policy_package: str,
                              results: Dict[str, str]) -> None:
    """Install the Threat Prevention policy, with one retry, and record a failure in results"""
    for attempt in (1, 2):
        try:
            mgmt_api.install_policy(
                policy_targets=gw_names,
                policy_package=policy_package,
                access=False, threat_prevention=True
            )
            return
        except Exception as e:
            log.error(f"Threat Prevention policy installation failed (attempt {attempt} of 2): {str(e)}")
            if attempt == 1:
                log.info(f"Retrying in {THREAT_PREVENTION_RETRY}s")
                time.sleep(THREAT_PREVENTION_RETRY)
    for gw_name in gw_names:
        results[gw_name] = THREAT_PREVENTION_FAILED


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
        if gateway.has_appliance_credentials():
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
            blades=gateway.blades()
        )
        enabled = [blade for blade, state in gateway.blades().items() if state]
        log.info(f"Configured {gateway.gw_name} successfully. Blades: "
                 f"{', '.join(['firewall'] + enabled)}")

    except Exception as e:
        log.error(f"Configuration failed for {gateway.gw_name}: {redact(str(e), [gateway.sic_key])}")
        raise


def configure_sparks_gateway(gateway: GatewayConfig, mgmt_ip: str) -> None:
    """Configure physical gateway using dedicated API client"""
    if not gateway.has_appliance_credentials():
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
    sparks_gw.execute_clish(["set maas mode disable"], delay=5)
    # 'fw sic_reset' restarts the firewall and loads the initial policy, which can drop
    # the REST API connection before the command returns. Log in again and continue.
    try:
        sparks_gw.execute_clish(["fw sic_reset"], delay=5)
    except requests.exceptions.RequestException:
        log.warning("Connection to the appliance dropped during 'fw sic_reset', logging in again")
        # The appliance can take a few minutes to answer again
        for attempt in range(1, RELOGIN_ATTEMPTS + 1):
            time.sleep(30)
            try:
                sparks_gw.login()
                break
            except (RuntimeError, requests.exceptions.RequestException):
                if attempt == RELOGIN_ATTEMPTS:
                    raise
                log.warning(f"Appliance not answering yet (attempt {attempt} of {RELOGIN_ATTEMPTS})")
    # The local management mode must be set after 'fw sic_reset', which otherwise
    # switches the appliance back to central management (verified on R81.10.17)
    outputs = sparks_gw.execute_clish([
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
