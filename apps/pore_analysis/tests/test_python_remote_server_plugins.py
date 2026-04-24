from types import ModuleType
from unittest import TestCase
from unittest.mock import patch

import python_remote_server as prs


class PythonRemoteServerPluginTests(TestCase):
    def setUp(self):
        self.original_handlers = dict(prs.ANALYSIS_HANDLERS)
        self.original_sources = dict(prs.HANDLER_SOURCES)

    def tearDown(self):
        prs.ANALYSIS_HANDLERS.clear()
        prs.ANALYSIS_HANDLERS.update(self.original_handlers)
        prs.HANDLER_SOURCES.clear()
        prs.HANDLER_SOURCES.update(self.original_sources)

    def test_builtin_poresize_handler_is_registered(self):
        handlers = prs.list_registered_handlers()
        names = {item["analysis_type"] for item in handlers}
        self.assertIn("poresize", names)
        self.assertIn("network_extraction", names)

    def test_register_handler_rejects_duplicates(self):
        prs.register_handler("unique-test-handler", lambda payload: payload, source="test")

        with self.assertRaises(ValueError):
            prs.register_handler("unique-test-handler", lambda payload: payload, source="test")

    def test_load_handler_modules_registers_plugin_handlers(self):
        module = ModuleType("plugin_mod")

        def get_handlers():
            return {
                "plugin-analysis": lambda payload: {"solution": payload},
            }

        module.get_handlers = get_handlers

        with patch("python_remote_server.importlib.import_module", return_value=module):
            summary = prs.load_handler_modules(module_names=["plugin_mod"], strict=True)

        self.assertEqual(summary["loaded_modules"], ["plugin_mod"])
        self.assertIn("plugin-analysis", summary["registered_analysis_types"])
        self.assertEqual(summary["errors"], [])

        handlers = prs.list_registered_handlers()
        by_name = {item["analysis_type"]: item for item in handlers}
        self.assertEqual(by_name["plugin-analysis"]["source"], "plugin:plugin_mod")

    def test_load_handler_modules_non_strict_keeps_running_on_error(self):
        with patch(
            "python_remote_server.importlib.import_module",
            side_effect=ModuleNotFoundError("missing module"),
        ):
            summary = prs.load_handler_modules(module_names=["missing.plugin"], strict=False)

        self.assertEqual(summary["loaded_modules"], [])
        self.assertEqual(summary["registered_analysis_types"], [])
        self.assertEqual(len(summary["errors"]), 1)

    def test_load_handler_modules_strict_raises_on_error(self):
        with patch(
            "python_remote_server.importlib.import_module",
            side_effect=ModuleNotFoundError("missing module"),
        ), self.assertRaises(RuntimeError):
            prs.load_handler_modules(module_names=["missing.plugin"], strict=True)
