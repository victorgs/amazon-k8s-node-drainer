import logging
import time

from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def cordon_node(api, node_name):
    """Marks the specified node as unschedulable, which means that no new pods can be launched on the
    node by the Kubernetes scheduler.
    """
    patch_body = {
        'apiVersion': 'v1',
        'kind': 'Node',
        'metadata': {
            'name': node_name
        },
        'spec': {
            'unschedulable': True
        }
    }

    api.patch_node(node_name, patch_body)


def remove_all_pods(api, node_name, poll=5):
    """Removes all Kubernetes pods from the specified node."""
    pods = get_pods_on_node(api, node_name)

    logger.debug('Number of pods to delete: ' + str(len(pods.items)))

    evict_until_completed(api, pods, poll)
    wait_until_empty(api, node_name, poll)


def get_pods_on_node(api, node_name):
    field_selector = 'spec.nodeName=' + node_name
    return api.list_pod_for_all_namespaces(watch=False, field_selector=field_selector, include_uninitialized=True)


def evict_until_completed(api, pods, poll):
    pending = pods.items
    while True:
        pending = evict_pods(api, pending)
        if (len(pending)) <= 0:
            return
        time.sleep(poll)


def evict_pods(api, pods):
    remaining = []
    for pod in pods:
        logger.info('Evicting pod {} in namespace {}'.format(pod.metadata.name, pod.metadata.namespace))
        body = {
            'apiVersion': 'policy/v1beta1',
            'kind': 'Eviction',
            'deleteOptions': {},
            'metadata': {
                'name': pod.metadata.name,
                'namespace': pod.metadata.namespace
            }
        }
        try:
            api.create_namespaced_pod_eviction(pod.metadata.name + '-eviction', pod.metadata.namespace, body)
        except ApiException as err:
            if err.status == 429:
                remaining.append(pod)
                logger.warning("Pod %s in namespace %s could not be evicted due to disruption budget. Will retry.", pod.metadata.name, pod.metadata.namespace)
            else:
                logger.exception("Unexpected error adding eviction for pod %s in namespace %s", pod.metadata.name, pod.metadata.namespace)
        except:
            logger.exception("Unexpected error adding eviction for pod %s in namespace %s", pod.metadata.name, pod.metadata.namespace)
    return remaining


def wait_until_empty(api, node_name, poll):
    logger.info("Waiting for evictions to complete")
    while True:
        pods = get_pods_on_node(api, node_name)
        if len(pods.items) <= 0:
            logger.info("All pods evicted successfully")
            return
        logger.debug("Still waiting for deletion of the following pods: %s", ", ".join(map(lambda pod: pod.metadata.namespace + "/" + pod.metadata.name, pods.items)))
        time.sleep(poll)


def node_exists(api, node_name):
    """Determines whether the specified node is still part of the cluster."""
    nodes = api.list_node(include_uninitialized=True, pretty=True).items
    node = next((n for n in nodes if n.metadata.name == node_name), None)
    return False if not node else True


def abandon_lifecycle_action(asg_client, auto_scaling_group_name, lifecycle_hook_name, instance_id):
    """Completes the lifecycle action with the ABANDON result, which stops any remaining actions,
    such as other lifecycle hooks.
    """
    asg_client.complete_lifecycle_action(LifecycleHookName=lifecycle_hook_name,
                                         AutoScalingGroupName=auto_scaling_group_name,
                                         LifecycleActionResult='ABANDON',
                                         InstanceId=instance_id)
