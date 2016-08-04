#!/usr/bin/env python3
"""Utilities to determine network information about Kubernetes Services"""

import os
import socket
from urllib.request import urlopen, Request
import yaml
from netaddr import IPNetwork, IPAddress
import pykube

ALLOCATED_ERR = "provided IP is already allocated"

VPN_HOST_ENV = "OVPN_HOST"
DNS_ENV = "KUBE_DNS"
DNS_SEARCH_ARR_ENV = "DNS_SEARCH_ARR"
DNS_SEARCH_ENV = "KUBE_DNS_SEARCH"
SVC_NETWORK_ENV = "KUBE_SVC_NET"
SVC_MASK_ENV = "KUBE_SVC_MASK"


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
    try:
        node_name = get_pod(kube_api, namespace, host).obj["spec"]["nodeName"]
        if node_name == "minikubevm":
            return "minikube"
        provider_id = str(get_node(kube_api, node_name).obj["spec"]["providerID"])
        return provider_id.split("://", 1)[0]
    except KeyError:
        return None


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
    try:
        provider = detect_cloud_provider(kube_api)
        if provider == "gce":
            # get sample IP to determine range
            svc_ip = test_service(kube_api)
            if svc_ip:
                # Use GCE metadata service to lookup service range
                ip_range = gce_kubeenv()["SERVICE_CLUSTER_IP_RANGE"]
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
        elif provider == "minikube":
            return check_service_iprange(kube_api, "10.0.0.1/24")
        print("Cloud provider '%s' is not supported" % provider)
    except pykube.exceptions.HTTPError as err:
        print("Encountered error: %s" % str(err))
    return False


def network_and_mask(cidr):
    """
    Determines network and subnet mask of the CIDR
    :param cidr: String representing CIDR
    :return: Tuple of network and subnetmask
    """
    net = IPNetwork(cidr)
    return str(net.network), str(net.netmask)


def get_resolv():
    """
    Reads '/etc/resolv.conf' and returns a dictionary with it's contents
    :return: dict with resolve.conf directive as key
    """
    contents = dict()
    try:
        with open('/etc/resolv.conf', 'r') as resolvconf:
            for line in resolvconf.readlines():
                parsed_line = line.split(maxsplit=1)
                if len(parsed_line) > 1:
                    val = parsed_line[1].rstrip("\n")
                    contents[parsed_line[0]] = val
    except IOError:
        pass
    return contents


def gce_kubeenv():
    """
    Uses the Google Compute Engine Metadata service to retrieve information about the cluster.
    :return: Dictionary of cluster specific information.
    """
    url = "http://metadata/computeMetadata/v1/instance/attributes/kube-env"
    headers = {"Metadata-Flavor": "Google"}
    request = Request(url, headers=headers)
    with urlopen(request) as stream:
        return yaml.load(stream)


def export_vars(kube_api):
    """
    String to be used with bash's eval which sets environment variables
    based on detecting details about the Pods network. The values
    of environment variables that are already set are used.
    :param kube_api: Pykube API Object
    :return: String to be eval'd by bash
    """
    resolv = get_resolv()
    out = str()
    dns = os.environ.get(DNS_ENV)
    if dns is None or len(dns) == 0:
        dns = resolv.get("nameserver")
        if dns is not None:
            out += "export %s=\"%s\"\n" % (DNS_ENV, dns)

    search_arr = os.environ.get(DNS_SEARCH_ARR_ENV)
    if search_arr is None or len(search_arr) == 0:
        search = os.environ.get(DNS_SEARCH_ENV)
        if search is None or len(search) == 0:
            search = resolv.get("search")
        out += "export %s=(\t%s\t)\n" % (DNS_SEARCH_ARR_ENV, search)

    cidr = find_services_cidr(kube_api)
    if cidr:
        net, mask = network_and_mask(cidr)
        service_net = os.environ.get(SVC_NETWORK_ENV)
        if service_net is None or len(service_net) == 0:
            out += "export %s=\"%s\"\n" % (SVC_NETWORK_ENV, net)
        service_mask = os.environ.get(SVC_MASK_ENV)
        if service_mask is None or len(service_mask) == 0:
            out += "export %s=\"%s\"\n" % (SVC_MASK_ENV, mask)
    return out


if __name__ == '__main__':
    KUBE = pykube.HTTPClient(pykube.KubeConfig.from_service_account())
    print(export_vars(KUBE))
