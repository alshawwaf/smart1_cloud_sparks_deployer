
#!/usr/bin/env python3
"""
This script will use the provided variables from tfvard.tf to login to the mgmt instance
and configure the gateway we deployed on Azure.

https://alshawwaf-us-s1c-nhb4hsi0.maas.checkpoint.com/c2964eb6-daaa-4eb7-84bb-2935476cbdc9/web_api/login
-i alshawwaf-us-s1c-nhb4hsi0
-c c2964eb6-daaa-4eb7-84bb-2935476cbdc9
-k Lx8Nye1U0z2/UhDuyWTbXQ==
-g sparks_east_1
-v R81.10
-s Vpn123@
-h 1570/1590 Appliances
-t wireless

.venv/Scripts/python.exe assets/smart-1-Cloud-Mgmt-API-Generic -i alshawwaf-us-s1c-nhb4hsi0 -c c2964eb6-daaa-4eb7-84bb-2935476cbdc9 -k Lx8Nye1U0z2/UhDuyWTbXQ== -g "sparks_3" -v "R81.10" -s vpn123 -hw "1570/1590 Appliances" -t "Wireless"
"""

import argparse
import requests
import json
import logging
import sys
import time

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--context", required=True)
    #parser.add_argument("-d", "--domain", required=False)
    parser.add_argument("-i", "--instance", required=True)
    parser.add_argument("-k", "--apikey", required=True)
    parser.add_argument(
        "-g", "--gateway", help="the Gateway Name")
    parser.add_argument("-v", "--version", required=True,
                        help="used to set the Gateway version")
    parser.add_argument("-hw", "--hardware", required=False,
                        help="used to set the Gateway Hardware")
    parser.add_argument("-t", "--type", required=False,
                        help="used to set the Gateway Hardware Type")
    parser.add_argument("-s", "--sickey", required=True)
    parsed_args = parser.parse_args()

    # login to the MGMT Instaincec on SMart-1 Cloud
    login_URL = f"https://{parsed_args.instance}.maas.checkpoint.com/{parsed_args.context}/web_api/login"
    headers = {
        'Content-Type': 'application/json'
    }
    login_payload = json.dumps({
        "api-key": parsed_args.apikey,
    })

    login_res = requests.request(
        "POST", login_URL, headers=headers, data=login_payload)

    if login_res.status_code != 200:
        print("Login failed:\n{}".format(login_res.text))
        exit(1)
    else:
        sid = login_res.json()['sid']
        #print(f" Login Success. Session-id: {sid}")


    # show details regarding the GW
    show_gateway_config_URL = f"https://{parsed_args.instance}.maas.checkpoint.com/{parsed_args.context}/web_api/show-simple-gateway"
    
    headers = {
        'Content-Type': 'application/json',
        'X-chkp-sid': sid
    }

    show_gateway_config_res = requests.request(
                "POST", show_gateway_config_URL, headers=headers, json={"name": parsed_args.gateway})
    show_gateway_response = json.loads(show_gateway_config_res.text)
    gateway_uid = show_gateway_response.get('uid')
    ipv4_address = show_gateway_response.get('ipv4-address')


    
    # Below we use the Generic API call to set the GW type to Sparks. The API call for it is unavailable for now.
    headers = {
        'Content-Type': 'application/json',
        'X-chkp-sid': sid
    }
    show_generic_gateway_URL = f"https://{parsed_args.instance}.maas.checkpoint.com/{parsed_args.context}/web_api/show-generic-object"
    show_generic_gateway_URL_payload = json.dumps({
        "uid": gateway_uid,

    })
    show_generic_gateway_res = requests.request(
                "POST", show_generic_gateway_URL, headers=headers, data=show_generic_gateway_URL_payload)

    print(show_generic_gateway_res.text)


    
    # logout
    logout_URL = f"https://{parsed_args.instance}.maas.checkpoint.com/{parsed_args.context}/web_api/logout"

    logout_res = requests.request(
        "POST", logout_URL, headers=headers, json={})
    #print(f"logout response: {logout_res}")


if __name__ == '__main__':
    main()
