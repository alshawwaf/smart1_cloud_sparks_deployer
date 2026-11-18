# Changelog

[Back to the README](README.MD)

## November 2026: Interfaces and topology on the gateway object

- The gateway object now gets its interfaces: the deployer reads them from the appliance and sets
  them with their topology (external or internal) and Anti-Spoofing, before the policy is
  installed. Before, the object had `global and automatic` topology and no real interfaces.
- `get-interfaces` of the Management API does not work for Spark gateways, and the first Threat
  Prevention installation empties the interface list. Both are handled, see
  [Interfaces and topology](docs/HOW_IT_WORKS.md#interfaces-and-topology). Gateways with Threat Prevention blades get
  one more Access Control installation at the end, about one minute.
- Gateways without appliance credentials keep `global and automatic` topology.
- A task status request that times out is repeated instead of failing the installation.

## November 2026: Blades, appliance failures and version line

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

## November 2026: net_type values by model

- New [net_type values by model](docs/COMPATIBILITY.md#net_type-values-by-model) table, tested against Smart-1 Cloud
  R82.20. The 2530/2550 and 2560/2570 Wi-Fi models use `WiFi-LTE`, not `Wireless`.
- A model and `net_type` combination that Smart-1 Cloud rejects is now reported by name, with a
  pointer to the table, instead of the generic API error.
- The example configuration used `Wireless` for an 1800, which Smart-1 Cloud rejects. It now uses
  `Wired`.

## November 2026: Verified on Management API 2.2

Verified again end to end after the tenant moved to Management API 2.2: automated deployment,
manual onboarding with the token file, and `--delete`.

- `--delete` logs in to the appliance again when `fw sic_reset` drops the REST API connection,
  instead of failing the reset.
- New troubleshooting entry for an appliance that kept a broken Smart-1 Cloud connection.

## November 2026: Manual onboarding

- Gateways without appliance credentials are registered and configured, and their cloud token and
  onboarding steps are saved to `tokens/<gw_name>.txt` for manual onboarding. They are not part of
  the SIC wait and policy installation, and are not reported as failures. `--delete` removes their
  token file.
- New Network Requirements section: all connections are outbound, and no public IP address is
  needed.

## November 2026: Documented Spark API, Infinity Portal registration removed

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

## November 2026: Spark topology fix and `--delete`

Verified with repeated deploy and delete cycles against the lab.

- Spark gateway objects get `interfaces-topology-settings: global and automatic`. Before, they kept
  `per interface` topology with no interfaces. Policy installation then warned about missing
  topology, and the appliance dropped local WebUI and SSH access ("access attempt from unallowed
  source") after every policy installation.
- New `--delete` mode: returns each appliance to local management and deletes its gateway object.
- New optional `application_control` and `url_filtering` settings for each gateway, for groups
  such as `Playblocks_Gateways` whose rules need those blades.

## November 2026: Lab-verified, registration without Infinity Portal keys

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

## November 2026: Deployment order and security

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
  templates. See the upgrade note in [Configuration](README.MD#configuration).

## November 2026: Smart-1 Cloud R82.20 support

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
