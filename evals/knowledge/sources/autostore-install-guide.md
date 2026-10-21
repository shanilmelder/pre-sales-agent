# AutoStore integration: installation guide

## Prerequisites

## Network

The port controller talks to the warehouse management system over TCP. Open port 4711 on the
site firewall for the controller's static address, and allow outbound HTTPS to the vendor's
update service.

The controller needs a fixed IPv4 address; DHCP reservations are not supported.

## Power

Each grid segment needs a dedicated 400 V three-phase supply with its own residual current
device. Charging stations draw up to 3 kW each during the night cycle.

## Licences

The licence server runs on the controller. Licences are bound to the controller's MAC address,
so replacing the controller hardware requires a licence transfer request to vendor support.
