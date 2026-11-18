# Smart-1 Cloud Spark Gateway Deployer

Automated onboarding of Check Point Quantum Spark gateways to Smart-1 Cloud.

![Smart-1 Cloud R82.20](https://img.shields.io/badge/Smart--1_Cloud-R82.20-555555)
![Spark firmware R81.10.X and R82.00.X](https://img.shields.io/badge/Spark-R81.10.X_%7C_R82.00.X-555555)
![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-555555)

[Overview](#overview) · [Live Example](#live-deployment-example) · [Quick Start](#quick-start) ·
[Compatibility](#version-compatibility) · [Configuration](#configuration) ·
[Troubleshooting](#troubleshooting) · [Changelog](#changelog)

---

## Overview

The Smart-1 Cloud Spark Gateway Deployer automates the onboarding of Check Point Quantum Spark
gateways to Check Point Smart-1 Cloud. From a single set of configuration files, it registers each
gateway, configures the gateway object, installs the security policy and, optionally, configures
the appliance itself.

| Capability | Description |
|:---|:---|
| **Registration** | Registers any number of gateways in Smart-1 Cloud with only a Management API key. |
| **Object configuration** | Creates the Spark gateway object with the parameters documented in the Smart-1 Cloud Administration Guide, after checking them against the tenant, sets the SIC trust settings and enables the blades configured for the gateway. |
| **Policy installation** | Waits for each gateway to establish SIC, then installs the policy package: first the Access Control policy, then the Threat Prevention policy on gateways where IPS, Anti-Bot or Anti-Virus is enabled. |
| **Appliance configuration** | Connects each appliance to Smart-1 Cloud over its local REST API, when its credentials are configured. Otherwise, saves the cloud token and the onboarding steps to a local file for manual onboarding. |
| **Removal** | Returns the appliances to local management and deletes their gateway objects (`--delete`). |
| **Validation and logging** | Validates all configuration files before the run and keeps a rotating DEBUG log of every run. |

### Architecture

<p align="center">
  <img src="docs/images/architecture.svg" alt="Architecture: the deployer calls the Smart-1 Cloud Management API and the Spark appliance local REST API" width="100%">
</p>

### Workflow

<p align="center">
  <img src="docs/images/workflow.svg" alt="Workflow: phase 1 register and configure, phase 2 configure the appliance, phase 3 install policy" width="100%">
</p>

Policy is installed last, because a gateway accepts policy only after it has connected to
Smart-1 Cloud and established SIC. Phase 3 waits for each gateway to reach the "communicating"
SIC state and installs policy only on those gateways. The Access Control policy is installed
first and the Threat Prevention policy in a second request, because a newly connected gateway
rejects the Threat Prevention policy when both are sent together.

Before the policy is installed, the deployer sets the interfaces of each gateway object. It reads
them from the appliance in phase 2 (`show interfaces table` and `show internet-connections table`)
and sets them on the object once SIC is established: Internet connections as external interfaces,
all other interfaces with an IP address as internal, with Anti-Spoofing on. For gateways with
Threat Prevention blades it sets them again after the Threat Prevention policy and installs the
Access Control policy once more. See
[Interfaces and topology](#interfaces-and-topology).

Phase 2 runs only for gateways whose appliance credentials (`gateway_ip`, `gateway_username`,
`gateway_password`) are configured. For a gateway without them, the deployer registers and
configures the object, then saves the cloud token and the onboarding steps to
`tokens/<gw_name>.txt` (see [Manual Onboarding](#manual-onboarding)). These gateways are not part
of phases 2 and 3: connect the appliance with the steps in the file, then install the policy from
SmartConsole.

If phase 2 fails for a gateway, for example because the appliance REST API is off or cannot be
reached, the deployer saves the same `tokens/<gw_name>.txt` file for it and does not wait for SIC
with that gateway. The gateway is reported as failed, and the appliance can still be connected
with the steps in the file.

A gateway that fails at any step is logged and skipped, and the run continues with the remaining
gateways. The run ends with a summary of each gateway and exits with a non-zero code if any
gateway was not deployed.

## Live Deployment Example

Console output of a real deployment against a Smart-1 Cloud tenant (Management API 2.1) and a
Quantum Spark VNF appliance running R81.10.17. Secrets are masked by the deployer. The 20-second
pauses between appliance commands are omitted.

<p align="center">
  <img src="docs/images/deployment-run.png" alt="Console output of a real deployment run: gateway registered, appliance configured, SIC established, policy installed, 1 of 1 gateways deployed" width="100%">
</p>

| Phase | Start | End | Duration |
|:---|:---:|:---:|---:|
| **1** &nbsp; Register and configure the object | `22:15:58` | `22:17:06` | 1 min 8 s |
| **2** &nbsp; Configure the appliance | `22:17:21` | `22:18:58` | 1 min 37 s |
| **3** &nbsp; Wait for SIC and install policy | `22:19:08` | `22:19:54` | 46 s |
| **Total** | | | **3 min 56 s** |

<details>
<summary><b>Configuration used for this run</b></summary>

`config/auth_data.json`:

```json
{
    "instance": "<instance>",
    "context": "<context-uuid>",
    "api_key": "<management-api-key>"
}
```

`config/config_data.json`:

```json
[
    {
        "gw_name": "spark-lab-01",
        "version": "R81.10",
        "hardware": "1800",
        "net_type": "Wired",
        "sic_key": "<one-time-password>",
        "gateway_ip": "<appliance-address>:4434",
        "gateway_username": "admin",
        "gateway_password": "<appliance-password>",
        "application_control": true,
        "url_filtering": true
    }
]
```

Application Control and URL Filtering are enabled because this tenant adds new gateways to
`Playblocks_Gateways`. See the note in [Configuration](#configuration).

`config/policy_package_data.json`:

```json
{
    "policy_package": "Standard",
    "sic_timeout": 600
}
```

</details>

**Result, verified in Smart-1 Cloud after the run:**

| Status | Check | Result |
|:---:|:---|:---|
| ![pass](https://img.shields.io/badge/-pass-2EA44F?style=flat-square) | **Gateway object** | `spark-lab-01`, Gaia Embedded, R81.10, 1800 Appliances, interfaces `WAN` (external) and `LAN1` (internal) read from the appliance, IP address generated by Smart-1 Cloud |
| ![pass](https://img.shields.io/badge/-pass-2EA44F?style=flat-square) | **SIC** | `test-sic-status`: `SIC Status for spark-lab-01: Communicating` |
| ![pass](https://img.shields.io/badge/-pass-2EA44F?style=flat-square) | **Access Control policy** | `Standard`, installed |
| ![pass](https://img.shields.io/badge/-pass-2EA44F?style=flat-square) | **Appliance access** | SSH and the web UI on port 4434 reachable after policy installation |

### Removal

The same gateway removed with `--delete`, 1 min 3 s. The 5-second pauses between appliance commands
are omitted.

<p align="center">
  <img src="docs/images/gateway-removal.png" alt="Console output of a real --delete run: appliance reset to local management, gateway object deleted, spark-lab-01 removed" width="100%">
</p>

**Result, verified after the run:** no gateway objects left in Smart-1 Cloud, `Playblocks_Gateways`
empty, and on the appliance `show security-management` reports `locally-managed`, `show maas`
reports `disabled`, and `fw sic_test` reports `SIC was not initialized`.

## Quick Start

Clone the repository, install the dependencies and create your configuration files from the
templates.

**Windows (PowerShell)**

```powershell
git clone https://github.com/alshawwaf/smart1_cloud_sparks_deployer.git
cd smart1_cloud_sparks_deployer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config\auth_data.example.json config\auth_data.json
copy config\config_data.example.json config\config_data.json
copy config\policy_package_data.example.json config\policy_package_data.json
```

**Linux**

```bash
git clone https://github.com/alshawwaf/smart1_cloud_sparks_deployer.git
cd smart1_cloud_sparks_deployer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/auth_data.example.json config/auth_data.json
cp config/config_data.example.json config/config_data.json
cp config/policy_package_data.example.json config/policy_package_data.json
```

Fill in the three files as described in [Configuration](#configuration), then run the deployment:

```bash
python s1c_deploy_sparks_gw.py
```

The run ends with a summary of each gateway. See [Live Deployment Example](#live-deployment-example)
for the output of a real run.

To remove the gateways in `config_data.json` again, run:

```bash
python s1c_deploy_sparks_gw.py --delete
```

For each gateway, `--delete`:

1. Returns the appliance to local management, when its REST API credentials are configured:
   `set maas mode disable`, `fw sic_reset`, `set security-management mode locally-managed`,
   and checks the result with `show security-management`.
2. Deletes the gateway object in Smart-1 Cloud, including its membership in groups such as
   `Playblocks_Gateways`, and publishes.

If the appliance reset fails, the gateway object is still deleted and the gateway is reported as
failed in the removal summary. A gateway that no longer exists in Smart-1 Cloud is skipped, so
`--delete` can be run again safely. After `--delete`, the appliance can be deployed again from
scratch. For a gateway without appliance credentials, `--delete` deletes the object and its token
file, and the appliance must be reset manually.

### Manual Onboarding

To onboard an appliance yourself, for example when the machine that runs the deployer cannot reach
it, leave out `gateway_ip`, `gateway_username` and `gateway_password` for that gateway. The
deployer then:

1. Registers and configures the gateway object as usual.
2. Saves `tokens/<gw_name>.txt` with the cloud token, its expiration date, and the onboarding
   steps for the Spark WebUI and for Gaia Clish, taken from the
   [Smart-1 Cloud Administration Guide](https://sc1.checkpoint.com/documents/Infinity_Portal/WebAdminGuides/EN/Check-Point-SmartCloud-Admin-Guide/CP_Check_Point_Smart-1_Cloud_AdminGuide.pdf) (Connecting a Spark Firewall
   Appliance). The file names the management server address for `fetch certificate`.
3. Reports the gateway as `registered, token saved for manual onboarding`. This does not count as
   a failure.

The SIC one-time password is not written to the file. Use the `sic_key` value from
`config_data.json`. After the appliance is connected, install the policy on it from SmartConsole.

> [!CAUTION]
> The token file contains a credential. `tokens/` is excluded by `.gitignore`. Delete the file
> after the appliance is connected.

### Requirements

- A Check Point Smart-1 Cloud tenant on R82.20 (Management API 2.1 or later).
- The Management API key of the tenant. In Web SmartConsole, go to **Settings > API &
  SmartConsole** and click **Generate** in the Management API section. Smart-1 Cloud supports only
  one API key.
- Python 3.9 or later on Windows or Linux.
- To configure the appliances (phase 2) and reset them with `--delete`:
  - Network access to the appliance local REST API, by default on port `4434`.
  - The REST API enabled on the appliance. It is off by default. Enable it in Gaia Clish with
    `set rest-api mode true`.

### Network Requirements

All connections are outbound. No inbound access and no public IP address are needed, and
Smart-1 Cloud never connects to the appliance local REST API.

| From | To | Port | Carries |
|:---|:---|:---:|:---|
| Machine that runs the deployer | `<instance>.maas.checkpoint.com` (Management API) | 443 | Management API key, gateway settings, SIC one-time password |
| Machine that runs the deployer | Appliance local REST API (`gateway_ip`, for example a private lab address) | 4434 | Appliance administrator credentials, cloud token, SIC one-time password. Phase 2 and `--delete` only. |
| Appliance | `<instance>.maas.checkpoint.com` and the regional `cloudinfra-gw` address | 443 | Outbound tunnel to Smart-1 Cloud. Management traffic, SIC and policy installation run inside this tunnel. |

If the appliance or the machine that runs the deployer is behind another firewall, allow this
outbound HTTPS traffic. The [Smart-1 Cloud Administration Guide](https://sc1.checkpoint.com/documents/Infinity_Portal/WebAdminGuides/EN/Check-Point-SmartCloud-Admin-Guide/CP_Check_Point_Smart-1_Cloud_AdminGuide.pdf) lists the
addresses for each region (How to Connect a Security Gateway Behind a NAT/Proxy or Third-Party
Security Gateway). Run phase 2 from a machine on a trusted network that can reach the appliances,
because the deployer does not verify the appliance certificate.

> [!WARNING]
> The deployer installs the policy package exactly as it is published. Before you run it, make
> sure the policy allows the management access you need to the appliances, for example HTTPS and
> SSH from your administration network. A cleanup rule that drops all traffic locks you out of
> the appliance local interfaces as soon as the policy is installed.

## Version Compatibility

The deployer reads the Management API version at each login and shows it in the console:

```text
INFO - Connected to Management API version 2.2
```

### Smart-1 Cloud Management

| Smart-1 Cloud | Management API | Status | Notes |
|:---:|:---:|:---:|:---|
| **R82.20** | `2.1`, `2.2` | ![supported](https://img.shields.io/badge/-supported-2EA44F?style=flat-square) | Gateways are created with `add-simple-gateway` and `trust-method: cloud_token`. SIC uses a one-time password with `trust-settings.initiation-phase` set to `when_gateway_connects`. |
| **Earlier versions** | earlier than `2.1` | ![not supported](https://img.shields.io/badge/-not_supported-CF222E?style=flat-square) | Management API versions earlier than 2.1 cannot issue cloud tokens. Registration fails with `Management API ... cannot issue cloud tokens`. |

> [!IMPORTANT]
> **Smart-1 Cloud R82.20 requires the current version of the deployer.**
> R82.20 added the `trust-method` and `trust-settings` parameters to `set-simple-gateway`. When a
> one-time password is set on an object that is not yet a Spark gateway, the management server
> pushes the SIC certificate immediately. Spark appliances behind Smart-1 Cloud cannot be reached
> in this way, so earlier versions of the deployer fail at the SIC step.

<p align="center">
  <img src="docs/images/sic-r82.20.svg" alt="SIC configuration before and after the R82.20 fix" width="100%">
</p>

### Spark Gateway Firmware

| Spark models | Minimum firmware | `version` in `config_data.json` |
|:---|:---:|:---:|
| **1500, 1600, 1800, 1900, 2000** | R81.10.X | `R81.10` or `R82` |
| **2530/2550, 2560/2570, 2580** | R82.00.05 | `R82` |
| **Quantum Edge** | R81.10.X | `R81.10` or `R82` |
| **Firmware R80.20.X and earlier** | ![not supported](https://img.shields.io/badge/-not_supported-CF222E?style=flat-square) | Upgrade the appliance first |

Models and minimum firmware are from the [Smart-1 Cloud Administration Guide](https://sc1.checkpoint.com/documents/Infinity_Portal/WebAdminGuides/EN/Check-Point-SmartCloud-Admin-Guide/CP_Check_Point_Smart-1_Cloud_AdminGuide.pdf)
(Supported Gateways and Versions, 26 October 2026). Use `R81.10` for appliances on R81.10.X and
`R82` for appliances on R82.00.X. The deployer was tested with a Quantum Spark VNF appliance on
R81.10.17, configured as `1800 Appliances`.

> [!WARNING]
> Rugged 1200R appliances are not supported by Management Servers R82.20 (R82.20 Release Notes).

> [!TIP]
> To list the versions and hardware models that your tenant accepts, run the Management API
> command `show-gateway-capabilities` with `{"platform": "smb"}`, for example from the
> SmartConsole command line.

### net_type values by model

`show-gateway-capabilities` lists the subtypes of all Spark models together, but each model
accepts only some of them. These are the combinations that Smart-1 Cloud R82.20 accepted when
tested with `add-simple-gateway` in November 2026:

| `hardware` | `version` | Accepted `net_type` |
|:---|:---:|:---|
| **1530/1550**, **1535/1555** | `R81.10`, `R82` | `Wired`, `Wireless` |
| **1570/1590**, **1575/1595** | `R81.10`, `R82` | `Wired`, `Wireless`, `Wireless + DSL`, `WiFi-LTE` |
| **1600**, **1800**, **1900/2000** | `R81.10`, `R82` | `Wired` |
| **2530/2550**, **2560/2570** | `R82` | `Wired`, `WiFi-LTE` |
| **2580**, **2590** | `R82` | `Wired` |

> [!IMPORTANT]
> The 2530/2550 and 2560/2570 Wi-Fi models are registered as `WiFi-LTE`. `Wireless` is rejected
> for these models with *"Hardware/hardware-subtype value is not valid or doesn't match specified
> platform"*. `DSL` on its own was not accepted for any model.

### Gateway Registration

Each gateway is created through the Management API, as described in the
[Smart-1 Cloud Administration Guide](https://sc1.checkpoint.com/documents/Infinity_Portal/WebAdminGuides/EN/Check-Point-SmartCloud-Admin-Guide/CP_Check_Point_Smart-1_Cloud_AdminGuide.pdf) (Example: Adding a Simple Gateway with the
Web API):

| Step | Management API command | Result |
|:---:|:---|:---|
| **1** | `show-gateway-capabilities` with `platform: smb` | `hardware`, `net_type` and `version` are checked against the values the tenant accepts, before any object is created |
| **2** | `add-simple-gateway` with `hardware` (for example `1800 Appliances`), `hardware-subtype`, `version`, `os-name: Gaia Embedded`, `trust-method: cloud_token` and `auto-generate-ip: true` | Spark gateway object with `global and automatic` topology, an IP address generated by Smart-1 Cloud, and a cloud token |
| **3** | `set-simple-gateway` with `one-time-password` and `trust-settings.initiation-phase: when_gateway_connects` | SIC waits for the appliance. The SIC name is generated by the management server. |

The one-time password is set in a separate call, because the Management API rejects
`one-time-password` together with `trust-method: cloud_token`.

### Interfaces and topology

A new Spark gateway object has `global and automatic` topology and only placeholder interfaces
without addresses (`WAN`, `LAN Switch`, `DMZ`). The Management API command `get-interfaces` does not work for Spark gateways (`Failed to get
interfaces`), so the deployer reads the interfaces from the appliance and sets them itself:

| Step | Where | Result |
|:---:|:---|:---|
| **1** | Appliance, `show internet-connections table` | Each Internet connection with an IPv4 address becomes an **external** interface, named after its interface, for example `WAN` |
| **2** | Appliance, `show interfaces table` | Each other interface with an IPv4 address becomes an **internal** interface, for example `LAN1`. Interfaces without an address are left out |
| **3** | Management API, `set-simple-gateway` with `interfaces-topology-settings: per interface` and `interfaces` | The interfaces are on the object, with Anti-Spoofing on (Prevent) |

- Step 3 runs after SIC is established and before the Access Control policy is installed.
- The first Threat Prevention installation on a Spark gateway empties the interface list of its
  object and leaves it in `per interface` mode (observed on R81.10.17 with Smart-1 Cloud R82.20).
  For gateways with IPS, Anti-Bot or Anti-Virus the deployer therefore repeats step 3 after the
  Threat Prevention installation and installs the Access Control policy once more. Later
  installations keep the list.
- The network behind an internal interface is the network of its own IP address and mask, the
  only choice the API accepts for Spark gateways. If other networks are routed behind an internal
  interface, add them to that interface in SmartConsole, or Anti-Spoofing drops their traffic.
- An interface named `DMZ` is marked as leading to a DMZ.
- If the interfaces cannot be read or set, the deployer logs a warning, the object keeps its
  `global and automatic` topology, and the deployment continues.
- Gateways without appliance credentials ([Manual Onboarding](#manual-onboarding)) keep
  `global and automatic` topology. Set their interfaces in SmartConsole.

In phase 2, the appliance joins Smart-1 Cloud with `connect maas auth-token <token>` and pulls its
certificate from the management server address, which the deployer reads from the
`Management_Service` object (a `100.64.x.x` address). The token is masked in the console and the
log file.

### Tested Environment

The current version was tested end to end against:

| Component | Version |
|:---|:---|
| **Smart-1 Cloud** | R82.20, Management API `2.1` and `2.2` |
| **Quantum Spark** | VNF appliance `R81.10.17`, Build 521 |
| **Registration** | Management API (cloud token) |
| **Blades** | Firewall, IPsec VPN, IPS, Anti-Bot, Anti-Virus, Application Control, URL Filtering |
| **Last tested** | 17 November 2026, deployer version `2026.11.17` |

| Status | Test | Result |
|:---:|:---|:---|
| ![pass](https://img.shields.io/badge/-pass-2EA44F?style=flat-square) | **Deployment** | Gateway registered, appliance connected, SIC communicating, policy installed, appliance still reachable on SSH and its web UI |
| ![pass](https://img.shields.io/badge/-pass-2EA44F?style=flat-square) | **Blades and policy** | All six optional blades enabled on the object. Access Control policy installed, then Threat Prevention policy installed in a second request, without a retry |
| ![pass](https://img.shields.io/badge/-pass-2EA44F?style=flat-square) | **Interfaces and topology** | `WAN 203.0.113.212/24` external and `LAN1 192.168.212.1/24` internal on the object after deployment with all six blades. Appliance still reachable for administration |
| ![pass](https://img.shields.io/badge/-pass-2EA44F?style=flat-square) | **Manual onboarding** | Gateway without appliance credentials registered, token file saved, no SIC wait |
| ![pass](https://img.shields.io/badge/-pass-2EA44F?style=flat-square) | **Removal**<br>`--delete` | Appliance back to local management with SIC reset, gateway object deleted |

Not tested on an appliance: the *REST API is off* message (the lab appliance has the REST API
enabled), and the login retry in `--delete` (the connection did not drop long enough to need it).

## Configuration

The deployer reads three JSON files from the `config` directory. The repository contains a
template for each file. Your own files are excluded by `.gitignore`, so credentials are never
committed.

```text
config/
├── auth_data.example.json             Template: Smart-1 Cloud credentials
├── config_data.example.json           Template: one entry for each gateway
├── policy_package_data.example.json   Template: policy package and timeouts
├── auth_data.json                     Your file (not tracked)
├── config_data.json                   Your file (not tracked)
└── policy_package_data.json           Your file (not tracked)
```

> [!NOTE]
> JSON does not support comments, so do not add `//` notes to the files. Keys that are not
> described below are ignored.

> [!IMPORTANT]
> **Upgrading from an earlier version:** the configuration files were previously tracked in the
> repository and are now excluded. Copy your `config` folder to a safe location before you run
> `git pull`, then copy your three files back into `config/`. If `git pull` reports local changes
> to the configuration files, run `git checkout -- config` after the backup and pull again.
> Earlier versions used Infinity Portal API keys (`client_id`, `access_key`, `portal_url`) in
> `auth_data.json`. They are no longer used and can be removed.

### `config/auth_data.json`

```json
{
    "instance": "your-instance",
    "context": "your-context-uuid",
    "api_key": "your-management-api-key"
}
```

| Key | Required | Description |
|:---|:---:|:---|
| `instance` | ![required](https://img.shields.io/badge/-required-0969DA?style=flat-square) | Smart-1 Cloud instance name, taken from the Management API URL `https://<instance>.maas.checkpoint.com/<context>/web_api`. Web SmartConsole shows this URL in **Settings > API & SmartConsole**. |
| `context` | ![required](https://img.shields.io/badge/-required-0969DA?style=flat-square) | Smart-1 Cloud context ID, taken from the same URL. |
| `api_key` | ![required](https://img.shields.io/badge/-required-0969DA?style=flat-square) | Management API key of the tenant, generated in Web SmartConsole in **Settings > API & SmartConsole**. |

### `config/config_data.json`

```json
[
    {
        "gw_name": "sparks1",
        "version": "R81.10",
        "hardware": "1575/1595",
        "net_type": "Wireless",
        "sic_key": "your-sic-key",
        "gateway_ip": "203.0.113.171:4434",
        "gateway_username": "admin",
        "gateway_password": "your-appliance-password",
        "vpn": true,
        "ips": true,
        "anti_bot": true,
        "anti_virus": true,
        "application_control": true,
        "url_filtering": true
    },
    {
        "gw_name": "sparks2",
        "version": "R82",
        "hardware": "1800",
        "net_type": "Wired",
        "sic_key": "your-sic-key"
    }
]
```

| Key | Required | Description |
|:---|:---:|:---|
| `gw_name` | ![required](https://img.shields.io/badge/-required-0969DA?style=flat-square) | Gateway name, used for the Smart-1 Cloud registration and the gateway object. |
| `version` | ![required](https://img.shields.io/badge/-required-0969DA?style=flat-square) | Firmware family of the appliance, as accepted by the tenant: `R81.10` or `R82`. See [Spark Gateway Firmware](#spark-gateway-firmware). |
| `hardware` | ![required](https://img.shields.io/badge/-required-0969DA?style=flat-square) | Spark model as listed by `show-gateway-capabilities`, for example `1800 Appliances` or `1575/1595 Appliances`. The short form without "Appliances", for example `1800`, is also accepted. |
| `net_type` | ![required](https://img.shields.io/badge/-required-0969DA?style=flat-square) | Appliance variant, not case-sensitive: `Wired`, `Wireless`, `Wireless + DSL` or `WiFi-LTE`. Each model accepts only some of them, for example a 2560/2570 with Wi-Fi uses `WiFi-LTE`, not `Wireless`. See [net_type values by model](#net_type-values-by-model). |
| `sic_key` | ![required](https://img.shields.io/badge/-required-0969DA?style=flat-square) | One-time password used to establish SIC. |
| `gateway_ip` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Address and port of the appliance local REST API, for example `203.0.113.171:4434`. |
| `gateway_username` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Administrator user name on the appliance. |
| `gateway_password` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Administrator password on the appliance. |
| `vpn` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Enable the IPsec VPN blade. Default `false`. |
| `ips` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Enable the IPS blade. Default `false`. |
| `anti_bot` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Enable the Anti-Bot blade. Default `false`. |
| `anti_virus` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Enable the Anti-Virus blade. Default `false`. |
| `application_control` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Enable the Application Control blade. Default `false`. |
| `url_filtering` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Enable the URL Filtering blade. Default `false`. |

The Firewall blade is always enabled. Every other blade is off unless its key is set to `true`
for that gateway, so a gateway without blade keys is created with the Firewall blade only. In the
example above, `sparks1` gets all six blades and `sparks2` gets the Firewall blade only. The
console shows the result for each gateway:

```text
INFO - Configured sparks1 successfully. Blades: firewall, vpn, ips, anti-bot, anti-virus, application-control, url-filtering
```

With `vpn` enabled, the Access Control installation reports the warning *"Gateway ... has an
empty Encryption Domain"* until you define the VPN domain of the gateway in SmartConsole. The
installation still succeeds. The policy package needs a Threat Prevention policy when `ips`,
`anti_bot` or `anti_virus` is enabled.

> [!NOTE]
> In the test tenant, which uses Playblocks, new gateways were added to the `Playblocks_Gateways`
> group shortly after they were deployed. The Quarantine Policy rules for that group require
> Application Control and URL Filtering. If this happens in your tenant, set both to `true` for
> those gateways, otherwise later policy installations fail with *"Rule 2 contains applications ... that require the 'Application
> Control' or the 'URL Filtering' blades"*.

To have the deployer configure the appliance in phase 2 and reset it with `--delete`, provide all
three of `gateway_ip`, `gateway_username` and `gateway_password`. Without them, the cloud token is
saved for [Manual Onboarding](#manual-onboarding). The deployer waits for SIC and installs policy
only for gateways that have all three, so remove them from every gateway that you onboard
yourself. At the start of a run, the console lists which gateways are in each group.

### `config/policy_package_data.json`

```json
{
    "policy_package": "Standard",
    "install_delay": 30,
    "sic_timeout": 600
}
```

| Key | Required | Description |
|:---|:---:|:---|
| `policy_package` | ![required](https://img.shields.io/badge/-required-0969DA?style=flat-square) | Name of the policy package to install on the gateways. |
| `sic_timeout` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Seconds to wait for gateways to establish SIC before policy installation. Default `600`. |
| `install_delay` | ![optional](https://img.shields.io/badge/-optional-6E7781?style=flat-square) | Reserved. Not used by the current version of the deployer. |

## Logging

| Output | Level | Content |
|:---|:---:|:---|
| **Console** | `INFO` | Progress of each phase and gateway. |
| **`logs/s1c_deploy_sparks_gw.log`** | `DEBUG` | Full details, including API responses. Rotated at 5 MB, with 3 backups. |

MaaS tokens, SIC one-time passwords and appliance passwords are replaced with `********` in the
console and in the log file.

**Resilience**

- All configuration files are validated before the deployment starts.
- Clish output from the appliance is checked, so a rejected command fails that gateway instead of
  being reported as successful.
- SIC is confirmed with `test-sic-status`, which actively tests the connection.
- The `hardware`, `net_type` and `version` of each gateway are checked against the tenant before
  any object is created. A gateway with an unsupported value fails with a list of the accepted
  values.
- Every HTTP request has a 60-second timeout, and publish and policy installation tasks have a
  30-minute limit, so a stalled connection cannot stop the run indefinitely.
- Each phase opens and closes its own Management API session.
- The Access Control policy and the Threat Prevention policy are installed in separate requests,
  and a failed Threat Prevention installation is repeated once.
- A gateway whose appliance cannot be configured keeps its object and gets a token file, and the
  run does not wait for SIC with it.
- The interfaces of the object are set before the Access Control policy is installed, and again
  after the first Threat Prevention installation, which empties them. A failure to set them is a
  warning, not a failed deployment.
- A task status request that gets no answer is repeated, so one timeout of a busy management
  server does not fail a publish or a policy installation.

## Troubleshooting

Expand an entry for its cause and resolution.

<details>
<summary>SIC errors on <code>set-simple-gateway</code>, or the gateway does not reach the "communicating" state, after the upgrade to R82.20</summary>

**Cause:** Earlier versions of the deployer set the one-time password before the object was a Spark gateway

**Resolution:** Update to the current version and confirm that the log shows `Management API version 2.1` or later.

</details>

<details>
<summary><code>Policy installation failed</code> with a session error</summary>

**Cause:** Earlier versions of the deployer used a closed Management API session

**Resolution:** Update to the current version.

</details>

<details>
<summary><code>SIC not established with ... skipping policy installation</code></summary>

**Cause:** The appliance did not connect to Smart-1 Cloud within `sic_timeout`

**Resolution:** Check the appliance connectivity and the phase 2 log entries. If the appliance needs more time, increase `sic_timeout`, or install policy from SmartConsole once the gateway connects.

</details>

<details>
<summary>SIC test fails with <code>Failed to establish a TCP connection</code>, or <code>set maas mode enable</code> reports <code>MaaS configuration has failed on this gateway</code></summary>

**Cause:** The appliance kept a broken Smart-1 Cloud connection from an earlier attempt, for example after it was connected and disconnected several times. `fw sic_test` on the appliance can still report success.

**Resolution:** Run `--delete`, reboot the appliance (`reboot` in Gaia Clish), confirm that `show maas` reports `disabled` and `show security-management` reports `locally-managed`, then deploy again.

</details>

<details>
<summary><code>Config file ... not found</code></summary>

**Cause:** The configuration file has not been created

**Resolution:** Copy the matching `.example.json` template in `config/` and fill in your values.

</details>

<details>
<summary><code>The REST API on this appliance is off</code></summary>

**Cause:** The appliance local REST API is disabled (default)

**Resolution:** On the appliance, run `set rest-api mode true` in Gaia Clish. The gateway object already exists, so either run `--delete` and deploy again, or connect the appliance with the steps in `tokens/<gw_name>.txt`.

</details>

<details>
<summary><code>Cannot reach the appliance REST API at ...</code></summary>

**Cause:** The machine that runs the deployer cannot open an HTTPS connection to `gateway_ip`

**Resolution:** Check the address and port in `gateway_ip` (the default port is `4434`) and the firewalls between this machine and the appliance. Then run `--delete` and deploy again, or connect the appliance with the steps in `tokens/<gw_name>.txt`.

</details>

<details>
<summary><code>failed: Threat Prevention policy installation (Access Control policy is installed)</code></summary>

**Cause:** The gateway accepted the Access Control policy but not the Threat Prevention policy, after two attempts

**Resolution:** Install the Threat Prevention policy on the gateway from SmartConsole and read the error it reports. Check that the policy package has a Threat Prevention policy and that the appliance is licensed for the enabled blades.

</details>

<details>
<summary><code>--delete</code> fails with <code>Object ... could not be deleted because it is referenced by other objects</code></summary>

**Cause:** The gateway is used in policy rules, for example as a source, a destination or an install-on target. The appliance is already reset to local management at this point.

**Resolution:** Remove the gateway from those rules in SmartConsole (right-click the object and select **Where Used**), publish, and run `--delete` again.

</details>

<details>
<summary>The gateway object has only the Firewall blade</summary>

**Cause:** Blades are enabled only when their keys are set for the gateway

**Resolution:** Set `vpn`, `ips`, `anti_bot`, `anti_virus`, `application_control` and `url_filtering` to `true` as needed in `config_data.json`. See [Configuration](#configconfig_datajson).

</details>

<details>
<summary>A gateway without appliance credentials still waits for SIC</summary>

**Cause:** An earlier version of the deployer is running, or another gateway in `config_data.json` still has appliance credentials

**Resolution:** Check the first console line, `Smart-1 Cloud Spark Gateway Deployer version ...`. If it is missing, the copy is older than 17 November 2026: update it with `git pull` (see the upgrade note in [Configuration](#configuration) if `git pull` reports local changes). Then check the two lines that list the gateways with and without appliance credentials.

</details>

<details>
<summary><code>Command '...' failed: ...</code> in phase 2</summary>

**Cause:** The appliance rejected a Clish command. The message contains the appliance output.

**Resolution:** For `A trusted communication certificate already exists` or `You must reinitialize trusted communications`, the appliance has SIC from an earlier connection. Run `python s1c_deploy_sparks_gw.py --delete`, then deploy again.

</details>

<details>
<summary><code>Security Gateway and Security Management policy versions are incompatible</code></summary>

**Cause:** The policy was unloaded or changed locally on the appliance after an installation, so the accelerated policy installation no longer matches

**Resolution:** Run `--delete` and deploy again, or disable Accelerated Install Policy for the gateway in SmartConsole (sk168055).

</details>

<details>
<summary>Access to the appliance is lost after policy installation, and the logs show <code>WebUI/SSH access attempt from unallowed source</code></summary>

**Cause:** Earlier versions of the deployer left the gateway object with `per interface` topology and no interfaces

**Resolution:** Update to the current version. It sets the interfaces of the object from the appliance before the policy is installed, and falls back to `global and automatic` topology when it cannot. For an existing gateway, add its interfaces in SmartConsole, or set the topology to `global and automatic`, and install policy.

</details>

<details>
<summary>Access to the appliance is lost after policy installation, and the logs show a policy rule</summary>

**Cause:** The installed policy drops management traffic

**Resolution:** Unload the policy from the appliance console, allow management access in the policy, publish, and redeploy.

</details>

<details>
<summary>Policy installation fails with <code>... require the 'Application Control' or the 'URL Filtering' blades</code></summary>

**Cause:** The gateway was added to a group whose rules need those blades, such as `Playblocks_Gateways`

**Resolution:** Set `application_control` and `url_filtering` to `true` for the gateway and redeploy, or enable the blades in SmartConsole.

</details>

<details>
<summary><code>hardware '...' is not supported</code>, <code>net_type '...' is not supported</code> or <code>version '...' is not supported</code></summary>

**Cause:** The value in `config_data.json` is not one that the tenant accepts for Spark gateways

**Resolution:** Use one of the values listed in the error message. They come from `show-gateway-capabilities`.

</details>

<details>
<summary><code>... does not accept net_type '...'</code></summary>

**Cause:** The model does not accept this `net_type`, although the tenant lists it for other
models. For example, a 2560/2570 with Wi-Fi set to `Wireless`.

**Resolution:** Use a value from [net_type values by model](#net_type-values-by-model), for example
`WiFi-LTE` for a 2560/2570 with Wi-Fi. Nothing is created in Smart-1 Cloud when this error occurs.

</details>

<details>
<summary><code>Management API ... cannot issue cloud tokens</code></summary>

**Cause:** The Smart-1 Cloud tenant is not on R82.20 (Management API 2.1)

**Resolution:** Gateway registration requires Smart-1 Cloud R82.20. See [Version Compatibility](#version-compatibility).

</details>

<details>
<summary><code>Management server upgrade in progress</code> warning</summary>

**Cause:** Smart-1 Cloud is running a background upgrade

**Resolution:** Wait for the upgrade to complete, then run the deployment.

</details>

<details>
<summary>The appliance runs firmware earlier than R81.10.X, or is a Rugged 1200R appliance</summary>

**Cause:** Smart-1 Cloud R82.20 does not support these appliances

**Resolution:** See [Version Compatibility](#version-compatibility).

</details>

For full details of a run, see `logs/s1c_deploy_sparks_gw.log`.

## Security

> [!CAUTION]
> The configuration files contain credentials. They are excluded by `.gitignore`; do not force-add
> them to version control.

- Token files in `tokens/` contain the cloud token of a gateway. Delete them after the appliance
  is connected. `--delete` also deletes them.
- Secrets are masked in the console and the log file. Treat the log file as sensitive anyway,
  because it contains API responses.
- The local REST API client does not verify the appliance certificate. Run phase 2 only on
  trusted management networks.
- Smart-1 Cloud supports only one Management API key, and the deployer uses it. Protect it like an
  administrator password.

## References

The deployer and this README were checked against these documents:

| Resource | Edition | Used for |
|:---|:---|:---|
| **[Smart-1 Cloud Administration Guide](https://sc1.checkpoint.com/documents/Infinity_Portal/WebAdminGuides/EN/Check-Point-SmartCloud-Admin-Guide/CP_Check_Point_Smart-1_Cloud_AdminGuide.pdf)** | 26 October 2026 | Adding a Spark gateway with the Web API, cloud token, supported Spark models and versions, MaaS commands, API key |
| **[Quantum Spark R81.10.X CLI Reference Guide](https://sc1.checkpoint.com/documents/SMB_R81.10.X/CLI/EN/CP_R81.10.X_1500_1600_1800_1900_2000_Appliances_CLI_Guide.pdf)** | 5 October 2026 | `connect maas`, `set maas mode`, `set security-management mode`, `set sic_init`, `fetch certificate`, `fw sic_reset`, `set rest-api` |
| **[Quantum Spark R82.00.X Centrally Managed Administration Guide](https://sc1.checkpoint.com/documents/Appliances/Quantum_Spark_R82.00.X/AdminGuides_Centrally_Managed/EN/CP_R82.00.X_Quantum_Spark_Appliances_Centrally_Managed_AdminGuide.pdf)** | 22 September 2026 | Smart-1 Cloud onboarding of R82.00.X appliances |
| **[Check Point Management API Reference](https://sc1.checkpoint.com/documents/latest/APIs/)** | v2.1 | `add-simple-gateway`, `set-simple-gateway` (including `trust-settings`), `show-gateway-capabilities`, `test-sic-status`, `delete-simple-gateway`, `install-policy` |
| **[R82.20 Release Notes](https://sc1.checkpoint.com/documents/R82.20/WebAdminGuides/EN/CP_R82.20_RN/CP_R82.20_ReleaseNotes.pdf)** | R82.20 | Supported Spark versions, Rugged 1200R |

## Changelog

### November 2026: Interfaces and topology on the gateway object

- The gateway object now gets its interfaces: the deployer reads them from the appliance and sets
  them with their topology (external or internal) and Anti-Spoofing, before the policy is
  installed. Before, the object had `global and automatic` topology and no real interfaces.
- `get-interfaces` of the Management API does not work for Spark gateways, and the first Threat
  Prevention installation empties the interface list. Both are handled, see
  [Interfaces and topology](#interfaces-and-topology). Gateways with Threat Prevention blades get
  one more Access Control installation at the end, about one minute.
- Gateways without appliance credentials keep `global and automatic` topology.
- A task status request that times out is repeated instead of failing the installation.

### November 2026: Blades, appliance failures and version line

- New optional `vpn`, `ips`, `anti_bot` and `anti_virus` settings for each gateway, next to
  `application_control` and `url_filtering`. The console lists the blades enabled on each gateway.
- When phase 2 fails for a gateway, the deployer saves its cloud token and onboarding steps to
  `tokens/<gw_name>.txt` and no longer waits for SIC with it.
- A disabled or unreachable appliance REST API is reported by name, with the command that
  enables it.
- The Access Control policy is installed first and the Threat Prevention policy in a second
  request, with one retry. Sent together, the Threat Prevention installation failed on a newly
  connected gateway with IPS, Anti-Bot and Anti-Virus enabled.
- `--delete` retries the appliance login for up to 2.5 minutes after `fw sic_reset`, instead of
  once.
- Tested end to end against Smart-1 Cloud R82.20 (Management API 2.2) and a Spark VNF appliance on
  R81.10.17 with all six blades: automated deployment, manual onboarding and `--delete`.
- Each run starts with the deployer version and the list of gateways with and without appliance
  credentials. A gateway with only some of the three credential keys gets a warning.

### November 2026: net_type values by model

- New [net_type values by model](#net_type-values-by-model) table, tested against Smart-1 Cloud
  R82.20. The 2530/2550 and 2560/2570 Wi-Fi models use `WiFi-LTE`, not `Wireless`.
- A model and `net_type` combination that Smart-1 Cloud rejects is now reported by name, with a
  pointer to the table, instead of the generic API error.
- The example configuration used `Wireless` for an 1800, which Smart-1 Cloud rejects. It now uses
  `Wired`.

### November 2026: Verified on Management API 2.2

Verified again end to end after the tenant moved to Management API 2.2: automated deployment,
manual onboarding with the token file, and `--delete`.

- `--delete` logs in to the appliance again when `fw sic_reset` drops the REST API connection,
  instead of failing the reset.
- New troubleshooting entry for an appliance that kept a broken Smart-1 Cloud connection.

### November 2026: Manual onboarding

- Gateways without appliance credentials are registered and configured, and their cloud token and
  onboarding steps are saved to `tokens/<gw_name>.txt` for manual onboarding. They are not part of
  the SIC wait and policy installation, and are not reported as failures. `--delete` removes their
  token file.
- New Network Requirements section: all connections are outbound, and no public IP address is
  needed.

### November 2026: Documented Spark API, Infinity Portal registration removed

Verified again end to end in the lab (deploy and `--delete`).

- Spark gateways are created with one `add-simple-gateway` call, using the parameters from the
  Smart-1 Cloud Administration Guide (`hardware`, `hardware-subtype`, `version`,
  `trust-method: cloud_token`, `auto-generate-ip`). The undocumented `set-generic-object`
  conversion, the explicit topology setting and the SIC name built by the deployer are no longer
  needed.
- `hardware`, `net_type` and `version` are checked against `show-gateway-capabilities` before any
  object is created.
- The management server address for `fetch certificate` is read from the `Management_Service`
  object instead of using a fixed `100.64.0.52`.
- `--delete` uses `set maas mode disable`, the command documented to stop Smart-1 Cloud management.
- Gateways are registered only through the Management API. The Infinity Portal API registration and
  its `client_id`, `access_key` and `portal_url` keys were removed, together with
  `utils/smart1_cloud_api.py`. The deployer now requires Smart-1 Cloud R82.20.

### November 2026: Spark topology fix and `--delete`

Verified with repeated deploy and delete cycles against the lab.

- Spark gateway objects get `interfaces-topology-settings: global and automatic`. Before, they kept
  `per interface` topology with no interfaces. Policy installation then warned about missing
  topology, and the appliance dropped local WebUI and SSH access ("access attempt from unallowed
  source") after every policy installation.
- New `--delete` mode: returns each appliance to local management and deletes its gateway object.
- New optional `application_control` and `url_filtering` settings for each gateway, for groups
  such as `Playblocks_Gateways` whose rules need those blades.

### November 2026: Lab-verified, registration without Infinity Portal keys

Verified end to end against Smart-1 Cloud (Management API 2.1) and a Quantum Spark R81.10.17
appliance.

- Gateways can be registered with only a Management API key (`add-simple-gateway` with
  `auto-generate-ip`, then `set-trust` with `cloud_token`). The Infinity Portal API credentials are
  now optional.
- SIC is confirmed with `test-sic-status`. The `sic-state` field of the gateway object stays
  `waiting_for_first_connection` after the appliance pulls its certificate, so it cannot be used.
- `connect security-management ... use-one-time-password true` was removed from appliance
  configuration. After `fetch certificate` it always fails with "You must reinitialize trusted
  communications", and the MaaS connection and certificate pull already complete the setup.
- Clish output is checked for errors, so a rejected appliance command is reported as a failure.

### November 2026: Deployment order and security

- Policy is now installed last. The appliance is configured first, then the deployer waits for
  each gateway to establish SIC (`sic_timeout`) and installs policy only on those gateways.
  Previously, policy installation ran before the appliance was connected and stopped the run
  when it failed.
- A failure no longer stops the run. Each gateway is reported in a summary, and the deployer exits
  with a non-zero code if any gateway was not deployed.
- The `fw fetch` command was removed from appliance configuration, because policy is installed
  from the management server.
- MaaS tokens, SIC one-time passwords and appliance passwords are masked in the console and the
  log file.
- All HTTP requests have a timeout, and publish and policy installation tasks have a time limit.
- The configuration files are no longer tracked. The repository now contains `.example.json`
  templates. See the upgrade note in [Configuration](#configuration).

### November 2026: Smart-1 Cloud R82.20 support

- SIC is configured after the gateway object is converted to a Spark gateway. On R82.20
  (Management API 2.1), the deployer also sets `trust-settings.initiation-phase` to
  `when_gateway_connects`, so the appliance pulls its certificate.
- Policy installation opens its own Management API session, and the logout request is sent
  correctly.
- The deployer waits for Smart-1 Cloud to create the gateway object instead of relying only on a
  fixed delay.
- The management SIC name is parsed regardless of field order or case.
- Policy installation is skipped when no gateway was configured.
- A task that partially succeeds is reported as a failure.
- Fixed `delete_gateway()` in `utils/smart1_cloud_api.py`.
- Console and log messages no longer contain emojis.
