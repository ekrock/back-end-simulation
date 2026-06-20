import json


class SimLogger:
    def __init__(self, log_path: str):
        self._file = open(log_path, "w")

    def log(self, event: dict) -> None:
        self._file.write(json.dumps(event) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
