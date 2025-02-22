import io
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from spark_client.utils import WithLogging, union


class PropertyFile(WithLogging):
    """Class for providing basic functionalities for IO properties files."""

    def __init__(self, props: Dict[str, Any]):
        """Initialize a PropertyFile class with data provided by a dictionary.

        Args:
            props: input dictionary
        """
        self.props = props

    def __len__(self):
        """Return the size of the property dictionary, i.e. the number of configuration parameters."""
        return len(self.props)

    @classmethod
    def _is_property_with_options(cls, key: str) -> bool:
        """Check if a given property is known to be options-like requiring special parsing.

        Args:
            key: Property for which special options-like parsing decision has to be taken
        """
        return key in ["spark.driver.extraJavaOptions"]

    @classmethod
    def _read_property_file_unsafe(cls, name: str) -> Dict:
        """Read properties in given file into a dictionary.

        Args:
            name: file name to be read
        """
        defaults = dict()
        with open(name) as f:
            for line in f:
                prop_assignment = list(filter(None, re.split("=| ", line.strip())))
                prop_key = prop_assignment[0].strip()
                if cls._is_property_with_options(prop_key):
                    option_assignment = line.split("=", 1)
                    value = option_assignment[1].strip()
                else:
                    value = prop_assignment[1].strip()
                defaults[prop_key] = os.path.expandvars(value)
        return defaults

    @classmethod
    def read(cls, filename: str) -> "PropertyFile":
        """Read properties file and return a PropertyFile object.

        Args:
            filename: input filename
        """
        try:
            return PropertyFile(cls._read_property_file_unsafe(filename))
        except FileNotFoundError as e:
            raise e

    def write(self, fp: io.TextIOWrapper) -> "PropertyFile":
        """Write out a property file to disk.

        Args:
            fp: file pointer to write to
        """
        for k, v in self.props.items():
            line = f"{k}={v.strip()}"
            fp.write(line + "\n")
        return self

    def log(self, log_func: Optional[Callable[[str], None]] = None) -> "PropertyFile":
        """Print a given dictionary to screen.

        Args:
            log_func: callable to specify another custom printer function. Default uses the class logger with an
                      INFO level.
        """

        printer = (lambda msg: self.logger.info(msg)) if log_func is None else log_func

        for k, v in self.props.items():
            printer(f"{k}={v}")
        return self

    @classmethod
    def _parse_options(cls, options_string: Optional[str]) -> Dict:
        options: Dict[str, str] = dict()

        if not options_string:
            return options

        # cleanup quotes
        line = options_string.strip().replace("'", "").replace('"', "")
        for arg in line.split("-D")[1:]:
            kv = arg.split("=")
            options[kv[0].strip()] = kv[1].strip()

        return options

    @property
    def options(self) -> Dict[str, Dict]:
        """Extract properties which are known to be options-like requiring special parsing."""
        return {
            k: self._parse_options(v)
            for k, v in self.props.items()
            if self._is_property_with_options(k)
        }

    @staticmethod
    def _construct_options_string(options: Dict) -> str:
        result = ""
        for k in options:
            v = options[k]
            result += f" -D{k}={v}"
        return result

    @classmethod
    def empty(cls) -> "PropertyFile":
        """Return an empty property file object."""
        return PropertyFile(dict())

    def __add__(self, other: "PropertyFile"):
        return self.union([other])

    def union(self, others: List["PropertyFile"]) -> "PropertyFile":
        """Merge multiple PropertyFile objects, with right to left priority.

        Args:
            others: List of Property file to be merged.
        """
        all_together = [self] + others

        simple_properties = union(*[prop.props for prop in all_together])
        merged_options = {
            k: self._construct_options_string(v)
            for k, v in union(*[prop.options for prop in all_together]).items()
        }
        return PropertyFile(union(*[simple_properties, merged_options]))


class Defaults:
    """Class containing all relevant defaults for the application."""

    def __init__(self, environ: Dict = dict(os.environ)):
        """Initialize a Defaults class using the value contained in a dictionary

        Args:
            environ: dictionary representing the environment. Default uses the os.environ key-value pairs.
        """

        self.environ = environ if environ is not None else {}

    @property
    def snap_folder(self) -> str:
        """Return the SNAP folder"""
        return self.environ["SNAP"]

    @property
    def static_conf_file(self) -> str:
        """Return static config properties file packaged with the client snap."""
        return f"{self.environ.get('SNAP')}/conf/spark-defaults.conf"

    @property
    def dynamic_conf_file(self) -> str:
        """Return dynamic config properties file generated during client setup."""
        return f"{self.environ.get('SNAP_USER_DATA')}/spark-defaults.conf"

    @property
    def env_conf_file(self) -> Optional[str]:
        """Return env var provided by user to point to the config properties file with conf overrides."""
        return self.environ.get("SNAP_SPARK_ENV_CONF")

    @property
    def snap_temp_folder(self) -> str:
        """Return /tmp directory as seen by the snap, for user's reference."""
        return "/tmp/snap.spark-client"

    @property
    def service_account(self):
        return "spark"

    @property
    def namespace(self):
        return "defaults"

    @property
    def home_folder(self):
        return self.environ.get("SNAP_REAL_HOME", self.environ["HOME"])

    @property
    def kube_config(self) -> str:
        """Return default kubeconfig to use if not explicitly provided."""
        return self.environ.get("KUBECONFIG", f"{self.home_folder}/.kube/config")

    @property
    def kubectl_cmd(self) -> str:
        """Return default kubectl command."""
        return (
            f"{self.environ['SNAP']}/kubectl" if "SNAP" in self.environ else "kubectl"
        )

    @property
    def scala_history_file(self):
        return f"{self.environ['SNAP_USER_DATA']}/.scala_history"

    @property
    def spark_submit(self) -> str:
        return f"{self.environ['SNAP']}/bin/spark-submit"

    @property
    def spark_shell(self) -> str:
        return f"{self.environ['SNAP']}/bin/spark-shell"

    @property
    def pyspark(self) -> str:
        return f"{self.environ['SNAP']}/bin/pyspark"


@dataclass
class ServiceAccount:
    """Class representing the spark ServiceAccount domain object."""

    name: str
    namespace: str
    api_server: str
    primary: bool = False
    extra_confs: PropertyFile = PropertyFile.empty()

    @property
    def id(self):
        """Return the service account id, as a concatenation of namespace and username."""
        return f"{self.namespace}:{self.name}"

    @property
    def _k8s_configurations(self):
        return PropertyFile(
            {
                "spark.kubernetes.authenticate.driver.serviceAccountName": self.name,
                "spark.kubernetes.namespace": self.namespace,
            }
        )

    @property
    def configurations(self) -> PropertyFile:
        """Return the service account configuration, associated to a given spark service account."""
        return self.extra_confs + self._k8s_configurations
