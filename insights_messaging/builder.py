import yaml

from insights import dr, apply_default_enabled, apply_configs
from insights.formats.text import HumanReadableFormat
from .downloaders.localfs import LocalFS
from .engine import Engine
from .consumers.cli import Interactive
from .publishers.cli import StdOut
from .watcher import EngineWatcher, ConsumerWatcher


class AppBuilder(object):
    default_manifest = """
    plugins:
        default_component_enabled: true
        packages:
            - insights.specs.default
            - insights.specs.insights_archive
            - examples.rules.bash_version
    configs:
        - name: examples.rules.bash_version.report
          enabled: true
    service:
        consumer:
            name: insights_messaging.consumers.cli.Interactive
        publisher:
            name: insights_messaging.publishers.cli.StdOut
        downloader:
            name: insights_messaging.downloaders.localfs.LocalFS
        format: insights_messaging.formats.rhel_stats.Stats
        target_components:
            - examples.rules.bash_version.report
        watchers:
            - name: insights_messaging.watchers.stats.LocalStatWatcher
    """

    def __init__(self, manifest=None):
        if manifest is None:
            manifest = self.default_manifest
        if not isinstance(manifest, dict):
            manifest = yaml.load(manifest, Loader=yaml.CSafeLoader)

        self.manifest = manifest
        self.plugins = manifest.get("plugins", {})
        self.service = manifest.get("service", {})
        self.configs = manifest.get("configs", {})

    def _load_packages(self, pkgs):
        for p in pkgs:
            dr.load_components(p, continue_on_error=False)

    def _load_plugins(self):
        self._load_packages(self.plugins.get("packages", []))

    def _get_format(self):
        if "format" not in self.service:
            return HumanReadableFormat
        name = self.service["format"]
        fmt = dr.get_component(name)
        if fmt is None:
            raise Exception(f"Couldn't find {name}.")
        return fmt

    def _get_consumer(self, publisher, downloader, engine):
        if "consumer" not in self.service:
            return Interactive(publisher, downloader, engine)
        spec = self.service["consumer"]
        Consumer = dr.get_component(spec["name"])
        if Consumer is None:
            raise Exception(f"Couldn't find {spec['name']}.")
        args = spec.get("args", [])
        kwargs = spec.get("kwargs", {})
        return Consumer(publisher, downloader, engine, *args, **kwargs)

    def _get_publisher(self):
        if "publisher" not in self.service:
            return StdOut()
        spec = self.service["publisher"]
        Publisher = dr.get_component(spec["name"])
        if Publisher is None:
            raise Exception(f"Couldn't find {spec['name']}.")
        args = spec.get("args", [])
        kwargs = spec.get("kwargs", {})
        return Publisher(*args, **kwargs)

    def _load(self, spec):
        comp = dr.get_component(spec["name"])
        if comp is None:
            raise Exception(f"Couldn't find {spec['name']}.")
        args = spec.get("args", [])
        kwargs = spec.get("kwargs", {})
        return comp(*args, **kwargs)

    def _get_downloader(self):
        if "downloader" not in self.service:
            return LocalFS
        return self._load(self.service["downloader"])

    def _get_watchers(self):
        if "watchers" not in self.service:
            return []
        return [self._load(w) for w in self.service["watchers"]]

    def _get_target_components(self):
        tc = tuple(self.service.get("target_components", []))
        if not tc:
            return
        graph = {}
        for c in dr.DELEGATES:
            if dr.get_name(c).startswith(tc):
                graph.update(dr.get_dependency_graph(c))
        return graph or None

    def build_app(self):
        self._load_plugins()
        apply_default_enabled(self.plugins)
        apply_configs(self.plugins)

        target_components = self._get_target_components()
        publisher = self._get_publisher()
        downloader = self._get_downloader()
        engine = Engine(target_components, self._get_format())
        consumer = self._get_consumer(publisher, downloader, engine)

        for w in self._get_watchers():
            if isinstance(w, EngineWatcher):
                w.watch(engine)
            if isinstance(w, ConsumerWatcher):
                w.watch(consumer)

        return consumer