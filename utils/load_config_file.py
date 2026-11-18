"""Reads and validates the JSON configuration files"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ValidationError, ConfigDict
from .logger_main import log

class AuthConfig(BaseModel):
    """Smart-1 Cloud tenant and Management API key (auth_data.json)"""
    instance: str
    context: str
    api_key: str

class GatewayConfig(BaseModel):
    """One gateway in config_data.json"""
    gw_name: str
    version: str
    hardware: str
    net_type: str
    sic_key: str
    gateway_ip: Optional[str] = None
    gateway_username: Optional[str] = None
    gateway_password: Optional[str] = None
    # Optional blades. The Firewall blade is always enabled. All others are off unless set.
    vpn: bool = False
    ips: bool = False
    anti_bot: bool = False
    anti_virus: bool = False
    application_control: bool = False
    url_filtering: bool = False
    maas_token: Optional[str] = None
    # Read from the appliance during deployment, for the topology of the gateway object
    interfaces: List[Dict[str, Any]] = []

    # v2 configuration syntax
    model_config = ConfigDict(frozen=False)

    def blades(self) -> Dict[str, bool]:
        """Blade settings, keyed by their set-simple-gateway parameter names"""
        return {
            "vpn": self.vpn,
            "ips": self.ips,
            "anti-bot": self.anti_bot,
            "anti-virus": self.anti_virus,
            "application-control": self.application_control,
            "url-filtering": self.url_filtering,
        }

    def has_threat_prevention(self) -> bool:
        """True when a blade that needs the Threat Prevention policy is enabled"""
        return any([self.ips, self.anti_bot, self.anti_virus])

    def has_appliance_credentials(self) -> bool:
        """True when the deployer can configure the appliance over its local REST API"""
        return all([self.gateway_ip, self.gateway_username, self.gateway_password])

    def has_partial_appliance_credentials(self) -> bool:
        """True when only some of gateway_ip, gateway_username and gateway_password are set"""
        return (any([self.gateway_ip, self.gateway_username, self.gateway_password])
                and not self.has_appliance_credentials())

BLADE_KEYS = ("vpn", "ips", "anti_bot", "anti_virus", "application_control", "url_filtering")

class PolicyPackage(BaseModel):
    """Policy package and SIC wait (policy_package_data.json)"""
    policy_package: str
    install_delay: int = 30  # Default 30 seconds if not specified
    sic_timeout: int = 600  # Seconds to wait for gateways to establish SIC before policy install
    model_config = ConfigDict(frozen=False)


def read_config_file(file_name: str) -> Any:
    """
    Original file reading function with added validation
    """
    config_path = Path(file_name)

    if not config_path.exists():
        example = config_path.with_name(f"{config_path.stem}.example{config_path.suffix}")
        raise FileNotFoundError(
            f"Config file {file_name} not found. Copy {example.as_posix()} to "
            f"{config_path.as_posix()} and fill in your values."
        )

    with config_path.open('r', encoding='utf-8') as f:
        try:
            config_data = json.load(f)

            # Automatically validate based on file name
            if "auth_data" in file_name:
                return validate_auth_config(config_data)
            if "config_data" in file_name:
                return validate_gateway_config(config_data)
            if "policy_package_data" in file_name:
                return validate_policy_package_config(config_data)

            return config_data

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {file_name}") from e

def validate_auth_config(config: Dict) -> AuthConfig:
    """Validation wrapper for auth data"""
    try:
        return AuthConfig(**config)
    except ValidationError as e:
        raise ValueError(f"Invalid auth configuration: {str(e)}") from e

def validate_gateway_config(config: List[Dict]) -> List[GatewayConfig]:
    """Validation wrapper for gateway data"""
    try:
        return [GatewayConfig(**normalize_gateway_keys(item)) for item in config]
    except ValidationError as e:
        raise ValueError(f"Invalid gateway configuration: {str(e)}") from e

def normalize_gateway_keys(item: Dict) -> Dict:
    """
    Accept gateway keys in any case and with hyphens or spaces, for example "Anti-Bot" for
    anti_bot. Keys that are still unknown would be ignored without a trace, so they are reported.
    """
    normalized = {}
    for key, value in item.items():
        name = key.strip().lower().replace("-", "_").replace(" ", "_")
        if name in GatewayConfig.__annotations__:
            normalized[name] = value
        else:
            log.warning(f"{item.get('gw_name', 'gateway')}: unknown key '{key}' in config_data.json "
                        f"is ignored. Blade keys: {', '.join(BLADE_KEYS)}")
    return normalized

def validate_policy_package_config(config: Dict) -> PolicyPackage:
    """Validation wrapper for policy package data"""
    try:
        return PolicyPackage(**config)
    except ValidationError as e:
        raise ValueError(f"Invalid auth configuration: {str(e)}") from e
