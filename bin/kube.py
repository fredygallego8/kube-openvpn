#!/usr/bin/env python3
"""Utilities to determine network information about Kubernetes Services"""

import os
import socket
from netaddr import IPNetwork, IPAddress
import pykube

ALLOCATED_ERR = "provided IP is already allocated"

def base_obj(kind, namespace, name, api_version="v1"):
    """
    Creates an object that can be used in Pykube requests
    :param kind: Kubernetes kind to be created
    :param namespace: Namespace where object lives
    :param name: Name of object
    :param api_version: Kube API version
    :return: dict of Kube object
    """
    return {
        "kind": kind,
        "apiVersion": api_version,
        "metadata": {
            "name": name,
            "namespace": namespace
        }
    }


def min_service(spec=False, cluster_ip="", name="openvpntest-ok-to-delete", port=19555):
    """
    Creates a minimal service for usage with Pykube.
    :param spec: If True, a ServiceSpec is included
    :param cluster_ip: IP to be requested for the service
    :param name: Name of the service
    :param port: Port to use with the service
    :return: Service object dict
    """
    svc = base_obj("Service", "default", name)
    if spec:
        svc["spec"] = {
            "ports": [
                {
                    "protocol": "UDP",
                    "port": port
                }
            ],
            "type": "ClusterIP",
            "clusterIP": cluster_ip
        }
    return svc


def test_service(kube_api, target_ip="", ignore_allocated=False):
    """
    Checks that a service can be created with the given IP.
    In order to check this it will create a service, check for success, get its IP, and delete it.
    :param kube_api: Pykube API Object
    :param target_ip: IP to attempt to create the service with
    :param ignore_allocated: If true, don't ignore errors about an IP already being allocated
    :return: IPAddress that was successfully used. If error, returns False
    """
    try:
        svc_id = pykube.Service(kube_api, min_service())
        if svc_id.exists():
            svc_id.delete()

        svc = pykube.Service(kube_api, min_service(True, str(target_ip)))
        svc.create()
        svc_ip = IPAddress(svc.obj["spec"]["clusterIP"])
        svc_id.delete()
        return svc_ip
    except pykube.exceptions.HTTPError as err:
        err_str = str(err)
        if err_str.endswith(ALLOCATED_ERR) and ignore_allocated:
            return IPAddress(target_ip)
        print("Error with %s: %s" % (str(target_ip), err_str))
        return False


def get_pod(kube_api, namespace, name):
    """
    Retrieve Pod from cluster
    :param kube_api: Pykube API Object
    :param namespace: Namespace of pod
    :param name: Name of pod
    :return: Pykube Pod object from cluster
    """
    pod = pykube.Pod(kube_api, base_obj("Pod", namespace, name))
    pod.reload()
    return pod


def get_node(kube_api, name):
    """
    Retrieve Node from cluster
    :param kube_api: Pykube API Object
    :param name: Name of Node
    :return: Pykube Node object from cluster
    """
    node = pykube.Node(kube_api, base_obj("Node", "", name))
    node.reload()
    return node


def pod_namespace(svcact_path="/var/run/secrets/kubernetes.io/serviceaccount"):
    """
    Uses the service account to determine the namespace of the current pod
    :param svcact_path: Override the default service account location
    :return: Name of namespace
    """
    with open(os.path.join(svcact_path, "namespace")) as ns_file:
        return ns_file.read()


def detect_cloud_provider(kube_api):
    """
    Attempts to detect cloud provider by checking the Node the Pod is running on
    :param kube_api: Pykube API Object
    :return: cloud provider prefix from ".spec.providerID"
    """
    host = socket.gethostname()
    namespace = pod_namespace()
    node_name = get_pod(kube_api, namespace, host).obj["spec"]["nodeName"]
    provider_id = str(get_node(kube_api, node_name).obj["spec"]["providerID"])
    return provider_id.split("://", 1)[0]


def check_service_iprange(kube_api, cidr):
    """
    Verify that provided CIDR is same as what Kubernetes uses for services.
    Returns true if can confirm (a, b), where a is the lowest IP in the CIDR and b is the highest
    :param kube_api: Pykube API Object
    :param cidr: CIDR block to be checked
    :return: True, if cluster uses CIDR for services
    """
    net = IPNetwork(cidr)
    first, last = IPAddress(net.first), IPAddress(net.last)
    if test_service(kube_api, first - 1, True):
        return False
    # ranges seem to be not inclusive so check lowest + 1
    if not test_service(kube_api, first + 1, True):
        return False

    # same as above but highest - 1
    if not test_service(kube_api, last - 1, True):
        return False

    if test_service(kube_api, last + 1, True):
        return False
    return net


def find_services_cidr(kube_api):
    """
    Uses cloud provider specific heuristic to determine IP address
    :param kube_api: Pykube API Object
    :return: IPNetwork if can be determined. Otherwise, returns False.
    """
    provider = detect_cloud_provider(kube_api)
    if provider == "gce":
        # get sample IP to determine range
        svc_ip = test_service(kube_api)
        if svc_ip:
            # GKE uses IPs that match the pattern "10.*.240.0/20"
            ip_range = "10.%d.240.0/20" % svc_ip.words[1]
            return check_service_iprange(kube_api, ip_range)
    elif provider == "aws":
        ip_range = False
        # kube-aws
        if not ip_range:
            ip_range = check_service_iprange(kube_api, "10.3.0.0/24")
        # kube-up.sh AWS
        if not ip_range:
            ip_range = check_service_iprange(kube_api, "10.0.0.0/16")
        return ip_range
    return False


def network_and_mask(cidr):
    """
    Determines network and subnet mask of the CIDR
    :param cidr: String representing CIDR
    :return: Tuple of network and subnetmask
    """
    net = IPNetwork(cidr)
    return str(net.network), str(net.netmask)

print("Connecting to KubeAPI")
KUBE = pykube.HTTPClient(pykube.KubeConfig.from_service_account())

print("Determining Service Range")
print(find_services_cidr(KUBE))
