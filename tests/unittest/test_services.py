import base64
import logging
import unittest
import uuid
from unittest.mock import patch

import yaml

from spark_client.domain import PropertyFile, ServiceAccount
from spark_client.services import (
    K8sServiceAccountRegistry,
    KubeInterface,
    parse_conf_overrides,
)
from tests import TestCase


class TestServices(TestCase):
    def test_conf_expansion_cli(self):
        home_var = "/this/is/my/home"

        parsed_property = parse_conf_overrides(
            ["my-conf=$HOME/folder", "my-other-conf=/this/does/$NOT/change"],
            environ_vars={"HOME": home_var},
        )
        self.assertEqual(parsed_property.props["my-conf"], f"{home_var}/folder")
        self.assertEqual(
            parsed_property.props["my-other-conf"], "/this/does/$NOT/change"
        )

    def test_kube_interface(self):
        # mock logic
        test_id = str(uuid.uuid4())
        username1 = str(uuid.uuid4())
        context1 = str(uuid.uuid4())
        token1 = str(uuid.uuid4())
        username2 = str(uuid.uuid4())
        context2 = str(uuid.uuid4())
        token2 = str(uuid.uuid4())
        username3 = str(uuid.uuid4())
        context3 = str(uuid.uuid4())
        token3 = str(uuid.uuid4())
        test_kubectl_cmd = str(uuid.uuid4())

        kubeconfig_yaml = {
            "apiVersion": "v1",
            "clusters": [
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}-1",
                        "server": f"https://0.0.0.0:{test_id}-1",
                    },
                    "name": f"{context1}-cluster",
                },
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}-2",
                        "server": f"https://0.0.0.0:{test_id}-2",
                    },
                    "name": f"{context2}-cluster",
                },
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}-3",
                        "server": f"https://0.0.0.0:{test_id}-3",
                    },
                    "name": f"{context3}-cluster",
                },
            ],
            "contexts": [
                {
                    "context": {
                        "cluster": f"{context1}-cluster",
                        "user": f"{username1}",
                    },
                    "name": f"{context1}",
                },
                {
                    "context": {
                        "cluster": f"{context2}-cluster",
                        "user": f"{username2}",
                    },
                    "name": f"{context2}",
                },
                {
                    "context": {
                        "cluster": f"{context3}-cluster",
                        "user": f"{username3}",
                    },
                    "name": f"{context3}",
                },
            ],
            "current-context": f"{context2}",
            "kind": "Config",
            "preferences": {},
            "users": [
                {"name": f"{username1}", "user": {"token": f"{token1}"}},
                {"name": f"{username2}", "user": {"token": f"{token2}"}},
                {"name": f"{username3}", "user": {"token": f"{token3}"}},
            ],
        }

        k = KubeInterface(kube_config_file=kubeconfig_yaml)

        self.assertEqual(k.context_name, context2)
        self.assertEqual(k.with_context(context3).context_name, context3)
        self.assertEqual(
            k.with_context(context3).context.get("cluster"), f"{context3}-cluster"
        )
        self.assertEqual(
            k.with_kubectl_cmd(test_kubectl_cmd).kubectl_cmd, test_kubectl_cmd
        )
        self.assertEqual(k.kube_config, kubeconfig_yaml)

        self.assertTrue(context1 in k.available_contexts)
        self.assertTrue(context2 in k.available_contexts)
        self.assertTrue(context3 in k.available_contexts)
        self.assertEqual(len(k.available_contexts), 3)

        current_context = k.context
        self.assertEqual(current_context.get("cluster"), f"{context2}-cluster")
        self.assertEqual(current_context.get("user"), f"{username2}")

        current_cluster = k.cluster
        self.assertEqual(
            current_cluster.get("certificate-authority-data"), f"{test_id}-2"
        )
        self.assertEqual(current_cluster.get("server"), f"https://0.0.0.0:{test_id}-2")

    @patch("helpers.utils.yaml.safe_load")
    @patch("builtins.open")
    @patch("helpers.utils.subprocess.check_output")
    def test_kube_interface_get_secret(
        self, mock_subprocess, mock_open, mock_yaml_safe_load
    ):
        # mock logic
        def side_effect(*args, **kwargs):
            return values[args[0]]

        mock_subprocess.side_effect = side_effect

        test_id = str(uuid.uuid4())
        kubeconfig = str(uuid.uuid4())
        username = str(uuid.uuid4())
        namespace = str(uuid.uuid4())
        secret_name = f"spark-client-sa-conf-{username}"
        context = str(uuid.uuid4())
        token = str(uuid.uuid4())
        conf_key = str(uuid.uuid4())
        conf_value = str(uuid.uuid4())
        conf_value_base64_encoded = base64.b64encode(conf_value.encode("utf-8"))

        kubeconfig_yaml = {
            "apiVersion": "v1",
            "clusters": [
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}",
                        "server": f"https://0.0.0.0:{test_id}",
                    },
                    "name": f"{context}-cluster",
                }
            ],
            "contexts": [
                {
                    "context": {"cluster": f"{context}-cluster", "user": f"{username}"},
                    "name": f"{context}",
                }
            ],
            "current-context": f"{context}",
            "kind": "Config",
            "preferences": {},
            "users": [{"name": f"{username}", "user": {"token": f"{token}"}}],
        }

        kubeconfig_yaml_str = yaml.dump(kubeconfig_yaml, sort_keys=False)

        cmd_get_secret = f"kubectl --kubeconfig {kubeconfig}  --namespace {namespace}  --context {context} get secret {secret_name} --ignore-not-found -o yaml "
        output_get_secret_yaml = {
            "apiVersion": "v1",
            "data": {conf_key: conf_value_base64_encoded},
            "kind": "Secret",
            "metadata": {
                "creationTimestamp": "2022-11-21T07:54:51Z",
                "name": f"spark-client-sa-conf-{username}",
                "namespace": namespace,
                "resourceVersion": "292967",
                "uid": "943b82c3-2891-4332-886c-621ef4f4633f",
            },
            "type": "Opaque",
        }
        output_get_secret = yaml.dump(output_get_secret_yaml, sort_keys=False).encode(
            "utf-8"
        )
        values = {
            cmd_get_secret: output_get_secret,
        }

        mock_yaml_safe_load.side_effect = [kubeconfig_yaml, output_get_secret_yaml]

        with patch("builtins.open", mock_open(read_data=kubeconfig_yaml_str)):
            k = KubeInterface(kube_config_file=kubeconfig)
            secret_result = k.get_secret(secret_name, namespace)
            self.assertEqual(conf_value, secret_result["data"][conf_key])

        mock_subprocess.assert_any_call(cmd_get_secret, shell=True, stderr=None)

    @patch("helpers.utils.yaml.safe_load")
    @patch("builtins.open")
    @patch("helpers.utils.subprocess.check_output")
    def test_kube_interface_set_label(
        self, mock_subprocess, mock_open, mock_yaml_safe_load
    ):
        # mock logic
        def side_effect(*args, **kwargs):
            return values[args[0]]

        mock_subprocess.side_effect = side_effect

        test_id = str(uuid.uuid4())
        kubeconfig = str(uuid.uuid4())
        username = str(uuid.uuid4())
        namespace = str(uuid.uuid4())
        context = str(uuid.uuid4())
        token = str(uuid.uuid4())
        resource_type = str(uuid.uuid4())
        resource_name = str(uuid.uuid4())
        label = str(uuid.uuid4())

        kubeconfig_yaml = {
            "apiVersion": "v1",
            "clusters": [
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}",
                        "server": f"https://0.0.0.0:{test_id}",
                    },
                    "name": f"{context}-cluster",
                }
            ],
            "contexts": [
                {
                    "context": {"cluster": f"{context}-cluster", "user": f"{username}"},
                    "name": f"{context}",
                }
            ],
            "current-context": f"{context}",
            "kind": "Config",
            "preferences": {},
            "users": [{"name": f"{username}", "user": {"token": f"{token}"}}],
        }

        kubeconfig_yaml_str = yaml.dump(kubeconfig_yaml, sort_keys=False)

        cmd_set_label = f"kubectl --kubeconfig {kubeconfig}  --namespace {namespace}  --context {context} label {resource_type} {resource_name} {label} -o yaml "
        output_set_label_yaml = {}
        output_set_label = "0".encode("utf-8")
        values = {
            cmd_set_label: output_set_label,
        }

        mock_yaml_safe_load.side_effect = [kubeconfig_yaml, output_set_label_yaml]

        with patch("builtins.open", mock_open(read_data=kubeconfig_yaml_str)):
            k = KubeInterface(kube_config_file=kubeconfig)
            k.set_label(resource_type, resource_name, label, namespace)

        mock_subprocess.assert_any_call(cmd_set_label, shell=True, stderr=None)

    @patch("helpers.utils.yaml.safe_load")
    @patch("builtins.open")
    @patch("helpers.utils.subprocess.check_output")
    def test_kube_interface_create(
        self, mock_subprocess, mock_open, mock_yaml_safe_load
    ):
        # mock logic
        def side_effect(*args, **kwargs):
            return values[args[0]]

        mock_subprocess.side_effect = side_effect

        test_id = str(uuid.uuid4())
        kubeconfig = str(uuid.uuid4())
        username = str(uuid.uuid4())
        namespace = str(uuid.uuid4())
        context = str(uuid.uuid4())
        token = str(uuid.uuid4())
        resource_type = str(uuid.uuid4())
        resource_name = str(uuid.uuid4())

        kubeconfig_yaml = {
            "apiVersion": "v1",
            "clusters": [
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}",
                        "server": f"https://0.0.0.0:{test_id}",
                    },
                    "name": f"{context}-cluster",
                }
            ],
            "contexts": [
                {
                    "context": {"cluster": f"{context}-cluster", "user": f"{username}"},
                    "name": f"{context}",
                }
            ],
            "current-context": f"{context}",
            "kind": "Config",
            "preferences": {},
            "users": [{"name": f"{username}", "user": {"token": f"{token}"}}],
        }

        kubeconfig_yaml_str = yaml.dump(kubeconfig_yaml, sort_keys=False)

        cmd_create = f"kubectl --kubeconfig {kubeconfig}  --namespace {namespace}  --context {context} create {resource_type} {resource_name} --k1=v1 --k2=v21 --k2=v22 -o name "
        output_create_yaml = {}
        output_create = "0".encode("utf-8")
        values = {
            cmd_create: output_create,
        }

        mock_yaml_safe_load.side_effect = [kubeconfig_yaml, output_create_yaml]

        with patch("builtins.open", mock_open(read_data=kubeconfig_yaml_str)):
            k = KubeInterface(kube_config_file=kubeconfig)
            k.create(
                resource_type,
                resource_name,
                namespace,
                **{"k1": "v1", "k2": ["v21", "v22"]},
            )

        mock_subprocess.assert_any_call(cmd_create, shell=True, stderr=None)

    @patch("helpers.utils.yaml.safe_load")
    @patch("builtins.open")
    @patch("helpers.utils.subprocess.check_output")
    def test_kube_interface_delete(
        self, mock_subprocess, mock_open, mock_yaml_safe_load
    ):
        # mock logic
        def side_effect(*args, **kwargs):
            return values[args[0]]

        mock_subprocess.side_effect = side_effect

        test_id = str(uuid.uuid4())
        kubeconfig = str(uuid.uuid4())
        username = str(uuid.uuid4())
        namespace = str(uuid.uuid4())
        context = str(uuid.uuid4())
        token = str(uuid.uuid4())
        resource_type = str(uuid.uuid4())
        resource_name = str(uuid.uuid4())

        kubeconfig_yaml = {
            "apiVersion": "v1",
            "clusters": [
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}",
                        "server": f"https://0.0.0.0:{test_id}",
                    },
                    "name": f"{context}-cluster",
                }
            ],
            "contexts": [
                {
                    "context": {"cluster": f"{context}-cluster", "user": f"{username}"},
                    "name": f"{context}",
                }
            ],
            "current-context": f"{context}",
            "kind": "Config",
            "preferences": {},
            "users": [{"name": f"{username}", "user": {"token": f"{token}"}}],
        }

        kubeconfig_yaml_str = yaml.dump(kubeconfig_yaml, sort_keys=False)

        cmd_delete = f"kubectl --kubeconfig {kubeconfig}  --namespace {namespace}  --context {context} delete {resource_type} {resource_name} --ignore-not-found -o name "
        output_delete_yaml = {}
        output_delete = "0".encode("utf-8")
        values = {
            cmd_delete: output_delete,
        }

        mock_yaml_safe_load.side_effect = [kubeconfig_yaml, output_delete_yaml]

        with patch("builtins.open", mock_open(read_data=kubeconfig_yaml_str)):
            k = KubeInterface(kube_config_file=kubeconfig)
            k.delete(resource_type, resource_name, namespace)

        mock_subprocess.assert_any_call(cmd_delete, shell=True, stderr=None)

    @patch("helpers.utils.yaml.safe_load")
    @patch("builtins.open")
    @patch("helpers.utils.subprocess.check_output")
    def test_kube_interface_get_service_accounts(
        self, mock_subprocess, mock_open, mock_yaml_safe_load
    ):
        # mock logic
        def side_effect(*args, **kwargs):
            return values[args[0]]

        mock_subprocess.side_effect = side_effect

        test_id = str(uuid.uuid4())
        kubeconfig = str(uuid.uuid4())
        username = str(uuid.uuid4())
        namespace = str(uuid.uuid4())
        context = str(uuid.uuid4())
        token = str(uuid.uuid4())
        label1 = str(uuid.uuid4())
        label2 = str(uuid.uuid4())
        labels = [label1, label2]

        kubeconfig_yaml = {
            "apiVersion": "v1",
            "clusters": [
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}",
                        "server": f"https://0.0.0.0:{test_id}",
                    },
                    "name": f"{context}-cluster",
                }
            ],
            "contexts": [
                {
                    "context": {"cluster": f"{context}-cluster", "user": f"{username}"},
                    "name": f"{context}",
                }
            ],
            "current-context": f"{context}",
            "kind": "Config",
            "preferences": {},
            "users": [{"name": f"{username}", "user": {"token": f"{token}"}}],
        }

        kubeconfig_yaml_str = yaml.dump(kubeconfig_yaml, sort_keys=False)

        cmd_get_sa = f"kubectl --kubeconfig {kubeconfig}  --namespace default  --context {context} get serviceaccount -l {label1}  -l {label2} -n {namespace} -o yaml "
        output_get_sa_yaml = {
            "apiVersion": "v1",
            "items": [
                {
                    "apiVersion": "v1",
                    "kind": "ServiceAccount",
                    "metadata": {
                        "creationTimestamp": "2022-11-21T14:32:06Z",
                        "labels": {
                            "app.kubernetes.io/managed-by": "spark-client",
                            "app.kubernetes.io/spark-client-primary": "1",
                        },
                        "name": f"{username}",
                        "namespace": f"{namespace}",
                        "resourceVersion": "321848",
                        "uid": "87ef7231-8106-4a36-b545-d8cf167788a6",
                    },
                }
            ],
            "kind": "List",
            "metadata": {"resourceVersion": ""},
        }
        output_get_sa = yaml.dump(output_get_sa_yaml, sort_keys=False).encode("utf-8")
        values = {
            cmd_get_sa: output_get_sa,
        }

        mock_yaml_safe_load.side_effect = [kubeconfig_yaml, output_get_sa_yaml]

        with patch("builtins.open", mock_open(read_data=kubeconfig_yaml_str)):
            k = KubeInterface(kube_config_file=kubeconfig)
            sa_list = k.get_service_accounts(namespace, labels)
            self.assertEqual(sa_list[0].get("metadata").get("name"), username)
            self.assertEqual(sa_list[0].get("metadata").get("namespace"), namespace)

        mock_subprocess.assert_any_call(cmd_get_sa, shell=True, stderr=None)

    @patch("helpers.utils.yaml.safe_load")
    @patch("builtins.open")
    @patch("helpers.utils.subprocess.check_output")
    def test_kube_interface_autodetect(
        self, mock_subprocess, mock_open, mock_yaml_safe_load
    ):
        # mock logic
        def side_effect(*args, **kwargs):
            return values[args[0]]

        mock_subprocess.side_effect = side_effect

        test_id = str(uuid.uuid4())
        kubeconfig = str(uuid.uuid4())
        username = str(uuid.uuid4())
        namespace = str(uuid.uuid4())
        context = str(uuid.uuid4())
        token = str(uuid.uuid4())
        kubectl_cmd_str = str(uuid.uuid4())

        kubeconfig_yaml = {
            "apiVersion": "v1",
            "clusters": [
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}",
                        "server": f"https://0.0.0.0:{test_id}",
                    },
                    "name": f"{context}-cluster",
                }
            ],
            "contexts": [
                {
                    "context": {"cluster": f"{context}-cluster", "user": f"{username}"},
                    "name": f"{context}",
                }
            ],
            "current-context": f"{context}",
            "kind": "Config",
            "preferences": {},
            "users": [{"name": f"{username}", "user": {"token": f"{token}"}}],
        }

        kubeconfig_yaml_str = yaml.dump(kubeconfig_yaml, sort_keys=False)

        cmd_autodetect = (
            f"{kubectl_cmd_str} --context {context} config view --minify -o yaml"
        )
        output_autodetect_yaml = {
            "apiVersion": "v1",
            "items": [
                {
                    "apiVersion": "v1",
                    "kind": "ServiceAccount",
                    "metadata": {
                        "creationTimestamp": "2022-11-21T14:32:06Z",
                        "labels": {
                            "app.kubernetes.io/managed-by": "spark-client",
                            "app.kubernetes.io/spark-client-primary": "1",
                        },
                        "name": f"{username}",
                        "namespace": f"{namespace}",
                        "resourceVersion": "321848",
                        "uid": "87ef7231-8106-4a36-b545-d8cf167788a6",
                    },
                }
            ],
            "kind": "List",
            "metadata": {"resourceVersion": ""},
        }
        output_autodetect = yaml.dump(output_autodetect_yaml, sort_keys=False).encode(
            "utf-8"
        )
        values = {
            cmd_autodetect: output_autodetect,
        }

        mock_yaml_safe_load.side_effect = [kubeconfig_yaml, output_autodetect_yaml]

        with patch("builtins.open", mock_open(read_data=kubeconfig_yaml_str)):
            k = KubeInterface(kube_config_file=kubeconfig)
            ki = k.autodetect(context, kubectl_cmd_str)
            self.assertEqual(ki.context_name, context)
            self.assertEqual(ki.kubectl_cmd, kubectl_cmd_str)

        mock_subprocess.assert_any_call(cmd_autodetect, shell=True, stderr=None)

    @patch("helpers.utils.yaml.safe_load")
    @patch("builtins.open")
    @patch("helpers.utils.subprocess.check_output")
    def test_kube_interface_select_by_master(
        self, mock_subprocess, mock_open, mock_yaml_safe_load
    ):
        test_id = str(uuid.uuid4())
        kubeconfig = str(uuid.uuid4())
        username = str(uuid.uuid4())
        namespace = str(uuid.uuid4())
        context = str(uuid.uuid4())
        token = str(uuid.uuid4())

        kubeconfig_yaml = {
            "apiVersion": "v1",
            "clusters": [
                {
                    "cluster": {
                        "certificate-authority-data": f"{test_id}",
                        "server": f"https://0.0.0.0:{test_id}",
                    },
                    "name": f"{context}-cluster",
                }
            ],
            "contexts": [
                {
                    "context": {"cluster": f"{context}-cluster", "user": f"{username}"},
                    "name": f"{context}",
                }
            ],
            "current-context": f"{context}",
            "kind": "Config",
            "preferences": {},
            "users": [{"name": f"{username}", "user": {"token": f"{token}"}}],
        }

        kubeconfig_yaml_str = yaml.dump(kubeconfig_yaml, sort_keys=False)

        output_select_by_master_yaml = {
            "apiVersion": "v1",
            "items": [
                {
                    "apiVersion": "v1",
                    "kind": "ServiceAccount",
                    "metadata": {
                        "creationTimestamp": "2022-11-21T14:32:06Z",
                        "labels": {
                            "app.kubernetes.io/managed-by": "spark-client",
                            "app.kubernetes.io/spark-client-primary": "1",
                        },
                        "name": f"{username}",
                        "namespace": f"{namespace}",
                        "resourceVersion": "321848",
                        "uid": "87ef7231-8106-4a36-b545-d8cf167788a6",
                    },
                }
            ],
            "kind": "List",
            "metadata": {"resourceVersion": ""},
        }

        mock_yaml_safe_load.side_effect = [
            kubeconfig_yaml,
            output_select_by_master_yaml,
        ]

        with patch("builtins.open", mock_open(read_data=kubeconfig_yaml_str)):
            k = KubeInterface(kube_config_file=kubeconfig)
            self.assertEqual(k, k.select_by_master(f"https://0.0.0.0:{test_id}"))

    @patch("spark_client.services.KubeInterface")
    def test_k8s_registry_retrieve_account_configurations(self, mock_kube_interface):
        data = {"k": "v"}
        mock_kube_interface.get_secret.return_value = {"data": data}
        registry = K8sServiceAccountRegistry(mock_kube_interface)
        self.assertEqual(
            registry._retrieve_account_configurations(
                str(uuid.uuid4()), str(uuid.uuid4())
            ).props,
            data,
        )

    @patch("spark_client.services.KubeInterface")
    def test_k8s_registry_all(self, mock_kube_interface):
        data = {"k": "v"}
        mock_kube_interface.get_secret.return_value = {"data": data}

        name1 = str(uuid.uuid4())
        namespace1 = str(uuid.uuid4())
        labels11 = K8sServiceAccountRegistry.PRIMARY_LABEL
        labels12 = str(uuid.uuid4())
        name2 = str(uuid.uuid4())
        namespace2 = str(uuid.uuid4())
        labels21 = str(uuid.uuid4())
        labels22 = str(uuid.uuid4())

        sa1 = {
            "metadata": {
                "name": name1,
                "namespace": namespace1,
                "labels": [labels11, labels12],
            }
        }
        sa2 = {
            "metadata": {
                "name": name2,
                "namespace": namespace2,
                "labels": [labels21, labels22],
            }
        }

        mock_kube_interface.get_service_accounts.return_value = [sa1, sa2]
        registry = K8sServiceAccountRegistry(mock_kube_interface)
        output = registry.all()
        self.assertEqual(output[0].name, name1)
        self.assertEqual(output[0].namespace, namespace1)
        self.assertEqual(output[0].primary, True)
        self.assertEqual(output[1].name, name2)
        self.assertEqual(output[1].namespace, namespace2)
        self.assertEqual(output[1].primary, False)

    @patch("spark_client.services.KubeInterface")
    def test_k8s_registry_set_primary(self, mock_kube_interface):
        data = {"k": "v"}
        mock_kube_interface.get_secret.return_value = {"data": data}

        name1 = str(uuid.uuid4())
        namespace1 = str(uuid.uuid4())
        labels11 = K8sServiceAccountRegistry.PRIMARY_LABEL
        labels12 = str(uuid.uuid4())
        name2 = str(uuid.uuid4())
        namespace2 = str(uuid.uuid4())
        labels21 = str(uuid.uuid4())
        labels22 = str(uuid.uuid4())

        sa1 = {
            "metadata": {
                "name": name1,
                "namespace": namespace1,
                "labels": [labels11, labels12],
            }
        }
        sa2 = {
            "metadata": {
                "name": name2,
                "namespace": namespace2,
                "labels": [labels21, labels22],
            }
        }

        mock_kube_interface.get_service_accounts.return_value = [sa1, sa2]
        mock_kube_interface.set_label.return_value = 0
        registry = K8sServiceAccountRegistry(mock_kube_interface)
        self.assertEqual(
            registry.set_primary(f"{namespace2}:{name2}"), f"{namespace2}:{name2}"
        )

        mock_kube_interface.set_label.assert_any_call(
            "serviceaccount",
            name1,
            f"{K8sServiceAccountRegistry.PRIMARY_LABEL}-",
            namespace1,
        )

        mock_kube_interface.set_label.assert_any_call(
            "rolebinding",
            f"{name1}-role-binding",
            f"{K8sServiceAccountRegistry.PRIMARY_LABEL}-",
            namespace1,
        )

        mock_kube_interface.set_label.assert_any_call(
            "serviceaccount",
            name2,
            f"{K8sServiceAccountRegistry.PRIMARY_LABEL}=True",
            namespace2,
        )

        mock_kube_interface.set_label.assert_any_call(
            "rolebinding",
            f"{name2}-role-binding",
            f"{K8sServiceAccountRegistry.PRIMARY_LABEL}=True",
            namespace2,
        )

    @patch("spark_client.services.KubeInterface")
    def test_k8s_registry_create(self, mock_kube_interface):
        data = {"k": "v"}
        mock_kube_interface.get_secret.return_value = {"data": data}

        name1 = str(uuid.uuid4())
        namespace1 = str(uuid.uuid4())
        labels11 = K8sServiceAccountRegistry.PRIMARY_LABEL
        labels12 = str(uuid.uuid4())
        name2 = str(uuid.uuid4())
        namespace2 = str(uuid.uuid4())
        labels21 = str(uuid.uuid4())
        labels22 = str(uuid.uuid4())
        name3 = str(uuid.uuid4())
        namespace3 = str(uuid.uuid4())
        labels31 = K8sServiceAccountRegistry.PRIMARY_LABEL
        labels32 = str(uuid.uuid4())
        api_server = str(uuid.uuid4())

        sa1 = {
            "metadata": {
                "name": name1,
                "namespace": namespace1,
                "labels": [labels11, labels12],
            }
        }
        sa2 = {
            "metadata": {
                "name": name2,
                "namespace": namespace2,
                "labels": [labels21, labels22],
            }
        }
        sa3 = {
            "metadata": {
                "name": name3,
                "namespace": namespace3,
                "labels": [labels31, labels32],
            }
        }
        sa3_obj = ServiceAccount(
            name=name3,
            namespace=namespace3,
            api_server=api_server,
            primary=True,
            extra_confs=PropertyFile(data),
        )

        mock_kube_interface.get_service_accounts.return_value = [sa1, sa2, sa3]
        mock_kube_interface.set_label.return_value = 0
        mock_kube_interface.create.return_value = 0

        registry = K8sServiceAccountRegistry(mock_kube_interface)
        self.assertEqual(registry.create(sa3_obj), sa3_obj.id)

        for call in mock_kube_interface.create.call_args_list:
            print(call)

        mock_kube_interface.create.assert_any_call(
            "serviceaccount", name3, namespace=namespace3
        )

        mock_kube_interface.create.assert_any_call(
            "role",
            f"{name3}-role",
            namespace=namespace3,
            **{
                "resource": ["pods", "configmaps", "services"],
                "verb": ["create", "get", "list", "watch", "delete"],
            },
        )

        mock_kube_interface.create.assert_any_call(
            "rolebinding",
            f"{name3}-role-binding",
            namespace=namespace3,
            **{"role": f"{name3}-role", "serviceaccount": sa3_obj.id},
        )

        mock_kube_interface.set_label.assert_any_call(
            "serviceaccount",
            name3,
            f"{K8sServiceAccountRegistry.SPARK_MANAGER_LABEL}=spark-client",
            namespace=namespace3,
        )

        mock_kube_interface.set_label.assert_any_call(
            "rolebinding",
            f"{name3}-role-binding",
            f"{K8sServiceAccountRegistry.SPARK_MANAGER_LABEL}=spark-client",
            namespace=namespace3,
        )

        mock_kube_interface.set_label.assert_any_call(
            "serviceaccount",
            name1,
            f"{K8sServiceAccountRegistry.PRIMARY_LABEL}-",
            namespace1,
        )

        mock_kube_interface.set_label.assert_any_call(
            "rolebinding",
            f"{name1}-role-binding",
            f"{K8sServiceAccountRegistry.PRIMARY_LABEL}-",
            namespace1,
        )

        mock_kube_interface.set_label.assert_any_call(
            "serviceaccount",
            name3,
            f"{K8sServiceAccountRegistry.PRIMARY_LABEL}=True",
            namespace3,
        )

        mock_kube_interface.set_label.assert_any_call(
            "rolebinding",
            f"{name3}-role-binding",
            f"{K8sServiceAccountRegistry.PRIMARY_LABEL}=True",
            namespace3,
        )

    @patch("spark_client.services.KubeInterface")
    def test_k8s_registry_delete(self, mock_kube_interface):
        data = {"k": "v"}
        mock_kube_interface.get_secret.return_value = {"data": data}

        name2 = str(uuid.uuid4())
        namespace2 = str(uuid.uuid4())

        mock_kube_interface.delete.return_value = 0

        registry = K8sServiceAccountRegistry(mock_kube_interface)

        self.assertEqual(
            registry.delete(f"{namespace2}:{name2}"), f"{namespace2}:{name2}"
        )
        mock_kube_interface.delete.assert_any_call(
            "serviceaccount", name2, namespace=namespace2
        )
        mock_kube_interface.delete.assert_any_call(
            "role", f"{name2}-role", namespace=namespace2
        )
        mock_kube_interface.delete.assert_any_call(
            "rolebinding", f"{name2}-role-binding", namespace=namespace2
        )

        mock_kube_interface.delete.assert_any_call(
            "secret", f"spark-client-sa-conf-{name2}", namespace=namespace2
        )


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level="DEBUG")
    unittest.main()
