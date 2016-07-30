#!/usr/bin/env python3
# check if initialization needs to occur
# if has, start OpenVPN
# if not:
# - get network and subset mask for pods
# - get network and subset mask for services
# - get cluster DNS address
# - configure OpenVPN

from pprint import pprint

import operator
import pykube
from netaddr import *

SVC_NET = ""
SVC_MASK = ""
POD_NET = ""
POD_MASK = ""


def netAndMask(CIDR):
    net = IPNetwork(CIDR)
    return str(net.network), str(net.netmask)

def podNets(api):
    for node in pykube.Node.objects(api):
        cidr = node.obj["spec"]["podCIDR"]
        return netAndMask(cidr)


api = pykube.HTTPClient(pykube.KubeConfig.from_service_account())
serviceNets(api)
