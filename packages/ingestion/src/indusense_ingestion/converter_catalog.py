"""Inventaire des convertisseurs réellement enregistrés dans le moteur."""

import inspect

from .contracts import CONVERTERS, load_type_catalog


def build_converter_catalog(types_path):
    types = load_type_catalog(types_path)
    return {
        "version": 1,
        "converters": {
            name: {
                "function": f"{function.__module__}.{function.__qualname__}",
                "arguments": list(inspect.signature(function).parameters),
                "types": {
                    kind: {key: value for key, value in options.items() if key != "converter"}
                    for kind, options in types.items()
                    if options["converter"] == name
                },
            }
            for name, function in CONVERTERS.items()
        },
    }
