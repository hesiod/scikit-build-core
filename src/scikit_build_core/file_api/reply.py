import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Type, TypeVar, Union

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

from .model.cache import Cache
from .model.cmakefiles import CMakeFiles
from .model.codemodel import CodeModel, Target
from .model.directory import Directory
from .model.index import Index

__all__ = ["load_reply_dir"]

T = TypeVar("T")

InputDict = Dict[str, Any]


class Converter:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def load(self) -> Index:
        """
        Load the newest index.json file and return the Index object.
        """
        index_file = sorted(self.base_dir.glob("index-*"))[-1]
        with open(index_file, encoding="utf-8") as f:
            data = json.load(f)

        return self.make_class(data, Index)

    def _load_from_json(self, name: Path, target: Type[T]) -> T:
        with open(self.base_dir / name, encoding="utf-8") as f:
            data = json.load(f)

        return self.make_class(data, target)

    def make_class(self, data: InputDict, target: Type[T]) -> T:
        """
        Convert a dict to a dataclass. Automatically load a few nested jsonFile classes.
        """
        if (
            target in (CodeModel, Target, Cache, CMakeFiles, Directory)
            and "jsonFile" in data
        ):
            return self._load_from_json(Path(data["jsonFile"]), target)

        input_dict = {}
        exceptions: List[Exception] = []

        for field in dataclasses.fields(target):
            json_field = field.name.replace("_v", "-v").replace(
                "cmakefiles", "cmakeFiles"
            )
            if json_field in data:
                try:
                    input_dict[field.name] = self._convert_any(
                        data[json_field], field.type
                    )
                except TypeError as err:
                    msg = f"Failed to convert field {field.name!r} of type {field.type}"
                    if sys.version_info < (3, 11):
                        err.__notes__ = getattr(err, "__notes__", ()) + (msg,)  # type: ignore[attr-defined]
                    else:
                        err.add_note(msg)  # pylint: disable=no-member
                    exceptions.append(err)
                except ExceptionGroup as err:
                    exceptions.append(err)

        if exceptions:
            raise ExceptionGroup(f"Failed converting {target}", exceptions)

        return target(**input_dict)

    def _convert_any(self, item: Any, target: Type[T]) -> T:
        if dataclasses.is_dataclass(target):
            return self.make_class(item, target)
        if hasattr(target, "__origin__"):
            if target.__origin__ == list:  # type: ignore[attr-defined]
                return [self._convert_any(i, target.__args__[0]) for i in item]  # type: ignore[return-value,attr-defined]
            if target.__origin__ == Union:  # type: ignore[attr-defined]
                return self._convert_any(item, target.__args__[0])  # type: ignore[no-any-return,attr-defined]

        return target(item)  # type: ignore[call-arg]


def load_reply_dir(path: Path) -> Index:
    return Converter(path).load()


if __name__ == "__main__":
    import argparse

    import rich

    parser = argparse.ArgumentParser()
    parser.add_argument("reply_dir", type=Path, help="Path to the reply directory")
    args = parser.parse_args()

    reply = Path(args.reply_dir)
    rich.print(load_reply_dir(reply))