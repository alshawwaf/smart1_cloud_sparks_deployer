# Troubleshooting

[Back to the README](../README.MD)

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

**Cause:** Blades are enabled only when their keys are set for the gateway, with or without appliance credentials. Updating the deployer with `git pull` does not add the keys to your own `config_data.json`. The console shows `Blades: firewall` and a warning for such a gateway, and a warning for each key it does not know.

**Resolution:** Set `vpn`, `ips`, `anti_bot`, `anti_virus`, `application_control` and `url_filtering` to `true` as needed in `config_data.json`, then run `--delete` and deploy again, or enable the blades on the existing object in SmartConsole. See [Configuration](../README.MD#configconfig_datajson).

</details>

<details>
<summary>A gateway without appliance credentials still waits for SIC</summary>

**Cause:** An earlier version of the deployer is running, or another gateway in `config_data.json` still has appliance credentials

**Resolution:** Check the first console line, `Smart-1 Cloud Spark Gateway Deployer version ...`. If it is missing, the copy is older than 17 November 2026: update it with `git pull` (see the upgrade note in [Configuration](../README.MD#configuration) if `git pull` reports local changes). Then check the two lines that list the gateways with and without appliance credentials.

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

**Resolution:** Use a value from [net_type values by model](COMPATIBILITY.md#net_type-values-by-model), for example
`WiFi-LTE` for a 2560/2570 with Wi-Fi. Nothing is created in Smart-1 Cloud when this error occurs.

</details>

<details>
<summary><code>Management API ... cannot issue cloud tokens</code></summary>

**Cause:** The Smart-1 Cloud tenant is not on R82.20 (Management API 2.1)

**Resolution:** Gateway registration requires Smart-1 Cloud R82.20. See [Version Compatibility](COMPATIBILITY.md#version-compatibility).

</details>

<details>
<summary><code>Management server upgrade in progress</code> warning</summary>

**Cause:** Smart-1 Cloud is running a background upgrade

**Resolution:** Wait for the upgrade to complete, then run the deployment.

</details>

<details>
<summary>The appliance runs firmware earlier than R81.10.X, or is a Rugged 1200R appliance</summary>

**Cause:** Smart-1 Cloud R82.20 does not support these appliances

**Resolution:** See [Version Compatibility](COMPATIBILITY.md#version-compatibility).

</details>

For full details of a run, see `logs/s1c_deploy_sparks_gw.log`.
