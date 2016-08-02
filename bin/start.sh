#!/bin/bash

# Detect unset environment variables.
eval $(kube.py)

OPENVPN=/etc/openvpn
OPENVPN_CFG="$OPENVPN/openvpn.conf"

# Generate OpenVPN config
ovpn_genconfig -u tcp://$OVPN_HOST

# Add additional configuration if variables are set
if [ -n "$KUBE_SVC_NET" -a -n "$KUBE_SVC_MASK" ]; then
    printf "push \"route $KUBE_SVC_NET $KUBE_SVC_MASK\"\n" >> $OPENVPN_CFG
fi

if [ -n "$KUBE_DNS_SEARCH" ]; then
    printf "push \"dhcp-option SEARCH $KUBE_DNS_SEARCH\"\n" >> $OPENVPN_CFG
fi

if [ -n "$KUBE_DNS" ]; then
    printf "push \"dhcp-option DNS $KUBE_DNS\"\n" >> $OPENVPN_CFG
fi

# Setup CA and other PKI components
EASYRSA_BATCH=1 ovpn_initpki nopass

# Start VPN
ovpn_run
