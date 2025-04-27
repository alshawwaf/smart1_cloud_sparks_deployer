import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ValidationError, ConfigDict

class AuthConfig(BaseModel):
    client_id: str
    access_key: str
    portal_url: str
    instance: str
    context: str
    api_key: str

class GatewayConfig(BaseModel):
    gw_name: str
    version: str
    hardware: str
    net_type: str
    sic_key: str
    gateway_ip: Optional[str] = None
    gateway_username: Optional[str] = None
    gateway_password: Optional[str] = None
    maas_token: Optional[str] = None
    
    # v2 configuration syntax
    model_config = ConfigDict(frozen=False)

class PolicyPackage(BaseModel):
    policy_package: str
    install_delay: int = 30  # Default 30 seconds if not specified
    model_config = ConfigDict(frozen=False)

    
def read_config_file(file_name: str) -> Any:
    """
    Original file reading function with added validation
    """
    config_path = Path(file_name)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file {file_name} not found")
    
    with config_path.open('r') as f:
        try:
            config_data = json.load(f)
            
            # Automatically validate based on file name
            if "auth_data" in file_name:
                return validate_auth_config(config_data)
            elif "config_data" in file_name:
                return validate_gateway_config(config_data)
            elif "policy_package_data" in file_name:
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
        return [GatewayConfig(**item) for item in config]
    except ValidationError as e:
        raise ValueError(f"Invalid gateway configuration: {str(e)}") from e
    
def validate_policy_package_config(config: Dict) -> PolicyPackage:
    """Validation wrapper for policy package data"""
    try:
        return PolicyPackage(**config)
    except ValidationError as e:
        raise ValueError(f"Invalid auth configuration: {str(e)}") from e