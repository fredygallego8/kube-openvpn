#!/bin/bash

# Detect unset environment variables.
eval $(kube.py)

OPENVPN=/etc/openvpn
OPENVPN_CFG="$OPENVPN/openvpn.conf"
OPENVPN_PKI="$OPENVPN/pki"

if [ ! -e "OPENVPN_CFG" ]; then
    # Add additional configuration if variables are set
    if [ -n "$KUBE_DNS" ]; then
        DNS_ARG="-n $KUBE_DNS"
    fi

    # Generate OpenVPN config
    if [ -n "$OVPN_HOST" ]; then
        ovpn_genconfig -u tcp://$OVPN_HOST $DNS_ARG $ROUTE_ARG
    else
        printf "ERROR: The environment variable \$OVPN_HOST must be set to the hostname desired for the VPN.\n" 1>&2
        exit 1
    fi

    if [ -n "$DNS_SEARCH_ARR" ]; then
        for i in ${DNS_SEARCH_ARR[@]}; do
            printf "push \"dhcp-option DOMAIN-SEARCH $i\"\n" >> $OPENVPN_CFG
        done
    fi

    if [ -n "$KUBE_SVC_NET" -a -n "$KUBE_SVC_MASK" ]; then
        printf "push route $KUBE_SVC_NET $KUBE_SVC_MASK\n" >> $OPENVPN_CFG
    fi

    echo "OpenVPN Configuration:"
    cat $OPENVPN_CFG
fi

if [ ! -d "$OPENVPN_PKI" ]; then
    # Setup CA and other PKI components
    EASYRSA_BATCH=1 ovpn_initpki nopass
fi

# Start VPN
ovpn_run
